"""Offline assessment of an accepted response against its captured student moment.

Reference construction belongs to the evaluator catalogue. Neither candidate
prose nor an item's unreviewed worked steps can manufacture a trusted reference.
"""
from dataclasses import asdict, dataclass
import json
import re
from typing import Any

from learnai.eval.ports import Judge
from learnai.adapters.tutor.context import scoped_context
from learnai.adapters.tutor.rendering import render_history, render_moment, render_skill_pack
from learnai.domain.items import Submission
from learnai.domain.turn import TurnContext, TutorTurn


class JudgeError(ValueError):
    """Malformed output or operational failure; never an evidence abstention."""


def _strings(value: Any, name: str, *, nonempty: bool = False) -> None:
    if (not isinstance(value, tuple) or (nonempty and not value)
            or any(not isinstance(entry, str) or not entry.strip() for entry in value)):
        raise JudgeError(f"{name} must be a {'nonempty ' if nonempty else ''}tuple of nonempty strings")


@dataclass(frozen=True, slots=True)
class JudgeReference:
    answer: Submission | None
    reasoning: tuple[str, ...]
    provenance: str
    teaching_notes: str
    misconception_explanations: tuple[str, ...]
    criteria: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JudgePacket:
    context: TurnContext
    turn: TutorTurn
    reference: JudgeReference
    learner_level: str | None = None
    missing_information: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _strings(self.missing_information, "missing_information")
        gaps = list(self.missing_information)
        available = {
            "learner_level": self.learner_level,
            "reference.answer": self.reference.answer,
            "reference.reasoning": self.reference.reasoning,
            "reference.provenance": self.reference.provenance,
            "interaction": self.context.interaction,
            "verification": self.context.verification,
            "task_progress": self.context.task_progress,
        }
        for name, value in available.items():
            if value is None or value == () or value == "":
                gaps.append(name)
        object.__setattr__(self, "missing_information", tuple(dict.fromkeys(gaps)))


def build_judge_messages(packet: JudgePacket) -> tuple[dict[str, Any], ...]:
    """Serialize captured state and isolated evaluator data, without inference/I/O."""
    context, reference, turn = scoped_context(packet.context), packet.reference, packet.turn
    data = {
        "student_situation": {
            "moment": json.loads(render_moment(context)),
            "history_scope": asdict(context.history_scope) if context.history_scope else None,
            "history": json.loads(render_history(context.history)),
            "transcript": [{
                "speaker": entry.speaker, "text": entry.text, "record_id": entry.record_id,
                "task_id": entry.task_id, "revision": entry.revision,
                "at": entry.at.isoformat() if entry.at else None,
            } for entry in context.transcript],
            "learner_level": packet.learner_level,
        },
        "evaluator_reference": {
            "answer": asdict(reference.answer) if reference.answer is not None else None,
            "reasoning": reference.reasoning,
            "provenance": reference.provenance,
            "teaching_notes": reference.teaching_notes,
            "misconception_explanations": reference.misconception_explanations,
            "criteria": reference.criteria,
            "skill_pack": json.loads(render_skill_pack(context)),
            "item_provenance": {
                "kind": context.item.provenance.kind.name,
                "template_id": context.item.provenance.template_id,
                "seed": context.item.provenance.seed,
            },
        },
        "candidate_response": {
            "message": turn.message, "rung_used": turn.rung_used.name,
            "diagnosis": turn.diagnosis,
            "proposals": [{"kind": proposal.kind.name, "target_skill_id": proposal.target_skill_id}
                          for proposal in turn.proposals],
        },
        "missing_information": packet.missing_information,
    }
    return ({"role": "user", "content": json.dumps(data, ensure_ascii=False, separators=(",", ":"))},)


@dataclass(frozen=True, slots=True)
class JudgeScores:
    mathematics: int | None
    help_level: int | None
    diagnosis: int | None
    tone: int | None
    reasons: tuple[str, ...]
    status: str = "scored"
    missing_information: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _strings(self.reasons, "reasons", nonempty=True)
        _strings(self.missing_information, "missing_information")
        values = (self.mathematics, self.help_level, self.diagnosis, self.tone)
        if self.status == "scored":
            if any(type(value) is not int or not 0 <= value <= 2 for value in values):
                raise JudgeError("scored results require four integers in 0–2")
        elif self.status == "insufficient_evidence":
            if any(value is not None for value in values) or not self.missing_information:
                raise JudgeError("insufficient_evidence requires four nulls and named missing evidence")
        else:
            raise JudgeError("unknown score status")


_DIMENSIONS = ("mathematics", "help_level", "diagnosis", "tone")
_SCORE_KEYS = frozenset((*_DIMENSIONS, "reasons", "status", "missing_information"))
SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        # Provider schemas omit numerical bounds; JudgeScores enforces 0–2 locally.
        **{name: {"type": ["integer", "null"]} for name in _DIMENSIONS},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "enum": ["scored", "insufficient_evidence"]},
        "missing_information": {"type": "array", "items": {"type": "string"}},
    },
    "required": list((*_DIMENSIONS, "reasons", "status", "missing_information")),
    "additionalProperties": False,
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JudgeError(f"duplicate key: {key}")
        result[key] = value
    return result


def parse_scores(text: str) -> JudgeScores:
    """Accept one JSON object (optionally fenced); enforce whole-turn scoring."""
    if not isinstance(text, str):
        raise JudgeError("scores must be JSON text")
    text = text.strip()
    if fenced := re.fullmatch(r"```(?:json)?\s*\n?(.*?)\s*```", text, re.DOTALL | re.IGNORECASE):
        text = fenced[1]
    try:
        data = json.loads(text, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as exc:
        raise JudgeError(f"invalid score JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) != _SCORE_KEYS:
        raise JudgeError("scores require exactly the seven rubric keys")
    for name in ("reasons", "missing_information"):
        if not isinstance(data[name], list):
            raise JudgeError(f"{name} must be an array")
        data[name] = tuple(data[name])
    return JudgeScores(**data)


def run_judge(judge: Judge, *, packet: JudgePacket) -> JudgeScores:
    """Score the exact captured packet through a bound provider-independent port."""
    return judge.evaluate(packet)
