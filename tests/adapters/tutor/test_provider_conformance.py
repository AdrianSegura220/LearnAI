"""The same real-engine behavior through both official SDK-scripted providers."""
from dataclasses import replace
import json

import pytest

from learnai.adapters.tutor.configuration import schema_hash
from learnai.adapters.tutor.runtime import TerminationReason
from learnai.adapters.tutor.tools import tool_definitions
from learnai.domain.enums import Confidence, HelpRung, Verdict
from learnai.domain.events import AttemptRecorded
from learnai.domain.history import HistoryKind
from learnai.domain.ids import SessionId, StudentId
from learnai.domain.interaction import ResponseJob, WorkStatus
from learnai.domain.items import Submission
from learnai.domain.turn import RejectionReason
from tests.adapters.tutor import test_adapter_engine as regressions
from tests.domain.test_engine import right
from tests.eval.test_provider_admission import corpus_packets, dependencies
from tests.support.provider_contracts import prepare_role, provider_route, scripted_engine
from tests.support.scripted_client import Reply, final, tool


@pytest.fixture(params=['anthropic', 'openai'])
def provider_tutor(request):
    harnesses = []

    def make(replies, **kwargs):
        h = scripted_engine(request.param, replies, **kwargs)
        harnesses.append(h)
        return h

    yield make
    for h in harnesses:
        h.sdk.client.close()


def test_current_revised_work_and_unchecked_answer_reach_native_request(provider_tutor):
    h = provider_tutor([final(submit=False)])
    interaction = regressions.draft(h.session, revision=3, status=WorkStatus.REVISED)
    updated, delivered = h.engine.ask_question(h.session, {}, interaction)
    sent = h.context()
    work = sent['moment']['interaction']
    assert work['task_id'] == h.session.current_task.id
    assert work['revision'] == 3 and work['status'] == 'REVISED'
    assert work['steps'] == ['(x-3)(x+4)', 'x^2+4x-3x-12']
    assert work['answer'] == {'fields': ['x^2+x'], 'claims_none': False}
    assert work['question'] == 'Do I combine these middle terms?' and work['referenced_step'] == 1
    assert work['verification'] == {
        'revision': 3, 'steps_checked': True, 'step_diff': None, 'answer_checked': False,
        'answer': 'not checked', 'verdict': None, 'diagnosis': None, 'failed_constraints': []}
    assert sent['moment']['progress'] == {
        'submissions': 0, 'genuine_attempts': 0, 'declines': 0, 'delivered_rungs': [],
        'independence_spent': False, 'last_checked_revision': 3}
    assert sent['active'] == sent['earlier'] == []
    assert updated.history[0].interaction == interaction
    assert updated.history[0].kind is HistoryKind.STUDENT_QUESTION
    assert updated.history[1].message == delivered.message
    assert not any(isinstance(e, AttemptRecorded) for e in h.engine.evidence_log.events())
    assert h.session.history == h.session.transcript == ()
    trace = h.traces[0]
    assert trace.source_ids == (updated.history[0].id,) and trace.accepted == delivered
    assert json.loads(trace.initial_context) == sent
    prepared = prepare_role(h.factory, h.configs[0], context=h.contexts[0], dependencies=h.dependencies)
    assert prepared.payload == h.sdk.requests[0]
    from dataclasses import asdict
    assert h.configs[0].schema_hashes['canonical_read_tools'] == schema_hash([asdict(t) for t in tool_definitions()])


def test_revision_does_not_inherit_stale_verification(provider_tutor):
    h = provider_tutor([final()])
    session, states, outcome = h.engine.submit(h.session, {}, steps=['x+1', 'x+2'],
        answer=Submission.of('0'), confidence=Confidence.UNSURE)
    assert outcome.verdict is Verdict.WRONG and not h.sdk.requests
    original = session.history
    updated, _ = h.engine.ask_question(session, states,
        regressions.draft(session, revision=1, status=WorkStatus.REVISED))
    sent = h.context()
    verification = sent['moment']['interaction']['verification']
    assert verification['revision'] == 1 and verification['answer_checked'] is False
    assert verification['answer'] == 'not checked' and verification['verdict'] is None
    assert verification['step_diff'] is verification['diagnosis'] is None
    assert sent['active'][0]['record']['historical_verdict'] == 'WRONG'
    assert sent['active'][0]['record']['revision'] == 0
    assert updated.history[:len(original)] == original
    assert sum(isinstance(e, AttemptRecorded) for e in h.engine.evidence_log.events()) == 1


