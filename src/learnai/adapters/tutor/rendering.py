"""Provider-neutral rendering of engine state and untrusted student data.

JSON framing preserves exact student fields without turning role-like text into
operator instructions. Reference answers and generator solutions have no path
through these renderers.
"""
from dataclasses import asdict
import json
from typing import Any

from learnai.domain.history import HistoryRecord
from learnai.domain.interaction import StudentInteraction, VerificationSnapshot
from learnai.domain.items import Block, Formula, Text
from learnai.domain.turn import TurnContext


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def render_blocks(blocks: tuple[Block, ...]) -> str:
    """Keep statement blocks in reading order; unknown media must be supported explicitly."""
    pieces: list[str] = []
    for block in blocks:
        if isinstance(block, Text):
            pieces.append(block.text)
        elif isinstance(block, Formula):
            pieces.append(block.source)
        else:
            raise TypeError(f"unsupported statement block: {type(block).__name__}")
    return "\n".join(pieces)


def render_skill_pack(context: TurnContext) -> str:
    pack = context.skill_pack
    return _json({
        "skill_id": pack.skill_id,
        "can_do_statement": pack.can_do_statement,
        "teaching_notes": pack.teaching_notes,
        "misconceptions": [asdict(misconception) for misconception in pack.misconceptions],
    })


def render_session_preamble(context: TurnContext) -> str:
    """No stable learner profile exists in this slice; omit the optional layer."""
    return ""


def _verification_data(verification: VerificationSnapshot) -> dict[str, Any]:
    return {
        "revision": verification.revision,
        "answer_checked": verification.answer_checked,
        "steps_checked": verification.steps_checked,
        "answer": verification.verdict.name if verification.verdict else "not checked",
        "verdict": verification.verdict.name if verification.verdict else None,
        "step_diff": asdict(verification.step_diff) if verification.step_diff else None,
        "diagnosis": verification.diagnosis,
        "failed_constraints": list(verification.failed_constraints),
    }


def render_interaction(
    interaction: StudentInteraction, verification: VerificationSnapshot | None,
) -> str:
    current = verification is not None and verification.revision == interaction.revision
    data: dict[str, Any] = {
        "task_id": interaction.task_id,
        "revision": interaction.revision,
        "kind": interaction.kind.name,
        "status": interaction.status.name,
        "steps": list(interaction.steps),
        "answer": {"fields": list(interaction.answer.fields),
                   "claims_none": interaction.answer.claims_none},
        "question": interaction.question,
        "referenced_step": interaction.referenced_step,
        "verification": _verification_data(verification) if current else {
            "revision": interaction.revision, "answer_checked": False,
            "steps_checked": False, "answer": "not checked", "verdict": None,
            "step_diff": None, "diagnosis": None, "failed_constraints": [],
        },
    }
    if verification is not None and not current:
        data["historical_verification"] = _verification_data(verification)
    return _json(data)


def render_history(records: tuple[HistoryRecord, ...]) -> str:
    return _json([{
        "id": record.id, "at": record.at.isoformat(),
        "task_id": record.task_id, "item_id": record.item_id,
        "skill_id": record.skill_id, "revision": record.revision,
        "kind": record.kind.name,
        "interaction": json.loads(render_interaction(record.interaction, None))
        if record.interaction is not None else None,
        "message": record.message,
        "historical_verdict": record.verdict.name if record.verdict else None,
        "evidence_class": record.evidence_class.name if record.evidence_class else None,
        "rung": record.rung.name if record.rung is not None else None,
        "related_record_ids": list(record.related_record_ids),
    } for record in records])


def render_moment(context: TurnContext) -> str:
    progress = context.task_progress
    summary = context.student_summary
    interaction = context.interaction
    current_record = next((record for record in context.history
                           if record.id == context.current_interaction_id), None)
    metadata = json.loads(render_history((current_record,)))[0] if current_record else None
    if metadata is not None:
        # Identity and current work already have their own fields below.
        for key in ("id", "interaction", "message"):
            del metadata[key]
    return _json({
        "current_interaction_id": context.current_interaction_id,
        "current_record": metadata,
        "exercise": {
            "item_id": context.item.id, "skill_id": context.item.skill_id,
            "instructions": render_blocks(context.item.statement),
            "answer_kind": context.item.answer_spec.kind.value,
            "form_constraints": list(context.item.answer_spec.form_constraints),
            "answer_label": context.item.answer_spec.label,
        },
        "interaction": json.loads(render_interaction(interaction, context.verification))
        if interaction is not None else None,
        "progress": {
            "submissions": progress.submissions,
            "genuine_attempts": progress.genuine_attempts,
            "declines": progress.declines,
            "delivered_rungs": [rung.name for rung in progress.delivered_rungs],
            "independence_spent": progress.independence_spent,
            "last_checked_revision": progress.last_checked_revision,
        } if progress is not None else None,
        "student_state": {
            "strength": summary.strength, "is_fresh": summary.is_fresh,
            "calibration_gap": summary.calibration_gap,
            "prior_misconceptions": list(summary.prior_misconceptions),
        },
        "permitted_rung": context.permitted_rung.name,
        "response_job": context.response_job.name,
        "legacy_findings": {
            "verdict": context.last_verdict.name if context.last_verdict else None,
            "step_diff": asdict(context.step_diff) if context.step_diff else None,
            "diagnosis": context.diagnosis,
        } if interaction is None else None,
    })
