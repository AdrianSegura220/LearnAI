# tests/domain/test_session.py
from dataclasses import replace

from learnai.adapters.clock import FakeClock
from learnai.domain.contracts import PRACTICE
from learnai.domain.enums import VettingLevel
from learnai.domain.ids import CourseId, ItemId, SessionId, SkillId, StudentId, TaskId
from learnai.domain.items import AnswerSpec, Item, Provenance, Text
from learnai.domain.session import Session, Task, TaskState, advance, end_session, replace_task


def item(n: int) -> Item:
    return Item(ItemId(f"i{n}"), SkillId("s"), Provenance.authored(), (Text(f"q{n}"),),
                AnswerSpec("1"), (), 0.0, VettingLevel.MACHINE_VERIFIED)


def session(n_tasks: int = 2) -> Session:
    clock = FakeClock()
    tasks = tuple(
        Task(TaskId(f"t{i}"), SessionId("sess"), item(i), SkillId("s")) for i in range(n_tasks)
    )
    return Session(SessionId("sess"), StudentId("stu"), CourseId("c"), PRACTICE,
                   tasks, 0, clock.now())


def test_current_task_follows_the_cursor():
    s = session()
    assert s.current_task.id == TaskId("t0")
    assert advance(s).current_task.id == TaskId("t1")


def test_a_session_finishes_when_the_plan_is_exhausted():
    s = advance(advance(session()))
    assert s.current_task is None and s.is_finished


def test_ending_a_session_marks_it_finished_early():
    clock = FakeClock()
    s = end_session(session(), clock.advance(0.01))
    assert s.is_finished and s.ended_at is not None


def test_replacing_a_task_leaves_the_others_untouched():
    s = session()
    updated = replace(s.plan[0], state=TaskState.COMPLETED)
    after = replace_task(s, updated)
    assert after.plan[0].state is TaskState.COMPLETED
    assert after.plan[1] == s.plan[1]


def test_transitions_never_mutate_the_original():
    s = session()
    advance(s)
    assert s.cursor == 0
