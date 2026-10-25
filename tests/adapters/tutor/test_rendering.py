"""Renderer contracts: preserve raw student data and checker provenance."""
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from learnai.adapters.tutor.rendering import (
    render_blocks, render_history, render_interaction, render_moment,
    render_session_preamble, render_skill_pack,
)
from learnai.domain.enums import HelpRung, Verdict, VettingLevel
from learnai.domain.history import HistoryKind, HistoryRecord, HistoryScope
from learnai.domain.ids import ItemId, SessionId, SkillId, StudentId, TaskId
from learnai.domain.interaction import (
    InteractionKind, StudentInteraction, TaskProgress, VerificationSnapshot, WorkStatus,
)
from learnai.domain.items import AnswerSpec, Formula, FormConstraint, Item, Provenance, Submission, Text
from learnai.domain.turn import SkillPack, StudentSummary, TurnContext


AT = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def make_context(**changes):
    interaction = StudentInteraction(
        TaskId("active"), 2, InteractionKind.TASK_QUESTION, WorkStatus.DRAFT,
        ("x^2 + 3*x + 2", "(x+1)*(x+2)"), Submission.of("  (x+1)*(x+2)  ", ""),
        "Why does my second line work?", 1,
    )
    item = Item(
        ItemId("item-active"), SkillId("factoring"), Provenance.authored(),
        (Text("Factor fully:"), Formula("x^2 + 3*x + 2"), Text("Show working.")),
        AnswerSpec("SECRET_REFERENCE", (FormConstraint("fully_factored"),), label="Answer:"),
        ("SECRET_WORKED_SOLUTION",), 0.5, VettingLevel.MACHINE_VERIFIED,
    )
    context = TurnContext(
        SkillPack(item.skill_id, "Factor a quadratic", "Check the product and sum.", ()),
        item, StudentSummary(0.4, False, 0.1, ()), None, None, HelpRung.NUDGE,
        interaction=interaction,
        verification=VerificationSnapshot(2, False, False, None, None, None),
        task_progress=TaskProgress(1, 1, 0, (), True, 1),
        history_scope=HistoryScope(StudentId("student"), SessionId("session")),
        current_interaction_id="current-question",
    )
    return replace(context, **changes)


def record(record_id, *, task="active", kind=HistoryKind.STUDENT_QUESTION,
           message=None, verdict=None, at=AT, interaction=None, skill="factoring"):
    return HistoryRecord(
        record_id, at, StudentId("student"), SessionId("session"), TaskId(task),
        ItemId("item-" + task), SkillId(skill), 1, kind,
        interaction=interaction, message=message, verdict=verdict,
    )


def test_render_current_work_and_question_without_grading_a_draft():
    context = make_context()
    data = json.loads(render_interaction(context.interaction, context.verification))
    assert data["steps"] == ["x^2 + 3*x + 2", "(x+1)*(x+2)"]
    assert data["answer"]["fields"] == ["  (x+1)*(x+2)  ", ""]
    assert data["status"] == "DRAFT"
    assert data["revision"] == 2
    assert data["question"] == "Why does my second line work?"
    assert data["referenced_step"] == 1
    assert data["verification"]["answer"] == "not checked"
    assert "WRONG" not in render_moment(context)


def test_old_check_is_identified_as_old():
    old = VerificationSnapshot(1, True, False, Verdict.WRONG, None, None)
    context = make_context(verification=old, last_verdict=Verdict.WRONG)
    data = json.loads(render_interaction(context.interaction, old))
    assert data["verification"]["answer"] == "not checked"
    assert data["historical_verification"]["revision"] == 1
    assert data["historical_verification"]["verdict"] == "WRONG"
    assert json.loads(render_moment(context))["interaction"]["verification"]["answer"] == "not checked"


def test_blocks_preserve_order_and_reject_unknown_types():
    assert render_blocks((Text("Before"), Formula("x^2"), Text("After"))) == "Before\nx^2\nAfter"
    with pytest.raises(TypeError):
        render_blocks((object(),))


def test_moment_has_constraints_progress_and_volatile_student_state_without_reference():
    moment = render_moment(make_context())
    data = json.loads(moment)
    assert data["exercise"]["answer_kind"] == "single_value"
    assert data["exercise"]["form_constraints"] == ["fully_factored"]
    assert data["exercise"]["answer_label"] == "Answer:"
    assert data["progress"]["genuine_attempts"] == 1
    assert data["progress"]["last_checked_revision"] == 1
    assert data["student_state"]["strength"] == 0.4
    assert data["permitted_rung"] == "NUDGE"
    assert "SECRET_REFERENCE" not in moment
    assert "SECRET_WORKED_SOLUTION" not in moment
    assert json.loads(render_skill_pack(make_context()))["teaching_notes"] == "Check the product and sum."
    assert "strength" not in render_session_preamble(make_context())


def test_student_expression_equal_to_reference_is_retained():
    context = make_context()
    context = replace(context, item=replace(context.item, answer_spec=replace(
        context.item.answer_spec, expression="  (x+1)*(x+2)  ")))
    assert json.loads(render_moment(context))["interaction"]["answer"]["fields"][0] == "  (x+1)*(x+2)  "


def test_history_renders_provenance_and_textless_help_requests():
    records = (record("help", kind=HistoryKind.HELP_REQUEST),)
    data = json.loads(render_history(records))[0]
    assert data["id"] == "help"
    assert data["task_id"] == "active"
    assert data["item_id"] == "item-active"
    assert data["skill_id"] == "factoring"
    assert data["kind"] == "HELP_REQUEST"
    assert data["at"] == "2026-10-15T12:00:00+00:00"
    assert data["revision"] == 1
    assert data["related_record_ids"] == []


def test_current_record_metadata_survives_exclusion_from_history():
    current = replace(record("current-question"), related_record_ids=("prior-question",))
    context = make_context(history=(current,))
    moment = json.loads(render_moment(context))
    assert moment["current_record"]["at"] == "2026-10-15T12:00:00+00:00"
    assert moment["current_record"]["related_record_ids"] == ["prior-question"]
    assert moment["current_record"]["skill_id"] == "factoring"
