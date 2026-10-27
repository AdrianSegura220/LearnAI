"""Paid opt-in Responses probes; never part of the ordinary keyless suite.

Cache profile checked against official documentation on 2026-10-27. The
selected current profile requires at least 1,024 visible input tokens for caching.
"""
from collections.abc import Iterator
from dataclasses import asdict, replace
from importlib.metadata import version
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import OpenAI
import pytest

from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.openai.adapter import OpenAITutor
from learnai.adapters.tutor.openai.config import resolve_config
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.routing import load_budget_profiles, load_routes
from learnai.adapters.tutor.runtime import TerminationReason, TurnTrace
from learnai.domain.enums import Confidence, Verdict
from learnai.domain.interaction import WorkStatus
from tests.adapters.tutor.test_adapter_engine import draft
from tests.domain.test_engine import CLUSTER, build

pytestmark = [pytest.mark.live, pytest.mark.openai]
ROOT = Path(__file__).resolve().parents[4]
LiveTutor = tuple[OpenAITutor, list[TurnTrace], dict[str, Any]]
CACHE_SOURCE = 'https://developers.openai.com/api/docs/guides/prompt-caching'


@pytest.fixture
def live_tutor(request: pytest.FixtureRequest) -> Iterator[LiveTutor]:
    key = os.environ.get('OPENAI_API_KEY', '')
    if not key.strip():
        pytest.skip('OPENAI_API_KEY absent; live compatibility has not been verified')
    path = ROOT / 'config/llm_routes.yaml'
    route = load_routes(path)['tutor_openai']
    config = resolve_config(route, role='tutor', profiles=load_budget_profiles(path),
                            prompts_root=PROMPTS_ROOT)
    traces: list[TurnTrace] = []
    measurements: dict[str, Any] = {
        'test': request.node.nodeid, 'provider': 'openai', 'requested_model': route.model,
        'sdk_version': version('openai'), 'transport_version': version('httpx2'),
        'cache_prerequisites_checked_at': '2026-10-27', 'cache_source': CACHE_SOURCE,
        'cache_minimum_visible_tokens': 1024,
        'cache_minimum_status': 'documented minimum; actual prefix eligibility unverified',
        'cache_options': config.effective_settings['prompt_cache_options'],
        'budget_profile': route.budget_profile, 'budget': asdict(config.profile),
    }
    with OpenAI(api_key=key, max_retries=0) as client:
        tutor = OpenAITutor(config, client, GeneratorRegistry(QUADRATICS_TEMPLATES),
                            CLUSTER.misconceptions, trace_sink=traces.append)
        try:
            yield tutor, traces, measurements
        finally:
            directory = ROOT / 'eval/reports' / ('live-openai-' + str(uuid4()))
            directory.mkdir(parents=True, mode=0o700)
            artifact = directory / 'measurements.json'
            artifact.write_text(json.dumps({**measurements, 'traces': [t.to_dict() for t in traces]},
                                           ensure_ascii=False, indent=2), encoding='utf-8')
            artifact.chmod(0o600)
            print(f'Private live measurements: {artifact}')


def _assert_accepted_protocol(tutor: OpenAITutor, trace: TurnTrace) -> None:
    reason = trace.termination_reason.value if trace.termination_reason else 'unclassified'
    assert trace.accepted is not None, (
        f'No accepted buffered turn: outcome={reason}, elapsed={trace.elapsed_seconds:.3f}s; '
        'inspect the private trace for exhaustion/provider/validation failure')
    assert trace.termination_reason is TerminationReason.ACCEPTED
    assert trace.validation_results and trace.validation_results[-1].accepted
    route = tutor.config.route
    assert trace.provider == 'openai' and trace.api_family == 'responses'
    assert trace.model == route.model and trace.prompt_ids == (route.prompt,)
    assert trace.settings == tutor.config.effective_settings
    assert trace.provider_requests and trace.provider_responses and trace.usages
    assert len(trace.attempts) == len(trace.provider_requests) == trace.model_calls
    for payload in trace.provider_requests:
        assert payload['model'] == route.model and payload['stream'] is route.stream
        assert payload['store'] is False and 'previous_response_id' not in payload
        assert payload['include'] == ['reasoning.encrypted_content']
        assert payload['truncation'] == 'disabled'
        assert payload['reasoning'] == tutor.config.effective_settings['reasoning']
        assert payload['text']['format']['strict'] is True
        assert 0 < payload['max_output_tokens'] <= route.max_tokens
        assert payload['input'][0]['content'] == trace.initial_context
        assert payload['tool_choice'] in {'auto', 'none'}
        for name, value in tutor.config.effective_settings.items():
            assert payload[name] == value
        assert 'api_profile' not in payload
    for previous, current in zip(trace.provider_requests, trace.provider_requests[1:]):
        assert current['input'][:len(previous['input'])] == previous['input']
    for attempt in trace.attempts:
        if attempt.response is not None:
            response = attempt.response
            assert response['object'] == 'response' and response['status'] == 'completed'
            assert response['model'] and response['output'] and response['usage']
            assert attempt.response_model == response['model']
            index = attempt.request_index
            if index + 1 < len(trace.provider_requests):
                inputs = trace.provider_requests[index + 1]['input']
                offset = len(trace.provider_requests[index]['input'])
                assert inputs[offset:offset + len(response['output'])] == response['output']
    assert [item['call_id'] for item in trace.messages if item.get('type') == 'function_call'] == [
        item['call_id'] for item in trace.messages if item.get('type') == 'function_call_output']


def _cache_reads(trace: TurnTrace) -> int:
    return sum((usage.get('input_tokens_details') or {}).get('cached_tokens', 0) or 0
               for usage in trace.usages)


def test_repeated_stable_prefix_records_provider_cache_reads(live_tutor: LiveTutor) -> None:
    tutor, traces, measurements = live_tutor
    options = tutor.config.effective_settings
    assert options.get('prompt_cache_key') and options.get('prompt_cache_options') == {
        'mode': 'implicit', 'ttl': '30m'}, (
        'Recheck configured-model cache support/retention and stable routing key before this probe')
    engine, session, _ = build(tutor)
    question = draft(session)
    session, _ = engine.ask_question(session, {}, question)
    first = traces[-1]
    _assert_accepted_protocol(tutor, first)
    # Complete the first exchange before reuse. No parallel warmup or extra calls.
    session, _ = engine.ask_question(session, {}, replace(question, revision=1, status=WorkStatus.REVISED))
    second = traces[-1]
    _assert_accepted_protocol(tutor, second)
    a, b = first.provider_requests[0], second.provider_requests[0]
    for name in ('model', 'instructions', 'tools', 'text', 'reasoning', 'prompt_cache_key',
                 'prompt_cache_options', 'service_tier'):
        assert a.get(name) == b.get(name), f'Cache-relevant {name} changed before sequential reuse'
    assert a['input'][0]['content'] != b['input'][0]['content']
    measurements['first_cache_read_tokens'] = _cache_reads(first)
    measurements['repeat_cache_read_tokens'] = _cache_reads(second)
    assert measurements['repeat_cache_read_tokens'] > 0, (
        'Cache prerequisite/read gate unmet: no provider-reported repeat cached_tokens. '
        'The documented minimum is 1,024 visible input tokens, excluding hidden system tokens; '
        'the byte admission counter cannot prove cacheable prefix length. Inspect reusable '
        'prefix length, tools/schema/effort, model support, TTL, routing and '
        'account/cache availability. A miss alone does not diagnose volatile-prefix leakage.')
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
