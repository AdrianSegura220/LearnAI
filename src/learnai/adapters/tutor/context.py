"""Select immutable tutor context by token allowance and exercise boundaries."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from learnai.adapters.tutor.rendering import render_history, render_interaction, render_moment
from learnai.domain.history import HistoryKind, HistoryRecord
from learnai.domain.ids import TaskId
from learnai.domain.turn import TranscriptEntry, TurnContext


class ContextLimitError(ValueError):
    """The protected active exercise cannot fit without losing student work."""

    def __init__(self, message: str, *, context_view=None) -> None:
        super().__init__(message)
        self.context_view = context_view


@dataclass(frozen=True, slots=True)
class ContextView:
    active: tuple[TranscriptEntry, ...]
    earlier: tuple[TranscriptEntry, ...]
    summary: str
    source_ids: tuple[str, ...]
    input_tokens: int


def _entry_data(entry: TranscriptEntry, records: dict[str, HistoryRecord]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "speaker": entry.speaker, "text": entry.text,
        "record_id": entry.record_id, "task_id": entry.task_id,
        "revision": entry.revision, "at": entry.at.isoformat() if entry.at else None,
    }
    record = records.get(entry.record_id) if entry.record_id is not None else None
    if record is not None:
        metadata = json.loads(render_history((record,)))[0]
        # The text carries the interaction/message once; metadata keeps its scope.
        del metadata["interaction"]
        del metadata["message"]
        data["record"] = metadata
    return data


def render_context(context: TurnContext, view: ContextView) -> str:
    """Render precisely the selected volatile layer; the full history stays retrievable."""
    records = {record.id: record for record in context.history}
    return json.dumps({
        "moment": json.loads(render_moment(context)),
        "active": [_entry_data(entry, records) for entry in view.active],
        "earlier": [_entry_data(entry, records) for entry in view.earlier],
        "earlier_outcome_summary": view.summary,
    }, ensure_ascii=False, separators=(",", ":"))


def _history_entry(record: HistoryRecord) -> TranscriptEntry:
    speaker = "tutor" if record.kind in {
        HistoryKind.TUTOR_DELIVERED, HistoryKind.HELP_DELIVERED,
    } else "student"
    text = record.message
    if text is None:
        text = render_interaction(record.interaction, None) if record.interaction else ""
    return TranscriptEntry(speaker, text, record.id, record.task_id, record.revision, record.at)


def _summary(records: tuple[HistoryRecord, ...]) -> str:
    # No student prose becomes a diagnosis. Preserve all chronological engine
    # outcomes, including corrections, rather than projecting a permanent error.
    return json.dumps([{
        "source_id": record.id, "task_id": record.task_id,
        "item_id": record.item_id, "skill_id": record.skill_id,
        "at": record.at.isoformat(), "revision": record.revision,
        "kind": record.kind.name,
        "verdict": record.verdict.name if record.verdict else None,
        "evidence_class": record.evidence_class.name if record.evidence_class else None,
        "rung": record.rung.name if record.rung is not None else None,
        "related_record_ids": list(record.related_record_ids),
    } for record in sorted(records, key=lambda record: record.at)],
        ensure_ascii=False, separators=(",", ":"))


def select_context(
    context: TurnContext, *, input_budget: int, count_tokens: Callable[[str], int],
) -> ContextView:
    """Protect active exchanges, then select whole earlier tasks by relevance/recency.

    Both raw earlier tasks and deterministic summaries are optional and compete
    for the remainder. Unselected history remains available through retrieval.
    The injected counter can also include fixed prompt framing/provider overhead.
    """
    if input_budget < 0:
        raise ContextLimitError("protected exercise exceeds input allowance")
    active_id = context.interaction.task_id if context.interaction else None
    current_id = context.current_interaction_id
    entries = [_history_entry(record) for record in context.history if record.id != current_id]
    seen = {entry.record_id for entry in entries if entry.record_id is not None}
    for entry in context.transcript:
        if current_id is not None and entry.record_id == current_id:
            continue
        if entry.record_id is not None and entry.record_id in seen:
            continue
        entries.append(entry)
        if entry.record_id is not None:
            seen.add(entry.record_id)
    minimum_time = datetime.min.replace(tzinfo=timezone.utc)
    entries.sort(key=lambda entry: entry.at or minimum_time)
    # Unscoped legacy transcript cannot safely be discarded as an older task.
    active = tuple(entry for entry in entries if entry.task_id is None or entry.task_id == active_id)
    groups: dict[TaskId, list[TranscriptEntry]] = {}
    for entry in entries:
        if entry.task_id is not None and entry.task_id != active_id:
            groups.setdefault(entry.task_id, []).append(entry)
    record_groups: dict[TaskId, tuple[HistoryRecord, ...]] = {
        task_id: tuple(record for record in context.history
                       if record.task_id == task_id and record.id != current_id)
        for task_id in groups
    }

    def rank(task_id: TaskId) -> tuple[bool, datetime]:
        records = record_groups[task_id]
        relevant = any(record.skill_id == context.skill_pack.skill_id for record in records)
        recency = max((entry.at or minimum_time for entry in groups[task_id]), default=minimum_time)
        return relevant, recency

    def make_view(earlier: tuple[TranscriptEntry, ...], summarized: tuple[HistoryRecord, ...]) -> ContextView:
        ids = tuple(dict.fromkeys(
            ([current_id] if current_id is not None else [])
            + [entry.record_id for entry in active + earlier if entry.record_id is not None]
            + [record.id for record in summarized]
        ))
        view = ContextView(active, earlier, _summary(summarized) if summarized else "", ids, 0)
        return ContextView(active, earlier, view.summary, ids, count_tokens(render_context(context, view)))

    view = make_view((), ())
    if view.input_tokens > input_budget:
        raise ContextLimitError(
            f"protected exercise requires {view.input_tokens} tokens; allowance is {input_budget}",
            context_view=view
        )
    selected: set[TaskId] = set()
    summarized: tuple[HistoryRecord, ...] = ()
    for task_id in sorted(groups, key=rank, reverse=True):
        raw = tuple(entry for entry in entries if entry.task_id in selected | {task_id})
        candidate = make_view(raw, summarized)
        if candidate.input_tokens <= input_budget:
            selected.add(task_id)
            view = candidate
            continue
        records = record_groups[task_id]
        if records:
            candidate = make_view(view.earlier, summarized + records)
            if candidate.input_tokens <= input_budget:
                summarized += records
                view = candidate
    return view
