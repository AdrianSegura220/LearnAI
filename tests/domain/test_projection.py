# tests/domain/test_projection.py
from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st

from learnai.adapters.clock import FakeClock
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.domain.enums import Confidence, EvidenceClass, HelpRung, PrereqStrength
from learnai.domain.events import AttemptRecorded, HelpTaken
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import ItemId, SkillId, StudentId, TaskId, VerificationKind
from learnai.domain.mastery import is_learned
from learnai.domain.parameters import DEFAULT_PARAMETERS
from learnai.domain.projection import apply_event, project
from learnai.domain.skills import PrereqEdge, Skill

STUDENT = StudentId("stu")
SKILL = SkillId("quad.factor.monic")
PREREQ = SkillId("quad.expand.binomial")


def _skill(sid: SkillId) -> Skill:
    return Skill(sid, "math", str(sid), "can", VerificationKind("cas_symbolic"), (), ())


GRAPH = SkillGraph.build(
    [_skill(PREREQ), _skill(SKILL)], [PrereqEdge(PREREQ, SKILL, PrereqStrength.HARD)]
)


def attempt(clock, *, skill=SKILL, correct=True, evidence=EvidenceClass.UNASSISTED_COLD,
            confidence=Confidence.FAIRLY_SURE, difficulty=0.0, outcome=None):
    return AttemptRecorded(
        at=clock.now(), student_id=STUDENT, skill_id=skill, item_id=ItemId("i"),
        task_id=TaskId("t"), item_difficulty=difficulty,
        outcome=(1.0 if correct else 0.0) if outcome is None else outcome,
        evidence_class=evidence, confidence=confidence, contract_weight=1.0,
    )


def test_a_cold_success_raises_strength_and_sets_stability():
    clock = FakeClock()
    states = project([attempt(clock)], GRAPH, STUDENT)
    assert states[SKILL].strength > 0.0
    assert states[SKILL].stability > 0.0


def test_assisted_attempts_move_nothing():
    clock = FakeClock()
    events = [attempt(clock, evidence=EvidenceClass.ASSISTED) for _ in range(20)]
    states = project(events, GRAPH, STUDENT)
    assert states[SKILL].strength == 0.0
    assert states[SKILL].stability == 0.0
    assert not is_learned(states[SKILL])


def test_help_events_never_change_state():
    clock = FakeClock()
    help_event = HelpTaken(clock.now(), STUDENT, SKILL, ItemId("i"), TaskId("t"), HelpRung.NUDGE)
    before = project([attempt(clock)], GRAPH, STUDENT)
    after = project([attempt(clock), help_event], GRAPH, STUDENT)
    assert before == after


def test_events_for_other_students_are_ignored():
    clock = FakeClock()
    other = AttemptRecorded(
        clock.now(), StudentId("someone_else"), SKILL, ItemId("i"), TaskId("t"),
        0.0, 1.0, EvidenceClass.UNASSISTED_COLD, Confidence.CERTAIN, 1.0,
    )
    assert project([other], GRAPH, STUDENT) == {}


def test_a_downstream_success_refreshes_a_learned_prerequisite():
    """Six cold successes on a hard item cross the learned bar (strength >= 1.5); three easy ones would not."""
    clock = FakeClock()
    events = [attempt(clock, skill=PREREQ, difficulty=2.0) for _ in range(6)]
    clock.advance(20.0)
    before = project(events, GRAPH, STUDENT)[PREREQ].last_success_at
    events.append(attempt(clock, skill=SKILL))
    after = project(events, GRAPH, STUDENT)[PREREQ].last_success_at
    assert after > before


def test_a_later_lapse_does_not_revoke_a_learned_badge():
    """is_learned is an achievement: strength moves on a cold failure, the
    badge does not (spec §7.3)."""
    clock = FakeClock()
    events = [attempt(clock, skill=SKILL, difficulty=2.0) for _ in range(6)]
    before = project(events, GRAPH, STUDENT)[SKILL]
    assert is_learned(before)
    events.append(attempt(clock, skill=SKILL, correct=False, difficulty=0.0))
    after = project(events, GRAPH, STUDENT)[SKILL]
    assert after.strength < DEFAULT_PARAMETERS.strength_threshold < before.strength
    assert is_learned(after)


