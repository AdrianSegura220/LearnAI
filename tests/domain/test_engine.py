# tests/domain/test_engine.py
import pathlib
from collections.abc import Mapping
from dataclasses import replace

import pytest

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC, FULLY_FACTORED
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.contracts import ModeContract, PRACTICE
from learnai.domain.engine import PracticeEngine, UnregisteredVerifierError
from learnai.domain.enums import Confidence, EvidenceClass, HelpRung, InterventionTiming, Verdict
from learnai.domain.ids import CourseId, SessionId, SkillId, StudentId
from learnai.domain.items import AnswerSpec, Formula, Submission, Text
from learnai.domain.mastery import is_learned
from learnai.domain.parameters import DEFAULT_PARAMETERS, MasteryParameters
from learnai.domain.projection import project
from learnai.domain.session import replace_task

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
COURSE = CLUSTER.graph.topological_order()


def right(task) -> Submission:
    """What a student who knows the answer enters."""
    return SympyVerifier().key_submission(task.item.answer_spec)


def build(
    tutor: FakeTutor | None = None,
    clock: FakeClock | None = None,
    contract: ModeContract = PRACTICE,
    parameter_overrides: Mapping[SkillId, MasteryParameters] | None = None,
):
    clock = clock or FakeClock()
    verifier = SympyVerifier()
    engine = PracticeEngine(
        graph=CLUSTER.graph,
        misconceptions=CLUSTER.misconceptions,
        item_source=GeneratorRegistry(QUADRATICS_TEMPLATES),
        verifiers={CAS_SYMBOLIC: verifier},
        tutor=tutor or FakeTutor(),
        matcher=SympyMisconceptionRules(),
        evidence_log=InMemoryEvidenceLog(),
        clock=clock,
        contract=contract,
        parameter_overrides=parameter_overrides,
    )
    session = engine.start_session(
        student_id=StudentId("stu"),
        course_id=CourseId("quadratics"),
        course_skills=COURSE,
        states={},
        budget_items=4,
        session_id=SessionId("sess-1"),
        seed=7,
    )
    return engine, session, clock


def _form_trap(session):
    """Swap the current task for a fully-factored item the student can miss on
    form alone: the working is equivalent, the final line is not factored."""
    task = session.current_task
    item = replace(
        task.item,
        skill_id=SkillId("quad.factor.common"),
        statement=(Text("Factor completely: "), Formula("12x^2 + 18x")),
        answer_spec=AnswerSpec("6x(2x + 3)", (FULLY_FACTORED,)),
    )
    return replace_task(
        session, replace(task, skill_id=SkillId("quad.factor.common"), item=item)
    )


def test_a_session_starts_with_a_plan_of_the_requested_size():
    _, session, _ = build()
    assert len(session.plan) == 4
    assert session.current_task is not None


def test_an_unregistered_verification_kind_is_refused_at_construction():
    """Fail at startup, not on some student's first attempt at the skill."""
    with pytest.raises(UnregisteredVerifierError, match="cas_symbolic"):
        PracticeEngine(
            graph=CLUSTER.graph,
            misconceptions=CLUSTER.misconceptions,
            item_source=GeneratorRegistry(QUADRATICS_TEMPLATES),
            verifiers={},
            tutor=FakeTutor(),
            matcher=SympyMisconceptionRules(),
            evidence_log=InMemoryEvidenceLog(),
            clock=FakeClock(),
            contract=PRACTICE,
        )


def test_a_correct_first_attempt_costs_no_tutor_turn():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    task = session.current_task
    session, states, outcome = engine.submit(
        session, {}, steps=[], answer=right(task),
        confidence=Confidence.FAIRLY_SURE,
    )
    assert outcome.verdict is Verdict.CORRECT
    assert outcome.evidence_class is EvidenceClass.UNASSISTED_COLD
    assert outcome.tutor_turn is None
    assert tutor.contexts_seen == [], "the model must not be invoked on a clean success"
    assert states[task.skill_id].strength > 0.0
    assert outcome.task_completed


