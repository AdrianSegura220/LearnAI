"""Deterministic read tools; mathematics is checked by the existing CAS adapter."""
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from typing import Any

from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.cas.vocabulary import (
    InvalidAnswerKeyError, UnknownConstraintError, UnsupportedAnswerKindError,
)
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.persistence.in_memory_history import (
    HistoryLookupError, HistoryQueryError, InMemoryHistoryReader,
)
from learnai.adapters.tutor.rendering import render_blocks, render_history
from learnai.domain.enums import VettingLevel
from learnai.domain.history import HistoryKind, HistoryQuery
from learnai.domain.ids import MisconceptionId
from learnai.domain.items import Submission, SubmissionShapeError
from learnai.domain.ports import HistoryReader
from learnai.domain.skills import Misconception
from learnai.domain.turn import TurnContext


class ToolError(ValueError):
    """A failed tool call; provider runtimes must emit an error tool_result."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: Callable[[Mapping[str, Any], TurnContext], str]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolError("invalid_arguments", f"{name} must be a nonblank string")
    return value


def _parameters(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any]


def tool_definitions() -> tuple[ToolDefinition, ...]:
    """Canonical read schemas, also used to bind every executable handler."""
    text = {"type": "string", "minLength": 1}
    return (
        ToolDefinition("check_expression",
             "Check mathematics using the CAS. With reference, check only equivalence; "
             "otherwise grade one active-item answer field including required form.",
             _parameters({"expression": text, "reference": text}, ("expression",))),
        ToolDefinition("get_worked_example", "Read a vetted, distinct worked example of this skill.",
             _parameters({})),
        ToolDefinition("lookup_misconception", "Read a misconception catalogue entry by its id.",
             _parameters({"misconception_id": text}, ("misconception_id",))),
        ToolDefinition("get_student_summary", "Read the current student summary.",
             _parameters({})),
        ToolDefinition("get_session_history", "Browse bounded history for the current student and "
             "current session, across skills. Time bounds are exclusive and UTC.",
             _parameters({"task_id": text, "skill_id": text, "item_id": text,
                 "kind": {"type": "string", "enum": [kind.value for kind in HistoryKind]},
                 "after": {"type": "string", "format": "date-time"},
                 "before": {"type": "string", "format": "date-time"},
                 "before_id": text,
                 "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}})),
    )


class Toolbox:
    """Read-only capabilities over content, catalogue and a request-local reader."""

    def __init__(self, items: GeneratorRegistry,
                 catalogue: Mapping[MisconceptionId, Misconception],
                 history: HistoryReader | None = None) -> None:
        self._items = items
        self._catalogue = catalogue
        self._history = history if history is not None else InMemoryHistoryReader(())
        self._tools = tuple(Tool(definition.name, definition.description, definition.parameters,
                                 getattr(self, '_' + definition.name))
                            for definition in tool_definitions())

    def tools(self) -> tuple[Tool, ...]:
        return self._tools

    def execute(self, name: str, arguments: Mapping[str, Any], context: TurnContext) -> str:
        tool = next((tool for tool in self._tools if tool.name == name), None)
        if tool is None:
            raise ToolError("unknown_tool", "unknown tool")
        if not isinstance(arguments, Mapping):
            raise ToolError("invalid_arguments", "tool arguments must be an object")
        if (set(arguments) - set(tool.parameters["properties"])
                or set(tool.parameters["required"]) - set(arguments)):
            raise ToolError("invalid_arguments", "unknown or missing tool arguments")
        for key, value in arguments.items():
            schema = tool.parameters["properties"][key]
            if schema["type"] == "string":
                _text(value, key)
            elif schema["type"] == "integer":
                if type(value) is not int or not schema["minimum"] <= value <= schema["maximum"]:
                    raise ToolError("invalid_arguments", f"{key} is outside its integer bounds")
            if "enum" in schema and value not in schema["enum"]:
                raise ToolError("invalid_arguments", f"unknown {key}")
        return tool.handler(arguments, context)

    def _check_expression(self, arguments: Mapping[str, Any], context: TurnContext) -> str:
        expression = _text(arguments["expression"], "expression")
        verifier = SympyVerifier()
        if "reference" in arguments:
            reference = _text(arguments["reference"], "reference")
            diff = verifier.diff_steps((reference, expression))
            if diff is not None and diff.unreadable:
                raise ToolError("expression_uncheckable", "CAS could not check these steps")
            return _json({"scope": "equivalence_only", "equivalent": diff is None})
        try:
            result = verifier.check_answer(Submission.of(expression), context.item.answer_spec)
        except (InvalidAnswerKeyError, UnknownConstraintError, UnsupportedAnswerKindError) as exc:
            raise ToolError("expression_uncheckable", "CAS cannot check this item's answer specification") from exc
        except SubmissionShapeError as exc:
            raise ToolError("invalid_arguments", str(exc)) from exc
        return _json({"scope": "active_item_answer", "verdict": result.verdict.name,
                      "failed_constraints": list(result.failed_constraints)})

    def _get_worked_example(self, arguments: Mapping[str, Any], context: TurnContext) -> str:
        # A finite, reproducible search; never manufacture steps from the answer key.
        templates = sorted(self._items.templates_for(context.item.skill_id), key=lambda s: s.id)
        for template in templates:
            for seed in range(20):
                item = self._items.instantiate(template.id, seed)
                if (item.id != context.item.id and item.statement != context.item.statement
                        and item.skill_id == context.item.skill_id and item.worked_steps
                        and item.vetting_level >= VettingLevel.HUMAN_REVIEWED):
                    return _json({"item_id": item.id, "skill_id": item.skill_id,
                                  "statement": render_blocks(item.statement),
                                  "worked_steps": list(item.worked_steps),
                                  "vetting_level": item.vetting_level.name,
                                  "provenance": {"template_id": item.provenance.template_id,
                                                 "seed": item.provenance.seed}})
        raise ToolError("worked_example_unavailable", "No distinct vetted worked example available")

    def _lookup_misconception(self, arguments: Mapping[str, Any], context: TurnContext) -> str:
        identifier = _text(arguments["misconception_id"], "misconception_id")
        entry = self._catalogue.get(MisconceptionId(identifier))
        if entry is None:
            raise ToolError("misconception_not_found", "Unknown misconception id")
        return _json(asdict(entry))

    def _get_student_summary(self, arguments: Mapping[str, Any], context: TurnContext) -> str:
        return _json(asdict(context.student_summary))

    def _get_session_history(self, arguments: Mapping[str, Any], context: TurnContext) -> str:
        if context.history_scope is None:
            raise ToolError("history_scope_required", "Current-session history scope is required")
        values = dict(arguments)
        for name in ("after", "before"):
            if name in values:
                raw = _text(values[name], name)
                try:
                    values[name] = datetime.fromisoformat(raw)
                except ValueError as exc:
                    raise ToolError("invalid_arguments", "Time bounds must be ISO UTC timestamps") from exc
        if "kind" in values:
            try:
                values["kind"] = HistoryKind(values["kind"])
            except (ValueError, TypeError) as exc:
                raise ToolError("invalid_arguments", "Unknown history kind") from exc
        try:
            page = self._history.read(context.history_scope, HistoryQuery(**values))
        except HistoryQueryError as exc:
            raise ToolError("invalid_arguments", str(exc)) from exc
        except HistoryLookupError as exc:
            raise ToolError("history_cursor_not_found", str(exc)) from exc
        return _json({"records": json.loads(render_history(page.records)),
                      "next_before_id": page.next_before_id})
