# src/learnai/domain/ports.py
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from learnai.domain.ids import SkillId
from learnai.domain.items import AnswerSpec, FormConstraint, Item, StepDiff, Submission
from learnai.domain.verification import CheckResult

if TYPE_CHECKING:
    from learnai.domain.events import EvidenceEvent
    from learnai.domain.turn import TutorTurn, TurnContext, TurnFeedback, ValidationResult
    from learnai.domain.history import HistoryQuery, HistoryPage, HistoryScope


class Verifier(Protocol):
    """Deterministic judgement of student work. Implementations are subject-specific."""

    @property
    def supported_constraints(self) -> frozenset[FormConstraint]:
        """The form vocabulary this adapter can judge. Content is validated against it."""
        ...

    def check_answer(self, submission: Submission, spec: AnswerSpec) -> CheckResult:
        """Grade a submission. A blank one is NO_ANSWER; an answer key or form
        constraint the adapter cannot use raises, because a content error must
        never be reported to the student as their mistake."""
        ...

    def key_submission(self, spec: AnswerSpec) -> Submission:
        """The submission that enters this item's answer key.

        Only the adapter can build it, because the key's format is the
        adapter's. It is what a reveal shows and what a test submits as right.
        """
        ...

    def diff_steps(self, steps: Sequence[str]) -> StepDiff | None: ...

    def extract_candidate_expressions(self, text: str) -> tuple[str, ...]: ...

    def matches_answer(self, expression: str, spec: AnswerSpec) -> bool:
        """Would this text, entered as the answer, give it away?

        The leak guard's definition of a leak: text a student could copy into the
        answer field and be marked correct — or, for a list of values, one of them.
        """
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class ItemSource(Protocol):
    def next_item(self, skill_id: SkillId, target_difficulty: float, seed: int) -> Item: ...


class TutorExchange(Protocol):
    def respond(self, *, feedback: "TurnFeedback | None" = None) -> "TutorTurn | None": ...

    def expired(self) -> bool: ...

    def record_validation(self, result: "ValidationResult") -> None: ...

    @property
    def stop_reason(self) -> str | None: ...

    def finish(self, *, accepted: "TutorTurn | None", reason: str) -> None: ...


class Tutor(Protocol):
    def begin_turn(self, context: "TurnContext") -> TutorExchange: ...

    def respond(self, context: "TurnContext", *, feedback: "TurnFeedback | None" = None) -> "TutorTurn | None": ...


class HistoryReader(Protocol):
    """Read a snapshot using the student/session scope bound by the application."""

    def read(self, scope: "HistoryScope", query: "HistoryQuery") -> "HistoryPage": ...


class EvidenceLog(Protocol):
    def append(self, event: "EvidenceEvent") -> None: ...

    def events(self) -> tuple["EvidenceEvent", ...]: ...
