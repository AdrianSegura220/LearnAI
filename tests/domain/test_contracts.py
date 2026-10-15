# tests/domain/test_contracts.py
from dataclasses import replace

import pytest

from learnai.domain.contracts import PRACTICE, EffortCondition, ModeContract
from learnai.domain.enums import HelpRung, InterventionTiming, RevealPrice, VettingLevel


def test_practice_never_starts_above_naming_the_method():
    assert PRACTICE.base_max_rung is HelpRung.NAME_METHOD


def test_practice_unlocks_a_reveal_only_after_documented_effort():
    assert PRACTICE.unlock_full_reveal_after == EffortCondition(
        min_attempts=2, ladder_exhausted=True
    )


def test_practice_charges_the_fresh_variant_price():
    assert PRACTICE.reveal_price is RevealPrice.FRESH_VARIANT_COLD


def test_practice_only_serves_cas_verified_items():
    assert PRACTICE.min_vetting_level is VettingLevel.MACHINE_VERIFIED


def test_practice_lets_an_error_run_before_intervening():
    assert PRACTICE.intervention_timing is InterventionTiming.LET_RUN


def test_practice_is_untimed_and_mixes_skills():
    assert PRACTICE.timed is False and PRACTICE.mixes_skills is True


def test_a_timed_contract_must_not_offer_help():
    """TIMED_EXAM's full weight claims unassisted performance under time
    pressure; a ladder in an exam would make that claim false. The combination
    is rejected at construction, and Task 9's classifier demotes any helped
    timed attempt as an accounting backstop."""
    with pytest.raises(ValueError):
        ModeContract(
            name="assessment",
            base_max_rung=HelpRung.NUDGE,
            unlock_full_reveal_after=None,
            reveal_price=RevealPrice.NONE,
            evidence_weight=1.0,
            min_vetting_level=VettingLevel.MACHINE_VERIFIED,
            intervention_timing=InterventionTiming.NEVER,
            timed=True,
            mixes_skills=False,
        )
    assessment = ModeContract(
        name="assessment",
        base_max_rung=HelpRung.NONE,
        unlock_full_reveal_after=None,
        reveal_price=RevealPrice.NONE,
        evidence_weight=1.0,
        min_vetting_level=VettingLevel.MACHINE_VERIFIED,
        intervention_timing=InterventionTiming.NEVER,
        timed=True,
        mixes_skills=False,
    )
    assert assessment.base_max_rung is HelpRung.NONE
    with pytest.raises(ValueError):
        replace(assessment, intervention_timing=InterventionTiming.IMMEDIATE)


def test_a_contract_is_immutable():
    try:
        PRACTICE.timed = True  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ModeContract must be frozen")
