# tests/simulation/test_simulated_students.py
from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.domain.ids import SessionId, SkillId, TaskId
from learnai.domain.mastery import is_fresh, is_learned, retrievability
from learnai.domain.misconceptions import diagnose
from learnai.domain.session import Task

from tests.simulation.personas import (
    CLUSTER,
    Diligent,
    HintAbuser,
    MisconceptionCarrier,
    Overconfident,
    run_term,
)


def test_a_diligent_student_learns_the_cluster_over_a_term():
    result = run_term(Diligent())
    learned = [sid for sid, state in result.states.items() if is_learned(state)]
    assert len(learned) >= 6, f"only learned {learned}"


def test_a_diligent_student_ends_the_term_with_long_intervals():
    result = run_term(Diligent())
    matured = [s for s in result.states.values() if is_learned(s)]
    assert max(s.stability for s in matured) > 20.0, "stability never matured"


def test_the_hint_abuser_answers_correctly_all_term_and_masters_nothing():
    """The headline guarantee, end to end rather than as a unit property."""
    result = run_term(HintAbuser())
    assert result.sessions_run > 10
    assert all(not is_learned(s) for s in result.states.values())
    assert all(s.strength == 0.0 for s in result.states.values())


def test_the_hint_abuser_never_advances_past_the_graph_roots():
    result = run_term(HintAbuser())
    roots = {sid for sid in CLUSTER.graph.skills if not CLUSTER.graph.hard_prereqs(sid)}
    assert set(result.states), "the abuser did attempt work"
    assert set(result.states) <= roots, "answering correctly all term must not unlock anything"


def test_the_misconception_carrier_is_diagnosed_by_name():
    persona = MisconceptionCarrier()
    verifier = SympyVerifier()
    registry = GeneratorRegistry(QUADRATICS_TEMPLATES)

    item = registry.next_item(SkillId("quad.expand.square"), target_difficulty=-0.5, seed=1)
    task = Task(TaskId("t"), SessionId("s"), item, SkillId("quad.expand.square"))

    diff = verifier.diff_steps(persona.steps(task))
    assert diff is not None
    skill = CLUSTER.graph.skills[SkillId("quad.expand.square")]
    catalogue = tuple(CLUSTER.misconceptions[m] for m in skill.misconception_ids)
    assert diagnose(diff, catalogue, SympyMisconceptionRules()) is not None


def test_an_overconfident_student_accumulates_a_positive_calibration_gap():
    result = run_term(Overconfident(), days=20)
    gaps = [s.calibration_gap for s in result.states.values()]
    assert gaps and max(gaps) > 0.3


def test_memory_decays_across_a_long_absence():
    result = run_term(Diligent(), days=30)
    learned_states = [s for s in result.states.values() if is_learned(s)]
    assert learned_states
    state = max(learned_states, key=lambda s: s.stability)
    far_future = result.clock.advance(365.0)
    assert not is_fresh(state, far_future)
    assert retrievability(state, far_future) < 0.5


def test_an_earned_achievement_survives_the_decay():
    """is_learned is a badge, is_fresh is a reading. Decay must not revoke the badge."""
    result = run_term(Diligent(), days=30)
    learned_before = {sid for sid, s in result.states.items() if is_learned(s)}
    result.clock.advance(365.0)
    learned_after = {sid for sid, s in result.states.items() if is_learned(s)}
    assert learned_before == learned_after
