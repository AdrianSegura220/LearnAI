# src/learnai/domain/verification.py
from dataclasses import dataclass

from learnai.domain.enums import Verdict
from learnai.domain.items import FormConstraint, StepDiff


@dataclass(frozen=True, slots=True)
class CheckResult:
    verdict: Verdict
    failed_constraints: tuple[FormConstraint, ...] = ()
    step_diff: StepDiff | None = None
