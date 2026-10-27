"""Explicit paid compatibility probes; collection and ordinary pytest are keyless.

Cache prerequisites were checked against the official docs on 2026-10-26 for
the model in config/llm_routes.yaml. Recheck support/minimum on a model change.
These probes record measurements; they do not certify teaching quality.
"""
from collections.abc import Iterator
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import anthropic
import pytest

from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
from learnai.adapters.tutor.anthropic.routing import load_budget_profiles, load_routes, resolve_tutor_route
from learnai.adapters.tutor.runtime import TerminationReason, TurnTrace
from learnai.domain.enums import Confidence, Verdict
from learnai.domain.interaction import ResponseJob, WorkStatus
from tests.adapters.tutor.test_adapter_engine import draft
from tests.domain.test_engine import CLUSTER, build

pytestmark = [pytest.mark.live, pytest.mark.anthropic]
ROOT = Path(__file__).resolve().parents[3]
# https://platform.claude.com/docs/en/build-with-claude/prompt-caching
CACHE_MINIMUM_TOKENS = 512
LiveTutor = tuple[AnthropicTutor, list[TurnTrace], dict[str, Any]]


@pytest.fixture
def live_tutor(request: pytest.FixtureRequest) -> Iterator[LiveTutor]:
    key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not key.strip():
        pytest.skip('ANTHROPIC_API_KEY absent; live compatibility has not been verified')
    routes_path = ROOT / 'config/llm_routes.yaml'
    routes, profiles = load_routes(routes_path), load_budget_profiles(routes_path)
    route = resolve_tutor_route(routes, ResponseJob.NORMAL)
    traces: list[TurnTrace] = []
    measurements: dict[str, Any] = {'test': request.node.nodeid,
        'cache_minimum_tokens': CACHE_MINIMUM_TOKENS,
        'cache_prerequisites_checked_at': '2026-10-26',
        'response_job': ResponseJob.NORMAL.value, 'budget_profile': route.budget_profile,
        'budget': asdict(profiles[route.budget_profile])}
    with anthropic.Anthropic(api_key=key, max_retries=0) as client:
        tutor = AnthropicTutor(routes, client, GeneratorRegistry(QUADRATICS_TEMPLATES),
            CLUSTER.misconceptions, budget_profiles=profiles, trace_sink=traces.append)
        try:
            yield tutor, traces, measurements
        finally:
            directory = ROOT / 'eval/reports' / ('live-' + str(uuid4()))
            directory.mkdir(parents=True, mode=0o700)
            artifact = directory / 'measurements.json'
            artifact.write_text(json.dumps({**measurements, 'traces': [t.to_dict() for t in traces]},
                                           ensure_ascii=False, indent=2), encoding='utf-8')
            artifact.chmod(0o600)
            print(f'Private live measurements: {artifact}')


def _assert_accepted_protocol(tutor: AnthropicTutor, trace: TurnTrace) -> None:
    reason = trace.termination_reason.value if trace.termination_reason else 'unclassified'
    assert trace.accepted is not None, (
        f'No accepted buffered turn: outcome={reason}, elapsed={trace.elapsed_seconds:.3f}s; '
        'inspect the private trace for exhaustion/provider/validation failure')
    assert trace.termination_reason is TerminationReason.ACCEPTED
    assert trace.validation_results and trace.validation_results[-1].accepted
    route = resolve_tutor_route(tutor.routes, ResponseJob.NORMAL)
    assert trace.model == route.model and trace.prompt_ids == (route.prompt,)
    assert trace.settings['thinking'] == {'type': route.thinking}
    assert trace.settings['output_config']['effort'] == route.effort
    assert trace.provider_requests and trace.provider_responses and trace.usages
    assert len(trace.attempts) == len(trace.provider_requests) == trace.model_calls
    for provider_request in trace.provider_requests:
        assert provider_request['model'] == route.model
        assert provider_request['thinking'] == trace.settings['thinking']
        assert provider_request['output_config'] == trace.settings['output_config']
        assert provider_request['stream'] is route.stream
        assert 0 < provider_request['max_tokens'] <= route.max_tokens
        assert 'temperature' not in provider_request
        assert provider_request['tool_choice']['type'] in {'auto', 'none'}
        assert provider_request['messages'][0]['content'] == trace.initial_context
    for previous, current in zip(trace.provider_requests, trace.provider_requests[1:]):
        # Tool/format/validation continuations must retain accumulated provider history.
        assert current['messages'][:len(previous['messages'])] == previous['messages']
    for response in trace.provider_responses:
        assert response['type'] == 'message' and response['role'] == 'assistant'
        assert response['model'] and response['content'] and response['usage']
    for attempt in trace.attempts:
        if attempt.response is not None:
            assert attempt.response_model == attempt.response['model']
    blocks = [block for message in trace.messages if isinstance(message['content'], list)
              for block in message['content']]
    assert [b['id'] for b in blocks if b['type'] == 'tool_use'] == [
        b['tool_use_id'] for b in blocks if b['type'] == 'tool_result']


