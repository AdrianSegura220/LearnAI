# src/learnai/domain/turn.py
from dataclasses import dataclass
from enum import Enum

from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId, SkillId
from learnai.domain.items import Item, StepDiff
from learnai.domain.leakguard import detect_leak
from learnai.domain.ports import Verifier
from learnai.domain.skills import Misconception


@dataclass(frozen=True, slots=True)
class SkillPack:
    skill_id: SkillId
    can_do_statement: str
    teaching_notes: str
    misconceptions: tuple[Misconception, ...]


@dataclass(frozen=True, slots=True)
class StudentSummary:
    strength: float
    is_fresh: bool
    calibration_gap: float
    prior_misconceptions: tuple[MisconceptionId, ...]


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    speaker: str  # "student" | "tutor"
    text: str


@dataclass(frozen=True, slots=True)
class TurnContext:
    skill_pack: SkillPack
    item: Item
    student_summary: StudentSummary
    step_diff: StepDiff | None
    diagnosis: MisconceptionId | None
    permitted_rung: HelpRung
    last_verdict: Verdict | None = None
    """NO_ANSWER means the student declined: there is no work to diagnose, so the
    tutor's opening move is orientation rather than error correction."""
    transcript: tuple[TranscriptEntry, ...] = ()


class ProposalKind(Enum):
    DROP_TO_PREREQUISITE = "drop_to_prerequisite"
    SERVE_EASIER_ITEM = "serve_easier_item"
    END_TASK_UNPRODUCTIVE = "end_task_unproductive"


@dataclass(frozen=True, slots=True)
class Proposal:
    """A request, never a command. The engine decides."""

    kind: ProposalKind
    target_skill_id: SkillId | None = None


@dataclass(frozen=True, slots=True)
class TutorTurn:
    message: str
    rung_used: HelpRung
    diagnosis: MisconceptionId | None = None
    proposals: tuple[Proposal, ...] = ()


class RejectionReason(Enum):
    RUNG_EXCEEDED = "rung_exceeded"
    ANSWER_LEAKED = "answer_leaked"
    INVALID_PROPOSAL = "invalid_proposal"
    EMPTY_MESSAGE = "empty_message"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    accepted: bool
    reason: RejectionReason | None = None
    detail: str | None = None


def validate_turn(
    turn: TutorTurn,
    context: TurnContext,
    graph: SkillGraph,
    verifier: Verifier,
) -> ValidationResult:
    """Gate every tutor turn before a character of it reaches the student.

    Order matters: cheap structural checks first, the CAS-backed leak check last.
    """
    if not turn.message.strip():
        return ValidationResult(False, RejectionReason.EMPTY_MESSAGE)

    if turn.rung_used > context.permitted_rung:
        return ValidationResult(
            False,
            RejectionReason.RUNG_EXCEEDED,
            f"used {turn.rung_used.name}, permitted {context.permitted_rung.name}",
        )

    for proposal in turn.proposals:
        if proposal.kind is ProposalKind.DROP_TO_PREREQUISITE:
            target = proposal.target_skill_id
            if target is None or target not in graph.hard_prereqs(context.skill_pack.skill_id):
                return ValidationResult(
                    False,
                    RejectionReason.INVALID_PROPOSAL,
                    f"{target} is not a hard prerequisite of {context.skill_pack.skill_id}",
                )

    verdict = detect_leak(
        verifier, turn.message, context.item.answer_spec, context.permitted_rung
    )
    if verdict.leaked:
        return ValidationResult(
            False, RejectionReason.ANSWER_LEAKED, verdict.offending_expression
        )

    return ValidationResult(True)
