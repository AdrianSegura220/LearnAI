# src/learnai/adapters/tutor/fake_tutor.py
from collections.abc import Sequence

from learnai.domain.enums import HelpRung
from learnai.domain.turn import TurnContext, TutorTurn

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

    def respond(self, context: TurnContext) -> TutorTurn:
        self.contexts_seen.append(context)
        if self._index < len(self._script):
            turn = self._script[self._index]
            self._index += 1
            return turn
        message = _GENERIC_NUDGES[len(self.contexts_seen) % len(_GENERIC_NUDGES)]
        rung = context.permitted_rung if context.permitted_rung > HelpRung.NONE else HelpRung.NUDGE
        return TutorTurn(message=message, rung_used=rung, diagnosis=context.diagnosis)
