# src/learnai/domain/contracts.py
from dataclasses import dataclass

from learnai.domain.enums import HelpRung, InterventionTiming, RevealPrice, VettingLevel


@dataclass(frozen=True, slots=True)
class EffortCondition:
    """What a student must have done before a reveal can be unlocked."""

    min_attempts: int
    ladder_exhausted: bool


@dataclass(frozen=True, slots=True)
class ModeContract:
    name: str
    base_max_rung: HelpRung
    unlock_full_reveal_after: EffortCondition | None
    reveal_price: RevealPrice
    evidence_weight: float
    min_vetting_level: VettingLevel
    intervention_timing: InterventionTiming
    timed: bool
    mixes_skills: bool

    def __post_init__(self) -> None:
        """A timed contract offers no help — see Task 9's evidence weights.

        `TIMED_EXAM` carries full weight because it claims unassisted
        performance under time pressure, so a ladder, a reveal unlock, or any
        unsolicited intervention in exam conditions would make the claim false.
        """
        if not self.timed:
            return
        if (
            self.base_max_rung > HelpRung.NONE
            or self.unlock_full_reveal_after is not None
            or self.intervention_timing is not InterventionTiming.NEVER
        ):
            raise ValueError(f"{self.name}: a timed contract must not offer help")


PRACTICE = ModeContract(
    name="practice",
    base_max_rung=HelpRung.NAME_METHOD,
    unlock_full_reveal_after=EffortCondition(min_attempts=2, ladder_exhausted=True),
    reveal_price=RevealPrice.FRESH_VARIANT_COLD,
    evidence_weight=1.0,
    min_vetting_level=VettingLevel.MACHINE_VERIFIED,
    intervention_timing=InterventionTiming.LET_RUN,
    timed=False,
    mixes_skills=True,
)