@pytest.mark.parametrize('rung', [HelpRung.NONE, HelpRung.NUDGE, HelpRung.NEXT_STEP])
def test_delivered_assistance_spends_cold_credit_at_actual_rung(provider_tutor, rung):
    # Preserve every original state, evidence, mastery and history assertion.
    regressions.test_delivered_task_reply_spends_independence_and_records_actual_rung(provider_tutor, rung)


@pytest.mark.parametrize('replies,reason', [
    ([Reply([], status=400)], TerminationReason.API_ERROR),
    ([Reply([{'type': 'text', 'text': 'not JSON'}])] * 3, TerminationReason.FORMAT_EXHAUSTED),
    ([final('PRIVATE_REJECTED', 'FULL_REVEAL')] * 2, TerminationReason.VALIDATION_EXHAUSTED),
    ([final('PRIVATE_LATE', elapsed=15)], TerminationReason.DEADLINE),
], ids=['api', 'format', 'validation', 'deadline'])
def test_silence_and_rejection_preserve_cold_credit(provider_tutor, replies, reason):
    regressions.test_failed_question_stays_silent_and_preserves_independent_credit(provider_tutor, replies, reason)


def test_multiple_tools_and_private_correction_share_history_deadline_and_budget(provider_tutor):
    h = provider_tutor([final('Earlier delivered hint.'),
        Reply([tool('check_expression', {'expression': 'x+x', 'reference': '2*x'}),
               tool('get_student_summary')], elapsed=1),
        final('PRIVATE_REJECTED', 'FULL_REVEAL', elapsed=2),
        final('Compare your middle terms.', elapsed=3)])
    session, _ = h.engine.request_help(h.session, {})
    history, transcript = session.history, session.transcript
    updated, turn = h.engine.ask_question(session, {}, regressions.draft(session, revision=1))
    requests = h.sdk.requests[1:]
    assert len(requests) == 3
    assert [max(t.values()) for t in h.sdk.timeouts[1:]] == [15, 14, 12]
    assert [h.context(i) for i in range(1, 4)] == [h.context(1)] * 3
    assert [entry['record_id'] for entry in h.context(1)['active']] == [r.id for r in history]
    assert h.context(1)['moment']['progress']['delivered_rungs'] == ['NUDGE']
    paired = h.results(3)
    assert [identifier for identifier, _ in paired[:2]] == ['tool-2-0', 'tool-2-1']
    assert paired[0][1]['equivalent'] is True
    assert 'RUNG_EXCEEDED' in json.dumps(requests[-1])
    if h.provider == 'anthropic':
        assert paired[2][0] == 'tool-3-0'
        assert regressions.tool_results(requests[-1])[-1]['is_error'] is True
    else:
        assert len(paired) == 2
        assert any(item.get('role') == 'developer' for item in requests[-1]['input'])
    assert turn.message == 'Compare your middle terms.'
    assert updated.history[:len(history)] == history and updated.transcript[:len(transcript)] == transcript
    assert session.history == history
    assert 'PRIVATE_REJECTED' not in str(updated.history) + str(updated.transcript)
    trace = h.traces[-1]
    assert trace.elapsed_seconds == 6 and trace.validation_retries == 1
    assert trace.model_calls == 3 and trace.tool_calls == 2 and trace.output_tokens == 120
    assert [v.accepted for v in trace.validation_results] == [False, True]
    assert trace.validation_results[0].reason is RejectionReason.RUNG_EXCEEDED
    assert trace.termination_reason is TerminationReason.ACCEPTED and trace.accepted == turn


