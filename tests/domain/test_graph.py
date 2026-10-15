# tests/domain/test_graph.py
import pytest

from learnai.domain.enums import PrereqStrength
from learnai.domain.graph import CycleError, SkillGraph
from learnai.domain.ids import SkillId, VerificationKind
from learnai.domain.skills import PrereqEdge, Skill


def skill(sid: str) -> Skill:
    return Skill(
        id=SkillId(sid),
        subject_id="math",
        name=sid,
        can_do_statement=f"can do {sid}",
        verification_kind=VerificationKind("cas_symbolic"),
        concept_ids=(),
        misconception_ids=(),
    )


def hard(a: str, b: str) -> PrereqEdge:
    return PrereqEdge(SkillId(a), SkillId(b), PrereqStrength.HARD)


def test_hard_prereqs_are_direct_only():
    g = SkillGraph.build([skill("a"), skill("b"), skill("c")], [hard("a", "b"), hard("b", "c")])
    assert g.hard_prereqs(SkillId("c")) == frozenset({SkillId("b")})
    assert g.hard_prereqs(SkillId("a")) == frozenset()


def test_dependents_are_direct_only():
    g = SkillGraph.build([skill("a"), skill("b"), skill("c")], [hard("a", "b"), hard("a", "c")])
    assert g.dependents(SkillId("a")) == frozenset({SkillId("b"), SkillId("c")})


def test_frontier_is_unlearned_skills_whose_hard_prereqs_are_learned():
    g = SkillGraph.build([skill("a"), skill("b"), skill("c")], [hard("a", "b"), hard("b", "c")])
    assert g.frontier(learned=set()) == frozenset({SkillId("a")})
    assert g.frontier(learned={SkillId("a")}) == frozenset({SkillId("b")})
    assert g.frontier(learned={SkillId("a"), SkillId("b")}) == frozenset({SkillId("c")})
    assert g.frontier(learned={SkillId("a"), SkillId("b"), SkillId("c")}) == frozenset()


def test_soft_edges_do_not_gate_the_frontier():
    edges = [PrereqEdge(SkillId("a"), SkillId("b"), PrereqStrength.SOFT)]
    g = SkillGraph.build([skill("a"), skill("b")], edges)
    assert SkillId("b") in g.frontier(learned=set())
    assert g.soft_prereqs(SkillId("b")) == frozenset({SkillId("a")})


def test_cycle_in_hard_edges_is_rejected():
    with pytest.raises(CycleError):
        SkillGraph.build([skill("a"), skill("b")], [hard("a", "b"), hard("b", "a")])


def test_a_cycle_error_names_the_path_and_nothing_downstream():
    """d depends on the cycle but is not part of it, so it must not be blamed."""
    edges = [hard("a", "b"), hard("b", "c"), hard("c", "a"), hard("c", "d")]
    with pytest.raises(CycleError) as err:
        SkillGraph.build([skill(s) for s in "abcd"], edges)
    assert err.value.cycle == (SkillId("a"), SkillId("b"), SkillId("c"), SkillId("a"))
    assert "a -> b -> c -> a" in str(err.value)


def test_edge_referencing_unknown_skill_is_rejected():
    with pytest.raises(KeyError):
        SkillGraph.build([skill("a")], [hard("a", "ghost")])
