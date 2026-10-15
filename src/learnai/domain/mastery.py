# src/learnai/domain/mastery.py
import math
from dataclasses import dataclass, replace
from datetime import datetime

from learnai.domain.ids import MisconceptionId, SkillId, StudentId
from learnai.domain.parameters import DEFAULT_PARAMETERS, MasteryParameters


@dataclass(frozen=True, slots=True)
class SkillState:
    student_id: StudentId
    skill_id: SkillId
    strength: float = 0.0
    stability: float = 0.0
    """Memory half-life in days. Zero means never successfully retrieved."""
    last_success_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    attempt_count: int = 0
    unassisted_correct_count: int = 0
    calibration_gap: float = 0.0
    active_misconceptions: tuple[MisconceptionId, ...] = ()
    ever_learned: bool = False
    """Set the moment the learned bar is first crossed; is_learned honours it
    forever, so a later lapse never revokes an earned badge (spec §7.3)."""


def p_expected(
    strength: float, difficulty: float, params: MasteryParameters = DEFAULT_PARAMETERS
) -> float:
    return 1.0 / (1.0 + math.exp(-(strength - difficulty) / params.strength_scale))


def k_factor(attempt_count: int, params: MasteryParameters = DEFAULT_PARAMETERS) -> float:
    return params.k0 / (1.0 + params.k_decay * attempt_count)


def update_strength(
    state: SkillState,
    item_difficulty: float,
    outcome: float,
    weight: float,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> SkillState:
    """Elo update, scaled by how much this observation is permitted to count.

    `outcome` is 1.0 for a correct answer and 0.0 for a wrong one. A decline is
    scored at the format's guess baseline instead, so declining and guessing
    cost the same in expectation and the system never teaches a stuck student
    to guess rather than say so.

    `weight` is the product of the mode contract's weight and the evidence
    class weight. A weight of zero leaves strength untouched — that is the
    whole of P2, expressed arithmetically.
    """
    surprise = outcome - p_expected(state.strength, item_difficulty, params)
    delta = k_factor(state.attempt_count, params) * weight * surprise
    return replace(
        state,
        strength=state.strength + delta,
        attempt_count=state.attempt_count + 1,
        # Only an actual correct answer counts toward the mastery gate: a decline
        # scored near the guess baseline must never mint evidence of competence.
        unassisted_correct_count=state.unassisted_correct_count
        + (1 if outcome >= 1.0 and weight > 0.0 else 0),
    )