def test_repeated_stable_prefix_records_provider_cache_reads(live_tutor: LiveTutor) -> None:
    tutor, traces, measurements = live_tutor
    route = resolve_tutor_route(tutor.routes, ResponseJob.NORMAL)
    assert route.thinking == 'adaptive' and route.temperature is None and route.effort is not None, (
        'Recheck official caching and settings support for the configured route before this probe')
    engine, session, _ = build(tutor)
    question = draft(session)
    session, _ = engine.ask_question(session, {}, question)
    first = traces[-1]
    _assert_accepted_protocol(tutor, first)
    # A completed first response establishes the cache before the sequential repeat.
    # Provider cache usage proves the actual cached prefix met the vendor threshold;
    # total input alone would include volatile context and cannot establish that.
    cached_prefix = max((u.get('cache_creation_input_tokens', 0) or 0)
                        + (u.get('cache_read_input_tokens', 0) or 0) for u in first.usages)
    measurements['first_cached_prefix_tokens'] = cached_prefix
    assert cached_prefix >= CACHE_MINIMUM_TOKENS, (
        f'Cache prerequisite unproven (observed {cached_prefix}, minimum {CACHE_MINIMUM_TOKENS}); '
        'check minimum cacheable prefix length, configured-model support, cache_control, '
        'account routing and cache availability; this alone does not diagnose volatile-prefix leakage')
    session, _ = engine.ask_question(session, {}, replace(question, revision=1, status=WorkStatus.REVISED))
    second = traces[-1]
    _assert_accepted_protocol(tutor, second)
    a, b = first.provider_requests[0], second.provider_requests[0]
    assert a['system'] == b['system'] and a['tools'] == b['tools']
    assert all(block.get('cache_control') == {'type': 'ephemeral'} for block in a['system'])
    reads = sum(u.get('cache_read_input_tokens', 0) or 0 for u in second.usages)
    measurements['repeat_cache_read_tokens'] = reads
    assert reads >= CACHE_MINIMUM_TOKENS, (
        'No cache-read proof despite the established prefix prerequisite; inspect TTL, '
        'routing, supported settings and raw usage before attributing the miss to prefix changes')
    assert first.request_id != second.request_id


def test_real_engine_accepts_draft_question_and_retains_historical_revision(live_tutor: LiveTutor) -> None:
    tutor, traces, measurements = live_tutor
    engine, session, _ = build(tutor)
    session, states, outcome = engine.submit(session, {}, steps=['x+1', 'x+2'],
        answer=draft(session).answer, confidence=Confidence.UNSURE)
    assert outcome.verdict is Verdict.WRONG and outcome.tutor_turn is None and not traces
    earlier = session.history
    interaction = draft(session, revision=1, status=WorkStatus.REVISED)
    updated, turn = engine.ask_question(session, states, interaction)
    assert len(traces) == 1
    trace = traces[0]
    measurements['response_job'] = ResponseJob.NORMAL.value
    measurements['buffered_delivery_seconds'] = trace.elapsed_seconds
    measurements['termination_reason'] = trace.termination_reason.value
    _assert_accepted_protocol(tutor, trace)
    assert turn == trace.accepted and updated.history[:len(earlier)] == earlier
    assert updated.history[-2].interaction == interaction
    assert updated.history[-1].message == turn.message
    sent = json.loads(trace.initial_context)
    work = sent['moment']['interaction']
    assert work['revision'] == 1 and work['status'] == 'REVISED'
    assert work['verification']['answer_checked'] is False
    assert work['verification']['verdict'] is None
    assert sent['active'][0]['record']['historical_verdict'] == 'WRONG'
    assert updated.current_task.help_state.assistance_received
