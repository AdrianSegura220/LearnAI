from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.enums import Confidence, EvidenceClass, HelpRung, Verdict
from learnai.domain.history import HistoryKind, HistoryQuery, HistoryScope
from learnai.domain.items import Submission
from learnai.domain.turn import TutorTurn
from tests.domain.test_engine import build, right
from tests.domain.test_interaction import question


def test_history_preserves_metadata_links_and_clock():
    tutor = FakeTutor([TutorTurn("Check the previous line.", HelpRung.NONE)])
    engine, session, clock = build(tutor)
    task = session.current_task
    session, _ = engine.ask_question(session, {}, question(task))
    student, delivered = session.history
    assert student.id == "sess-1:1" and delivered.id == "sess-1:2"
    assert student.at == delivered.at == clock.now()
    assert student.student_id == session.student_id and student.session_id == session.id
    assert student.task_id == task.id and student.item_id == task.item.id
    assert student.skill_id == task.skill_id and student.revision == 0
    assert student.kind is HistoryKind.STUDENT_QUESTION
    assert delivered.kind is HistoryKind.TUTOR_DELIVERED
    assert delivered.related_record_ids == (student.id,)
    assert delivered.rung is HelpRung.NONE
    assert tutor.contexts_seen[0].history == (student,)
    assert tutor.contexts_seen[0].history_scope == HistoryScope(session.student_id, session.id)


def test_read_scope_cannot_be_overridden_by_query():
    import pytest
    with pytest.raises(TypeError):
        HistoryQuery(student_id="other")


def test_decline_and_no_solutions_are_distinct():
    engine, session, _ = build()
    session, _, outcome = engine.submit(session, {}, [], Submission.of(""), Confidence.CERTAIN)
    assert outcome.verdict is Verdict.NO_ANSWER
    record = session.history[0]
    assert record.kind is HistoryKind.SUBMISSION
    assert record.verdict is Verdict.NO_ANSWER
    assert record.evidence_class is EvidenceClass.UNASSISTED_COLD
    assert record.interaction.answer == Submission.of("")
    assert not record.interaction.answer.claims_none
    import pytest
    with pytest.raises(ValueError):
        engine.submit(session, {}, [], Submission.none(), Confidence.CERTAIN)


def test_correct_submission_is_recorded_even_without_tutor():
    engine, session, _ = build()
    task = session.current_task
    session, _, _ = engine.submit(session, {}, [], right(task), Confidence.CERTAIN)
    assert len(session.history) == len(session.transcript) == 1
    assert session.history[0].verdict is Verdict.CORRECT
    assert session.transcript[0].task_id == task.id


def test_silent_help_retains_request_provenance_without_fabricated_student_text():
    from tests.domain.test_assistance import SilentTutor
    engine, session, _ = build(SilentTutor())
    task = session.current_task
    session, turn = engine.request_help(session, {})
    assert turn is None
    assert len(session.history) == 1
    record = session.history[0]
    assert record.kind is HistoryKind.HELP_REQUEST
    assert record.interaction.kind.value == "help_request"
    assert record.task_id == task.id and record.message is None
    assert session.transcript == ()
    assert engine.evidence_log.events() == ()
    assert session.current_task.help_state == task.help_state
