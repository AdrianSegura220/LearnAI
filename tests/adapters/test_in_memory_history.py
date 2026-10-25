"""Reader regression contracts: scope leaks, lost provenance, unsafe pagination."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from learnai.adapters.persistence.in_memory_history import (
    HistoryLookupError, HistoryQueryError, InMemoryHistoryReader,
)
from learnai.domain.history import HistoryKind, HistoryQuery, HistoryRecord, HistoryScope
from learnai.domain.ids import ItemId, SessionId, SkillId, StudentId, TaskId

AT = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
SCOPE = HistoryScope(StudentId("student"), SessionId("session"))


def record(n, **changes):
    return replace(HistoryRecord(
        str(n), AT + timedelta(minutes=n), SCOPE.student_id, SCOPE.session_id,
        TaskId(f"task-{n}"), ItemId(f"item-{n}"), SkillId("factoring"), n,
        HistoryKind.STUDENT_QUESTION, message=f"raw question {n}",
        related_record_ids=(f"source-{n}",),
    ), **changes)


def test_history_is_bound_to_student_and_session():
    reader = InMemoryHistoryReader((record(1), record(2, student_id=StudentId("other")),
                                    record(3, session_id=SessionId("other"))))
    assert [r.id for r in reader.read(SCOPE, HistoryQuery()).records] == ["1"]
    assert reader.read(SCOPE, HistoryQuery(task_id=TaskId("task-2"))).records == ()
    for cursor in ("2", "3", "missing"):
        with pytest.raises(HistoryLookupError, match="cursor"):
            reader.read(SCOPE, HistoryQuery(before_id=cursor))


def test_history_filters_are_optional_and_composable():
    records = (record(0), record(1, skill_id=SkillId("expanding")),
               record(2, kind=HistoryKind.HELP_REQUEST), record(3))
    reader = InMemoryHistoryReader(records)
    assert [r.id for r in reader.read(SCOPE, HistoryQuery()).records] == ["3", "2", "1", "0"]
    assert [r.id for r in reader.read(SCOPE, HistoryQuery(skill_id=SkillId("expanding"))).records] == ["1"]
    query = HistoryQuery(skill_id=SkillId("factoring"), task_id=TaskId("task-2"),
                         item_id=ItemId("item-2"), kind=HistoryKind.HELP_REQUEST,
                         after=AT + timedelta(minutes=1), before=AT + timedelta(minutes=3))
    page = reader.read(SCOPE, query)
    assert [r.id for r in page.records] == ["2"]
    assert page.records[0].related_record_ids == ("source-2",)
    assert reader.read(SCOPE, replace(query, before=AT + timedelta(minutes=2))).records == ()
    assert reader.read(SCOPE, replace(query, after=AT + timedelta(minutes=2))).records == ()


def test_history_pages_previous_exercises_with_provenance():
    reader = InMemoryHistoryReader(tuple(record(n) for n in range(25)))
    first = reader.read(SCOPE, HistoryQuery())
    second = reader.read(SCOPE, HistoryQuery(before_id=first.next_before_id))
    third = reader.read(SCOPE, HistoryQuery(before_id=second.next_before_id))
    assert [len(p.records) for p in (first, second, third)] == [10, 10, 5]
    records = first.records + second.records + third.records
    assert [r.id for r in records] == [str(n) for n in range(24, -1, -1)]
    assert [(r.task_id, r.item_id, r.revision) for r in third.records] == [
        (f"task-{n}", f"item-{n}", n) for n in range(4, -1, -1)]
    assert third.next_before_id is None


def test_equal_times_have_stable_order_and_filtered_pages_do_not_skip():
    reader = InMemoryHistoryReader(tuple(record(n, at=AT, skill_id=SkillId(
        "factoring" if n % 2 else "expanding")) for n in range(8)))
    first = reader.read(SCOPE, HistoryQuery(skill_id=SkillId("factoring"), limit=2))
    second = reader.read(SCOPE, HistoryQuery(skill_id=SkillId("factoring"), limit=2,
                                           before_id=first.next_before_id))
    assert [r.id for r in first.records + second.records] == ["7", "5", "3", "1"]


def test_history_excludes_private_drafts_and_operators():
    # Private traces are deliberately not HistoryKind values or history records.
    reader = InMemoryHistoryReader((record(1), record(2, kind="rejected_draft"),
                                    record(3, kind="operator"), record(4, kind="tool_trace")))
    assert [r.id for r in reader.read(SCOPE, HistoryQuery()).records] == ["1"]
    with pytest.raises(HistoryLookupError):
        reader.read(SCOPE, HistoryQuery(before_id="2"))


@pytest.mark.parametrize("changes", [
    {"limit": 0}, {"limit": 21}, {"limit": -1}, {"limit": True}, {"limit": "10"},
    {"task_id": 1}, {"skill_id": []}, {"item_id": False}, {"kind": "submission"},
    {"before_id": 1}, {"after": AT.replace(tzinfo=None)}, {"before": "yesterday"},
    {"after": AT.astimezone(timezone(timedelta(hours=1)))},
    {"after": AT, "before": AT}, {"after": AT + timedelta(days=1), "before": AT},
])
def test_reader_rejects_invalid_filter_values(changes):
    with pytest.raises(HistoryQueryError):
        InMemoryHistoryReader(()).read(SCOPE, HistoryQuery(**changes))
