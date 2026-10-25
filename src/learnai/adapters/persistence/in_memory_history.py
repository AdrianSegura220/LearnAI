"""Bounded reads over immutable, delivered-only session history snapshots."""
from datetime import datetime, timedelta

from learnai.domain.history import HistoryKind, HistoryPage, HistoryQuery, HistoryRecord, HistoryScope


class HistoryQueryError(ValueError):
    """The caller supplied unsupported history filter values."""


class HistoryLookupError(LookupError):
    """A cursor is absent from the permitted snapshot (including private records)."""


def _utc_bound(value: datetime | None) -> None:
    if value is not None and (
        not isinstance(value, datetime) or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise HistoryQueryError("time bounds must be aware UTC datetimes")


def _validate(query: HistoryQuery) -> None:
    if type(query.limit) is not int or not 1 <= query.limit <= 20:
        raise HistoryQueryError("limit must be an integer from 1 to 20")
    for value in (query.task_id, query.skill_id, query.item_id, query.before_id):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise HistoryQueryError("ids must be nonblank strings")
    if query.kind is not None and not isinstance(query.kind, HistoryKind):
        raise HistoryQueryError("kind must be a HistoryKind")
    _utc_bound(query.after)
    _utc_bound(query.before)
    if query.after is not None and query.before is not None and query.after >= query.before:
        raise HistoryQueryError("after must be earlier than before")


class InMemoryHistoryReader:
    """No engine or persistence writes are reachable through this reader."""

    def __init__(self, records: tuple[HistoryRecord, ...]) -> None:
        self._records = tuple(records)

    def read(self, scope: HistoryScope, query: HistoryQuery) -> HistoryPage:
        _validate(query)
        scoped = [record for record in self._records
                  if isinstance(record, HistoryRecord) and isinstance(record.kind, HistoryKind)
                  and record.student_id == scope.student_id and record.session_id == scope.session_id]
        # Last-appended first breaks timestamp ties deterministically across pages.
        ordered = [record for _, record in sorted(enumerate(scoped),
                   key=lambda pair: (pair[1].at, pair[0]), reverse=True)]
        if query.before_id is not None:
            cursor = next((index for index, record in enumerate(ordered)
                           if record.id == query.before_id), None)
            if cursor is None:
                raise HistoryLookupError("history cursor not found in permitted scope")
            ordered = ordered[cursor + 1:]
        filtered = [record for record in ordered
                    if (query.task_id is None or record.task_id == query.task_id)
                    and (query.skill_id is None or record.skill_id == query.skill_id)
                    and (query.item_id is None or record.item_id == query.item_id)
                    and (query.kind is None or record.kind == query.kind)
                    and (query.after is None or record.at > query.after)
                    and (query.before is None or record.at < query.before)]
        records = tuple(filtered[:query.limit])
        cursor = records[-1].id if len(filtered) > query.limit else None
        return HistoryPage(records, cursor)