def test_history_retrieval_preserves_scope_and_provenance(provider_tutor):
    h = provider_tutor([Reply([tool('get_session_history'),
        tool('get_session_history', {'skill_id': 'quad.expand.binomial'})]), final('Recall your earlier exercise.')])
    first = h.session.current_task
    session, states, outcome = h.engine.submit(h.session, {}, steps=[], answer=right(first), confidence=Confidence.CERTAIN)
    assert outcome.task_completed and not h.sdk.requests
    assert session.current_task.skill_id != first.skill_id
    earlier = session.history[0]
    foreign_student = replace(earlier, id='foreign-student', student_id=StudentId('other'))
    foreign_session = replace(earlier, id='foreign-session', session_id=SessionId('other'))
    session = replace(session, history=session.history + (foreign_student, foreign_session))
    updated, turn = h.engine.ask_question(session, states, regressions.draft(session,
        steps=('21x+3', '3(7x+1)'), answer=Submission.of('3(7x+1)')))
    browse, filtered = [value['records'] for _, value in h.results(1)]
    assert [record['id'] for record in browse] == [updated.history[-2].id, earlier.id]
    assert [record['id'] for record in filtered] == [earlier.id]
    assert filtered[0]['task_id'] == first.id and filtered[0]['historical_verdict'] == 'CORRECT'
    assert filtered[0]['item_id'] == first.item.id and filtered[0]['revision'] == earlier.revision
    assert filtered[0]['at'] == earlier.at.isoformat()
    assert filtered[0]['kind'] == earlier.kind.name
    assert filtered[0]['related_record_ids'] == list(earlier.related_record_ids)
    assert all(r['skill_id'] == 'quad.expand.binomial' for r in filtered)
    assert not any(r['id'].startswith('foreign-') for r in browse + filtered)
    assert 'foreign-' not in json.dumps(h.sdk.requests[0])
    assert earlier.id in h.traces[0].source_ids
    assert not any(identifier.startswith('foreign-') for identifier in h.traces[0].source_ids)
    assert turn is not None and h.traces[0].tool_calls == 2 and session.history[0] == earlier


def test_disabled_complex_job_has_no_provider_or_session_effects(provider_tutor):
    regressions.test_disabled_complex_job_is_rejected_before_provider_or_session_effects(provider_tutor)


@pytest.mark.parametrize('job,route_name,deadline', [
    (ResponseJob.BRIEF, 'tutor_brief', 8), (ResponseJob.NORMAL, 'tutor_dialogue', 15),
    (ResponseJob.SUBSTANTIAL, 'tutor_explanation', 30)])
def test_engine_response_job_preserves_actual_configured_route(provider_tutor, job, route_name, deadline):
    h = provider_tutor([final(submit=False)])
    _, delivered = h.engine.ask_question(h.session, {}, regressions.draft(h.session), response_job=job)
    assert delivered is not None
    assert h.context()['moment']['response_job'] == job.name
    assert h.traces[0].route_name == route_name
    assert h.configs[0].route.name == route_name
    assert h.traces[0].model == h.sdk.requests[0]['model']
    assert max(h.sdk.timeouts[0].values()) == deadline


def test_help_ladder_stops_before_reveal_without_documented_effort(provider_tutor):
    rungs = ('NUDGE', 'NEXT_STEP', 'NAME_METHOD')
    h = provider_tutor([final('Delivered ' + rung, rung) for rung in rungs])
    session = h.session
    for index, rung in enumerate(rungs):
        session, delivered = h.engine.request_help(session, {})
        assert delivered.rung_used.name == rung
        assert h.context(index)['moment']['permitted_rung'] == rung
        assert h.context(index)['moment']['progress']['delivered_rungs'] == list(rungs[:index])
    prior = session
    session, delivered = h.engine.request_help(session, {})
    assert delivered is None and session == prior
    assert len(h.sdk.requests) == 3
    assert [r.name for r in session.current_task.help_state.rungs_used] == list(rungs)
    assert session.current_task.help_state.attempts == 0


def test_documented_attempts_and_delivered_ladder_unlock_reveal(provider_tutor):
    h = provider_tutor([final(rung=rung) for rung in
        ('NUDGE', 'NUDGE', 'NEXT_STEP', 'NAME_METHOD', 'FULL_REVEAL')])
    session, states = h.session, {}
    for _ in range(2):
        session, states, outcome = h.engine.submit(session, states, steps=[],
            answer=Submission.of('0'), confidence=Confidence.UNSURE)
        assert outcome.verdict is Verdict.WRONG and outcome.tutor_turn.rung_used is HelpRung.NUDGE
    for rung in (HelpRung.NEXT_STEP, HelpRung.NAME_METHOD, HelpRung.FULL_REVEAL):
        session, delivered = h.engine.request_help(session, states)
        assert delivered.rung_used is rung
    assert session.current_task.help_state.attempts == 2
    assert h.context(4)['moment']['permitted_rung'] == 'FULL_REVEAL'
    assert h.context(4)['moment']['progress']['delivered_rungs'] == ['NUDGE', 'NUDGE', 'NEXT_STEP', 'NAME_METHOD']
    assert len(h.sdk.requests) == 5


