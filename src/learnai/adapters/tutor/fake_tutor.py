# src/learnai/adapters/tutor/fake_tutor.py
from collections.abc import Sequence

from learnai.domain.turn import TurnContext, TutorTurn, TurnFeedback, ValidationResult

_GENERIC_NUDGES = (
    "What is the very next thing you could try?",
    "Look again at the step before this one.",
    "What does the method say to do first here?",
)


class FakeTutor:
    """Deterministic, scripted Tutor. No API key, no cost, no flakiness.

    With no script it answers with a bland, never-leaking nudge at the highest
    rung the context permits, which is enough to drive the whole engine.
    """

    def __init__(self, script: Sequence[TutorTurn] | None = None) -> None:
        self._script = list(script or [])
        self._index = 0
        self.contexts_seen: list[TurnContext] = []
        self.feedback_seen: list[TurnFeedback | None] = []

    def begin_turn(self, context: TurnContext) -> "_FakeExchange":
        return _FakeExchange(self, context)

    def respond(self, context: TurnContext, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        self.contexts_seen.append(context)
        self.feedback_seen.append(feedback)
        if self._index < len(self._script):
            turn = self._script[self._index]
            self._index += 1
            return turn
        message = _GENERIC_NUDGES[len(self.contexts_seen) % len(_GENERIC_NUDGES)]
        rung = context.permitted_rung
        return TutorTurn(message=message, rung_used=rung, diagnosis=context.diagnosis)


class _FakeExchange:
    def __init__(self, tutor: FakeTutor, context: TurnContext) -> None:
        self._tutor = tutor
        self._context = context

    def respond(self, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        return self._tutor.respond(self._context, feedback=feedback)

    def expired(self) -> bool:
        return False

    def record_validation(self, result: ValidationResult) -> None:
        pass

    @property
    def stop_reason(self) -> str | None:
        return None

    def finish(self, *, accepted: TutorTurn | None, reason: str) -> None:
        pass
