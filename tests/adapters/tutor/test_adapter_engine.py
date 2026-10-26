"""Keyless integration of engine operations with the actual provider SDK adapter."""
from dataclasses import dataclass, replace
import json
from pathlib import Path

import pytest

from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
from learnai.adapters.tutor.anthropic.routing import load_budget_profiles, load_routes
from learnai.adapters.tutor.runtime import TerminationReason, TurnTrace
from learnai.domain.engine import PracticeEngine
from learnai.domain.enums import Confidence, EvidenceClass, HelpRung, Verdict
from learnai.domain.events import AttemptRecorded, HelpTaken
from learnai.domain.history import HistoryKind
from learnai.domain.ids import SessionId, SkillId, StudentId
from learnai.domain.interaction import (
    InteractionKind, ResponseJob, StudentInteraction, WorkStatus,
)
from learnai.domain.items import Submission
from learnai.domain.session import Session, replace_task
from learnai.domain.turn import RejectionReason
from tests.domain.test_engine import CLUSTER, build, right
from tests.support.scripted_client import Reply, ScriptedAnthropic, final, tool


ROUTES_PATH = Path(__file__).resolve().parents[3] / "config" / "llm_routes.yaml"


@dataclass
class EngineHarness:
    engine: PracticeEngine
    session: Session
    sdk: ScriptedAnthropic
    traces: list[TurnTrace]


@pytest.fixture
def harness():
    clients = []

    def make(replies, *, distinct_routes=False):
        sdk = ScriptedAnthropic(replies)
        clients.append(sdk.client)
        routes = dict(load_routes(ROUTES_PATH))
        if distinct_routes:
            # Synthetic provider labels distinguish selection without pinning model ids.
            for name, model in (("tutor_brief", "scripted-brief"),
                                ("tutor_explanation", "scripted-substantial")):
                routes[name] = replace(routes[name], model=model, max_tokens=5000)
        traces = []
        tutor = AnthropicTutor(
            routes, sdk.client, GeneratorRegistry(QUADRATICS_TEMPLATES),
            CLUSTER.misconceptions, budget_profiles=load_budget_profiles(ROUTES_PATH),
            monotonic=sdk.clock, sleep=sdk.clock.sleep,
            count_tokens=lambda text: len(text) // 4, trace_sink=traces.append,
        )
        engine, session, _ = build(tutor)
        return EngineHarness(engine, session, sdk, traces)

    yield make
    for client in clients:
        client.close()


def draft(session, **changes):
    values = dict(
        task_id=session.current_task.id, revision=session.current_task.work_revision,
        kind=InteractionKind.TASK_QUESTION, status=WorkStatus.DRAFT,
        steps=("(x-3)(x+4)", "x^2+4x-3x-12"), answer=Submission.of("x^2+x"),
        question="Do I combine these middle terms?", referenced_step=1,
    )
    values.update(changes)
    return StudentInteraction(**values)


def context(request):
    return json.loads(request["messages"][0]["content"])


def tool_results(request):
    return [block for message in request["messages"]
            if isinstance(message["content"], list)
            for block in message["content"] if block["type"] == "tool_result"]


def test_draft_question_sends_work_and_selected_step_without_recording_an_attempt(harness):
    h = harness([final(submit=False)])
    interaction = draft(h.session, revision=3, status=WorkStatus.REVISED)
    updated, turn = h.engine.ask_question(h.session, {}, interaction)

    sent = context(h.sdk.requests[0])
    moment = sent["moment"]
    work = moment["interaction"]
    assert work["task_id"] == h.session.current_task.id
    assert work["revision"] == 3 and work["status"] == "REVISED"
    assert work["kind"] == "TASK_QUESTION"
    assert work["steps"] == ["(x-3)(x+4)", "x^2+4x-3x-12"]
    assert work["answer"] == {"fields": ["x^2+x"], "claims_none": False}
    assert work["question"] == "Do I combine these middle terms?"
    assert work["referenced_step"] == 1
    assert work["verification"]["revision"] == 3
    assert work["verification"]["steps_checked"] is True
    assert work["verification"]["step_diff"] is None
    assert work["verification"]["answer_checked"] is False
    assert work["verification"]["answer"] == "not checked"
    assert work["verification"]["verdict"] is None
    assert moment["progress"] == {
        "submissions": 0, "genuine_attempts": 0, "declines": 0,
        "delivered_rungs": [], "independence_spent": False, "last_checked_revision": 3,
    }
    assert moment["response_job"] == "NORMAL"
    assert moment["current_interaction_id"] == updated.history[0].id
    assert sent["active"] == [] and sent["earlier"] == []
    assert h.session.history == () and h.session.transcript == ()
    assert updated.history[0].interaction == interaction
    assert updated.history[0].kind is HistoryKind.STUDENT_QUESTION
    assert updated.history[1].message == turn.message
    assert not any(isinstance(e, AttemptRecorded) for e in h.engine.evidence_log.events())
    assert h.traces[0].initial_context == h.sdk.requests[0]["messages"][0]["content"]
    assert h.traces[0].source_ids == (updated.history[0].id,)
    assert h.traces[0].accepted == turn


