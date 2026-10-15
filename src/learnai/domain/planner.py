# src/learnai/domain/planner.py
from collections.abc import Sequence
from datetime import datetime

from learnai.domain.contracts import ModeContract
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import CourseId, SessionId, SkillId, StudentId, TaskId
from learnai.domain.mastery import SkillState, is_fresh, is_learned
from learnai.domain.parameters import DEFAULT_PARAMETERS, MasteryParameters
from learnai.domain.ports import ItemSource
from learnai.domain.session import Session, Task


def target_difficulty(
    state: SkillState | None, params: MasteryParameters = DEFAULT_PARAMETERS
) -> float:
    """Aim an item the student should clear about 75% of the time."""
    strength = 0.0 if state is None else state.strength
    return strength - params.target_logit_margin


def select_skills(
    graph: SkillGraph,
    states: dict[SkillId, SkillState],
    course_skills: Sequence[SkillId],
    count: int,
    now: datetime,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> tuple[SkillId, ...]:
    """Repair stale prerequisites before advancing to new material.

    Slice 1 has no spaced-review queue; freshness enters only through this
    repair rule. The full due-queue arbitration arrives with the scheduler.
    """
    learned = {sid for sid, state in states.items() if is_learned(state, params)}
    frontier = graph.frontier(learned) & set(course_skills)
    ordered_frontier = [sid for sid in course_skills if sid in frontier]

    repair: list[SkillId] = []
    for sid in ordered_frontier:
        for prereq in sorted(graph.hard_prereqs(sid)):
            state = states.get(prereq)
            if (
                state
                and is_learned(state, params)
                and not is_fresh(state, now, params)
                and prereq not in repair
            ):
                repair.append(prereq)

    ordered = repair + ordered_frontier
    if not ordered:
        return ()
    return tuple(ordered[i % len(ordered)] for i in range(count))


def plan_session(
    *,
    session_id: SessionId,
    student_id: StudentId,
    course_id: CourseId,
    contract: ModeContract,
    graph: SkillGraph,
    states: dict[SkillId, SkillState],
    course_skills: Sequence[SkillId],
    item_source: ItemSource,
    budget_items: int,
    now: datetime,
    seed: int,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> Session:
    skills = select_skills(graph, states, course_skills, budget_items, now, params)
    tasks: list[Task] = []
    for position, skill_id in enumerate(skills):
        item = item_source.next_item(
            skill_id,
            target_difficulty(states.get(skill_id), params),
            seed=seed * 1000 + position,
        )
        if item.vetting_level < contract.min_vetting_level:
            continue
        tasks.append(
            Task(
                id=TaskId(f"{session_id}:{position}"),
                session_id=session_id,
                item=item,
                skill_id=skill_id,
            )
        )
    return Session(
        id=session_id,
        student_id=student_id,
        course_id=course_id,
        contract=contract,
        plan=tuple(tasks),
        cursor=0,
        started_at=now,
    )
