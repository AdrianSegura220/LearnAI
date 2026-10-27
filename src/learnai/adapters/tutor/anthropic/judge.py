"""Provider transport for the offline rubric judge, with one response budget.

Packet construction, rubric policy and score validation live in the evaluator.
This module owns only SDK framing, bounded retries and private usage traces.
"""
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from dataclasses import dataclass
import json
import time
from typing import Any, NoReturn
from uuid import uuid4

import anthropic
import httpx2

from learnai.adapters.tutor.anthropic.config import resolve_config
from learnai.adapters.tutor.anthropic.usage import normalize_anthropic_usage
from learnai.adapters.tutor.observations import JudgeTrace, TraceSink
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.configuration import ResolvedRoleConfig
from learnai.adapters.tutor.anthropic.prompt import judge_payload, require_config
from learnai.eval.judge import JudgeError, JudgePacket, JudgeScores, build_judge_messages, parse_scores
from pathlib import Path
from learnai.adapters.tutor.routing import BudgetProfile, Route
from learnai.adapters.tutor.runtime import (
    DEFAULT_BUDGET_PROFILES, ProviderAttempt, ResponseBudget, TerminationReason,
    UsageStatus, conservative_token_count,
)

MAX_API_ATTEMPTS = 3
MAX_FORMAT_RETRIES = 2


class JudgeTransportError(ValueError):
    """The offline provider exchange could not yield a usable judgment."""


@dataclass
class JudgeAttempt(ProviderAttempt):
    """Compatibility name for the shared attempt metadata."""




