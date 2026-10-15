# tests/domain/test_propagation.py
from learnai.adapters.clock import FakeClock
from learnai.domain.enums import PrereqStrength
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import SkillId, StudentId, VerificationKind
from learnai.domain.mastery import SkillState
from learnai.domain.propagation import propagate_success
from learnai.domain.skills import PrereqEdge, Skill


def skill(sid: str) -> Skill:
    return Skill(SkillId(sid), "math", sid, f"can {sid}", VerificationKind("cas_symbolic"), (), ())


GRAPH = SkillGraph.build(
    [skill("base"), skill("mid"), skill("top"), skill("soft")],
    [
        PrereqEdge(SkillId("base"), SkillId("mid"), PrereqStrength.HARD),
        PrereqEdge(SkillId("mid"), SkillId("top"), PrereqStrength.HARD),
        PrereqEdge(SkillId("soft"), SkillId("top"), PrereqStrength.SOFT),
    ],
)


def st(sid: str, **kwargs) -> SkillState:
    return SkillState(student_id=StudentId("s1"), skill_id=SkillId(sid), **kwargs)


def learned_state(sid: str, clock: FakeClock) -> SkillState:
    return st(sid, strength=2.0, unassisted_correct_count=2, stability=10.0,
              last_success_at=clock.now())


def test_a_downstream_success_refreshes_a_learned_hard_prerequisite():
    clock = FakeClock()
    states = {SkillId("mid"): learned_state("mid", clock)}
    before = states[SkillId("mid")].stability
    clock.advance(8.0)

    updated = propagate_success(states, GRAPH, SkillId("top"), clock.now())
    assert updated[SkillId("mid")].stability > before


def test_propagation_is_weaker_than_a_direct_retrieval():
    from learnai.domain.mastery import update_stability

    clock = FakeClock()
    original = learned_state("mid", clock)
    clock.advance(8.0)

    direct = update_stability(original, correct=True, now=clock.now())
    propagated = propagate_success(
        {SkillId("mid"): original}, GRAPH, SkillId("top"), clock.now()
    )[SkillId("mid")]
    assert propagated.stability < direct.stability


def test_soft_prerequisites_are_not_propagated_to():
    clock = FakeClock()
    states = {SkillId("soft"): learned_state("soft", clock)}
    clock.advance(8.0)
    updated = propagate_success(states, GRAPH, SkillId("top"), clock.now())
    assert updated[SkillId("soft")] == states[SkillId("soft")]


def test_propagation_stops_at_direct_prerequisites():
    clock = FakeClock()
    states = {
        SkillId("mid"): learned_state("mid", clock),
        SkillId("base"): learned_state("base", clock),
    }
    clock.advance(8.0)
    updated = propagate_success(states, GRAPH, SkillId("top"), clock.now())
    assert updated[SkillId("base")] == states[SkillId("base")]


def test_an_unlearned_prerequisite_is_not_credited():
    clock = FakeClock()
    states = {SkillId("mid"): st("mid", strength=0.1, stability=2.0,
                                 last_success_at=clock.now())}
    clock.advance(8.0)
    updated = propagate_success(states, GRAPH, SkillId("top"), clock.now())
    assert updated[SkillId("mid")] == states[SkillId("mid")]


def test_propagation_never_touches_strength():
    """Only direct evidence moves competence; propagation is a memory refresh."""
    clock = FakeClock()
    states = {SkillId("mid"): learned_state("mid", clock)}
    clock.advance(8.0)
    updated = propagate_success(states, GRAPH, SkillId("top"), clock.now())
    assert updated[SkillId("mid")].strength == states[SkillId("mid")].strength
