# src/learnai/adapters/clock.py
from datetime import UTC, datetime, timedelta


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Lets a term of study run in milliseconds. Essential for decay testing."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, days: float) -> datetime:
        self._now = self._now + timedelta(days=days)
        return self._now

    def set(self, moment: datetime) -> None:
        self._now = moment