def test_tool_and_rejected_submit_retain_delivered_history_and_one_deadline(harness):
    h = harness([
        final("Earlier delivered hint."),
        Reply([tool("check_expression", {"expression": "x+x", "reference": "2*x"})], elapsed=1),
        final("PRIVATE_REJECTED", "FULL_REVEAL", elapsed=2),
        final("Compare your middle terms.", elapsed=3),
    ])
    session, _ = h.engine.request_help(h.session, {})
    original_history, original_transcript = session.history, session.transcript
    updated, turn = h.engine.ask_question(session, {}, draft(session, revision=1))

    requests = h.sdk.requests[1:]
    assert len(requests) == 3
    assert all(request["messages"][0] == requests[0]["messages"][0] for request in requests)
    sent = context(requests[0])
    assert [entry["record_id"] for entry in sent["active"]] == [r.id for r in original_history]
    assert "Earlier delivered hint." in requests[0]["messages"][0]["content"]
    assert sent["moment"]["progress"]["delivered_rungs"] == ["NUDGE"]
    assert [max(timeout.values()) for timeout in h.sdk.timeouts[1:]] == [15, 14, 12]
    results = tool_results(requests[-1])
    assert [result["tool_use_id"] for result in results] == ["tool-2-0", "tool-3-0"]
    assert json.loads(results[0]["content"])["equivalent"] is True
    assert results[1]["is_error"] is True
    assert "RUNG_EXCEEDED" in json.dumps(requests[-1]["messages"])
    assert turn.message == "Compare your middle terms."
    assert updated.history[:len(original_history)] == original_history
    assert updated.transcript[:len(original_transcript)] == original_transcript
    assert "PRIVATE_REJECTED" not in str(updated.history) + str(updated.transcript)
    assert session.history == original_history
    trace = h.traces[-1]
    assert trace.elapsed_seconds == 6 and trace.validation_retries == 1
    assert [result.accepted for result in trace.validation_results] == [False, True]
    assert trace.validation_results[0].reason is RejectionReason.RUNG_EXCEEDED
    assert trace.termination_reason is TerminationReason.ACCEPTED
    assert trace.accepted == turn


@pytest.mark.parametrize("rung", [HelpRung.NONE, HelpRung.NUDGE, HelpRung.NEXT_STEP])
def test_delivered_task_reply_spends_independence_and_records_actual_rung(harness, rung):
    h = harness([final("Compare your middle terms.", rung.name)])
    task = h.session.current_task
    session, turn = h.engine.ask_question(h.session, {}, draft(h.session))

    assert turn.rung_used is rung
    help_state = session.current_task.help_state
    assert help_state.assistance_received and help_state.help_taken
    assert help_state.rungs_used == (() if rung is HelpRung.NONE else (rung,))
    assert help_state.submissions == 0 and help_state.attempts == 0
    events = h.engine.evidence_log.events()
    assert len(events) == 1 and isinstance(events[0], HelpTaken)
    assert events[0].rung is rung
    assert session.history[-1].rung is rung

    _, states, outcome = h.engine.submit(
        session, {}, steps=[], answer=right(task), confidence=Confidence.CERTAIN,
    )
    assert outcome.verdict is Verdict.CORRECT and outcome.task_completed
    assert outcome.evidence_class is EvidenceClass.ASSISTED
    assert states[task.skill_id].strength == 0
    assert h.engine.evidence_log.events()[-1].evidence_class is EvidenceClass.ASSISTED
    assert len(h.sdk.requests) == 1


