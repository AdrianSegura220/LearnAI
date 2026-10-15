# src/learnai/domain/misconceptions.py
from collections.abc import Sequence
from typing import Protocol

from learnai.domain.ids import MisconceptionId
from learnai.domain.items import StepDiff
from learnai.domain.skills import Misconception


class MisconceptionMatcher(Protocol):
    def exhibits(self, signature: str, previous: str, current: str) -> bool: ...


def diagnose(
    step_diff: StepDiff | None,
    candidates: Sequence[Misconception],
    matcher: MisconceptionMatcher,
) -> MisconceptionId | None:
    """Name the belief behind a broken step, if a catalogued one explains it.

    Candidates are tried in declaration order and the first match wins: the
    content author's ordering is the priority, not the matcher's.
    """
    if step_diff is None:
        return None
    for candidate in candidates:
        if matcher.exhibits(candidate.signature, step_diff.previous, step_diff.current):
            return candidate.id
    return None
