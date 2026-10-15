# tests/domain/test_calibration.py
from learnai.domain.calibration import is_overconfident, update_calibration
from learnai.domain.enums import Confidence
from learnai.domain.parameters import DEFAULT_PARAMETERS

MAPPING = DEFAULT_PARAMETERS.confidence_probability


def test_every_confidence_level_maps_to_a_probability():
    assert set(MAPPING) == set(Confidence)
    values = [MAPPING[c] for c in sorted(Confidence)]
    assert values == sorted(values), "probabilities must rise with confidence"
    assert all(0.0 < v < 1.0 for v in values)


def test_the_priors_are_free_response_shaped_not_multiple_choice():
    """A guess at a free-response item is nothing like a guess among four options."""
    assert MAPPING[Confidence.NO_IDEA] < 0.05
    assert MAPPING[Confidence.GUESSING] < 0.20


def test_declining_and_being_wrong_is_near_perfect_calibration():
    gap = 0.0
    for _ in range(20):
        gap = update_calibration(gap, Confidence.NO_IDEA, correct=False)
    assert abs(gap) < 0.05
    assert not is_overconfident(gap)


def test_certain_and_wrong_pushes_the_gap_positive():
    assert update_calibration(0.0, Confidence.CERTAIN, correct=False) > 0.0


def test_guessing_and_right_pushes_the_gap_negative():
    assert update_calibration(0.0, Confidence.GUESSING, correct=True) < 0.0


def test_a_well_calibrated_student_converges_toward_zero():
    gap = 0.5
    for _ in range(60):
        gap = update_calibration(gap, Confidence.FAIRLY_SURE, correct=True)
        gap = update_calibration(gap, Confidence.FAIRLY_SURE, correct=True)
        gap = update_calibration(gap, Confidence.FAIRLY_SURE, correct=True)
        gap = update_calibration(gap, Confidence.FAIRLY_SURE, correct=False)
    assert abs(gap) < 0.1


def test_persistent_overconfidence_is_detected():
    gap = 0.0
    for _ in range(20):
        gap = update_calibration(gap, Confidence.CERTAIN, correct=False)
    assert is_overconfident(gap)


def test_a_calibrated_student_is_not_flagged():
    assert not is_overconfident(0.0)