def test_a_first_wrong_attempt_that_localises_a_break_stays_quiet():
    """LET_RUN: one beat for the student to catch the slip themselves."""
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    session, _, outcome = engine.submit(
        session, {}, steps=["(x+1)(x+2)", "x^2 + 2"], answer=Submission.of("x^2 + 2"),
        confidence=Confidence.UNSURE,
    )
    assert outcome.verdict is Verdict.WRONG
    assert outcome.tutor_turn is None
    assert tutor.contexts_seen == [], "the first break is the student's to find"
    assert outcome.step_diff is not None


def test_the_failure_after_a_self_correction_summons_the_tutor():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    for _ in range(2):
        session, _, outcome = engine.submit(
            session, {}, steps=["(x+1)(x+2)", "x^2 + 2"], answer=Submission.of("x^2 + 2"),
            confidence=Confidence.UNSURE,
        )
    assert outcome.tutor_turn is not None
    assert len(tutor.contexts_seen) == 1, "the first failure was let run"
    assert tutor.contexts_seen[0].step_diff is not None


def test_a_wrong_attempt_with_nothing_to_let_run_summons_the_tutor():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    session, _, outcome = engine.submit(
        session, {}, steps=[], answer=Submission.of("0"), confidence=Confidence.UNSURE
    )
    assert outcome.verdict is Verdict.WRONG
    assert outcome.tutor_turn is not None, "no working to think about: the tutor orients"
    assert tutor.contexts_seen[0].step_diff is None


def test_a_form_miss_still_gets_the_self_correction_beat():
    """Work was shown, so the one beat applies even though nothing in it is
    broken; the belief behind the partial factoring is still named."""
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    session = _form_trap(session)
    session, _, outcome = engine.submit(
        session, {}, steps=["12x^2 + 18x", "2(6x^2 + 9x)"],
        answer=Submission.of("2(6x^2 + 9x)"), confidence=Confidence.UNSURE,
    )
    assert outcome.verdict is Verdict.WRONG
    assert outcome.step_diff is None, "the working is equivalent; only the form failed"
    assert outcome.diagnosis is not None
    assert outcome.tutor_turn is None
    assert tutor.contexts_seen == [], "visible working: one beat to catch it"


def test_an_immediate_contract_answers_the_very_first_failure():
    tutor = FakeTutor()
    engine, session, _ = build(
        tutor, contract=replace(PRACTICE, intervention_timing=InterventionTiming.IMMEDIATE)
    )
    session, _, outcome = engine.submit(
        session, {}, steps=["(x+1)(x+2)", "x^2 + 2"], answer=Submission.of("x^2 + 2"),
        confidence=Confidence.UNSURE,
    )
    assert outcome.tutor_turn is not None
    assert len(tutor.contexts_seen) == 1


def test_requesting_help_carries_the_last_break_back_to_the_tutor():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    session, _, _ = engine.submit(
        session, {}, steps=["(x+1)(x+2)", "x^2 + 2"], answer=Submission.of("x^2 + 2"),
        confidence=Confidence.UNSURE,
    )
    assert tutor.contexts_seen == []
    session, turn = engine.request_help(session, {})
    assert turn is not None
    assert tutor.contexts_seen[0].step_diff is not None, "the walk-back survives into the request"


def test_a_wrong_attempt_earns_nothing_but_is_still_recorded():
    engine, session, _ = build()
    task = session.current_task
    session, states, _ = engine.submit(
        session, {}, steps=[], answer=Submission.of("0"), confidence=Confidence.CERTAIN
    )
    assert states[task.skill_id].attempt_count == 1
    assert states[task.skill_id].strength < 0.0
    assert not is_learned(states[task.skill_id])


def test_requesting_help_climbs_one_rung_and_marks_the_attempt_assisted():
    engine, session, _ = build()
    task = session.current_task
    session, turn = engine.request_help(session, {})
    assert turn is not None and turn.rung_used is HelpRung.NUDGE

    session, states, outcome = engine.submit(
        session, {}, steps=[], answer=right(task),
        confidence=Confidence.CERTAIN,
    )
    assert outcome.verdict is Verdict.CORRECT
    assert outcome.evidence_class is EvidenceClass.ASSISTED
    assert states[task.skill_id].strength == 0.0, "P2: assistance never moves mastery"


