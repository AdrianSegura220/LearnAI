from dataclasses import replace

import pytest

from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.enums import Confidence, Verdict
from learnai.domain.events import AttemptRecorded
from learnai.domain.ids import TaskId
from learnai.domain.interaction import (
    InteractionKind, ResponseJob, StudentInteraction, VerificationSnapshot, WorkStatus,
    prepare_verification,
)
from learnai.domain.items import Submission
from tests.domain.test_engine import build, right, _form_trap


def question(task, **changes):
    values = dict(task_id=task.id, revision=task.work_revision,
                  kind=InteractionKind.TASK_QUESTION, status=WorkStatus.DRAFT,
                  steps=("(x+3)(x+4)", "x^2+4x+3x+12"), answer=Submission.of(""),
                  question="Do I add 4x and 3x?", referenced_step=1)
    values.update(changes)
    return StudentInteraction(**values)


def test_question_keeps_raw_work_and_reference_without_submission():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    interaction = question(session.current_task)
    session, turn = engine.ask_question(session, {}, interaction)
    context = tutor.contexts_seen[0]
    assert context.interaction == interaction
    assert context.interaction.steps == ("(x+3)(x+4)", "x^2+4x+3x+12")
    assert context.interaction.answer == Submission.of("")
    assert context.interaction.question == "Do I add 4x and 3x?"
    assert context.interaction.referenced_step == 1
    assert context.verification.answer_checked is False
    assert context.last_verdict is None and context.step_diff is None
    assert context.task_progress.genuine_attempts == 0
    assert not any(isinstance(e, AttemptRecorded) for e in engine.evidence_log.events())
    assert turn is not None


@pytest.mark.parametrize("changes", [dict(task_id=TaskId("other")), dict(revision=-1),
    dict(referenced_step=2), dict(referenced_step=-1), dict(revision=0),
    dict(revision=1, steps=("changed",)), dict(revision=1, answer=Submission.of("0")),
    dict(answer=Submission.none(), revision=2)])
def test_invalid_or_stale_work_is_rejected_before_side_effects(changes):
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    session, _ = engine.ask_question(session, {}, question(session.current_task, revision=1))
    events = engine.evidence_log.events()
    calls = len(tutor.contexts_seen)
    before = session
    with pytest.raises(ValueError):
        engine.ask_question(session, {}, question(session.current_task, **changes))
    assert session == before
    assert engine.evidence_log.events() == events
    assert len(tutor.contexts_seen) == calls


def test_question_only_change_keeps_work_revision():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    first = question(session.current_task)
    session, _ = engine.ask_question(session, {}, first)
    session, _ = engine.ask_question(session, {}, replace(first, question="Why?"))
    a, b = tutor.contexts_seen
    assert a.interaction.revision == b.interaction.revision == 0
    assert a.current_interaction_id != b.current_interaction_id
    assert session.current_task.work_revision == 0


def test_old_verdict_is_not_attached_to_revised_work():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    session, states, outcome = engine.submit(session, {}, ["x+1", "x+2"],
                                           Submission.of("0"), Confidence.UNSURE)
    assert outcome.verdict is Verdict.WRONG
    old = session.current_task.last_verification
    session, _ = engine.ask_question(session, states, question(session.current_task, revision=1))
    context = tutor.contexts_seen[-1]
    assert old.revision == 0 and old.verdict is Verdict.WRONG
    assert context.verification.revision == 1
    assert context.last_verdict is None and context.diagnosis is None
    assert context.step_diff is None
    assert session.history[0].verdict is Verdict.WRONG
    assert session.history[0].revision == 0


def test_question_does_not_unlock_reveal():
    engine, session, _ = build()
    for revision in range(5):
        session, _ = engine.ask_question(session, {}, question(session.current_task, revision=revision))
    assert session.current_task.help_state.attempts == 0
    assert session.current_task.help_state.submissions == 0
    for _ in range(3):
        session, _ = engine.request_help(session, {})
    session, turn = engine.request_help(session, {})
    assert turn is None


def test_timed_question_is_rejected_without_tutor():
    from learnai.domain.enums import HelpRung, InterventionTiming
    from learnai.domain.contracts import PRACTICE
    tutor = FakeTutor()
    engine, session, _ = build(tutor, contract=replace(PRACTICE, timed=True,
        base_max_rung=HelpRung.NONE, unlock_full_reveal_after=None,
        intervention_timing=InterventionTiming.NEVER))
    with pytest.raises(ValueError):
        engine.ask_question(session, {}, question(session.current_task))
    assert tutor.contexts_seen == []
    assert engine.evidence_log.events() == ()


