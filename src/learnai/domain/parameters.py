# src/learnai/domain/parameters.py
"""Tuned parameters of the mastery model. See spec §7.8 for how each is calibrated."""
from collections.abc import Mapping
from dataclasses import dataclass, field

from learnai.domain.enums import AnswerKind, Confidence


@dataclass(frozen=True, slots=True)
class MasteryParameters:
    # --- Strength (Elo, logit scale; spec §7.1) ------------------------------
    strength_scale: float = 1.0
    """1.0 means strength and difficulty are in logits: a gap of 1 is p≈0.73."""
    k0: float = 0.4
    k_decay: float = 0.05
    """K = k0 / (1 + k_decay * attempts): fast early, stable once well determined."""
    strength_threshold: float = 1.5
    """Logits above an item's difficulty required for mastery: p≈0.82 on a core item."""
    min_unassisted_correct: int = 2

    # --- Memory (half-life days; spec §7.2) ----------------------------------
    r_target: float = 0.9
    """Per-skill policy value: raise inside an exam horizon, lower for maintenance."""
    stability_growth_a: float = 5.0
    """Derived, not guessed: A = (m-1)/(1-r_target) with m=1.5 reaches ~30-day
    intervals after fourteen on-time successes."""
    failure_multiplier_f: float = 0.3
    """F = m**-3: a lapse forfeits about three reviews' progress."""
    initial_stability_days: float = 1.0
    min_stability_days: float = 0.2

    # --- Prerequisite propagation (spec §7.4) --------------------------------
    prereq_propagation_weight: float = 0.3

    # --- Calibration (spec §7.5) ---------------------------------------------
    calibration_ema_alpha: float = 0.2
    overconfidence_threshold: float = 0.15
    guess_baseline: Mapping[AnswerKind, float] = field(
        default_factory=lambda: {
            AnswerKind.SINGLE_VALUE: 0.03,
            AnswerKind.RELATION: 0.03,
            AnswerKind.VALUE_SET: 0.02,
        }
    )
    """P(correct | pure guess), per answer format.

    A decline is scored at this value rather than at zero, which makes declining
    and guessing cost exactly the same in expectation — at any guess rate. That
    matters little on free response (the edge is ~0.012 logits) and a great deal
    once four-option multiple choice exists, where guessing would otherwise pay
    about 0.1 logits an item. Fitted from data like every value here.
    """
    confidence_probability: Mapping[Confidence, float] = field(
        default_factory=lambda: {
            Confidence.NO_IDEA: 0.02,
            Confidence.GUESSING: 0.15,
            Confidence.UNSURE: 0.40,
            Confidence.FAIRLY_SURE: 0.75,
            Confidence.CERTAIN: 0.93,
        }
    )
    """P(correct | stated confidence). Free-response priors, not MCQ ones: a guess
    at "factor x^2 + 3x + 2" is nothing like a guess among four options, and the
    MCQ value of 0.25 would libel every honest low-confidence student.

    Fit from data, but **at population level only** — fitting each student against
    their own history makes everyone calibrated by construction and the metric
    measures nothing. Key it by answer kind once multiple-choice items exist.
    Treat the dict as immutable.
    """

    # --- Planning (spec §7.6) ------------------------------------------------
    target_logit_margin: float = 1.1
    """Serve items the student should clear about 75% of the time."""


DEFAULT_PARAMETERS = MasteryParameters()