@pytest.mark.parametrize("replies,reason", [
    ([Reply([], status=400)], TerminationReason.API_ERROR),
    ([Reply([{"type": "text", "text": "not JSON"}])] * 3, TerminationReason.FORMAT_EXHAUSTED),
    ([final("PRIVATE_REJECTED", "FULL_REVEAL")] * 2, TerminationReason.VALIDATION_EXHAUSTED),
    ([final("PRIVATE_LATE", elapsed=15)], TerminationReason.DEADLINE),
], ids=["api", "format", "validation", "deadline"])
def test_failed_question_stays_silent_and_preserves_independent_credit(harness, replies, reason):
    h = harness(replies)
    task = h.session.current_task
    session, turn = h.engine.ask_question(h.session, {}, draft(h.session))

    assert turn is None
    assert not session.current_task.help_state.help_taken
    assert session.current_task.help_state == task.help_state
    assert h.engine.evidence_log.events() == ()
    assert [record.kind for record in session.history] == [HistoryKind.STUDENT_QUESTION]
    assert [entry.speaker for entry in session.transcript] == ["student"]
    assert h.traces[0].termination_reason is reason
    assert h.traces[0].accepted is None
    assert "PRIVATE_" not in str(session.history) + str(session.transcript)

    _, _, outcome = h.engine.submit(
        session, {}, steps=[], answer=right(task), confidence=Confidence.CERTAIN,
    )
    assert outcome.evidence_class is EvidenceClass.UNASSISTED_COLD
    assert outcome.verdict is Verdict.CORRECT
    assert len(h.engine.evidence_log.events()) == 1
    assert isinstance(h.engine.evidence_log.events()[0], AttemptRecorded)
    assert not h.sdk.replies


def test_history_tools_retrieve_earlier_other_skill_with_student_and_session_scope(harness):
    h = harness([
        Reply([tool("get_session_history"),
               tool("get_session_history", {"skill_id": "quad.expand.binomial"})]),
        final("Recall your earlier exercise."),
    ])
    first_task = h.session.current_task
    session, states, outcome = h.engine.submit(
        h.session, {}, steps=[], answer=right(first_task), confidence=Confidence.CERTAIN,
    )
    assert outcome.task_completed and not h.sdk.requests
    assert session.current_task.skill_id != first_task.skill_id
    earlier = session.history[0]
    # Deliberately supply a mixed storage snapshot: either missing scope check leaks a record.
    foreign_student = replace(earlier, id="foreign-student", student_id=StudentId("other"))
    foreign_session = replace(earlier, id="foreign-session", session_id=SessionId("other"))
    session = replace(session, history=session.history + (foreign_student, foreign_session))
    updated, turn = h.engine.ask_question(session, states, draft(
        session, steps=("21x+3", "3(7x+1)"), answer=Submission.of("3(7x+1)"),
    ))

    results = tool_results(h.sdk.requests[1])
    browse, filtered = [json.loads(result["content"])["records"] for result in results]
    question_record = updated.history[-2]
    assert [record["id"] for record in browse] == [question_record.id, earlier.id]
    assert [record["id"] for record in filtered] == [earlier.id]
    assert filtered[0]["task_id"] == first_task.id
    assert filtered[0]["historical_verdict"] == "CORRECT"
    assert all(record["skill_id"] == "quad.expand.binomial" for record in filtered)
    assert not any(record["id"].startswith("foreign-") for record in browse + filtered)
    assert turn is not None
    assert h.traces[0].tool_calls == 2
    assert session.history[0] == earlier


def test_revised_draft_keeps_old_verdict_historical_in_the_actual_request(harness):
    h = harness([final()])
    session, states, outcome = h.engine.submit(
        h.session, {}, steps=["x+1", "x+2"], answer=Submission.of("0"),
        confidence=Confidence.UNSURE,
    )
    assert outcome.verdict is Verdict.WRONG and outcome.tutor_turn is None
    assert not h.sdk.requests  # LET_RUN leaves the first visible error to the student.
    original_history = session.history
    revised = draft(session, revision=1, status=WorkStatus.REVISED)
    updated, _ = h.engine.ask_question(session, states, revised)

    sent = context(h.sdk.requests[0])
    verification = sent["moment"]["interaction"]["verification"]
    assert verification["revision"] == 1
    assert verification["answer_checked"] is False and verification["verdict"] is None
    assert verification["answer"] == "not checked"
    assert verification["step_diff"] is None and verification["diagnosis"] is None
    assert sent["active"][0]["record"]["historical_verdict"] == "WRONG"
    assert sent["active"][0]["record"]["revision"] == 0
    assert updated.history[:len(original_history)] == original_history
    assert sum(isinstance(event, AttemptRecorded) for event in h.engine.evidence_log.events()) == 1