@pytest.mark.parametrize("job", [ResponseJob.BRIEF, ResponseJob.NORMAL, ResponseJob.SUBSTANTIAL])
def test_application_selects_enabled_response_job(job):
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    engine.ask_question(session, {}, question(session.current_task), response_job=job)
    assert tutor.contexts_seen[0].response_job is job


def test_complex_requires_explicit_opt_in():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    with pytest.raises(ValueError):
        engine.ask_question(session, {}, question(session.current_task), response_job=ResponseJob.COMPLEX)
    assert tutor.contexts_seen == [] and engine.evidence_log.events() == ()


def test_submit_assigns_revision_only_when_raw_work_changes():
    engine, session, _ = build()
    session, states, _ = engine.submit(session, {}, [], Submission.of("0"), Confidence.UNSURE)
    assert session.current_task.work_revision == 0
    session, states, _ = engine.submit(session, states, [], Submission.of("0"), Confidence.UNSURE)
    assert session.current_task.work_revision == 0
    session, _, _ = engine.submit(session, states, [], Submission.of("1"), Confidence.UNSURE)
    assert session.current_task.work_revision == 1


def test_verification_preserves_form_diagnosis_without_fabricating_a_break():
    engine, session, _ = build()
    session = _form_trap(session)
    interaction = question(session.current_task, steps=("12x^2+18x", "2(6x^2+9x)"),
        answer=Submission.of("2(6x^2+9x)"))
    result = prepare_verification(interaction, item=session.current_task.item,
        verifier=engine._verifier_for(session.current_task.skill_id),
        catalogue=engine._catalogue(session.current_task.skill_id), matcher=engine.matcher,
        check_answer=True, check_steps=True)
    assert result.verdict is Verdict.WRONG and result.step_diff is None
    assert result.diagnosis is not None
    assert tuple(map(str, result.failed_constraints)) == ("fully_factored",)


def test_wrong_draft_step_does_not_invent_wrong_final_answer():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    engine.ask_question(session, {}, question(session.current_task, steps=("x+1", "x+2")))
    context = tutor.contexts_seen[0]
    assert context.step_diff is not None
    assert context.verification.steps_checked and not context.verification.answer_checked
    assert context.last_verdict is None


def test_unchecked_answer_cannot_have_final_verdict():
    with pytest.raises(ValueError):
        VerificationSnapshot(0, False, False, Verdict.WRONG, None, None)


def test_correct_final_submission_completes_without_tutor_or_step_checks():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    task = session.current_task
    session, _, outcome = engine.submit(session, {}, ["x+1", "x+2"], right(task), Confidence.CERTAIN)
    assert outcome.task_completed and tutor.contexts_seen == []
    assert session.plan[0].last_verification.verdict is Verdict.CORRECT
    assert not session.plan[0].last_verification.steps_checked


def test_question_about_same_checked_work_keeps_form_diagnosis():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    session = _form_trap(session)
    session, states, outcome = engine.submit(session, {}, ["12x^2+18x", "2(6x^2+9x)"],
                                            Submission.of("2(6x^2+9x)"), Confidence.UNSURE)
    checked = session.current_task.last_verification
    interaction = question(session.current_task, steps=("12x^2+18x", "2(6x^2+9x)"),
                           answer=Submission.of("2(6x^2+9x)"))
    engine.ask_question(session, states, interaction)
    context = tutor.contexts_seen[-1]
    assert context.last_verdict is Verdict.WRONG
    assert context.step_diff is None
    assert context.diagnosis == outcome.diagnosis
    assert context.verification == checked


def test_unchecked_help_snapshot_does_not_claim_a_checked_revision():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    engine.request_help(session, {})
    assert tutor.contexts_seen[0].task_progress.last_checked_revision is None


def test_free_form_assessed_terminology_question_is_task_tutoring():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    interaction = question(session.current_task, question="What does expanding mean?")
    session, turn = engine.ask_question(session, {}, interaction)
    assert turn is not None
    assert tutor.contexts_seen[0].interaction.question == "What does expanding mean?"
    assert session.current_task.help_state.help_taken
    assert session.current_task.help_state.attempts == 0


def test_unchecked_revision_keeps_last_checked_draft_findings_on_old_revision():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    session, _ = engine.ask_question(session, {}, question(session.current_task,
        steps=("x+1", "x+2")))
    old = session.current_task.last_verification
    session, _ = engine.ask_question(session, {}, question(session.current_task, revision=1,
        steps=(), referenced_step=None))
    context = tutor.contexts_seen[-1]
    assert old.revision == 0 and old.step_diff is not None
    assert session.current_task.last_verification == old
    assert context.verification.revision == 1
    assert context.verification.verdict is None and context.step_diff is None
    assert context.task_progress.last_checked_revision == 0