def test_help_runs_out_at_the_base_rung_before_effort_is_documented():
    engine, session, _ = build()
    for _ in range(3):
        session, turn = engine.request_help(session, {})
        assert turn is not None
    session, turn = engine.request_help(session, {})
    assert turn is None, "no reveal until the effort condition is met"


def test_two_answered_attempts_and_three_hints_unlock_the_reveal():
    engine, session, _ = build()
    for _ in range(2):
        session, _, _ = engine.submit(
            session, {}, steps=[], answer=Submission.of("0"), confidence=Confidence.UNSURE
        )
    for expected in (HelpRung.NUDGE, HelpRung.NEXT_STEP, HelpRung.NAME_METHOD):
        session, turn = engine.request_help(session, {})
        assert turn is not None and turn.rung_used is expected
    session, turn = engine.request_help(session, {})
    assert turn is not None and turn.rung_used is HelpRung.FULL_REVEAL


def test_help_records_the_rung_the_tutor_delivered():
    """A NUDGE answer to a NEXT_STEP request logs a nudge — the ladder never
    claims a rung the student did not see."""
    from learnai.domain.turn import TutorTurn

    nudge = TutorTurn("Look again at the previous step.", HelpRung.NUDGE)
    engine, session, _ = build(FakeTutor([nudge] * 8))
    for _ in range(2):
        session, _, _ = engine.submit(
            session, {}, steps=[], answer=Submission.of("0"), confidence=Confidence.UNSURE
        )
    for _ in range(4):
        session, turn = engine.request_help(session, {})
        assert turn is not None and turn.rung_used is HelpRung.NUDGE
    assert session.current_task.help_state.rungs_used == (HelpRung.NUDGE,) * 4


def test_a_leaking_tutor_turn_never_reaches_the_student():
    from learnai.domain.turn import TutorTurn

    # Planning is deterministic for a seed, so probe once to learn the answer,
    # then rebuild with a tutor scripted to leak exactly it.
    _, probe, _ = build()
    answer = probe.current_task.item.answer_spec.expression

    leak = TutorTurn(f"Just write {answer}.", HelpRung.NUDGE)
    engine, session, _ = build(FakeTutor([leak, leak]))

    session, turn = engine.request_help(session, {})
    assert turn is None, "every retry leaked, so nothing may be delivered"


def test_declining_costs_the_same_as_a_wrong_answer():
    engine, session, _ = build()
    task = session.current_task
    session, states, outcome = engine.submit(
        session, {}, steps=[], answer=Submission.of(""), confidence=Confidence.CERTAIN
    )
    assert outcome.verdict is Verdict.NO_ANSWER
    assert outcome.evidence_class is EvidenceClass.UNASSISTED_COLD
    assert states[task.skill_id].strength < 0.0, "a decline is the same competence signal"
    assert outcome.tutor_turn is not None, "and it summons the tutor"


def test_declining_forces_the_no_idea_confidence_reading():
    engine, session, _ = build()
    engine.submit(session, {}, steps=[], answer=Submission.of("  "), confidence=Confidence.CERTAIN)
    recorded = engine.evidence_log.events()[0]
    assert recorded.confidence is Confidence.NO_IDEA


def test_declining_does_not_climb_toward_a_reveal():
    """Otherwise the cheapest route to the answer is two declines and three hints."""
    engine, session, _ = build()
    for _ in range(2):
        session, _, _ = engine.submit(
            session, {}, steps=[], answer=Submission.of(""), confidence=Confidence.NO_IDEA
        )
    for _ in range(3):
        session, turn = engine.request_help(session, {})
        assert turn is not None
    session, turn = engine.request_help(session, {})
    assert turn is None, "declines are not documented effort"