class _JudgeExchange:
    def __init__(
        self, client: anthropic.Anthropic, config: ResolvedRoleConfig, *,
        messages: tuple[dict[str, Any], ...], monotonic: Callable[[], float],
        count_tokens: Callable[[str], int], sleep: Callable[[float], None],
    ) -> None:
        self.client = client.with_options(max_retries=0)
        self.config = config
        route, prompt = config.route, config.prompt
        self.route = route
        self.policy = prompt.text
        self.messages = deepcopy(list(messages))
        self.count_tokens = count_tokens
        self.sleep = sleep
        self.budget = ResponseBudget(config.profile, monotonic=monotonic)
        self.settings = deepcopy(dict(config.effective_settings))
        self.trace = JudgeTrace(str(uuid4()), (prompt.id,), route.model, deepcopy(self.settings),
                                provider="anthropic", api_family="messages", route_name=route.name)

    def _fail(self, reason: TerminationReason, detail: str | None = None) -> NoReturn:
        self.trace.termination_reason = reason
        raise JudgeTransportError(reason.value + (f": {detail}" if detail else ""))

    def _available(self) -> None:
        if self.budget.expired():
            self._fail(TerminationReason.DEADLINE)
        if self.budget.model_calls >= self.budget.profile.max_round_trips:
            self._fail(TerminationReason.ROUND_TRIP_LIMIT)
        if self.budget.remaining_output_tokens <= 0:
            self._fail(TerminationReason.OUTPUT_LIMIT)

    def _record_response(self, response: anthropic.types.Message, *, complete: bool = True) -> None:
        attempt = self.trace.attempts[-1]
        attempt.provider_request_id = getattr(response, "_request_id", None) or attempt.provider_request_id
        raw_response = response.model_dump(mode="json", exclude_unset=True)
        attempt.response_model = raw_response.get("model")
        attempt.response = deepcopy(raw_response)
        attempt.outcome = raw_response.get("stop_reason") or "partial_response"
        self.trace.provider_responses.append(raw_response)
        raw = raw_response.get("usage")
        attempt.normalized_usage = normalize_anthropic_usage(
            raw if isinstance(raw, dict) else None,
            status=UsageStatus.COMPLETE if complete else UsageStatus.PARTIAL,
            response_metadata=raw_response,
            request_settings=self.trace.provider_requests[attempt.request_index])
        attempt.usage_status = attempt.normalized_usage.status
        if not isinstance(raw, dict):
            self._fail(TerminationReason.API_ERROR, "missing or invalid usage")
        attempt.usage = raw
        self.trace.usages.append(deepcopy(raw))
        output = raw.get("output_tokens")
        if type(output) is not int or output < 0:
            self._fail(TerminationReason.API_ERROR, "missing or invalid output usage")
        self.budget.record_output_tokens(output)

    def _stream_response(self, payload: dict[str, Any], timeout: float) -> anthropic.types.Message:
        kwargs = {key: value for key, value in payload.items() if key != "stream"}
        with self.client.messages.stream(**kwargs, timeout=timeout) as stream:
            self.trace.attempts[-1].provider_request_id = stream.request_id
            started = completed = False
            try:
                for event in stream:
                    self.trace.events.append(event.model_dump(mode="json", exclude_unset=True))
                    started = started or event.type == "message_start"
                    completed = completed or event.type == "message_stop"
                    if self.budget.expired():
                        if started:
                            self._record_response(stream.current_message_snapshot, complete=False)
                        self._fail(TerminationReason.DEADLINE)
                if not completed:
                    if started:
                        self._record_response(stream.current_message_snapshot, complete=False)
                    self._fail(TerminationReason.NETWORK_EXHAUSTED, "incomplete_stream")
                return stream.get_final_message()
            except (httpx2.TransportError, anthropic.APIStatusError) as exc:
                if not started:
                    raise
                self._record_response(stream.current_message_snapshot, complete=False)
                self.trace.api_errors.append({"type": type(exc).__name__,
                    "status_code": getattr(exc, "status_code", None), "request_id": stream.request_id})
                self._fail(TerminationReason.DEADLINE if self.budget.expired()
                           else TerminationReason.NETWORK_EXHAUSTED)
        raise AssertionError("stream must return or fail")

    def _model_call(self) -> anthropic.types.Message:
        for attempt in range(MAX_API_ATTEMPTS):
            self._available()
            payload = judge_payload(self.config, messages=self.messages,
                                    remaining_output=self.budget.remaining_output_tokens)
            serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if self.count_tokens(serialized) + payload["max_tokens"] > self.budget.profile.context_input_tokens:
                self._fail(TerminationReason.CONTEXT_LIMIT)
            if self.budget.expired():
                self._fail(TerminationReason.DEADLINE)
            self.trace.provider_requests.append(deepcopy(payload))
            self.trace.attempts.append(JudgeAttempt(len(self.trace.provider_requests) - 1,
                started_at=datetime.now(UTC).isoformat(), retry=attempt > 0 or self.trace.format_retries > 0,
                normalized_usage=normalize_anthropic_usage(None, status=UsageStatus.MISSING,
                    request_settings=payload)))
            self.budget.record_model_call(0)
            attempt_started = self.budget.monotonic()
            try:
                timeout = self.budget.remaining_seconds()
                response = (self._stream_response(payload, timeout) if self.route.stream
                            else self.client.messages.create(**payload, timeout=timeout))
            except (anthropic.APIError, httpx2.TransportError) as exc:
                status = getattr(exc, "status_code", None)
                self.trace.attempts[-1].outcome = type(exc).__name__
                self.trace.attempts[-1].provider_request_id = getattr(exc, "request_id", None)
                self.trace.api_errors.append({"type": type(exc).__name__, "status_code": status,
                    "request_id": getattr(exc, "request_id", None), "attempt": self.budget.model_calls})
                if self.budget.expired():
                    self._fail(TerminationReason.DEADLINE)
                retryable = (isinstance(exc, (anthropic.APIConnectionError, httpx2.TransportError))
                             or (status is not None and (status in {408, 409, 429} or status >= 500)))
                if not retryable:
                    self._fail(TerminationReason.API_ERROR, str(exc))
                if attempt == MAX_API_ATTEMPTS - 1:
                    self._fail(TerminationReason.NETWORK_EXHAUSTED)
                self._available()
                self.trace.api_retries += 1
                self.sleep(min(0.25 * 2 ** attempt, self.budget.remaining_seconds()))
                continue
            finally:
                self.trace.attempts[-1].finish(elapsed_seconds=self.budget.monotonic() - attempt_started)
            self._record_response(response)
            if self.budget.expired():
                self._fail(TerminationReason.DEADLINE)
            if self.budget.output_tokens > self.budget.profile.max_output_tokens:
                self._fail(TerminationReason.OUTPUT_LIMIT)
            if response.stop_reason == "refusal":
                self._fail(TerminationReason.REFUSAL)
            if response.stop_reason == "max_tokens":
                self._fail(TerminationReason.TRUNCATED)
            return response
        raise AssertionError("API attempts must return or fail")

    def run[T](self, parse: Callable[[str], T]) -> T:
        while True:
            response = self._model_call()
            blocks = self.trace.provider_responses[-1].get("content")
            if not isinstance(blocks, list) or any(
                not isinstance(block, dict)
                or block.get("type") not in ("text", "thinking", "redacted_thinking")
                or (block["type"] == "text" and not isinstance(block.get("text"), str))
                for block in blocks
            ):
                self._fail(TerminationReason.API_ERROR, "invalid provider content")
            self.messages.append({"role": "assistant", "content": deepcopy(blocks)})
            try:
                if response.stop_reason != "end_turn":
                    raise ValueError("unexpected response stop reason")
                result = parse("".join(block["text"] for block in blocks if block["type"] == "text"))
            except ValueError as exc:
                self.trace.attempts[-1].outcome = "format_rejected"
                if self.trace.format_retries >= MAX_FORMAT_RETRIES:
                    self._fail(TerminationReason.FORMAT_EXHAUSTED, str(exc))
                self.trace.format_retries += 1
                self.messages.append({"role": "system", "content": json.dumps({
                    "code": "invalid_format", "detail": str(exc)}, ensure_ascii=False)})
                continue
            if self.budget.expired():
                self._fail(TerminationReason.DEADLINE)
            self.trace.attempts[-1].outcome = "completed"
            self.trace.termination_reason = TerminationReason.COMPLETED
            return result

    def finish(self) -> None:
        self.trace.messages = deepcopy(self.messages)
        self.trace.elapsed_seconds = self.budget.elapsed_seconds
        self.trace.model_calls = self.budget.model_calls
        self.trace.output_tokens = self.budget.output_tokens


