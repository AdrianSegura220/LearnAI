from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.enums import Confidence, EvidenceClass, HelpRung
from learnai.domain.events import AttemptRecorded, HelpTaken
from learnai.domain.items import Submission
from learnai.domain.projection import project
from learnai.domain.turn import TutorTurn
from tests.domain.test_engine import build, right
from tests.domain.test_interaction import question


class SilentTutor(FakeTutor):
    def respond(self, context, *, feedback=None):
        self.contexts_seen.append(context)
        return None


def test_delivered_task_reply_spends_independence_even_at_none_rung():
    engine, session, _ = build(FakeTutor([TutorTurn("Check the previous line.", HelpRung.NONE)]))
    task = session.current_task
    session, turn = engine.ask_question(session, {}, question(task))
    assert turn is not None
    assert session.current_task.help_state.help_taken
    assert session.current_task.help_state.rungs_used == ()
    assert len(engine.evidence_log.events()) == 1
    assert isinstance(engine.evidence_log.events()[0], HelpTaken)
    assert engine.evidence_log.events()[0].rung is HelpRung.NONE
    session, states, outcome = engine.submit(session, {}, [], right(task), Confidence.CERTAIN)
    assert outcome.evidence_class is EvidenceClass.ASSISTED
    assert states[task.skill_id].strength == 0


def test_requested_none_rung_reply_does_not_climb_ladder():
    engine, session, _ = build(FakeTutor([TutorTurn("Check the previous line.", HelpRung.NONE)]))
    session, turn = engine.request_help(session, {})
    assert turn is not None and session.current_task.help_state.help_taken
    assert session.current_task.help_state.rungs_used == ()
    session, turn = engine.request_help(session, {})
    assert turn.rung_used is HelpRung.NUDGE


def test_silent_question_preserves_independence():
    engine, session, _ = build(SilentTutor())
    task = session.current_task
    session, turn = engine.ask_question(session, {}, question(task))
    assert turn is None and len(session.history) == 1
    assert not session.current_task.help_state.help_taken
    assert engine.evidence_log.events() == ()
    session, _, outcome = engine.submit(session, {}, [], right(task), Confidence.CERTAIN)
    assert outcome.evidence_class is EvidenceClass.UNASSISTED_COLD


def test_rejected_question_preserves_independence():
    rejected = TutorTurn("Here is everything.", HelpRung.FULL_REVEAL)
    engine, session, _ = build(FakeTutor([rejected, rejected]))
    session, turn = engine.ask_question(session, {}, question(session.current_task))
    assert turn is None and len(session.history) == 1
    assert engine.evidence_log.events() == ()
    assert not session.current_task.help_state.help_taken


def test_assistance_does_not_rewrite_a_cold_failure():
    engine, session, _ = build()
    task = session.current_task
    session, states, _ = engine.submit(session, {}, ["x+1", "x+2"], Submission.of("0"), Confidence.CERTAIN)
    failure = engine.evidence_log.events()[0]
    assert isinstance(failure, AttemptRecorded)
    assert failure.evidence_class is EvidenceClass.UNASSISTED_COLD
    session, _ = engine.ask_question(session, states, question(session.current_task, revision=1))
    session, states, outcome = engine.submit(session, states, [], right(task), Confidence.CERTAIN)
    assert engine.evidence_log.events()[0] == failure
    assert outcome.evidence_class is EvidenceClass.ASSISTED
    assert project(engine.evidence_log.events(), engine.graph, session.student_id) == states
