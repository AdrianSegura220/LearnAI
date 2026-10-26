"""Request-scoped Responses tutor; drafts stay private until engine validation."""
from collections.abc import Callable, Mapping
from copy import deepcopy
import json
import logging
import time
from uuid import uuid4

from openai import OpenAI

from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.persistence.in_memory_history import InMemoryHistoryReader
from learnai.adapters.tutor.configuration import ResolvedRoleConfig
from learnai.adapters.tutor.observations import TraceSink
from learnai.adapters.tutor.openai.config import validate_route
from learnai.adapters.tutor.openai.encoding import (
    correction_item, normalize_tool_arguments, prepare_tutor, require_config, tutor_payload,
)
from learnai.adapters.tutor.openai.transport import ResponsesTransport
from learnai.adapters.tutor.runtime import ResponseBudget, TerminationReason, TurnTrace, conservative_token_count
from learnai.adapters.tutor.tools import ToolError, Toolbox
from learnai.adapters.tutor.turn_schema import TurnSchemaError, parse_turn
from learnai.domain.ids import MisconceptionId
from learnai.domain.skills import Misconception
from learnai.domain.turn import TurnContext, TurnFeedback, TutorTurn, ValidationResult

MAX_FORMAT_RETRIES = 2
_LOG = logging.getLogger(__name__)


