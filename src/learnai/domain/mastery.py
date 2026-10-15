# src/learnai/domain/mastery.py
import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

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


def elapsed_days(earlier: datetime, later: datetime) -> float:
    """Wall-clock days as a float. Never quantise to calendar days."""
    return (later - earlier).total_seconds() / 86400.0


def retrievability(state: SkillState, now: datetime) -> float:
    """Probability the student could do this right now: 2 ** (-elapsed / half-life)."""
    if state.last_success_at is None or state.stability <= 0.0:
        return 0.0
    return 2.0 ** (-elapsed_days(state.last_success_at, now) / state.stability)


def update_stability(
    state: SkillState,
    correct: bool,
    now: datetime,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> SkillState:
    """Grow the half-life on a successful retrieval; collapse it on a lapse.

    Growth scales with 1 - retrievability, so a retrieval made when the memory
    had decayed further is worth more. That is the spacing effect, and it is why
    an immediate re-test earns almost nothing.
    """
    if not correct:
        collapsed = max(params.min_stability_days, state.stability * params.failure_multiplier_f)
        return replace(state, stability=collapsed, last_reviewed_at=now)

    if state.last_success_at is None or state.stability <= 0.0:
        return replace(
            state,
            stability=params.initial_stability_days,
            last_success_at=now,
            last_reviewed_at=now,
        )

    r = retrievability(state, now)
    grown = state.stability * (1.0 + params.stability_growth_a * (1.0 - r))
    return replace(state, stability=grown, last_success_at=now, last_reviewed_at=now)


def due_at(
    state: SkillState, params: MasteryParameters = DEFAULT_PARAMETERS
) -> datetime | None:
    """When retrievability will fall to r_target — roughly 0.152 half-lives.

    The microsecond nudge keeps the instant itself 'fresh': datetime arithmetic
    quantises to microseconds, and without it `is_fresh(state, due_at(state))`
    can land just below the target when the quantisation rounds the other way.
    """
    if state.last_success_at is None or state.stability <= 0.0:
        return None
    gap = state.stability * math.log2(1.0 / params.r_target)
    return state.last_success_at + timedelta(days=gap) - timedelta.resolution


def is_fresh(
    state: SkillState, now: datetime, params: MasteryParameters = DEFAULT_PARAMETERS
) -> bool:
    return retrievability(state, now) >= params.r_target


def is_learned(state: SkillState, params: MasteryParameters = DEFAULT_PARAMETERS) -> bool:
    """An achievement, not a freshness reading: once earned it never un-earns.

    A later failure may drop strength below the bar; the projection set
    `ever_learned` the moment it was first crossed, and this predicate honours
    it (spec §7.3)."""
    return state.ever_learned or (
        state.strength >= params.strength_threshold
        and state.unassisted_correct_count >= params.min_unassisted_correct
    )
