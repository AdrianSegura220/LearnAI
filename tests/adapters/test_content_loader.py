# tests/adapters/test_content_loader.py
import pathlib

import pytest
import yaml

from learnai.adapters.content.loader import ContentError, load_cluster, parse_cluster
from learnai.domain.ids import ConceptId, MisconceptionId, SkillId

CLUSTER = pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"


def test_loads_every_skill():
    cluster = load_cluster(CLUSTER)
    assert len(cluster.graph.skills) == 12


def test_hard_and_soft_edges_are_distinguished():
    cluster = load_cluster(CLUSTER)
    assert cluster.graph.hard_prereqs(SkillId("quad.factor.monic")) == frozenset(
        {SkillId("quad.expand.binomial")}
    )
    assert cluster.graph.soft_prereqs(SkillId("quad.factor.monic")) == frozenset(
        {SkillId("quad.factor.common")}
    )


def test_roots_are_the_initial_frontier():
    cluster = load_cluster(CLUSTER)
    assert cluster.graph.frontier(learned=set()) == frozenset(
        {SkillId("quad.expand.binomial"), SkillId("quad.factor.common")}
    )


def test_every_misconception_id_resolves():
    cluster = load_cluster(CLUSTER)
    for skill in cluster.graph.skills.values():
        for mid in skill.misconception_ids:
            assert mid in cluster.misconceptions


def test_a_misconception_can_be_shared_by_several_skills():
    """One belief, one catalogue entry, one memory — not one copy per skill."""
    cluster = load_cluster(CLUSTER)
    shared = MisconceptionId("mc.square.distributes")
    owners = [s.id for s in cluster.graph.skills.values() if shared in s.misconception_ids]
    assert set(owners) == {SkillId("quad.expand.square"), SkillId("quad.completesquare")}


def test_misconceptions_are_subject_scoped_not_skill_owned():
    cluster = load_cluster(CLUSTER)
    assert all(m.subject_id == "math" for m in cluster.misconceptions.values())
    assert not hasattr(next(iter(cluster.misconceptions.values())), "skill_id")


# Content rules are exercised through parse_cluster: no temp files, no YAML
# round-trip, and the failure cases read as data rather than as string escaping.

MC = {"id": "m1", "name": "M", "description": "d", "signature": "s"}
CONCEPT = {"id": "c1", "kind": "definition", "prompt": "p", "answer": "a"}
SKILL_A = {"id": "a", "name": "A", "can_do": "does a", "misconceptions": ["m1"]}
SKILL_B = {"id": "b", "name": "B", "can_do": "does b", "misconceptions": ["m1"]}


def cluster(**overrides) -> dict:
    # "any_checker", not "cas_symbolic": the loader treats the kind as opaque.
    base = {"subject": "math", "verification": "any_checker", "misconceptions": [MC], "skills": [SKILL_A]}
    return base | overrides


def test_the_baseline_cluster_is_valid():
    assert parse_cluster(cluster()).graph.skills.keys() == {SkillId("a")}


def test_a_cluster_without_a_subject_is_rejected():
    with pytest.raises(ContentError):
        parse_cluster({"skills": []})


def test_a_cluster_without_a_verification_kind_is_rejected():
    """No fallback: a history cluster that forgot the key must not be graded by SymPy."""
    without = {k: v for k, v in cluster().items() if k != "verification"}
    with pytest.raises(ContentError):
        parse_cluster(without)


def test_skills_inherit_the_cluster_verification_kind():
    skill = parse_cluster(cluster()).graph.skills[SkillId("a")]
    assert skill.verification_kind == "any_checker"


def test_a_skill_can_override_the_verification_kind():
    loaded = parse_cluster(cluster(skills=[SKILL_A | {"verification": "other_checker"}]))
    assert loaded.graph.skills[SkillId("a")].verification_kind == "other_checker"


def test_a_dangling_prereq_is_rejected():
    with pytest.raises(ContentError):
        parse_cluster(cluster(skills=[SKILL_A | {"prereqs": [{"skill": "ghost", "strength": "hard"}]}]))


def test_a_prereq_cycle_is_rejected_with_its_path():
    a = SKILL_A | {"prereqs": [{"skill": "b", "strength": "hard"}]}
    b = SKILL_B | {"prereqs": [{"skill": "a", "strength": "hard"}]}
    with pytest.raises(ContentError, match="a -> b -> a"):
        parse_cluster(cluster(skills=[a, b]))


def test_a_skill_without_misconceptions_is_accepted():
    """Diagnosis treats an unmatched error as novel; requiring an entry would invite invented ones."""
    bare = {"id": "a", "name": "A", "can_do": "does a"}
    loaded = parse_cluster(cluster(misconceptions=[], skills=[bare]))
    assert loaded.graph.skills[SkillId("a")].misconception_ids == ()


def test_a_dangling_misconception_reference_is_rejected():
    with pytest.raises(ContentError):
        parse_cluster(cluster(skills=[SKILL_A | {"misconceptions": ["ghost"]}]))


def test_a_misconception_no_skill_references_is_rejected():
    orphan = {"id": "orphan", "name": "O", "description": "d", "signature": "s"}
    with pytest.raises(ContentError):
        parse_cluster(cluster(misconceptions=[MC, orphan]))


def test_a_duplicate_misconception_id_is_rejected():
    with pytest.raises(ContentError):
        parse_cluster(cluster(misconceptions=[MC, dict(MC)]))


def test_a_duplicate_skill_id_is_rejected():
    with pytest.raises(ContentError, match="duplicate skill id: a"):
        parse_cluster(cluster(skills=[SKILL_A, dict(SKILL_A)]))


def test_introduced_by_may_name_any_skill_that_uses_the_concept():
    """An override, not "the first user": b may introduce it even though a also uses it."""
    loaded = parse_cluster(
        cluster(
            concepts=[CONCEPT | {"introduced_by": "b"}],
            skills=[SKILL_A | {"concepts": ["c1"]}, SKILL_B | {"concepts": ["c1"]}],
        )
    )
    assert loaded.concepts[ConceptId("c1")].introduced_by == SkillId("b")


def test_introduced_by_must_be_a_skill_that_uses_the_concept():
    with pytest.raises(ContentError):
        parse_cluster(
            cluster(
                concepts=[CONCEPT | {"introduced_by": "b"}],
                skills=[SKILL_A | {"concepts": ["c1"]}, SKILL_B],
            )
        )


def test_introduced_by_naming_an_unknown_skill_is_rejected():
    with pytest.raises(ContentError):
        parse_cluster(
            cluster(
                concepts=[CONCEPT | {"introduced_by": "ghost"}],
                skills=[SKILL_A | {"concepts": ["c1"]}],
            )
        )


def test_the_file_loader_adds_nothing_but_reading():
    assert load_cluster(CLUSTER) == parse_cluster(yaml.safe_load(CLUSTER.read_text()))
