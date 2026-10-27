"""Responses framing for the common offline rubric with one response budget."""
from collections.abc import Callable
from copy import deepcopy
import json
import time
from uuid import uuid4

from openai import OpenAI

from learnai.adapters.tutor.configuration import ResolvedRoleConfig
from learnai.adapters.tutor.observations import JudgeTrace, TraceSink
from learnai.adapters.tutor.openai.config import validate_route
from learnai.adapters.tutor.openai.encoding import judge_payload, prepare_judge, require_config
from learnai.adapters.tutor.openai.transport import ResponsesTransport
from learnai.adapters.tutor.runtime import ResponseBudget, TerminationReason, conservative_token_count
from learnai.eval.judge import JudgeError, JudgePacket, JudgeScores, parse_scores

MAX_FORMAT_RETRIES = 2


class OpenAIJudge:
    """Evaluate a captured candidate/moment packet without tutor tools or lookup."""
    def __init__(self, config: ResolvedRoleConfig, client: OpenAI, *,
                 trace_sink: TraceSink | None = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 count_tokens: Callable[[str], int] = conservative_token_count,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        require_config(config, role='judge')
        validate_route(config.route, role='judge')
        self.config = deepcopy(config)
        self.client = client.with_options(max_retries=0)
        self.trace_sink, self.monotonic = trace_sink, monotonic
        self.count_tokens, self.sleep = count_tokens, sleep

    def evaluate(self, packet: JudgePacket) -> JudgeScores:
        config = self.config
        budget = ResponseBudget(config.profile, monotonic=self.monotonic)
        trace = JudgeTrace(str(uuid4()), (config.prompt.id,), config.route.model,
            deepcopy(dict(config.effective_settings)), provider='openai', api_family='responses',
            route_name=config.route.name)
        transport = ResponsesTransport(self.client, budget, trace,
            count_tokens=self.count_tokens, sleep=self.sleep)
        inputs = []
        def fail(reason: TerminationReason, detail: str = ''):
            trace.termination_reason = reason
            raise JudgeError(reason.value + (': ' + detail if detail else ''))
        def payload():
            return judge_payload(config, inputs=inputs, remaining_output=budget.remaining_output_tokens)
        try:
            prepared = prepare_judge(config, packet=packet, count_tokens=self.count_tokens)
            inputs.extend(deepcopy(prepared.payload['input']))
            if not prepared.admitted:
                fail(TerminationReason.CONTEXT_LIMIT)
            while True:
                raw = transport.call(payload, retry=trace.format_retries > 0)
                if raw is None:
                    fail(transport.stop_reason or TerminationReason.API_ERROR)
                outputs = raw.get('output', [])
                inputs.extend(deepcopy(outputs))
                if raw.get('status') == 'incomplete':
                    fail(TerminationReason.TRUNCATED)
                if raw.get('status') != 'completed':
                    fail(TerminationReason.API_ERROR)
                if any(block.get('type') == 'refusal' for item in outputs
                       if item.get('type') == 'message' for block in item.get('content', [])):
                    fail(TerminationReason.REFUSAL)
                if any(item.get('type') not in ('message', 'reasoning') for item in outputs):
                    fail(TerminationReason.API_ERROR, 'unexpected judge output item')
                blocks = [block for item in outputs if item.get('type') == 'message'
                          for block in item.get('content', [])]
                if any(block.get('type') != 'output_text' or not isinstance(block.get('text'), str)
                       for block in blocks):
                    fail(TerminationReason.API_ERROR, 'invalid judge content')
                try:
                    scores = parse_scores(''.join(block['text'] for block in blocks))
                except JudgeError as exc:
                    trace.attempts[-1].outcome = 'format_rejected'
                    if trace.format_retries >= MAX_FORMAT_RETRIES:
                        fail(TerminationReason.FORMAT_EXHAUSTED, str(exc))
                    trace.format_retries += 1
                    inputs.append({'role': 'developer', 'content': json.dumps({
                        'code': 'invalid_format', 'detail': str(exc)}, ensure_ascii=False)})
                    continue
                if budget.expired():
                    fail(TerminationReason.DEADLINE)
                trace.attempts[-1].outcome = 'completed'
                trace.termination_reason = TerminationReason.COMPLETED
                return scores
        finally:
            trace.messages = deepcopy(inputs)
            trace.elapsed_seconds = budget.elapsed_seconds
            trace.model_calls, trace.output_tokens = budget.model_calls, budget.output_tokens
            if self.trace_sink is not None:
                self.trace_sink(trace)
