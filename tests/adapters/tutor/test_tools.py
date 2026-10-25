"""Tool contracts exercise real CAS, generators, catalogue and scoped reader."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json

import pytest

from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.adapters.persistence.in_memory_history import InMemoryHistoryReader
from learnai.adapters.tutor.anthropic.tool_schema import encode_tools
from learnai.adapters.tutor.tools import ToolError, Toolbox
from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.history import HistoryKind, HistoryRecord, HistoryScope
from learnai.domain.ids import MisconceptionId, SessionId, SkillId, StudentId, TaskId
from learnai.domain.interaction import InteractionKind, StudentInteraction, WorkStatus
from learnai.domain.items import Submission
from learnai.domain.mastery import SkillState
from learnai.domain.skills import Misconception
from learnai.domain.turn import SkillPack, StudentSummary, TurnContext

AT = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)
MISCONCEPTION = Misconception(MisconceptionId("square"), "math", "Square of sum",
                              "The cross term is missing.", "square_sum")
CATALOGUE = {MISCONCEPTION.id: MISCONCEPTION}


def context(skill="quad.factor.monic"):
    item = REGISTRY.next_item(SkillId(skill), 0.0, 0)
    return TurnContext(SkillPack(item.skill_id, "Factor", "Check signs", (MISCONCEPTION,)),
                       item, StudentSummary(0.4, True, 0.1, (MISCONCEPTION.id,)),
                       None, None, HelpRung.NUDGE,
                       history_scope=HistoryScope(StudentId("student"), SessionId("session")))


def test_five_advertised_tools_execute_and_provider_schema_uses_same_table():
    toolbox = Toolbox(REGISTRY, CATALOGUE)
    ctx = context()
    tools = toolbox.tools()
    assert {t.name for t in tools} == {"check_expression", "get_worked_example",
        "lookup_misconception", "get_student_summary", "get_session_history"}
    encoded = encode_tools(tools)
    assert [t["name"] for t in encoded] == [t.name for t in tools]
    assert all(t["input_schema"]["type"] == "object" for t in encoded)
    assert json.loads(toolbox.execute("get_session_history", {}, ctx)) == {
        "records": [], "next_before_id": None}
    assert json.loads(toolbox.execute("get_student_summary", {}, ctx)) == {
        "strength": 0.4, "is_fresh": True, "calibration_gap": 0.1,
        "prior_misconceptions": ["square"]}
    assert json.loads(toolbox.execute("lookup_misconception", {"misconception_id": "square"}, ctx)) == asdict(MISCONCEPTION)
    result = json.loads(toolbox.execute("check_expression", {"expression": ctx.item.answer_spec.expression}, ctx))
    assert result == {"scope": "active_item_answer", "verdict": "CORRECT", "failed_constraints": []}
    wrong = toolbox.execute("check_expression", {"expression": "123456"}, ctx)
    assert json.loads(wrong)["verdict"] == "WRONG"
    assert wrong == toolbox.execute("check_expression", {"expression": "123456"}, ctx)
    assert json.loads(toolbox.execute("check_expression", {"expression": "@!"}, ctx))["verdict"] == "MALFORMED"
    assert json.loads(toolbox.execute("get_worked_example", {}, ctx))["worked_steps"]


def test_worked_example_is_distinct_vetted_same_skill_with_actual_worked_steps():
    toolbox = Toolbox(REGISTRY, CATALOGUE)
    ctx = context()
    result = json.loads(toolbox.execute("get_worked_example", {}, ctx))
    assert result["item_id"] != ctx.item.id
    assert result["skill_id"] == ctx.item.skill_id
    assert result["statement"] != "\n".join(getattr(b, "source", getattr(b, "text", "")) for b in ctx.item.statement)
    assert result["vetting_level"] == "MACHINE_VERIFIED"
    assert len(result["worked_steps"]) >= 2
    assert result == json.loads(toolbox.execute("get_worked_example", {}, ctx))


@pytest.mark.parametrize("skill", ["quad.discriminant", "quad.vertex", "quad.word.area", "missing"])
def test_worked_example_unavailable_is_typed_error_not_fabricated_solution(skill):
    ctx = context() if skill == "missing" else context(skill)
    if skill == "missing":
        ctx = replace(ctx, item=replace(ctx.item, skill_id=SkillId(skill)),
                      skill_pack=replace(ctx.skill_pack, skill_id=SkillId(skill)))
    with pytest.raises(ToolError) as error:
        Toolbox(REGISTRY, CATALOGUE).execute("get_worked_example", {}, ctx)
    assert error.value.code == "worked_example_unavailable"


def test_history_tool_preserves_raw_work_provenance_and_browses_prior_skills():
    ctx = context()
    interaction = StudentInteraction(TaskId("old"), 2, InteractionKind.TASK_QUESTION,
        WorkStatus.DRAFT, ("x^2",), Submission.of(" raw "), "Why?", 0)
    record = HistoryRecord("question", AT, ctx.history_scope.student_id,
        ctx.history_scope.session_id, TaskId("old"), ctx.item.id, SkillId("prior-skill"),
        2, HistoryKind.STUDENT_QUESTION, interaction=interaction, verdict=Verdict.WRONG,
        related_record_ids=("submission",))
    ctx = replace(ctx, history=(record,))
    toolbox = Toolbox(REGISTRY, CATALOGUE, InMemoryHistoryReader(ctx.history))
    payload = json.loads(toolbox.execute("get_session_history", {}, ctx))
    result = payload["records"][0]
    assert result["skill_id"] == "prior-skill"
    assert result["task_id"] == "old"
    assert result["revision"] == 2
    assert result["at"] == "2026-10-15T12:00:00+00:00"
    assert result["related_record_ids"] == ["submission"]
    assert result["interaction"]["question"] == "Why?"
    assert result["interaction"]["answer"]["fields"] == [" raw "]
    assert result["historical_verdict"] == "WRONG"
    assert json.loads(toolbox.execute("get_session_history", {"skill_id": "prior-skill",
        "kind": "student_question", "after": "2026-10-15T11:00:00Z",
        "before": "2026-10-15T13:00:00+00:00", "limit": 1}, ctx)) == payload
    assert json.loads(toolbox.execute("get_session_history", {"task_id": "foreign"}, ctx))["records"] == []
    with pytest.raises(ToolError) as error:
        toolbox.execute("get_session_history", {"before_id": "foreign"}, ctx)
    assert error.value.code == "history_cursor_not_found"


def test_history_requires_explicit_scope_even_with_empty_default_reader():
    with pytest.raises(ToolError) as error:
        Toolbox(REGISTRY, CATALOGUE).execute("get_session_history", {}, replace(context(), history_scope=None))
    assert error.value.code == "history_scope_required"


@pytest.mark.parametrize("name,arguments", [
    ("missing", {}), ("check_expression", {}), ("check_expression", {"expression": 3}),
    ("lookup_misconception", {"misconception_id": "unknown"}),
    ("get_student_summary", {"write": True}), ("get_session_history", {"student_id": "other"}),
    ("get_session_history", {"search": "question"}), ("get_session_history", {"limit": 21}),
    ("get_session_history", {"limit": True}), ("get_session_history", {"kind": "operator"}),
    ("get_session_history", {"after": "2026-10-15T12:00:00"}),
    ("get_session_history", {"before": "yesterday"}),
    ("get_session_history", {"after": 123}), ("get_session_history", {"task_id": []}),
])
def test_invalid_tools_and_arguments_are_explicit_errors(name, arguments):
    with pytest.raises(ToolError):
        Toolbox(REGISTRY, CATALOGUE).execute(name, arguments, context())


def test_tool_reads_cannot_change_evidence_or_mastery():
    ctx = context()
    state = SkillState(StudentId("student"), ctx.item.skill_id, strength=0.4)
    log = InMemoryEvidenceLog()
    before = (asdict(state), log.events(), asdict(ctx))
    toolbox = Toolbox(REGISTRY, CATALOGUE, InMemoryHistoryReader(ctx.history))
    for name, arguments in (("check_expression", {"expression": "1"}),
        ("get_worked_example", {}), ("lookup_misconception", {"misconception_id": "square"}),
        ("get_student_summary", {}), ("get_session_history", {})):
        toolbox.execute(name, arguments, ctx)
    assert (asdict(state), log.events(), asdict(ctx)) == before


def test_intermediate_equivalence_is_separate_from_active_answer_grading():
    toolbox = Toolbox(REGISTRY, CATALOGUE)
    ctx = context()
    assert json.loads(toolbox.execute("check_expression", {
        "expression": "2*x+2", "reference": "2*(x+1)"}, ctx)) == {
            "scope": "equivalence_only", "equivalent": True}
    assert json.loads(toolbox.execute("check_expression", {
        "expression": "2*x+3", "reference": "2*(x+1)"}, ctx)) == {
            "scope": "equivalence_only", "equivalent": False}
    assert json.loads(toolbox.execute("check_expression", {
        "expression": "x=2", "reference": "x^2=4"}, ctx))["equivalent"] is False
    # Equivalent mathematics still fails the active item's required factored form.
    expanded = next(block.source for block in ctx.item.statement if hasattr(block, "source"))
    result = json.loads(toolbox.execute("check_expression", {"expression": expanded}, ctx))
    assert result["verdict"] == "WRONG"
    assert result["failed_constraints"] == ["fully_factored"]


@pytest.mark.parametrize("arguments", [
    {"expression": "@!", "reference": "x+1"},
    {"expression": "x+1", "reference": "@!"},
    {"expression": " "}, {"expression": "x", "reference": " "},
    {"expression": "x", "reference": None},
])
def test_uncheckable_or_blank_math_is_a_typed_tool_error(arguments):
    with pytest.raises(ToolError):
        Toolbox(REGISTRY, CATALOGUE).execute("check_expression", arguments, context())


@pytest.mark.parametrize("arguments", [
    {"task_id": None}, {"skill_id": None}, {"item_id": None}, {"before_id": None},
    {"kind": HistoryKind.SUBMISSION},
])
def test_history_tool_rejects_values_outside_its_json_schema(arguments):
    with pytest.raises(ToolError) as error:
        Toolbox(REGISTRY, CATALOGUE).execute("get_session_history", arguments, context())
    assert error.value.code == "invalid_arguments"


def test_invalid_active_item_key_is_a_tool_failure_not_a_student_verdict():
    ctx = context()
    ctx = replace(ctx, item=replace(ctx.item, answer_spec=replace(
        ctx.item.answer_spec, expression="@!")))
    with pytest.raises(ToolError) as error:
        Toolbox(REGISTRY, CATALOGUE).execute("check_expression", {"expression": "x"}, ctx)
    assert error.value.code == "expression_uncheckable"
