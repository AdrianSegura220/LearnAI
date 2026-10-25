"""Budgets reserve a final call and count output including thinking/retries."""
from dataclasses import replace

from learnai.adapters.tutor.anthropic.routing import BudgetProfile
from learnai.adapters.tutor.runtime import ResponseBudget
from tests.support.scripted_client import FakeMonotonic

PROFILE = BudgetProfile(3, 8, 4, 8, 4096, 16000, 512)


def test_reserve_stops_exploration_before_emergency_ceiling():
    clock = FakeMonotonic()
    budget = ResponseBudget(PROFILE, monotonic=clock)
    assert budget.can_explore()
    budget.record_model_call(2000)
    budget.record_model_call(1584)
    assert not budget.can_explore()
    assert not budget.expired()
    assert budget.remaining_output_tokens == 512


def test_round_trip_and_individual_tool_limits_are_independent():
    budget = ResponseBudget(PROFILE, monotonic=FakeMonotonic())
    budget.record_model_call(10)
    budget.record_tool_calls(8)
    assert budget.model_calls == 1 and budget.tool_calls == 8
    assert not budget.can_explore()
    budget = ResponseBudget(PROFILE, monotonic=FakeMonotonic())
    for _ in range(3):
        budget.record_model_call(10)
    assert not budget.can_explore()
    assert budget.tool_calls == 0


def test_monotonic_deadline_is_created_once():
    clock = FakeMonotonic()
    budget = ResponseBudget(PROFILE, monotonic=clock)
    clock.advance(3)
    assert not budget.can_explore() and not budget.expired()
    assert budget.remaining_seconds() == 5
    clock.advance(6)
    assert budget.expired() and budget.remaining_seconds() == 0
