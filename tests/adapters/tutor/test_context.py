"""Selection protects active work and evicts only complete earlier exercises."""
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from learnai.adapters.tutor.context import ContextLimitError, render_context, select_context
from learnai.domain.enums import Verdict
from learnai.domain.history import HistoryKind
from learnai.domain.ids import TaskId
from learnai.domain.turn import TranscriptEntry
from tests.adapters.tutor.test_rendering import AT, make_context, record


def test_context_keeps_active_exercise_beyond_twenty_entries():
    history = tuple(record(f"exchange-{i}", message=f"Short work {i}") for i in range(24))
    view = select_context(make_context(history=history), input_budget=50_000, count_tokens=len)
    assert len(view.active) == 24
    assert tuple(entry.record_id for entry in view.active) == tuple(f"exchange-{i}" for i in range(24))
    assert view.input_tokens <= 50_000


def test_budget_excludes_older_exercises_before_active_work():
    old = record("old-result", task="old", kind=HistoryKind.SUBMISSION,
                 message="OLD_RAW_DETAIL " * 400, verdict=Verdict.WRONG)
    active = record("active-work", message="Active working  x^2  + 3*x + 2  ")
    context = make_context(history=(old, active))
    view = select_context(context, input_budget=6000, count_tokens=len)
    assert [entry.record_id for entry in view.active] == ["active-work"]
    assert "Active working  x^2  + 3*x + 2  " in view.active[0].text
    assert not view.earlier
    assert "OLD_RAW_DETAIL" not in render_context(context, view)
    assert "old-result" in view.summary and "WRONG" in view.summary
    assert "2026-10-15T12:00:00+00:00" in view.summary
    assert view.input_tokens <= 6000
    assert context.history == (old, active)
    assert context.permitted_rung.name == "NUDGE"


def test_earlier_mistake_then_correction_stays_ordered():
    old = (
        record("wrong-source", task="old", kind=HistoryKind.SUBMISSION,
               message="Long raw work " * 400, verdict=Verdict.WRONG),
        record("correct-source", task="old", kind=HistoryKind.SUBMISSION,
               verdict=Verdict.CORRECT, at=AT + timedelta(minutes=1)),
    )
    view = select_context(make_context(history=old), input_budget=6000, count_tokens=len)
    assert view.summary.index("wrong-source") < view.summary.index("correct-source")
    assert "WRONG" in view.summary and "CORRECT" in view.summary
    assert "12:00:00" in view.summary and "12:01:00" in view.summary
    assert "unresolved" not in view.summary.lower()
    assert {"wrong-source", "correct-source"} <= set(view.source_ids)


def test_current_interaction_is_included_once():
    context = make_context()
    current = record("current-question", interaction=context.interaction)
    context = replace(context, history=(current,), transcript=(
        TranscriptEntry("student", "Why does my second line work?", "current-question", TaskId("active")),
    ))
    view = select_context(context, input_budget=20_000, count_tokens=len)
    rendered = render_context(context, view)
    assert not view.active
    assert rendered.count("Why does my second line work?") == 1
    assert rendered.count("current-question") == 1


def test_protected_overflow_is_explicit():
    context = make_context()
    context = replace(context, interaction=replace(context.interaction, steps=("x" * 10_000, "final")))
    with pytest.raises(ContextLimitError):
        select_context(context, input_budget=5000, count_tokens=len)


def test_earlier_exercises_are_atomic_and_prioritize_same_skill():
    records = (
        record("relevant-1", task="relevant", message="relevant" * 100),
        record("relevant-2", task="relevant", message="relevant continued" * 100),
        record("recent-1", task="recent", message="unrelated" * 300, skill="other"),
    )
    view = select_context(make_context(history=records), input_budget=6500, count_tokens=len)
    assert [entry.record_id for entry in view.earlier] == ["relevant-1", "relevant-2"]
    assert "recent-1" in view.summary


def test_active_delivered_transcript_is_preserved_without_duplicate_history():
    delivered = record("delivered", kind=HistoryKind.TUTOR_DELIVERED, message="Try the product.")
    context = make_context(history=(delivered,), transcript=(
        TranscriptEntry("tutor", "Try the product.", "delivered", TaskId("active"), 1, AT),
        TranscriptEntry("tutor", "Legacy delivered response.", task_id=TaskId("active")),
    ))
    view = select_context(context, input_budget=20_000, count_tokens=len)
    assert len(view.active) == 2
    rendered = render_context(context, view)
    assert rendered.count("Try the product.") == 1
    assert rendered.count("Legacy delivered response.") == 1


def test_source_ids_include_current_interaction_provenance():
    view = select_context(make_context(), input_budget=20_000, count_tokens=len)
    assert "current-question" in view.source_ids


def test_missing_history_transcript_entries_keep_chronological_order():
    later = record("later", message="Second exchange", at=AT + timedelta(minutes=1))
    first = TranscriptEntry("tutor", "First delivered exchange", "first", TaskId("active"), 1, AT)
    context = make_context(history=(later,), transcript=(first,))
    view = select_context(context, input_budget=20_000, count_tokens=len)
    assert [entry.record_id for entry in view.active] == ["first", "later"]


def test_older_summaries_can_be_omitted_when_only_active_work_fits():
    context = make_context()
    protected = select_context(context, input_budget=20_000, count_tokens=len)
    old = tuple(record(f"old-{i}", task="old", verdict=Verdict.WRONG,
                       message="long previous work" * 100) for i in range(100))
    view = select_context(replace(context, history=old), input_budget=protected.input_tokens, count_tokens=len)
    assert view.input_tokens == protected.input_tokens
    assert not view.summary and not view.earlier
    assert all(not source.startswith("old-") for source in view.source_ids)
