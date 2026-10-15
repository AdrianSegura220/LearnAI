# src/learnai/domain/calibration.py
from learnai.domain.enums import Confidence
from learnai.domain.parameters import DEFAULT_PARAMETERS, MasteryParameters


def update_calibration(
    gap: float,
    confidence: Confidence,
    correct: bool,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> float:
    """Exponential moving average of (stated probability - outcome).

    Positive means overconfident. This is the platform's core diagnostic: the
    failure it exists to fix is students not knowing what they do not know, and
    this number is that failure, measured.
    """
    observation = params.confidence_probability[confidence] - (1.0 if correct else 0.0)
    alpha = params.calibration_ema_alpha
    return (1.0 - alpha) * gap + alpha * observation


def is_overconfident(gap: float, params: MasteryParameters = DEFAULT_PARAMETERS) -> bool:
    return gap > params.overconfidence_threshold
