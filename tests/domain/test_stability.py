# tests/domain/test_stability.py
import math

from hypothesis import given
from hypothesis import strategies as st

from learnai.adapters.clock import FakeClock
from learnai.domain.ids import SkillId, StudentId
from learnai.domain.parameters import DEFAULT_PARAMETERS as P
from learnai.domain.mastery import (
    SkillState,
    due_at,
    is_fresh,
    is_learned,
    retrievability,
    update_stability,
)


def state(**kwargs) -> SkillState:
    base = {"student_id": StudentId("s1"), "skill_id": SkillId("quad.factor.monic")}
    return SkillState(**(base | kwargs))


def test_never_retrieved_has_zero_retrievability():
    clock = FakeClock()
    assert retrievability(state(), clock.now()) == 0.0


def test_retrievability_is_one_at_the_moment_of_success():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    assert retrievability(s, clock.now()) == 1.0


def test_retrievability_is_one_half_after_exactly_one_half_life():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    assert math.isclose(retrievability(s, clock.advance(10.0)), 0.5, abs_tol=1e-9)


def test_retrievability_is_one_quarter_after_two_half_lives():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    assert math.isclose(retrievability(s, clock.advance(20.0)), 0.25, abs_tol=1e-9)


def test_first_success_sets_the_initial_stability():
    clock = FakeClock()
    after = update_stability(state(), correct=True, now=clock.now())
    assert after.stability == P.initial_stability_days
    assert after.last_success_at == clock.now()


def test_a_late_success_grows_stability_more_than_a_prompt_one():
    clock = FakeClock()
    start = state(stability=10.0, last_success_at=clock.now())

    prompt_clock = FakeClock(clock.now())
    prompt = update_stability(start, correct=True, now=prompt_clock.advance(1.0))

    late_clock = FakeClock(clock.now())
    late = update_stability(start, correct=True, now=late_clock.advance(9.0))

    assert late.stability > prompt.stability


def test_failure_collapses_stability_by_the_failure_multiplier():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    after = update_stability(s, correct=False, now=clock.advance(5.0))
    assert math.isclose(after.stability, 10.0 * P.failure_multiplier_f, abs_tol=1e-9)
    assert after.last_success_at == s.last_success_at, "a failure is not a success"


def test_stability_never_falls_below_the_floor():
    clock = FakeClock()
    s = state(stability=P.min_stability_days, last_success_at=clock.now())
    assert update_stability(s, correct=False, now=clock.now()).stability == P.min_stability_days


def test_due_at_is_about_fifteen_percent_of_the_half_life():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    gap = (due_at(s) - clock.now()).total_seconds() / 86400.0
    assert math.isclose(gap, 10.0 * math.log2(1 / P.r_target), rel_tol=1e-6)
    assert 1.4 < gap < 1.6


def test_due_at_is_none_when_never_retrieved():
    assert due_at(state()) is None


def test_freshness_flips_exactly_at_the_target():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    assert is_fresh(s, clock.now())
    assert is_fresh(s, due_at(s))
    clock.set(due_at(s))
    assert not is_fresh(s, clock.advance(0.1))


def test_learned_requires_both_strength_and_repeated_cold_success():
    assert not is_learned(state(strength=3.0, unassisted_correct_count=1))
    assert not is_learned(state(strength=0.1, unassisted_correct_count=5))
    assert is_learned(state(strength=P.strength_threshold, unassisted_correct_count=2))


@given(days=st.floats(min_value=0.0, max_value=3650.0, allow_nan=False))
def test_retrievability_never_increases_with_time(days):
    clock = FakeClock()
    s = state(stability=30.0, last_success_at=clock.now())
    earlier = retrievability(s, clock.now())
    later = retrievability(s, clock.advance(days))
    assert later <= earlier + 1e-12
