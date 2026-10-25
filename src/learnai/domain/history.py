"""Immutable session history; access scope is bound by application code."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from learnai.domain.enums import EvidenceClass, HelpRung, Verdict
from learnai.domain.ids import ItemId, SessionId, SkillId, StudentId, TaskId
from learnai.domain.interaction import StudentInteraction


class HistoryKind(Enum):
    HELP_REQUEST = "help_request"
    STUDENT_QUESTION = "student_question"
    SUBMISSION = "submission"
    TUTOR_DELIVERED = "tutor_delivered"
    HELP_DELIVERED = "help_delivered"


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    id: str
    at: datetime
    student_id: StudentId
    session_id: SessionId
    task_id: TaskId
    item_id: ItemId
    skill_id: SkillId
    revision: int
    kind: HistoryKind
    interaction: StudentInteraction | None = None
    message: str | None = None
    verdict: Verdict | None = None
    evidence_class: EvidenceClass | None = None
    rung: HelpRung | None = None
    related_record_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoryScope:
    student_id: StudentId
    session_id: SessionId


@dataclass(frozen=True, slots=True)
class HistoryQuery:
    task_id: TaskId | None = None
    skill_id: SkillId | None = None
    before_id: str | None = None
    limit: int = 10
    item_id: ItemId | None = None
    kind: HistoryKind | None = None
    after: datetime | None = None
    before: datetime | None = None


@dataclass(frozen=True, slots=True)
class HistoryPage:
    records: tuple[HistoryRecord, ...]
    next_before_id: str | None