def test_brief_and_substantial_engine_questions_select_distinct_configured_routes(harness):
    h = harness([final("Brief reply."), final("Longer explanation.", submit=False)], distinct_routes=True)
    first = draft(h.session)
    session, brief = h.engine.ask_question(h.session, {}, first, response_job=ResponseJob.BRIEF)
    _, substantial = h.engine.ask_question(
        session, {}, replace(first, question="Explain the method."),
        response_job=ResponseJob.SUBSTANTIAL,
    )

    assert brief is not None and substantial is not None
    a, b = h.sdk.requests
    assert [request["model"] for request in (a, b)] == ["scripted-brief", "scripted-substantial"]
    assert [request["output_config"]["effort"] for request in (a, b)] == ["low", "high"]
    assert [request["thinking"] for request in (a, b)] == [{"type": "adaptive"}] * 2
    assert [context(request)["moment"]["response_job"] for request in (a, b)] == ["BRIEF", "SUBSTANTIAL"]
    # The configured brief output reserve and both profile deadlines reach the SDK.
    assert [request["max_tokens"] for request in (a, b)] == [3584, 5000]
    assert [max(timeout.values()) for timeout in h.sdk.timeouts] == [8, 30]
    assert [trace.model for trace in h.traces] == ["scripted-brief", "scripted-substantial"]
    for trace, request in zip(h.traces, (a, b), strict=True):
        assert trace.settings["model"] == request["model"]
        assert trace.settings["output_config"] == request["output_config"]
        assert trace.prompt_ids == ("tutor_math@1",)
        assert trace.initial_context == request["messages"][0]["content"]
        assert trace.termination_reason is TerminationReason.ACCEPTED


def test_disabled_complex_job_is_rejected_before_provider_or_session_effects(harness):
    h = harness([])
    with pytest.raises(ValueError, match="response job is not enabled"):
        h.engine.ask_question(h.session, {}, draft(h.session), response_job=ResponseJob.COMPLEX)
    assert not h.sdk.requests and not h.traces
    assert h.engine.evidence_log.events() == ()
    assert h.session.history == () and h.session.transcript == ()


def test_decline_uses_engine_no_answer_state_and_records_delivered_help(harness):
    h = harness([final("Start by looking at the factors.")])
    session, _, outcome = h.engine.submit(
        h.session, {}, steps=[], answer=Submission.of(""), confidence=Confidence.NO_IDEA,
    )
    assert outcome.verdict is Verdict.NO_ANSWER and outcome.tutor_turn is not None
    moment = context(h.sdk.requests[0])["moment"]
    assert moment["interaction"]["status"] == "SUBMITTED"
    assert moment["interaction"]["answer"] == {"fields": [""], "claims_none": False}
    assert moment["interaction"]["verification"]["verdict"] == "NO_ANSWER"
    assert moment["progress"]["submissions"] == 1
    assert moment["progress"]["genuine_attempts"] == 0
    assert moment["progress"]["declines"] == 1
    assert moment["progress"]["delivered_rungs"] == []
    assert session.current_task.help_state.rungs_used == (HelpRung.NUDGE,)


def test_unavailable_worked_example_is_a_tool_error_and_only_final_reply_is_delivered(harness):
    h = harness([Reply([tool("get_worked_example")]), final("Look at your previous step.")])
    # Discriminant items have no authored worked steps; expansion items do.
    item = h.engine.item_source.next_item(SkillId("quad.discriminant"), target_difficulty=0, seed=7)
    session = replace_task(h.session, replace(h.session.current_task, item=item, skill_id=item.skill_id))
    session, turn = h.engine.request_help(session, {})
    result = tool_results(h.sdk.requests[1])[0]
    assert result["is_error"] is True
    assert json.loads(result["content"])["code"] == "worked_example_unavailable"
    assert [record.kind for record in session.history] == [HistoryKind.HELP_REQUEST, HistoryKind.HELP_DELIVERED]
    assert [entry.text for entry in session.transcript] == [turn.message]
    assert session.current_task.help_state.rungs_used == (HelpRung.NUDGE,)
    assert len(h.engine.evidence_log.events()) == 1
    assert h.traces[0].tool_calls == 1
