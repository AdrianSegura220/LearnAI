# src/learnai/domain/leakguard.py
from dataclasses import dataclass

from learnai.domain.enums import HelpRung
from learnai.domain.items import AnswerSpec
from learnai.domain.ports import Verifier


@dataclass(frozen=True, slots=True)
class LeakVerdict:
    leaked: bool
    offending_expression: str | None = None


def detect_leak(
    verifier: Verifier,
    draft: str,
    answer_spec: AnswerSpec,
    permitted_rung: HelpRung,
) -> LeakVerdict:
    """Deterministic enforcement of the mode contract's answer-withholding policy.

    The verifier is passed in rather than held, because which one is correct
    depends on the skill being tutored.
    """
    if permitted_rung >= HelpRung.FULL_REVEAL:
        return LeakVerdict(leaked=False)
    for candidate in verifier.extract_candidate_expressions(draft):
        if verifier.matches_answer(candidate, answer_spec):
            return LeakVerdict(leaked=True, offending_expression=candidate)
    return LeakVerdict(leaked=False)
