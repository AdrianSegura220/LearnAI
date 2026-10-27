import pytest

from learnai.adapters.tutor.anthropic.turn_schema import TURN_SCHEMA
from learnai.adapters.tutor.turn_schema import TurnSchemaError, parse_turn
from learnai.domain.enums import HelpRung
from learnai.domain.turn import ProposalKind


def test_a_full_payload_round_trips():
    turn = parse_turn(
        {
            "message": "Try factoring out the common term first.",
            "rung_used": "NEXT_STEP",
            "diagnosis": "mc.gcf.partial",
            "proposals": [{"kind": "DROP_TO_PREREQUISITE", "target_skill_id": "quad.factor.common"}],
        }
    )
    assert turn.rung_used is HelpRung.NEXT_STEP
    assert turn.diagnosis == "mc.gcf.partial"
    assert turn.proposals[0].kind is ProposalKind.DROP_TO_PREREQUISITE
    assert turn.proposals[0].target_skill_id == "quad.factor.common"


def test_a_minimal_payload_defaults_the_rest():
    turn = parse_turn({"message": "What is the next thing you could try?", "rung_used": "NUDGE"})
    assert turn.diagnosis is None
    assert turn.proposals == ()


@pytest.mark.parametrize(
    "payload, match",
    [
        ("not an object", "not an object"),
        ({}, "'message'"),
        ({"message": "hi", "rung_used": "SHOUT"}, "'rung_used'"),
        ({"message": "hi", "rung_used": []}, "'rung_used'"),
        ({"message": "hi", "rung_used": "NUDGE", "proposals": [{"kind": {}}]}, "proposal kind"),
        ({"message": "hi", "rung_used": "NUDGE", "proposals": [{"kind": "SERVE_EASIER_ITEM", "extra": 1}]}, "unknown proposal fields"),
        ({"message": "hi", "rung_used": "NUDGE", "diagnosis": 3}, "'diagnosis'"),
        ({"message": "hi", "rung_used": "NUDGE", "proposals": {}}, "'proposals'"),
        ({"message": "hi", "rung_used": "NUDGE", "proposals": [{"kind": "TELEPORT"}]}, "proposal kind"),
        ({"message": "hi", "rung_used": "NUDGE", "extra": 1}, "unknown fields"),
    ],
)
def test_malformed_payloads_are_named_precisely(payload, match):
    with pytest.raises(TurnSchemaError, match=match):
        parse_turn(payload)


def test_the_schema_uses_member_names_as_enums():
    assert TURN_SCHEMA["properties"]["rung_used"]["enum"] == [
        "NONE",
        "NUDGE",
        "NEXT_STEP",
        "NAME_METHOD",
        "FULL_REVEAL",
    ]
    assert TURN_SCHEMA["required"] == ["message", "rung_used"]
