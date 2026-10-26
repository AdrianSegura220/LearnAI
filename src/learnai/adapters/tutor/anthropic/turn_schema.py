"""Anthropic wire schema with compatibility imports for shared turn parsing."""

from learnai.adapters.tutor.turn_schema import TurnSchemaError, parse_turn


TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "rung_used": {
            "type": "string",
            "enum": ["NONE", "NUDGE", "NEXT_STEP", "NAME_METHOD", "FULL_REVEAL"],
        },
        "diagnosis": {"type": ["string", "null"]},
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "DROP_TO_PREREQUISITE",
                            "SERVE_EASIER_ITEM",
                            "END_TASK_UNPRODUCTIVE",
                        ],
                    },
                    "target_skill_id": {"type": ["string", "null"]},
                },
                "required": ["kind"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["message", "rung_used"],
    "additionalProperties": False,
}
