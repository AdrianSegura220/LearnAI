"""Anthropic transport for a single retained, engine-validated tutor exchange."""
from collections.abc import Callable, Mapping
from copy import deepcopy
import json
import logging
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

import anthropic
import httpx2

from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.persistence.in_memory_history import InMemoryHistoryReader
from learnai.adapters.tutor.anthropic.prompt import SystemBlock, build_prompt, correction_text
from learnai.adapters.tutor.anthropic.routing import BudgetProfile, Route, resolve_route, resolve_tutor_route
from learnai.adapters.tutor.anthropic.tool_schema import encode_tools
from learnai.adapters.tutor.anthropic.turn_schema import TURN_SCHEMA, TurnSchemaError, parse_turn
from learnai.adapters.tutor.context import ContextLimitError
from learnai.adapters.tutor.prompts import PROMPTS_ROOT, TutorPrompt, load_prompt
from learnai.adapters.tutor.rendering import render_session_preamble, render_skill_pack
from learnai.adapters.tutor.runtime import (
    DEFAULT_BUDGET_PROFILES, ProviderAttempt, ResponseBudget, TerminationReason, TurnTrace,
    UsageStatus, conservative_token_count,
)
from learnai.adapters.tutor.tools import ToolError, Toolbox
from learnai.domain.ids import MisconceptionId
from learnai.domain.skills import Misconception
from learnai.domain.turn import TurnContext, TurnFeedback, TutorTurn, ValidationResult

MAX_FORMAT_RETRIES = 2
MAX_API_ATTEMPTS = 3
_LOG = logging.getLogger(__name__)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _system_block(block: SystemBlock) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "text", "text": block.text}
    if block.cache:
        result["cache_control"] = {"type": "ephemeral"}
    return result


def _request_kwargs(route: Route) -> dict[str, Any]:
    result: dict[str, Any] = {"model": route.model, "max_tokens": route.max_tokens,
        "stream": route.stream, "output_config": {"format": {
            "type": "json_schema", "schema": deepcopy(TURN_SCHEMA)}}}
    if route.effort is not None:
        result["output_config"]["effort"] = route.effort
    if route.thinking is not None:
        result["thinking"] = {"type": route.thinking}
    # Sampling controls are not supported by the configured adaptive model.
    if route.temperature is not None:
        raise ValueError("tutor routes must omit temperature")
    return result


