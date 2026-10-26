from dataclasses import replace
import json
import pytest

from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.openai.adapter import OpenAITutor
from learnai.adapters.tutor.openai.config import resolve_config
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.routing import Route
from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES, TerminationReason
from learnai.domain.turn import RejectionReason, TurnFeedback, ValidationResult
from tests.adapters.tutor.test_rendering import make_context, record
from tests.domain.test_engine import build
from tests.domain.test_interaction import question
from tests.support.scripted_openai import ResponseReply, ScriptedOpenAI, call, final, message, usage

PROFILE = DEFAULT_BUDGET_PROFILES['normal']
OPAQUE = {'type': 'reasoning', 'id': 'rs-a', 'summary': [], 'encrypted_content': 'opaque=='}


def setup(replies, *, profile=PROFILE, stream=False, count_tokens=lambda s: len(s)//4, options=None):
    route = Route('tutor_selected', 'openai', 'scripted', effort='low', prompt='tutor_math@1',
        stream=stream, provider_options=options or {})
    config = resolve_config(route, role='tutor', profiles={'normal': profile}, prompts_root=PROMPTS_ROOT)
    sdk, traces = ScriptedOpenAI(replies), []
    tutor = OpenAITutor(config, sdk.client.with_options(max_retries=8), GeneratorRegistry(()), {},
        monotonic=sdk.clock, sleep=sdk.clock.sleep, count_tokens=count_tokens, trace_sink=traces.append)
    return tutor, sdk, traces


def results(request):
    return [i for i in request['input'] if i.get('type') == 'function_call_output']


def test_final_structured_response_matches_wire_and_shared_parser():
    tutor, sdk, traces = setup([final()])
    assert tutor.respond(make_context()).message == 'Compare your two lines.'
    req, trace = sdk.requests[0], traces[0]
    assert req['store'] is False and req['include'] == ['reasoning.encrypted_content']
    assert 'previous_response_id' not in req and 'max_tokens' not in req
    assert req['text']['format']['type'] == 'json_schema'
    assert req['text']['format']['strict'] is True
    assert set(req['text']['format']['schema']['required']) == {'message','rung_used','diagnosis','proposals'}
    assert all(t['type'] == 'function' and t['strict'] is True for t in req['tools'])
    assert {t['name'] for t in req['tools']} == {'check_expression','get_worked_example',
        'lookup_misconception','get_student_summary','get_session_history'}
    assert trace.provider == 'openai' and trace.api_family == 'responses'
    assert trace.route_name == 'tutor_selected' and trace.accepted.message == 'Compare your two lines.'
    assert trace.provider_requests == sdk.requests
    assert trace.to_dict()['attempts'][0]['normalized_usage']['counts'] == {'input':80,'cache_read':20,'output':40}
    assert trace.attempts[0].provider_request_id == 'req-1'
    assert tutor.client.max_retries == 0


def test_two_distinct_calls_preserve_opaque_items_and_order_through_engine_correction():
    outputs = [OPAQUE, call('check_expression', {'expression':'x','reference':None}),
        call('get_student_summary', call_id='call-b', id='fc-b')]
    tutor, sdk, traces = setup([ResponseReply(outputs), final('PRIVATE', 'FULL_REVEAL'), final('Try this line.')])
    engine, session, _ = build(tutor)
    updated, delivered = engine.ask_question(session, {}, question(session.current_task))
    assert delivered.message == 'Try this line.'
    assert sdk.requests[1]['input'][1:4] == outputs
    assert [i['call_id'] for i in results(sdk.requests[2])] == ['call-a','call-b']
    assert json.loads(results(sdk.requests[1])[0]['output'])['scope'] == 'active_item_answer'
    assert 'RUNG_EXCEEDED' in json.dumps(sdk.requests[2]['input'])
    assert sdk.requests[0]['instructions'] == sdk.requests[2]['instructions']
    assert 'PRIVATE' not in str(updated.history)
    assert [v.accepted for v in traces[0].validation_results] == [False,True]
    assert traces[0].validation_retries == 1


def test_optional_history_nulls_are_removed_but_invalid_false_zero_empty_are_preserved():
    nulls = {k:None for k in ('task_id','skill_id','item_id','kind','after','before','before_id','limit')}
    tutor, sdk, traces = setup([ResponseReply([call('get_session_history', nulls)]), final()])
    assert tutor.respond(make_context(history=(record('one'),))) is not None
    assert json.loads(results(sdk.requests[1])[0]['output'])['records'][0]['id'] == 'one'
    for value in (False, 0, ''):
        tutor, sdk, traces = setup([ResponseReply([call('get_session_history', {**nulls,'limit':value})]), final()])
        assert tutor.respond(make_context()) is not None
        assert json.loads(results(sdk.requests[1])[0]['output'])['code'] == 'invalid_arguments'


def test_required_null_tool_arguments_remain_errors():
    tutor, sdk, _ = setup([ResponseReply([call('check_expression', {'expression':None,'reference':None})]),final()])
    assert tutor.respond(make_context()) is not None
    assert json.loads(results(sdk.requests[1])[0]['output'])['code'] == 'invalid_arguments'


@pytest.mark.parametrize('reply,reason', [
    (ResponseReply([{'type':'message','id':'msg-r','role':'assistant','status':'completed',
        'content':[{'type':'refusal','refusal':'No'}]}]),TerminationReason.REFUSAL),
    (final(status='incomplete'),TerminationReason.TRUNCATED),
    (ResponseReply(status='failed'),TerminationReason.API_ERROR),
])
def test_unusable_responses_consume_no_assistance(reply, reason):
    tutor, sdk, traces = setup([reply])
    engine, session, _ = build(tutor)
    updated, delivered = engine.ask_question(session, {}, question(session.current_task))
    assert delivered is None and updated.current_task.help_state == session.current_task.help_state
    assert traces[0].termination_reason is reason and traces[0].accepted is None
    assert len(sdk.requests) == 1


@pytest.mark.parametrize('output', [[], [message('')], [message('invalid json')], [message('[]')]])
def test_empty_and_malformed_outputs_have_at_most_two_format_retries(output):
    tutor, sdk, traces = setup([ResponseReply(output) for _ in range(4)])
    assert tutor.respond(make_context()) is None
    assert len(sdk.requests) == 3
    assert traces[0].format_retries == 2 and traces[0].termination_reason is TerminationReason.FORMAT_EXHAUSTED


@pytest.mark.parametrize('reply', [ResponseReply(http_status=500),ResponseReply(connection_error=True)])
def test_pre_response_failures_retry_with_one_budget_and_attempt_per_wire_request(reply):
    tutor, sdk, traces = setup([reply,final()])
    assert tutor.respond(make_context()) is not None
    trace = traces[0]
    assert len(trace.attempts) == len(sdk.requests) == trace.model_calls == 2
    assert trace.api_retries == 1 and trace.attempts[0].normalized_usage.counts == {}
    assert trace.attempts[0].usage_status.value == 'missing'
    assert trace.attempts[1].retry


def test_api_attempts_and_shared_round_trip_limit_bound_all_retry_layers():
    tutor, sdk, traces = setup([ResponseReply(http_status=500)]*5)
    assert tutor.respond(make_context()) is None
    assert len(sdk.requests) == 3 and traces[0].termination_reason is TerminationReason.NETWORK_EXHAUSTED
    tutor, sdk, traces = setup([ResponseReply(http_status=500)]*5,
        profile=replace(PROFILE,max_round_trips=2))
    assert tutor.respond(make_context()) is None
    assert len(sdk.requests) == 2 and traces[0].termination_reason is TerminationReason.ROUND_TRIP_LIMIT


def test_bad_request_is_not_retried():
    tutor, sdk, traces = setup([ResponseReply(http_status=400)])
    assert tutor.respond(make_context()) is None
    assert len(sdk.requests) == 1 and traces[0].termination_reason is TerminationReason.API_ERROR


@pytest.mark.parametrize('kwargs,reply,reason', [
    ({'profile':replace(PROFILE,context_input_tokens=100),'count_tokens':len},final(),TerminationReason.CONTEXT_LIMIT),
    ({},final(usage=usage(output_tokens=9000)),TerminationReason.OUTPUT_LIMIT),
    ({},final(elapsed=16),TerminationReason.DEADLINE),
])
def test_context_output_and_deadline_exhaustion(kwargs, reply, reason):
    tutor, sdk, traces = setup([reply], **kwargs)
    assert tutor.respond(make_context()) is None
    assert traces[0].termination_reason is reason
    assert len(sdk.requests) == (0 if reason is TerminationReason.CONTEXT_LIMIT else 1)


def test_soft_threshold_settles_tools_then_disables_exploration():
    tutor, sdk, traces = setup([ResponseReply([OPAQUE,call('get_student_summary')],elapsed=9),final()])
    assert tutor.respond(make_context()) is not None
    assert sdk.requests[1]['tool_choice'] == 'none' and sdk.requests[1]['tools'] == sdk.requests[0]['tools']
    assert json.loads(results(sdk.requests[1])[0]['output'])['code'] == 'exploration_exhausted'
    assert traces[0].tool_calls == 0


def test_successful_stream_retains_output_items_without_reordering():
    tutor, sdk, traces = setup([ResponseReply([OPAQUE,call('get_student_summary')]),final()],stream=True)
    assert tutor.respond(make_context()) is not None
    assert sdk.requests[1]['input'][1:3] == [OPAQUE,call('get_student_summary')]
    assert all(s.closed for s in sdk.streams)
    assert len(traces[0].attempts) == 2 and traces[0].output_tokens == 80


@pytest.mark.parametrize('disconnect',[True,False])
def test_partial_stream_never_replays_and_retains_observed_usage(disconnect):
    raw = {'id':'resp-p','model':'scripted','status':'in_progress','output':[], 'usage':usage(output_tokens=2)}
    reply = ResponseReply(events=[{'type':'response.created','sequence_number':0,'response':raw},
        {'type':'response.output_text.delta','sequence_number':1,'item_id':'msg-a','output_index':0,
         'content_index':0,'delta':'PRIVATE_PARTIAL','logprobs':[]}],disconnect=disconnect)
    tutor, sdk, traces = setup([reply,final()],stream=True)
    assert tutor.respond(make_context()) is None
    trace = traces[0]
    assert len(sdk.requests) == len(trace.attempts) == 1
    assert trace.termination_reason is TerminationReason.NETWORK_EXHAUSTED
    assert trace.attempts[0].usage_status.value == 'partial' and trace.output_tokens == 2
    assert sdk.streams[0].closed and trace.accepted is None


def test_usage_conditions_from_actual_transport_prefer_returned_and_keep_missing_unknown():
    tutor, _, traces = setup([final(metadata={'service_tier':'flex'})],options={'service_tier':'default'})
    assert tutor.respond(make_context()) is not None
    condition = traces[0].attempts[0].normalized_usage.billing_conditions['service_tier']
    assert condition.value == 'flex' and condition.source == 'returned' and 'mismatch' in condition.evidence
    tutor, _, traces = setup([final(metadata={})])
    assert tutor.respond(make_context()) is not None
    assert traces[0].attempts[0].normalized_usage.billing_conditions['service_tier'].source == 'unknown'


def test_final_only_round_never_dispatches_unrequested_exploration():
    tutor, sdk, traces = setup([ResponseReply([call('get_student_summary')])],
        profile=replace(PROFILE,max_round_trips=1))
    assert tutor.respond(make_context()) is None
    assert sdk.requests[0]['tool_choice'] == 'none'
    assert traces[0].tool_calls == 0
    assert json.loads(traces[0].tool_results[0]['output'])['code'] == 'exploration_exhausted'
    assert traces[0].termination_reason is TerminationReason.ROUND_TRIP_LIMIT


def test_deadline_during_tool_settles_remaining_calls_and_never_continues(monkeypatch):
    from learnai.adapters.tutor.tools import Toolbox
    tutor, sdk, traces = setup([ResponseReply([call('get_student_summary'),
        call('get_student_summary',call_id='call-b',id='fc-b')])])
    original = Toolbox.execute
    def slow(self, name, arguments, context):
        sdk.clock.advance(16)
        return original(self,name,arguments,context)
    monkeypatch.setattr(Toolbox,'execute',slow)
    assert tutor.respond(make_context()) is None
    assert len(sdk.requests) == 1 and traces[0].tool_calls == 1
    assert traces[0].termination_reason is TerminationReason.DEADLINE
    assert len(traces[0].tool_results) == 2
    assert json.loads(traces[0].tool_results[1]['output'])['code'] == 'exploration_exhausted'


def test_deadline_during_validation_suppresses_engine_accepted_draft(monkeypatch):
    import learnai.domain.turn as domain_turn
    tutor,sdk,traces = setup([final()])
    original = domain_turn.validate_turn
    def slow(*args):
        result = original(*args)
        sdk.clock.advance(16)
        return result
    monkeypatch.setattr(domain_turn,'validate_turn',slow)
    engine,session,_ = build(tutor)
    updated,turn = engine.ask_question(session,{},question(session.current_task))
    assert turn is None and updated.current_task.help_state == session.current_task.help_state
    assert traces[0].validation_results[0].accepted and traces[0].accepted is None
    assert traces[0].termination_reason is TerminationReason.DEADLINE


def test_independent_exchanges_retain_only_their_own_current_session_history():
    tutor,sdk,traces = setup([final('PRIVATE_A','FULL_REVEAL'),
        ResponseReply([call('get_session_history')]),final('B response'),
        ResponseReply([call('get_session_history',call_id='call-c',id='fc-c')]),final('A response')])
    a = make_context(history=(record('a',message='A_HISTORY'),))
    b = replace(a, history_scope=replace(a.history_scope, student_id='b',session_id='b-session'),
        history=(replace(record('b',message='B_HISTORY'),student_id='b',session_id='b-session'),))
    ea,eb = tutor.begin_turn(a),tutor.begin_turn(b)
    rejected = ea.respond()
    ea.record_validation(ValidationResult(False,RejectionReason.RUNG_EXCEEDED))
    accepted_b = eb.respond()
    eb.finish(accepted=accepted_b,reason='accepted')
    accepted_a = ea.respond(feedback=TurnFeedback(RejectionReason.RUNG_EXCEEDED,None,rejected))
    ea.finish(accepted=accepted_a,reason='accepted')
    assert 'A_HISTORY' not in json.dumps(sdk.requests[2])
    assert 'B_HISTORY' not in json.dumps(sdk.requests[4])
    assert [t.model_calls for t in traces] == [2,3]
    assert traces[0].request_id != traces[1].request_id


def test_full_continuation_including_tool_results_is_admitted_before_next_wire_request():
    def counter(text):
        return 100000 if 'LARGE_TOOL_REPLY' in text else len(text)//4
    tutor,sdk,traces = setup([ResponseReply([call('get_session_history')])],count_tokens=counter)
    assert tutor.respond(make_context(history=(record('older',task='old',message='LARGE_TOOL_REPLY'),))) is None
    assert len(sdk.requests) == 1 and traces[0].termination_reason is TerminationReason.CONTEXT_LIMIT


@pytest.mark.parametrize('arguments', [None, [], {'expression':'x','reference':''}])
def test_invalid_tool_arguments_produce_matched_error_without_silently_dropping_values(arguments):
    item = call('check_expression',{'expression':'x'})
    item['arguments'] = json.dumps(arguments)
    tutor,sdk,traces = setup([ResponseReply([item]),final()])
    assert tutor.respond(make_context()) is not None
    assert results(sdk.requests[1])[0]['call_id'] == 'call-a'
    assert json.loads(results(sdk.requests[1])[0]['output'])['code'] == 'invalid_arguments'


def test_missing_usage_remains_unknown_while_local_budget_reserves_maximum_output():
    tutor,sdk,traces = setup([final(usage=None)])
    assert tutor.respond(make_context()) is not None
    trace = traces[0]
    assert trace.attempts[0].normalized_usage.counts == {}
    assert trace.attempts[0].usage_status.value == 'missing'
    assert trace.output_tokens == sdk.requests[0]['max_output_tokens']
    assert trace.usages == []


def test_observed_zero_partial_stream_usage_is_partial_and_not_missing():
    raw = {'id':'resp-p','model':'scripted','status':'in_progress','output':[], 'usage':usage(output_tokens=0,reasoning_tokens=0)}
    tutor,sdk,traces = setup([ResponseReply(events=[{'type':'response.created',
        'sequence_number':0,'response':raw}],disconnect=True)],stream=True)
    assert tutor.respond(make_context()) is None
    attempt = traces[0].attempts[0]
    assert attempt.usage_status.value == 'partial' and attempt.normalized_usage.counts['output'] == 0
    assert len(sdk.requests) == 1


def test_expired_stream_closes_and_keeps_observed_partial_usage():
    raw = {'id':'resp-p','model':'scripted','status':'in_progress','output':[], 'usage':usage(output_tokens=2)}
    tutor,sdk,traces = setup([ResponseReply(events=[{'type':'response.created',
        'sequence_number':0,'response':raw}],stream_elapsed=16)],stream=True)
    assert tutor.respond(make_context()) is None
    assert traces[0].termination_reason is TerminationReason.DEADLINE
    assert traces[0].output_tokens == 2 and sdk.streams[0].closed
    assert traces[0].attempts[0].usage_status.value == 'partial'