def test_api_tools_format_and_validation_exhaust_one_finite_budget(provider_tutor):
    from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES
    profiles = {**DEFAULT_BUDGET_PROFILES,
                'normal': replace(DEFAULT_BUDGET_PROFILES['normal'], max_round_trips=4)}
    h = provider_tutor([Reply([], status=500),
        Reply([tool('get_student_summary'), tool('get_session_history')]),
        Reply([{'type': 'text', 'text': 'not JSON'}]),
        final('PRIVATE_REJECTED', 'FULL_REVEAL', submit=False),
        final('UNREACHABLE')], profiles=profiles)
    session, delivered = h.engine.ask_question(h.session, {}, regressions.draft(h.session))
    assert delivered is None and session.current_task.help_state == h.session.current_task.help_state
    assert h.engine.evidence_log.events() == ()
    assert len(h.sdk.requests) == 4 and len(h.sdk.replies) == 1
    trace = h.traces[0]
    assert trace.model_calls == 4 and trace.tool_calls == 2
    assert trace.api_retries == trace.format_retries == trace.validation_retries == 1
    assert trace.termination_reason is TerminationReason.ROUND_TRIP_LIMIT
    assert trace.accepted is None
    assert [v.accepted for v in trace.validation_results] == [False]
    assert 'PRIVATE_REJECTED' not in str(session.history) + str(session.transcript)


@pytest.mark.parametrize('profile_source', ['checked-in', 'defaults'])
def test_largest_corpus_preparations_match_native_tutor_and_judge_requests(
        provider_tutor, corpus_packets, profile_source):
    from learnai.adapters.tutor.prompts import PROMPTS_ROOT
    from learnai.adapters.tutor.routing import load_budget_profiles, load_routes
    from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES
    from learnai.eval.judge import SCORE_SCHEMA
    from tests.eval.test_judge import ScriptedJudge, reply, score_data
    from tests.support.provider_contracts import ROOT
    from tests.support.scripted_openai import ResponseReply, ScriptedOpenAI, message

    packet = next(packet for scenario, packet in corpus_packets if scenario.id == 'ladder-long-conversation')
    profiles = (load_budget_profiles(ROOT / 'config/llm_routes.yaml')
                if profile_source == 'checked-in' else DEFAULT_BUDGET_PROFILES)
    h = provider_tutor([final()], profiles=profiles)
    assert h.tutor.respond(packet.context) is not None
    prepared = prepare_role(h.factory, h.configs[0], context=packet.context, dependencies=h.dependencies)
    assert prepared.payload == h.sdk.requests[0] == h.traces[0].provider_requests[0]
    wire = h.sdk.requests[0]
    output_schema = (wire['text']['format']['schema'] if h.provider == 'openai'
                     else wire['output_config']['format']['schema'])
    wire_tools = wire['tools'] if h.provider == 'openai' else wire['tools'][:-1]
    assert h.configs[0].schema_hashes['final_output'] == schema_hash(output_schema)
    assert h.configs[0].schema_hashes['wire_read_tools'] == schema_hash(wire_tools)
    routes = load_routes(ROOT / 'config/llm_routes.yaml')
    judge_config = h.factory.resolve_config(provider_route(routes['rubric_judge'], h.provider),
        role='judge', profiles=profiles, prompts_root=PROMPTS_ROOT)
    prepared_judge = prepare_role(h.factory, judge_config, packet=packet)
    sdk = (ScriptedJudge([reply()]) if h.provider == 'anthropic'
           else ScriptedOpenAI([ResponseReply([message(json.dumps(score_data()))])]))
    traces = []
    try:
        judge = h.factory.create_judge(config=judge_config, client=sdk.client, trace_sink=traces.append)
        assert judge.evaluate(packet).mathematics == 2
        requests = sdk.wire_requests if h.provider == 'anthropic' else sdk.requests
        assert prepared_judge.payload == requests[0] == traces[0].provider_requests[0]
        assert traces[0].route_name == 'rubric_judge'
        assert judge_config.schema_hashes == {'final_output': schema_hash(SCORE_SCHEMA)}
    finally:
        sdk.client.close()