class AnthropicTutor:
    def __init__(self, routes: Mapping[str, Route], client: anthropic.Anthropic,
                 items: GeneratorRegistry, catalogue: Mapping[MisconceptionId, Misconception], *,
                 budget_profiles: Mapping[str, BudgetProfile] | None = None,
                 route_name: str | None = None, prompts_root: Path = PROMPTS_ROOT,
                 monotonic: Callable[[], float] = time.monotonic,
                 count_tokens: Callable[[str], int] | None = None,
                 trace_sink: Callable[[TurnTrace], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.routes = dict(routes)
        self.client = client.with_options(max_retries=0)
        self.items = items
        self.catalogue = catalogue
        self.profiles = dict(DEFAULT_BUDGET_PROFILES if budget_profiles is None else budget_profiles)
        self.route_name = route_name
        self.monotonic = monotonic
        self.count_tokens = count_tokens or conservative_token_count
        self.trace_sink = trace_sink
        self.sleep = sleep
        self.events_seen: list[dict[str, Any]] = []
        self.usages: list[anthropic.types.Usage] = []
        self.prompts: dict[str, TutorPrompt] = {}
        selected = (resolve_route(self.routes, route_name),) if route_name is not None else tuple(
            route for name, route in self.routes.items() if name.startswith("tutor_"))
        for route in selected:
            if route.prompt is None:
                raise ValueError(f"tutor route {route.name} requires an explicit prompt")
            _request_kwargs(route)
            if route.budget_profile not in self.profiles:
                raise ValueError(f"unknown budget profile: {route.budget_profile}")
            self.prompts[route.name] = load_prompt(route.prompt, root=prompts_root)

    def begin_turn(self, context: TurnContext) -> "_AnthropicExchange":
        route = (resolve_route(self.routes, self.route_name) if self.route_name is not None
                 else resolve_tutor_route(self.routes, context.response_job))
        return _AnthropicExchange(self, context, route, self.prompts[route.name])

    def respond(self, context: TurnContext, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        exchange = self.begin_turn(context)
        turn = None
        try:
            turn = exchange.respond(feedback=feedback)
            if exchange.expired():
                turn = None
            return turn
        finally:
            exchange.finish(accepted=turn, reason=exchange.stop_reason or "completed")


class _AnthropicExchange:
    def __init__(self, tutor: AnthropicTutor, context: TurnContext, route: Route, policy: TutorPrompt) -> None:
        self.tutor = tutor
        self.context = context
        self.route = route
        self.budget = ResponseBudget(tutor.profiles[route.budget_profile], monotonic=tutor.monotonic)
        self.toolbox = Toolbox(tutor.items, tutor.catalogue, InMemoryHistoryReader(context.history))
        self.tools = list(encode_tools(self.toolbox.tools())) + [{"name": "submit_turn",
            "description": "Submit the final tutor turn for engine validation.", "input_schema": deepcopy(TURN_SCHEMA)}]
        self.messages: list[dict[str, Any]] = []
        self.pending: list[dict[str, Any]] = []
        self.finished = False
        self._stop: TerminationReason | None = None
        scope, interaction = context.history_scope, context.interaction
        self.trace = TurnTrace(str(uuid4()), scope.student_id if scope else None,
            scope.session_id if scope else None, interaction.task_id if interaction else None,
            context.item.id, interaction.revision if interaction else None,
            (policy.id,), route.model, _request_kwargs(route))
        system = [SystemBlock(policy.text, cache=True), SystemBlock(render_skill_pack(context), cache=True)]
        if preamble := render_session_preamble(context):
            system.append(SystemBlock(preamble, cache=True))
        self.system = [_system_block(block) for block in system]
        # Prompt selection must charge schemas, tool definitions and provider framing
        # as well as policy and the volatile context. The volatile JSON is one line.
        def initial_counter(text: str) -> int:
            volatile = text.rsplit("\n", 1)[-1]
            return tutor.count_tokens(_json(self._payload(
                messages=[{"role": "user", "content": volatile}], explore=self.budget.can_explore())))
        try:
            prompt = build_prompt(context, policy.text,
                input_budget=self.budget.profile.context_input_tokens - self._max_tokens(self.budget.can_explore()),
                count_tokens=initial_counter)
        except ContextLimitError:
            self._stop = TerminationReason.CONTEXT_LIMIT
        else:
            self.messages = deepcopy(list(prompt.messages))
            self.trace.context_view = prompt.context_view
            self.trace.source_ids = prompt.context_view.source_ids
            self.trace.initial_context = self.messages[0]["content"]

    @property
    def stop_reason(self) -> str | None:
        return self._stop.value if self._stop is not None else None

    def expired(self) -> bool:
        if self.budget.expired() and self._stop is None:
            self._stop = TerminationReason.DEADLINE
        return self._stop is not None or self.finished

    def _max_tokens(self, explore: bool) -> int:
        available = self.budget.remaining_output_tokens
        if explore:
            available -= self.budget.profile.finalization_reserve_tokens
        return min(self.route.max_tokens, available)

    def _payload(self, *, explore: bool, messages: list[dict] | None = None) -> dict[str, Any]:
        return {**_request_kwargs(self.route), "max_tokens": self._max_tokens(explore),
            "system": self.system, "messages": self.messages if messages is None else messages,
            "tools": self.tools, "tool_choice": {"type": "auto" if explore else "none"}}

    def _correction(self, value: str) -> None:
        # Supported by the configured provider and SDK, without mutating the prefix.
        self.messages.append({"role": "system", "content": value})

    def _settle(self, contents: list[tuple[str, bool]]) -> None:
        assert len(contents) == len(self.pending)
        if not self.pending:
            return
        results = [{"type": "tool_result", "tool_use_id": call["id"],
                    "content": content, "is_error": error}
                   for call, (content, error) in zip(self.pending, contents, strict=True)]
        self.messages.append({"role": "user", "content": results})
        self.trace.tool_results.extend(deepcopy(results))
        self.pending = []

    def _settle_error(self, code: str, detail: str | None = None) -> None:
        self._settle([(_json({"code": code, "detail": detail}), True) for _ in self.pending])

    def _available(self) -> bool:
        if self.expired():
            return False
        if self.budget.model_calls >= self.budget.profile.max_round_trips:
            self._stop = TerminationReason.ROUND_TRIP_LIMIT
        elif self.budget.remaining_output_tokens <= 0:
            self._stop = TerminationReason.OUTPUT_LIMIT
        return self._stop is None

    def _model_call(self) -> tuple[anthropic.types.Message, bool] | None:
        for attempt in range(MAX_API_ATTEMPTS):
            if not self._available():
                return None
            explore = self.budget.can_explore()
            payload = self._payload(explore=explore)
            if self.tutor.count_tokens(_json(payload)) + payload["max_tokens"] > self.budget.profile.context_input_tokens:
                self._stop = TerminationReason.CONTEXT_LIMIT
                return None
            if self.expired():
                return None
            self.trace.provider_requests.append(deepcopy(payload))
            self.trace.attempts.append(ProviderAttempt(len(self.trace.provider_requests) - 1))
            self.budget.record_model_call(0)
            try:
                timeout = self.budget.remaining_seconds()
                if self.route.stream:
                    response = self._stream_response(payload, timeout)
                    if response is None:
                        return None
                else:
                    response = self.tutor.client.messages.create(**payload, timeout=timeout)
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                status = getattr(exc, "status_code", None)
                self.trace.attempts[-1].provider_request_id = getattr(exc, "request_id", None)
                self.trace.api_errors.append({"type": type(exc).__name__, "status_code": status,
                    "request_id": getattr(exc, "request_id", None), "attempt": self.budget.model_calls})
                if self.expired():
                    return None
                retryable = status is None or status in {408, 409, 429} or status >= 500
                if not retryable:
                    self._stop = TerminationReason.API_ERROR
                    return None
                if attempt == MAX_API_ATTEMPTS - 1:
                    self._stop = TerminationReason.NETWORK_EXHAUSTED
                    return None
                if not self._available():
                    return None
                self.trace.api_retries += 1
                self.tutor.sleep(min(0.25 * 2 ** attempt, self.budget.remaining_seconds()))
                continue
            raw = response.model_dump(mode="json", exclude_unset=True)
            self._record_response(response)
            blocks = deepcopy(raw["content"])
            if not self.route.stream:
                self.trace.events.extend(deepcopy(blocks))
                self.tutor.events_seen.extend(deepcopy(blocks))
            self.messages.append({"role": "assistant", "content": blocks})
            self.pending = [block for block in blocks if block["type"] == "tool_use"]
            if self.expired():
                self._settle_error("deadline")
                return None
            if self.budget.output_tokens > self.budget.profile.max_output_tokens:
                self._stop = TerminationReason.OUTPUT_LIMIT
                self._settle_error("output_limit")
                return None
            if response.stop_reason in {"refusal", "max_tokens"}:
                self._stop = (TerminationReason.REFUSAL if response.stop_reason == "refusal"
                              else TerminationReason.TRUNCATED)
                self._settle_error(self._stop.value)
                return None
            return response, explore
        return None

    def _record_response(self, response: anthropic.types.Message, *, complete: bool = True) -> None:
        attempt = self.trace.attempts[-1]
        attempt.usage_status = UsageStatus.COMPLETE if complete else UsageStatus.PARTIAL
        attempt.usage = response.usage.model_dump(mode="json", exclude_unset=True)
        attempt.provider_request_id = getattr(response, "_request_id", None) or attempt.provider_request_id
        self.trace.provider_responses.append(response.model_dump(mode="json", exclude_unset=True))
        self.trace.usages.append(response.usage.model_dump(mode="json", exclude_unset=True))
        self.tutor.usages.append(response.usage)
        self.budget.record_output_tokens(response.usage.output_tokens)

    def _stream_response(self, payload: dict[str, Any], timeout: float) -> anthropic.types.Message | None:
        kwargs = {key: value for key, value in payload.items() if key != "stream"}
        with self.tutor.client.messages.stream(**kwargs, timeout=timeout) as stream:
            self.trace.attempts[-1].provider_request_id = stream.request_id
            started = False
            completed = False
            try:
                for event in stream:
                    data = event.model_dump(mode="json", exclude_unset=True)
                    self.trace.events.append(data)
                    self.tutor.events_seen.append(deepcopy(data))
                    started = started or event.type == "message_start"
                    completed = completed or event.type == "message_stop"
                    if self.expired():
                        if started:
                            self._record_response(stream.current_message_snapshot, complete=False)
                        return None
                if not completed:
                    if started:
                        self._record_response(stream.current_message_snapshot, complete=False)
                    self._stop = TerminationReason.NETWORK_EXHAUSTED
                    self.trace.api_errors.append({"type": "incomplete_stream", "status_code": None,
                        "request_id": stream.request_id, "attempt": self.budget.model_calls})
                    return None
                return stream.get_final_message()
            except (httpx2.TransportError, anthropic.APIStatusError) as exc:
                # Once a stream begins, its partial usage is real. Retrying it
                # blindly would undercount unobserved output and replay an incomplete
                # tool call, so close the exchange with the observations available.
                if not started and isinstance(exc, anthropic.APIStatusError):
                    raise
                if started:
                    self._record_response(stream.current_message_snapshot, complete=False)
                self.trace.api_errors.append({"type": type(exc).__name__,
                    "status_code": getattr(exc, "status_code", None),
                    "request_id": stream.request_id, "attempt": self.budget.model_calls})
                if not self.expired():
                    self._stop = TerminationReason.NETWORK_EXHAUSTED
                return None

    def _format_error(self, detail: str) -> bool:
        self._settle_error("invalid_format", detail)
        if self.trace.format_retries >= MAX_FORMAT_RETRIES:
            self._stop = TerminationReason.FORMAT_EXHAUSTED
            return False
        self.trace.format_retries += 1
        self._correction(_json({"code": "invalid_format", "detail": detail}))
        return True

    def respond(self, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        if self.expired():
            return None
        if feedback is not None:
            self._settle_error(feedback.reason.name, feedback.detail)
            self.trace.validation_retries += 1
            self._correction(correction_text(feedback))
        elif self.pending:
            raise RuntimeError("pending tutor draft requires validation or feedback")
        while self._available():
            called = self._model_call()
            if called is None:
                return None
            response, explored = called
            submits = [call for call in self.pending if call["name"] == "submit_turn"]
            if submits:
                if len(self.pending) != 1:
                    if not self._format_error("submit_turn must be the sole tool call"):
                        return None
                    continue
                try:
                    return parse_turn(submits[0]["input"])
                except TurnSchemaError as exc:
                    if not self._format_error(str(exc)):
                        return None
                    continue
            if self.pending:
                results = []
                for call in self.pending:
                    if not explored or not self.budget.can_execute_tool():
                        results.append((_json({"code": "exploration_exhausted"}), True))
                        continue
                    self.budget.record_tool_calls(1)
                    try:
                        content = self.toolbox.execute(call["name"], call["input"], self.context)
                    except ToolError as exc:
                        results.append((_json({"code": exc.code, "detail": str(exc)}), True))
                    else:
                        results.append((content, False))
                    self.expired()
                self._settle(results)
                if self.expired():
                    return None
                continue
            try:
                if response.stop_reason != "end_turn":
                    raise TurnSchemaError(f"unexpected stop reason: {response.stop_reason}")
                text = "".join(block.text for block in response.content if block.type == "text")
                return parse_turn(json.loads(text))
            except (TurnSchemaError, json.JSONDecodeError) as exc:
                if not self._format_error(str(exc)):
                    return None
        return None

    def record_validation(self, result: ValidationResult) -> None:
        self.trace.validation_results.append(result)
        if self.expired():
            self._settle_error(self.stop_reason or "deadline")
        elif result.accepted:
            self._settle([(_json({"accepted": True}), False) for _ in self.pending])
        else:
            self._settle_error(result.reason.name if result.reason else "validation_rejected", result.detail)

    def finish(self, *, accepted: TutorTurn | None, reason: str) -> None:
        if self.finished:
            return
        self.expired()
        if self._stop is not None:
            accepted = None
            reason = self._stop.value
        termination = TerminationReason(reason)
        if accepted is None:
            self._settle_error(reason)
        else:
            self._settle([(_json({"accepted": True}), False) for _ in self.pending])
        self.finished = True
        self.trace.accepted = accepted
        self.trace.termination_reason = termination
        self.trace.elapsed_seconds = self.budget.elapsed_seconds
        self.trace.model_calls = self.budget.model_calls
        self.trace.tool_calls = self.budget.tool_calls
        self.trace.output_tokens = self.budget.output_tokens
        self.trace.messages = deepcopy(self.messages)
        if accepted is None:
            _LOG.warning("tutor response unavailable: %s (request=%s)", reason, self.trace.request_id)
        if self.tutor.trace_sink is not None:
            self.tutor.trace_sink(self.trace)
