"""The evaluator's provider-independent scoring port."""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from learnai.eval.judge import JudgePacket, JudgeScores


class Judge(Protocol):
    def evaluate(self, packet: JudgePacket) -> JudgeScores: ...
