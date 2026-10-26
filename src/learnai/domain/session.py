# src/learnai/domain/session.py
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from learnai.domain.contracts import ModeContract
from learnai.domain.help import HelpState
from learnai.domain.ids import CourseId, MisconceptionId, SessionId, SkillId, StudentId, TaskId
from learnai.domain.items import Item, StepDiff
from learnai.domain.history import HistoryRecord
from learnai.domain.interaction import StudentInteraction, VerificationSnapshot
from learnai.domain.turn import TranscriptEntry


class TaskState(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class Task:
    id: TaskId
    session_id: SessionId
    item: Item
    skill_id: SkillId
    state: TaskState = TaskState.PENDING
    help_state: HelpState = HelpState()
    last_step_diff: StepDiff | None = None
    last_diagnosis: MisconceptionId | None = None
    """Current-revision findings, also used for a later help-request walk-back."""

    work_revision: int = 0
    current_interaction: StudentInteraction | None = None
    last_verification: VerificationSnapshot | None = None


@dataclass(frozen=True, slots=True)
class Session:
    id: SessionId
    student_id: StudentId
    course_id: CourseId
    contract: ModeContract
    plan: tuple[Task, ...]
    cursor: int
    started_at: datetime
    ended_at: datetime | None = None
    skills_taught: frozenset[SkillId] = frozenset()
    """Skills instructed during this session; drives post_instruction weighting."""

    transcript: tuple[TranscriptEntry, ...] = ()
    history: tuple[HistoryRecord, ...] = ()

    @property
    def current_task(self) -> Task | None:
        if self.cursor >= len(self.plan):
            return None
        return self.plan[self.cursor]

    @property
    def is_finished(self) -> bool:
        return self.ended_at is not None or self.cursor >= len(self.plan)


def replace_task(session: Session, task: Task) -> Session:
    plan = tuple(task if t.id == task.id else t for t in session.plan)
    return replace(session, plan=plan)


def advance(session: Session) -> Session:
    return replace(session, cursor=session.cursor + 1)


def end_session(session: Session, now: datetime) -> Session:
    return replace(session, ended_at=now)