class OpenAITutor:
    def __init__(self, config: ResolvedRoleConfig, client: OpenAI, items: GeneratorRegistry,
                 catalogue: Mapping[MisconceptionId, Misconception], *,
                 monotonic: Callable[[], float] = time.monotonic,
                 count_tokens: Callable[[str], int] = conservative_token_count,
                 trace_sink: TraceSink | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        require_config(config, role='tutor')
        validate_route(config.route, role='tutor')
        self.config = deepcopy(config)
        self.client = client.with_options(max_retries=0)
        self.items, self.catalogue = items, catalogue
        self.monotonic, self.count_tokens, self.sleep = monotonic, count_tokens, sleep
        self.trace_sink = trace_sink

    def begin_turn(self, context: TurnContext) -> '_OpenAIExchange':
        return _OpenAIExchange(self, context)

    def respond(self, context: TurnContext, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        exchange = self.begin_turn(context)
        turn = None
        try:
            turn = exchange.respond(feedback=feedback)
            if exchange.expired():
                turn = None
            return turn
        finally:
            exchange.finish(accepted=turn, reason=exchange.stop_reason or 'completed')


class _OpenAIExchange:
    def __init__(self, tutor: OpenAITutor, context: TurnContext) -> None:
        self.tutor, self.context, self.config = tutor, context, tutor.config
        self.budget = ResponseBudget(self.config.profile, monotonic=tutor.monotonic)
        self.toolbox = Toolbox(tutor.items, tutor.catalogue, InMemoryHistoryReader(context.history))
        scope, interaction = context.history_scope, context.interaction
        self.trace = TurnTrace(str(uuid4()), scope.student_id if scope else None,
            scope.session_id if scope else None, interaction.task_id if interaction else None,
            context.item.id, interaction.revision if interaction else None,
            (self.config.prompt.id,), self.config.route.model, deepcopy(dict(self.config.effective_settings)),
            provider='openai', api_family='responses', route_name=self.config.route.name)
        self.transport = ResponsesTransport(tutor.client, self.budget, self.trace,
            count_tokens=tutor.count_tokens, sleep=tutor.sleep)
        self.finished, self._retry_pending, self._draft_pending = False, False, False
        self._stop: TerminationReason | None = None
        self.pending: list[dict] = []
        prepared = prepare_tutor(self.config, context=context, count_tokens=tutor.count_tokens)
        self.instructions, self.inputs, self.tools = (deepcopy(prepared.payload[key])
            for key in ('instructions', 'input', 'tools'))
        self.trace.context_view = prepared.context_view
        self.trace.source_ids = prepared.context_view.source_ids
        self.trace.initial_context = self.inputs[0]['content']
        if not prepared.admitted:
            self._stop = TerminationReason.CONTEXT_LIMIT

    @property
    def stop_reason(self) -> str | None:
        reason = self._stop or self.transport.stop_reason
        return reason.value if reason is not None else None

    def expired(self) -> bool:
        if self.budget.expired() and self._stop is None:
            self._stop = TerminationReason.DEADLINE
        return self.finished or self.stop_reason is not None

    def _payload(self) -> dict:
        return tutor_payload(self.config, instructions=self.instructions, inputs=self.inputs,
            tools=self.tools, explore=self.budget.can_explore(), remaining_output=self.budget.remaining_output_tokens)

    def _settle(self, contents: list[str]) -> None:
        assert len(contents) == len(self.pending)
        results = [{'type': 'function_call_output', 'call_id': call['call_id'], 'output': content}
            for call, content in zip(self.pending, contents, strict=True)]
        self.inputs.extend(results)
        self.trace.tool_results.extend(deepcopy(results))
        self.pending = []

    def _settle_error(self, code: str) -> None:
        self._settle([json.dumps({'code': code}) for _ in self.pending])

    def _format_error(self, detail: str) -> bool:
        self._settle_error('invalid_format')
        self.trace.attempts[-1].outcome = 'format_rejected'
        if self.trace.format_retries >= MAX_FORMAT_RETRIES:
            self._stop = TerminationReason.FORMAT_EXHAUSTED
            return False
        self.trace.format_retries += 1
        self._retry_pending = True
        self.inputs.append(correction_item(json.dumps({'code': 'invalid_format', 'detail': detail})))
        return True

    def respond(self, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        if self.expired():
            return None
        if feedback is not None:
            self.inputs.append(correction_item(feedback))
            self.trace.validation_retries += 1
            self._retry_pending, self._draft_pending = True, False
        elif self._draft_pending:
            raise RuntimeError('pending tutor draft requires validation or feedback')
        while not self.expired():
            raw = self.transport.call(self._payload, retry=self._retry_pending)
            self._retry_pending = False
            if raw is None:
                return None
            outputs = raw.get('output', [])
            self.inputs.extend(deepcopy(outputs))
            self.pending = [item for item in outputs if item.get('type') == 'function_call']
            if raw.get('status') == 'incomplete':
                self._stop = TerminationReason.TRUNCATED
                self._settle_error('truncated')
                return None
            if raw.get('status') != 'completed':
                self._stop = TerminationReason.API_ERROR
                self._settle_error('api_error')
                return None
            if any(block.get('type') == 'refusal' for item in outputs
                   if item.get('type') == 'message' for block in item.get('content', [])):
                self._stop = TerminationReason.REFUSAL
                self._settle_error('refusal')
                return None
            if self.pending:
                results = []
                for call in self.pending:
                    if (self.trace.provider_requests[-1]['tool_choice'] == 'none'
                            or not self.budget.can_execute_tool()):
                        results.append(json.dumps({'code': 'exploration_exhausted'}))
                        continue
                    self.budget.record_tool_calls(1)
                    try:
                        try:
                            arguments = json.loads(call['arguments'])
                        except (json.JSONDecodeError, TypeError) as exc:
                            raise ToolError('invalid_arguments', 'tool arguments must be JSON') from exc
                        result = self.toolbox.execute(call['name'],
                            normalize_tool_arguments(call['name'], arguments), self.context)
                    except ToolError as exc:
                        result = json.dumps({'code': exc.code, 'detail': str(exc)})
                    results.append(result)
                    self.expired()
                self._settle(results)
                continue
            try:
                text = ''.join(block.get('text', '') for item in outputs if item.get('type') == 'message'
                    for block in item.get('content', []) if block.get('type') == 'output_text')
                turn = parse_turn(json.loads(text))
                self._draft_pending = True
                return turn
            except (json.JSONDecodeError, TurnSchemaError) as exc:
                if not self._format_error(str(exc)):
                    return None
        return None

    def record_validation(self, result: ValidationResult) -> None:
        self.trace.validation_results.append(result)
        if self.trace.attempts:
            self.trace.attempts[-1].outcome = 'accepted' if result.accepted else 'validation_rejected'
        self.expired()

    def finish(self, *, accepted: TutorTurn | None, reason: str) -> None:
        if self.finished:
            return
        self.expired()
        if self.stop_reason is not None:
            accepted, reason = None, self.stop_reason
        self._settle_error(reason)
        self.finished = True
        self.trace.accepted, self.trace.termination_reason = accepted, TerminationReason(reason)
        self.trace.elapsed_seconds = self.budget.elapsed_seconds
        self.trace.model_calls, self.trace.tool_calls = self.budget.model_calls, self.budget.tool_calls
        self.trace.output_tokens = self.budget.output_tokens
        self.trace.messages = deepcopy(self.inputs)
        if accepted is None:
            _LOG.warning('tutor response unavailable: %s (request=%s)', reason, self.trace.request_id)
        if self.tutor.trace_sink is not None:
            self.tutor.trace_sink(self.trace)
