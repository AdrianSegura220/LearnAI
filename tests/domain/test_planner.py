# tests/domain/test_planner.py
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.domain.contracts import PRACTICE
from learnai.domain.enums import PrereqStrength
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import CourseId, SessionId, SkillId, StudentId, VerificationKind
from learnai.domain.mastery import SkillState
from learnai.domain.parameters import DEFAULT_PARAMETERS
from learnai.domain.planner import plan_session, select_skills, target_difficulty
from learnai.domain.skills import PrereqEdge, Skill

REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)


def _skill(sid: str) -> Skill:
    return Skill(SkillId(sid), "math", sid, f"can {sid}", VerificationKind("cas_symbolic"), (), ())


GRAPH = SkillGraph.build(
    [_skill("quad.expand.binomial"), _skill("quad.factor.monic"), _skill("quad.solve.factoring")],
    [
        PrereqEdge(SkillId("quad.expand.binomial"), SkillId("quad.factor.monic"), PrereqStrength.HARD),
        PrereqEdge(SkillId("quad.factor.monic"), SkillId("quad.solve.factoring"), PrereqStrength.HARD),
    ],
)
COURSE = (SkillId("quad.expand.binomial"), SkillId("quad.factor.monic"), SkillId("quad.solve.factoring"))


def learned(sid: str, clock: FakeClock, stability: float = 30.0) -> SkillState:
    return SkillState(StudentId("stu"), SkillId(sid), strength=2.0, stability=stability,
                      last_success_at=clock.now(), unassisted_correct_count=2)


def test_an_unknown_skill_targets_items_below_the_default_strength():
    assert target_difficulty(None) == -DEFAULT_PARAMETERS.target_logit_margin


def test_target_difficulty_tracks_strength():
    state = SkillState(StudentId("stu"), SkillId("s"), strength=2.0)
    assert target_difficulty(state) == 2.0 - DEFAULT_PARAMETERS.target_logit_margin


def test_an_empty_history_starts_at_the_graph_root():
    clock = FakeClock()
    chosen = select_skills(GRAPH, {}, COURSE, count=3, now=clock.now())
    assert set(chosen) == {SkillId("quad.expand.binomial")}


def test_the_frontier_advances_as_skills_are_learned():
    clock = FakeClock()
    states = {SkillId("quad.expand.binomial"): learned("quad.expand.binomial", clock)}
    chosen = select_skills(GRAPH, states, COURSE, count=2, now=clock.now())
    assert set(chosen) == {SkillId("quad.factor.monic")}


def test_a_stale_prerequisite_is_repaired_before_advancing():
    clock = FakeClock()
    states = {SkillId("quad.expand.binomial"): learned("quad.expand.binomial", clock, stability=2.0)}
    clock.advance(30.0)
    chosen = select_skills(GRAPH, states, COURSE, count=2, now=clock.now())
    assert chosen[0] == SkillId("quad.expand.binomial"), "repair before advance"


def test_the_plan_fills_the_requested_budget():
    clock = FakeClock()
    session = plan_session(
        session_id=SessionId("s1"), student_id=StudentId("stu"), course_id=CourseId("c"),
        contract=PRACTICE, graph=GRAPH, states={}, course_skills=COURSE,
        item_source=REGISTRY, budget_items=5, now=clock.now(), seed=11,
    )
    assert len(session.plan) == 5
    assert all(t.item.vetting_level >= PRACTICE.min_vetting_level for t in session.plan)


def test_planning_is_deterministic_for_a_given_seed():
    clock = FakeClock()
    kwargs = dict(
        session_id=SessionId("s1"), student_id=StudentId("stu"), course_id=CourseId("c"),
        contract=PRACTICE, graph=GRAPH, states={}, course_skills=COURSE,
        item_source=REGISTRY, budget_items=4, now=clock.now(), seed=11,
    )
    assert [t.item.id for t in plan_session(**kwargs).plan] == [
        t.item.id for t in plan_session(**kwargs).plan
    ]


def test_a_plan_never_repeats_an_item():
    clock = FakeClock()
    session = plan_session(
        session_id=SessionId("s1"), student_id=StudentId("stu"), course_id=CourseId("c"),
        contract=PRACTICE, graph=GRAPH, states={}, course_skills=COURSE,
        item_source=REGISTRY, budget_items=8, now=clock.now(), seed=3,
    )
    ids = [t.item.id for t in session.plan]
    assert len(ids) == len(set(ids))
