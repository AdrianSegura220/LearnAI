# src/learnai/adapters/persistence/in_memory.py
from learnai.domain.events import EvidenceEvent


class InMemoryEvidenceLog:
    """Append-only event log. Plan 2 replaces this with Postgres, same protocol."""

    def __init__(self) -> None:
        self._events: list[EvidenceEvent] = []

    def append(self, event: EvidenceEvent) -> None:
        self._events.append(event)

    def events(self) -> tuple[EvidenceEvent, ...]:
        return tuple(self._events)
