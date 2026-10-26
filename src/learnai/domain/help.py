# src/learnai/domain/help.py
from dataclasses import dataclass, replace

from learnai.domain.contracts import ModeContract
from learnai.domain.enums import HelpRung


@dataclass(frozen=True, slots=True)
class HelpState:
    """Per-task interaction history. Append-only: a rung once taken is never unrecorded."""

    rungs_used: tuple[HelpRung, ...] = ()
    attempts: int = 0
    """Answered attempts — the effort condition's counter. A decline never counts."""
    submissions: int = 0
    """Readable submissions recorded, declines included. Distinct from `attempts`:
    a decline spends a task's cold attempt but is not documented effort."""

    assistance_received: bool = False
    """Delivered task tutoring, independently of ladder progression."""

    @property
    def highest_rung(self) -> HelpRung:
        return max(self.rungs_used, default=HelpRung.NONE)

    @property
    def help_taken(self) -> bool:
        return self.assistance_received or bool(self.rungs_used)


def ladder_exhausted(contract: ModeContract, state: HelpState) -> bool:
    return state.highest_rung >= contract.base_max_rung


def reveal_unlocked(contract: ModeContract, state: HelpState) -> bool:
    condition = contract.unlock_full_reveal_after
    if condition is None:
        return False
    if state.attempts < condition.min_attempts:
        return False
    if condition.ladder_exhausted and not ladder_exhausted(contract, state):
        return False
    return True


def permitted_rung(contract: ModeContract, state: HelpState) -> HelpRung:
    """The highest rung the tutor may use right now."""
    if reveal_unlocked(contract, state):
        return HelpRung.FULL_REVEAL
    return contract.base_max_rung


def next_rung(contract: ModeContract, state: HelpState) -> HelpRung | None:
    """The single rung to offer next, or None when there is nothing left to give."""
    ceiling = permitted_rung(contract, state)
    candidate = HelpRung(min(state.highest_rung + 1, HelpRung.FULL_REVEAL))
    if state.highest_rung >= ceiling:
        return None
    return candidate if candidate <= ceiling else None


def record_help(state: HelpState, rung: HelpRung) -> HelpState:
    return replace(state, rungs_used=state.rungs_used + (rung,))


def record_attempt(state: HelpState) -> HelpState:
    """Count an *answered* attempt.

    Never called for a decline. If declining counted, the cheapest route to a
    full reveal would be: decline, decline, click through the ladder — zero
    effort, complete answer, which is precisely the hint abuse the effort
    condition exists to prevent.
    """
    return replace(state, attempts=state.attempts + 1)


def record_submission(state: HelpState) -> HelpState:
    """Count a readable submission — any recorded verdict, declines included.

    A decline gets the tutor's orientation, so it spends the task's cold
    attempt: a later correct answer on the same task is no longer unassisted.
    Malformed input is never recorded and never reaches this counter.
    """
    return replace(state, submissions=state.submissions + 1)
