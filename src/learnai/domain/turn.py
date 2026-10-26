# src/learnai/domain/turn.py
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from enum import Enum

from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId, SkillId, TaskId
from learnai.domain.history import HistoryRecord, HistoryScope
from learnai.domain.interaction import ResponseJob, StudentInteraction, TaskProgress, VerificationSnapshot
from learnai.domain.mastery import SkillState, is_fresh
from learnai.domain.parameters import MasteryParameters
from learnai.domain.items import Item, StepDiff
from learnai.domain.leakguard import detect_leak
from learnai.domain.ports import Tutor, Verifier
from learnai.domain.skills import Misconception

if TYPE_CHECKING:
    from learnai.domain.session import Session, Task


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
    record_id: str | None = None
    task_id: TaskId | None = None
    revision: int | None = None
    at: datetime | None = None


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

    interaction: StudentInteraction | None = None
    verification: VerificationSnapshot | None = None
    task_progress: TaskProgress | None = None
    history_scope: HistoryScope | None = None
    history: tuple[HistoryRecord, ...] = ()
    current_interaction_id: str | None = None
    response_job: ResponseJob = ResponseJob.NORMAL


def build_turn_context(
    *,
    session: "Session",
    task: "Task",
    states: dict[SkillId, SkillState],
    interaction: StudentInteraction,
    verification: VerificationSnapshot,
    graph: SkillGraph,
    catalogue: Mapping[MisconceptionId, Misconception],
    now: datetime,
    permitted_rung: HelpRung,
    parameters: MasteryParameters,
    response_job: ResponseJob = ResponseJob.NORMAL,
) -> TurnContext:
    """Build the same authoritative context for live practice and evaluation."""
    skill = graph.skills[task.skill_id]
    state = states.get(task.skill_id)
    current = verification.revision == interaction.revision
    record = next((r for r in reversed(session.history)
                   if r.task_id == task.id and r.interaction == interaction), None)
    checked = task.last_verification
    last_checked_revision = (
        checked.revision if checked is not None and (checked.answer_checked or checked.steps_checked)
        else None
    )
    return TurnContext(
        skill_pack=SkillPack(skill.id, skill.can_do_statement,
                             skill.teaching_notes,
                             tuple(catalogue[m] for m in skill.misconception_ids)),
        item=task.item,
        student_summary=StudentSummary(
            state.strength if state else 0.0,
            is_fresh(state, now, parameters) if state else False,
            state.calibration_gap if state else 0.0,
            state.active_misconceptions if state else (),
        ),
        step_diff=verification.step_diff if current else None,
        diagnosis=verification.diagnosis if current else None,
        permitted_rung=permitted_rung,
        last_verdict=verification.verdict if current else None,
        transcript=session.transcript,
        interaction=interaction,
        verification=verification,
        task_progress=TaskProgress(
            submissions=task.help_state.submissions,
            genuine_attempts=task.help_state.attempts,
            declines=task.help_state.submissions - task.help_state.attempts,
            delivered_rungs=task.help_state.rungs_used,
            independence_spent=task.help_state.help_taken or task.help_state.submissions > 0,
            last_checked_revision=last_checked_revision,
        ),
        history_scope=HistoryScope(session.student_id, session.id),
        history=session.history,
        current_interaction_id=record.id if record else None,
        response_job=response_job,
    )


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


@dataclass(frozen=True, slots=True)
class TurnFeedback:
    reason: RejectionReason
    detail: str | None
    rejected: TutorTurn


def request_validated_turn(
    tutor: Tutor,
    context: TurnContext,
    graph: SkillGraph,
    verifier: Verifier,
    *,
    max_attempts: int,
) -> tuple[TutorTurn | None, int]:
    """Run validation retries in one private exchange with one shared budget."""
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    exchange = tutor.begin_turn(context)
    accepted: TutorTurn | None = None
    attempts = 0
    reason = "validation_exhausted"
    feedback: TurnFeedback | None = None
    try:
        for _ in range(max_attempts):
            if exchange.expired():
                reason = exchange.stop_reason or "deadline"
                break
            attempts += 1
            turn = exchange.respond(feedback=feedback)
            if exchange.expired():
                reason = exchange.stop_reason or "deadline"
                break
            if turn is None:
                reason = exchange.stop_reason or "silent"
                break
            result = validate_turn(turn, context, graph, verifier)
            exchange.record_validation(result)
            if exchange.expired():
                reason = exchange.stop_reason or "deadline"
                break
            if result.accepted:
                accepted = turn
                reason = "accepted"
                break
            assert result.reason is not None
            feedback = TurnFeedback(result.reason, result.detail, turn)
        return accepted, attempts
    finally:
        exchange.finish(accepted=accepted, reason=exchange.stop_reason or reason)
