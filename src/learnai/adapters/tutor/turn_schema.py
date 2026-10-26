"""Provider-neutral parsing into the engine tutor-turn contract."""
from collections.abc import Mapping

from learnai.domain.enums import HelpRung
from learnai.domain.ids import MisconceptionId, SkillId
from learnai.domain.turn import Proposal, ProposalKind, TutorTurn


class TurnSchemaError(ValueError):
    """A model payload that does not carry a valid tutor turn."""


_RUNGS = {rung.name: rung for rung in HelpRung}
_PROPOSAL_KINDS = {kind.name: kind for kind in ProposalKind}
_TURN_FIELDS = frozenset({"message", "rung_used", "diagnosis", "proposals"})


def parse_turn(payload: Mapping[str, object]) -> TutorTurn:
    if not isinstance(payload, Mapping):
        raise TurnSchemaError(f"payload is {type(payload).__name__}, not an object")
    unknown = set(payload) - _TURN_FIELDS
    if unknown:
        raise TurnSchemaError(f"unknown fields {sorted(unknown)}")
    message = payload.get("message")
    if not isinstance(message, str):
        raise TurnSchemaError("'message' must be a string")
    rung_name = payload.get("rung_used")
    if not isinstance(rung_name, str) or rung_name not in _RUNGS:
        raise TurnSchemaError(
            f"'rung_used' must be one of {sorted(_RUNGS)}, got {rung_name!r}"
        )
    diagnosis = payload.get("diagnosis")
    if diagnosis is not None and not isinstance(diagnosis, str):
        raise TurnSchemaError("'diagnosis' must be a string or null")
    proposals_raw = payload.get("proposals", [])
    if not isinstance(proposals_raw, list):
        raise TurnSchemaError("'proposals' must be an array")
    proposals = []
    for entry in proposals_raw:
        if not isinstance(entry, Mapping):
            raise TurnSchemaError("each proposal must be an object")
        unknown = set(entry) - {"kind", "target_skill_id"}
        if unknown:
            raise TurnSchemaError(f"unknown proposal fields {sorted(unknown)}")
        kind_name = entry.get("kind")
        if not isinstance(kind_name, str) or kind_name not in _PROPOSAL_KINDS:
            raise TurnSchemaError(
                f"proposal kind must be one of {sorted(_PROPOSAL_KINDS)}, got {kind_name!r}"
            )
        target = entry.get("target_skill_id")
        if target is not None and not isinstance(target, str):
            raise TurnSchemaError("'target_skill_id' must be a string or null")
        proposals.append(
            Proposal(
                kind=_PROPOSAL_KINDS[kind_name],
                target_skill_id=SkillId(target) if target else None,
            )
        )
    return TutorTurn(
        message=message,
        rung_used=_RUNGS[rung_name],
        diagnosis=MisconceptionId(diagnosis) if diagnosis else None,
        proposals=tuple(proposals),
    )