class AnthropicJudge:
    """A bound judge role, retaining loaded prompt and effective settings."""
    def __init__(self, *, config: ResolvedRoleConfig, client: anthropic.Anthropic,
                 trace_sink: TraceSink | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 count_tokens: Callable[[str], int] = conservative_token_count,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        require_config(config, role='judge')
        self.config = deepcopy(config)
        self.client, self.trace_sink = client, trace_sink
        self.monotonic, self.count_tokens, self.sleep = monotonic, count_tokens, sleep

    def evaluate(self, packet: JudgePacket) -> JudgeScores:
        exchange = _JudgeExchange(self.client, self.config, messages=build_judge_messages(packet),
            monotonic=self.monotonic, count_tokens=self.count_tokens, sleep=self.sleep)
        try:
            return exchange.run(parse_scores)
        except JudgeTransportError as exc:
            raise JudgeError(str(exc)) from exc
        finally:
            exchange.finish()
            if self.trace_sink is not None:
                self.trace_sink(exchange.trace)


def run_judge(client: anthropic.Anthropic, routes: Mapping[str, Route], *, packet: JudgePacket,
              route_name: str = 'rubric_judge', prompts_root: Path = PROMPTS_ROOT,
              budget_profiles: Mapping[str, BudgetProfile] | None = None, **options) -> JudgeScores:
    """Compatibility constructor for existing Anthropic integrations."""
    from learnai.adapters.tutor.routing import resolve_route
    try:
        config = resolve_config(resolve_route(routes, route_name), role='judge',
            profiles=DEFAULT_BUDGET_PROFILES if budget_profiles is None else budget_profiles,
            prompts_root=prompts_root)
        return AnthropicJudge(config=config, client=client, **options).evaluate(packet)
    except ValueError as exc:
        if isinstance(exc, JudgeError):
            raise
        raise JudgeError(str(exc)) from exc
