# src/learnai/domain/events.py
from dataclasses import dataclass
from datetime import datetime

from learnai.domain.enums import Confidence, EvidenceClass, HelpRung
from learnai.domain.ids import ItemId, SkillId, StudentId, TaskId


@dataclass(frozen=True, slots=True)
class AttemptRecorded:
    at: datetime
    student_id: StudentId
    skill_id: SkillId
    item_id: ItemId
    task_id: TaskId
    item_difficulty: float
    outcome: float
    """1.0 correct, 0.0 wrong, the format's guess baseline for a decline."""
    evidence_class: EvidenceClass
    confidence: Confidence
    contract_weight: float

    @property
    def correct(self) -> bool:
        return self.outcome >= 1.0


@dataclass(frozen=True, slots=True)
class HelpTaken:
    at: datetime
    student_id: StudentId
    skill_id: SkillId
    item_id: ItemId
    task_id: TaskId
    rung: HelpRung


EvidenceEvent = AttemptRecorded | HelpTaken
