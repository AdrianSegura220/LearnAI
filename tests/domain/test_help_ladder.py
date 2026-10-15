# tests/domain/test_help_ladder.py
from learnai.domain.contracts import PRACTICE
from learnai.domain.enums import HelpRung
from learnai.domain.help import (
    HelpState,
    ladder_exhausted,
    next_rung,
    permitted_rung,
    record_attempt,
    record_help,
    record_submission,
    reveal_unlocked,
)


def test_a_fresh_task_has_taken_no_help():
    state = HelpState()
    assert state.highest_rung is HelpRung.NONE
    assert state.help_taken is False


def test_the_ladder_starts_at_a_nudge():
    assert next_rung(PRACTICE, HelpState()) is HelpRung.NUDGE


def test_the_ladder_climbs_one_rung_at_a_time():
    state = HelpState()
    for expected in (HelpRung.NUDGE, HelpRung.NEXT_STEP, HelpRung.NAME_METHOD):
        assert next_rung(PRACTICE, state) is expected
        state = record_help(state, expected)


def test_the_ladder_stops_at_the_base_maximum_without_effort():
    state = HelpState()
    for rung in (HelpRung.NUDGE, HelpRung.NEXT_STEP, HelpRung.NAME_METHOD):
        state = record_help(state, rung)
    assert ladder_exhausted(PRACTICE, state)
    assert not reveal_unlocked(PRACTICE, state), "one attempt is not documented effort"
    assert next_rung(PRACTICE, state) is None
    assert permitted_rung(PRACTICE, state) is HelpRung.NAME_METHOD


def test_effort_plus_an_exhausted_ladder_unlocks_the_reveal():
    state = HelpState()
    for rung in (HelpRung.NUDGE, HelpRung.NEXT_STEP, HelpRung.NAME_METHOD):
        state = record_help(state, rung)
    state = record_attempt(record_attempt(state))
    assert reveal_unlocked(PRACTICE, state)
    assert permitted_rung(PRACTICE, state) is HelpRung.FULL_REVEAL
    assert next_rung(PRACTICE, state) is HelpRung.FULL_REVEAL


def test_declines_do_not_climb_toward_a_reveal():
    """record_attempt is never called for a decline, so the counter stays put."""
    state = HelpState()
    for rung in (HelpRung.NUDGE, HelpRung.NEXT_STEP, HelpRung.NAME_METHOD):
        state = record_help(state, rung)
    assert not reveal_unlocked(PRACTICE, state)


def test_attempts_alone_do_not_unlock_a_reveal():
    state = record_attempt(record_attempt(record_attempt(HelpState())))
    assert not reveal_unlocked(PRACTICE, state)
    assert permitted_rung(PRACTICE, state) is HelpRung.NAME_METHOD


def test_taking_help_is_recorded_and_never_forgotten():
    state = record_help(HelpState(), HelpRung.NUDGE)
    assert state.help_taken
    assert state.rungs_used == (HelpRung.NUDGE,)


def test_recording_a_submission_is_not_an_attempt():
    state = record_submission(HelpState())
    assert state.submissions == 1 and state.attempts == 0


def test_nothing_is_left_after_a_reveal():
    state = HelpState(rungs_used=(HelpRung.FULL_REVEAL,), attempts=3)
    assert next_rung(PRACTICE, state) is None
