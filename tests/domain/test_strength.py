# tests/domain/test_strength.py
import math

from hypothesis import given
from hypothesis import strategies as st

from learnai.domain.enums import AnswerKind
from learnai.domain.ids import SkillId, StudentId
from learnai.domain.mastery import SkillState, k_factor, p_expected, update_strength
from learnai.domain.parameters import DEFAULT_PARAMETERS

FINITE = st.floats(min_value=-4.0, max_value=4.0, allow_nan=False, allow_infinity=False)


def state(strength: float = 0.0, attempts: int = 0) -> SkillState:
    return SkillState(
        student_id=StudentId("s1"),
        skill_id=SkillId("quad.factor.monic"),
        strength=strength,
        attempt_count=attempts,
    )


def test_equal_strength_and_difficulty_is_a_coin_flip():
    assert p_expected(0.5, 0.5) == 0.5


def test_one_logit_of_advantage_is_about_073():
    assert math.isclose(p_expected(1.0, 0.0), 0.7311, abs_tol=1e-4)


def test_p_expected_rises_with_strength():
    assert p_expected(-1.0, 0.0) < p_expected(0.0, 0.0) < p_expected(1.0, 0.0)


def test_success_on_a_hard_item_moves_more_than_on_an_easy_one():
    base = state(strength=0.5)
    hard = update_strength(base, item_difficulty=2.5, outcome=1.0, weight=1.0)
    easy = update_strength(base, item_difficulty=-1.5, outcome=1.0, weight=1.0)
    assert hard.strength - base.strength > easy.strength - base.strength


def test_failure_on_an_easy_item_costs_more_than_on_a_hard_one():
    base = state(strength=0.5)
    easy = update_strength(base, item_difficulty=-1.5, outcome=0.0, weight=1.0)
    hard = update_strength(base, item_difficulty=2.5, outcome=0.0, weight=1.0)
    assert base.strength - easy.strength > base.strength - hard.strength


def test_k_decays_with_observations():
    assert k_factor(0) == DEFAULT_PARAMETERS.k0
    assert k_factor(50) < k_factor(10) < k_factor(0)


def test_attempt_count_increments():
    assert update_strength(state(), 0.0, 1.0, 1.0).attempt_count == 1


def test_unassisted_correct_count_tracks_only_weighted_successes():
    assert update_strength(state(), 0.0, 1.0, 1.0).unassisted_correct_count == 1
    assert update_strength(state(), 0.0, 1.0, 0.0).unassisted_correct_count == 0
    assert update_strength(state(), 0.0, 0.0, 1.0).unassisted_correct_count == 0
    assert update_strength(state(), 0.0, 0.03, 1.0).unassisted_correct_count == 0


def test_declining_and_guessing_cost_the_same_in_expectation():
    """Scoring a decline at the guess baseline removes the incentive to guess."""
    base = state(strength=0.5)
    g = DEFAULT_PARAMETERS.guess_baseline[AnswerKind.SINGLE_VALUE]

    declined = update_strength(base, 0.0, g, 1.0).strength - base.strength
    guessed = g * (update_strength(base, 0.0, 1.0, 1.0).strength - base.strength) + (
        1 - g
    ) * (update_strength(base, 0.0, 0.0, 1.0).strength - base.strength)
    assert math.isclose(declined, guessed, abs_tol=1e-12)


def test_parameters_are_injected_not_baked_in():
    """Spec §7.8 fits these per skill; a module constant could never be overridden."""
    from dataclasses import replace as dc_replace

    from learnai.domain.parameters import MasteryParameters

    eager = dc_replace(MasteryParameters(), k0=2.0)
    base = state()
    assert (
        update_strength(base, 0.0, 1.0, 1.0, eager).strength
        > update_strength(base, 0.0, 1.0, 1.0).strength
    )


@given(strength=FINITE, difficulty=FINITE, correct=st.booleans())
def test_zero_weight_evidence_never_moves_strength(strength, difficulty, correct):
    """P2 and P4 in arithmetic: assistance cannot move mastery, at all."""
    before = state(strength=strength)
    after = update_strength(before, difficulty, float(correct), weight=0.0)
    assert after.strength == before.strength
    assert after.unassisted_correct_count == before.unassisted_correct_count


@given(strength=FINITE, difficulty=FINITE)
def test_a_correct_unassisted_attempt_never_lowers_strength(strength, difficulty):
    before = state(strength=strength)
    after = update_strength(before, difficulty, outcome=1.0, weight=1.0)
    assert after.strength >= before.strength


@given(strength=FINITE, difficulty=FINITE)
def test_a_wrong_unassisted_attempt_never_raises_strength(strength, difficulty):
    before = state(strength=strength)
    after = update_strength(before, difficulty, outcome=0.0, weight=1.0)
    assert after.strength <= before.strength