def test_a_declined_cold_attempt_is_spent():
    """The tutor oriented after the decline, so a later success is not
    unassisted evidence."""
    engine, session, _ = build()
    task = session.current_task
    session, states, _ = engine.submit(
        session, {}, steps=[], answer=Submission.of(""), confidence=Confidence.NO_IDEA
    )
    _, states, corrected = engine.submit(
        session, states, steps=[], answer=right(task), confidence=Confidence.CERTAIN
    )
    assert corrected.evidence_class is EvidenceClass.ASSISTED
    assert states[task.skill_id].unassisted_correct_count == 0


def test_the_tutor_is_told_the_student_declined():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    engine.submit(session, {}, steps=[], answer=Submission.of(""), confidence=Confidence.NO_IDEA)
    assert tutor.contexts_seen[0].last_verdict is Verdict.NO_ANSWER
    assert tutor.contexts_seen[0].step_diff is None


def test_an_unreadable_answer_changes_nothing():
    """A missing bracket is notation, not evidence (spec P7)."""
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    before = session
    session, states, outcome = engine.submit(
        session, {}, steps=[], answer=Submission.of("(x+1)(x+2"), confidence=Confidence.CERTAIN
    )
    assert outcome.verdict is Verdict.MALFORMED
    assert outcome.evidence_class is None
    assert len(engine.evidence_log.events()) == 0, "nothing is recorded"
    assert states == {}, "mastery does not move"
    assert session == before, "no attempt is counted and the task is untouched"
    assert tutor.contexts_seen == [], "no tutor call is spent on a typo"


def test_an_unreadable_answer_does_not_use_up_the_cold_attempt():
    engine, session, _ = build()
    task = session.current_task
    session, _, _ = engine.submit(
        session, {}, steps=[], answer=Submission.of("(x+1)(x+2"), confidence=Confidence.CERTAIN
    )
    session, _, outcome = engine.submit(
        session, {}, steps=[], answer=right(task), confidence=Confidence.CERTAIN
    )
    assert outcome.verdict is Verdict.CORRECT
    assert outcome.evidence_class is EvidenceClass.UNASSISTED_COLD


def test_the_session_advances_and_finishes():
    engine, session, _ = build()
    for _ in range(4):
        task = session.current_task
        assert task is not None
        session, _, _ = engine.submit(
            session, {}, steps=[], answer=right(task),
            confidence=Confidence.FAIRLY_SURE,
        )
    assert session.is_finished


def test_every_attempt_lands_in_the_append_only_log():
    engine, session, _ = build()
    task = session.current_task
    engine.submit(session, {}, steps=[], answer=right(task),
                  confidence=Confidence.CERTAIN)
    assert len(engine.evidence_log.events()) == 1


def test_each_skill_evolves_under_its_own_parameters_and_replays_from_the_log():
    """P6 with per-skill models: the prereq latches under its own threshold and
    takes its propagation nudge under its own weight, and the log rebuilds the
    live states exactly."""
    clock = FakeClock()
    prereq = SkillId("quad.expand.binomial")
    downstream = SkillId("quad.factor.monic")
    overrides = {
        prereq: replace(
            DEFAULT_PARAMETERS,
            strength_threshold=0.05,
            min_unassisted_correct=1,
            prereq_propagation_weight=5.0,
        )
    }
    engine, session, clock = build(clock=clock, parameter_overrides=overrides)
    first = session.current_task
    assert first.skill_id == prereq, "the frontier the plan opens on"
    session, live, _ = engine.submit(
        session, {}, steps=[], answer=right(first), confidence=Confidence.FAIRLY_SURE
    )
    assert live[prereq].ever_learned, "the prereq's own threshold governed its latch"

    task = replace(session.current_task, skill_id=downstream)
    session = replace_task(session, task)
    clock.advance(20.0)
    session, live, _ = engine.submit(
        session, live, steps=[], answer=right(task), confidence=Confidence.FAIRLY_SURE
    )

    events = engine.evidence_log.events()
    replayed = project(
        events,
        engine.graph,
        StudentId("stu"),
        params=engine.parameters,
        parameter_overrides=engine.parameter_overrides,
    )
    assert replayed == live, "P6: the log must rebuild the live states exactly"
    default = project(events, engine.graph, StudentId("stu"))
    assert live[prereq].stability > default[prereq].stability, (
        "the prereq's own propagation weight governed its nudge"
    )
