"""Strict rubric scores and shared-budget transport using the actual Responses SDK."""
from dataclasses import replace
import json

import pytest

from learnai.adapters.tutor.configuration import schema_hash
from learnai.adapters.tutor.openai.wiring import OpenAIFactory
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.routing import Route
from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES, TerminationReason
from learnai.eval.judge import JudgeError, SCORE_SCHEMA, build_judge_messages
from tests.eval.test_judge import packet, score_data
from tests.support.scripted_openai import ResponseReply, ScriptedOpenAI, message, usage

PROFILE = DEFAULT_BUDGET_PROFILES['normal']


def scored(data=None, **kwargs):
    return ResponseReply([message(json.dumps(score_data() if data is None else data))], **kwargs)


def setup(replies, *, profile=PROFILE, stream=False, counter=lambda text: len(text) // 4, options=None):
    from learnai.adapters.tutor.openai.judge import OpenAIJudge
    factory = OpenAIFactory()
    config = factory.resolve_config(Route('selected_judge', 'openai', 'same-model',
        prompt='rubric_judge@1', stream=stream, provider_options=options or {}),
        role='judge', profiles={'normal': profile}, prompts_root=PROMPTS_ROOT)
    sdk, traces = ScriptedOpenAI(replies), []
    judge = OpenAIJudge(config, sdk.client.with_options(max_retries=9), trace_sink=traces.append,
        monotonic=sdk.clock, count_tokens=counter, sleep=sdk.clock.sleep)
    return judge, sdk, traces


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('status', ['completed', 'failed'])
def test_native_judge_current_preflight_and_nested_usage_survive_sdk(stream, status):
    from tests.support.scripted_openai import mixed_cache_usage
    raw = mixed_cache_usage()
    judge, sdk, traces = setup([scored(usage=raw, status=status, metadata={})], stream=stream,
        options={'api_profile': 'reasoning', 'prompt_cache_options': {'ttl': '12h'}})
    prepared = OpenAIFactory().prepare_judge(judge.config, packet=packet())
    if status == 'completed':
        assert judge.evaluate(packet()).mathematics == 2
    else:
        with pytest.raises(JudgeError, match='api_error'):
            judge.evaluate(packet())
    assert prepared.admitted and prepared.payload == sdk.requests[0]
    assert sdk.requests[0]['reasoning'] == {'effort': 'low'}
    assert sdk.requests[0]['prompt_cache_options'] == {'mode': 'implicit', 'ttl': '12h'}
    assert 'api_profile' not in sdk.requests[0]
    attempt = traces[0].attempts[0]
    assert attempt.usage == raw and attempt.response['usage'] == raw
    assert attempt.normalized_usage.counts == {'input': 1000, 'cache_read': 4000,
        'cache_write_30m': 3000, 'cache_write_12h': 4000, 'output': 200}
    assert attempt.normalized_usage.details['mapper_version'] == judge.config.usage_mapper_id == 'openai-responses@2'
    assert attempt.normalized_usage.billing_conditions['service_tier'].source == 'unknown'
    assert attempt.normalized_usage.billing_conditions['inference_geo'].source == 'unknown'


@pytest.mark.parametrize('stream', [False, True])
def test_packet_schema_policy_and_first_preparation_match_real_request(stream):
    judge, sdk, traces = setup([scored()], stream=stream)
    p = packet()
    prepared = OpenAIFactory().prepare_judge(judge.config, packet=p)
    result = judge.evaluate(p)
    assert result.mathematics == 2
    body = sdk.requests[0]
    assert prepared.admitted and prepared.payload == body
    assert prepared.output_reservation == body['max_output_tokens']
    assert json.loads(body['input'][0]['content']) == json.loads(build_judge_messages(p)[0]['content'])
    assert body['instructions'] == judge.config.prompt.text
    assert 'tools' not in body and 'tool_choice' not in body
    assert body['text']['format'] == {'type': 'json_schema', 'name': 'rubric_scores',
                                      'strict': True, 'schema': SCORE_SCHEMA}
    assert judge.config.schema_hashes == {'final_output': schema_hash(SCORE_SCHEMA)}
    trace = traces[0]
    assert (trace.provider, trace.api_family, trace.route_name) == ('openai', 'responses', 'selected_judge')
    assert trace.termination_reason is TerminationReason.COMPLETED
    assert trace.attempts[0].normalized_usage.counts == {'input': 80, 'cache_read': 20, 'output': 40}
    assert trace.provider_requests == sdk.requests and trace.model_calls == 1
    assert judge.client.max_retries == 0


def test_evidence_abstention_is_a_valid_judgment():
    data = score_data()
    data.update(mathematics=None, help_level=None, diagnosis=None, tone=None,
                status='insufficient_evidence', missing_information=['reference'])
    judge, _, _ = setup([scored(data)])
    assert judge.evaluate(packet()).status == 'insufficient_evidence'


@pytest.mark.parametrize('change', [dict(mathematics=True), dict(tone=3), dict(extra='invalid'),
    dict(reasons=[]), dict(status='insufficient_evidence'), dict(mathematics=None)])
def test_invalid_semantics_retry_then_fail_with_retained_usage(change):
    data = score_data()
    data.update(change)
    judge, sdk, traces = setup([scored(data)] * 3)
    with pytest.raises(JudgeError, match='format_exhausted'):
        judge.evaluate(packet())
    trace = traces[0]
    assert len(sdk.requests) == trace.model_calls == 3
    assert trace.format_retries == 2 and trace.output_tokens == 120
    assert len(trace.usages) == 3
    assert sdk.requests[1]['input'][1] == sdk.responses[0]['output'][0]
    assert sdk.requests[1]['input'][2]['role'] == 'developer'
    assert 'invalid_format' in sdk.requests[1]['input'][2]['content']
    assert sdk.requests[0]['instructions'] == sdk.requests[2]['instructions']


@pytest.mark.parametrize('profile,expected_calls,reason', [
    (replace(PROFILE, max_round_trips=2), 2, 'round_trip_limit'),
    (replace(PROFILE, max_output_tokens=60, finalization_reserve_tokens=10), 3, 'output_limit'),
])
def test_api_and_format_retries_share_budget(profile, expected_calls, reason):
    judge, sdk, traces = setup([scored({'invalid': True}), ResponseReply(http_status=500), scored()], profile=profile)
    with pytest.raises(JudgeError, match=reason):
        judge.evaluate(packet())
    assert len(sdk.requests) == expected_calls
    assert traces[0].format_retries == 1
    assert all(a.retry for a in traces[0].attempts[1:])


@pytest.mark.parametrize('response,reason', [
    (ResponseReply(http_status=400), 'api_error'),
    (scored(status='incomplete'), 'truncated'),
    (scored(status='failed'), 'api_error'),
    (ResponseReply([{'type':'message', 'id':'r', 'role':'assistant', 'status':'completed',
        'content':[{'type':'refusal', 'refusal':'No'}]}]), 'refusal'),
    (scored(elapsed=16), 'deadline'),
])
def test_operational_failure_always_emits_identified_trace(response, reason):
    judge, sdk, traces = setup([response])
    with pytest.raises(JudgeError, match=reason):
        judge.evaluate(packet())
    assert len(sdk.requests) == len(traces[0].attempts) == 1
    assert traces[0].termination_reason.value == reason
    assert traces[0].provider == 'openai'
    if reason != 'api_error' or response.http_status == 200:
        assert traces[0].output_tokens == 40


def test_context_admission_fails_before_wire_request_but_still_emits_trace():
    judge, sdk, traces = setup([], profile=replace(PROFILE, context_input_tokens=100), counter=len)
    with pytest.raises(JudgeError, match='context_limit'):
        judge.evaluate(packet())
    assert not sdk.requests and traces[0].model_calls == 0


def test_partial_stream_retains_usage_without_replaying():
    raw = {'id':'r', 'model':'same-model', 'object':'response', 'created_at':0,
           'status':'in_progress', 'output':[], 'usage':usage(output_tokens=5)}
    judge, sdk, traces = setup([ResponseReply(events=[{'type':'response.created',
        'sequence_number':0, 'response':raw}], disconnect=True)], stream=True)
    with pytest.raises(JudgeError, match='network_exhausted'):
        judge.evaluate(packet())
    assert len(sdk.requests) == 1 and traces[0].output_tokens == 5
    assert traces[0].attempts[0].usage_status.value == 'partial'


def test_success_after_api_and_format_failure_retains_full_stateless_prefix():
    judge, sdk, traces = setup([ResponseReply(http_status=500), scored({'invalid':True}), scored()])
    assert judge.evaluate(packet()).tone == 2
    trace = traces[0]
    assert len(sdk.requests) == trace.model_calls == 3
    assert trace.api_retries == trace.format_retries == 1
    assert trace.output_tokens == 80
    assert sdk.requests[0] == sdk.requests[1]
    assert sdk.requests[2]['input'][:len(sdk.requests[1]['input'])] == sdk.requests[1]['input']
    assert sdk.clock.sleeps == [0.25]


def test_missing_usage_retains_unknown_billing_and_consumes_output_allowance():
    judge, sdk, traces = setup([scored({'invalid':True}, usage=None)],
        profile=replace(PROFILE, max_output_tokens=2048, finalization_reserve_tokens=100))
    with pytest.raises(JudgeError, match='output_limit'):
        judge.evaluate(packet())
    assert len(sdk.requests) == 1 and traces[0].output_tokens == 2048
    assert traces[0].attempts[0].normalized_usage.counts == {}
    assert traces[0].attempts[0].usage_status.value == 'missing'


def test_unrequested_judge_function_call_is_a_failure_and_never_executed():
    from tests.support.scripted_openai import call
    judge, sdk, traces = setup([ResponseReply([call('get_worked_example')])])
    with pytest.raises(JudgeError, match='unexpected judge output item'):
        judge.evaluate(packet())
    assert len(sdk.requests) == 1 and traces[0].output_tokens == 40