def test_calibration_records_overconfidence():
    clock = FakeClock()
    events = [attempt(clock, correct=False, confidence=Confidence.CERTAIN) for _ in range(10)]
    assert project(events, GRAPH, STUDENT)[SKILL].calibration_gap > 0.0


def test_rebuilding_from_the_log_reproduces_the_live_projection():
    clock = FakeClock()
    log = InMemoryEvidenceLog()
    live: dict[SkillId, object] = {}
    for _ in range(6):
        event = attempt(clock)
        log.append(event)
        live = apply_event(live, event, GRAPH)
        clock.advance(3.0)
    assert project(log.events(), GRAPH, STUDENT) == live


def test_each_updated_skills_own_parameters_govern_its_state():
    """P6 with per-skill models: a skill's own parameters price its strength,
    its latch, and the nudge it receives as a propagation target."""
    clock = FakeClock()
    overrides = {
        SKILL: replace(DEFAULT_PARAMETERS, k0=1.6),
        PREREQ: replace(DEFAULT_PARAMETERS, prereq_propagation_weight=5.0),
    }
    events = [attempt(clock, skill=PREREQ, difficulty=2.0) for _ in range(6)]
    clock.advance(20.0)
    events.append(attempt(clock, skill=SKILL))

    live: dict[SkillId, object] = {}
    for event in events:
        live = apply_event(live, event, GRAPH, DEFAULT_PARAMETERS, overrides)

    replayed = project(
        events, GRAPH, STUDENT, params=DEFAULT_PARAMETERS, parameter_overrides=overrides
    )
    assert replayed == live

    default = project(events, GRAPH, STUDENT)
    assert (
        replayed[SKILL].strength != default[SKILL].strength
    ), "the event skill's own k0 must govern its strength"
    assert (
        replayed[PREREQ].stability != default[PREREQ].stability
    ), "the propagation target's own weight must govern its nudge"


def test_a_skills_own_parameters_govern_its_ever_learned_latch():
    clock = FakeClock()
    overrides = {
        SKILL: replace(
            DEFAULT_PARAMETERS, strength_threshold=0.05, min_unassisted_correct=1
        )
    }
    event = attempt(clock)
    assert apply_event({}, event, GRAPH, DEFAULT_PARAMETERS, overrides)[
        SKILL
    ].ever_learned
    assert not apply_event({}, event, GRAPH)[SKILL].ever_learned


def test_a_decline_never_counts_toward_the_mastery_gate():
    """It is scored near the guess baseline, which must not read as competence."""
    clock = FakeClock()
    events = [
        attempt(clock, outcome=0.03, confidence=Confidence.NO_IDEA) for _ in range(30)
    ]
    states = project(events, GRAPH, STUDENT)
    assert states[SKILL].unassisted_correct_count == 0
    assert not is_learned(states[SKILL])


def test_the_log_is_append_only():
    log = InMemoryEvidenceLog()
    clock = FakeClock()
    log.append(attempt(clock))
    snapshot = log.events()
    log.append(attempt(clock))
    assert len(snapshot) == 1, "events() must return an immutable snapshot"
    assert len(log.events()) == 2


@given(count=st.integers(min_value=1, max_value=40))
def test_no_amount_of_help_can_ever_produce_mastery(count):
    """The headline invariant: assistance cannot manufacture a learned skill."""
    clock = FakeClock()
    events: list[object] = []
    for _ in range(count):
        events.append(
            HelpTaken(clock.now(), STUDENT, SKILL, ItemId("i"), TaskId("t"), HelpRung.NAME_METHOD)
        )
        events.append(attempt(clock, evidence=EvidenceClass.ASSISTED))
        clock.advance(1.0)
    states = project(events, GRAPH, STUDENT)
    assert not is_learned(states[SKILL])
