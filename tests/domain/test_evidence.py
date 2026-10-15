# tests/domain/test_evidence.py
from learnai.domain.enums import EvidenceClass
from learnai.domain.evidence import EVIDENCE_WEIGHT, classify_evidence


def test_a_clean_first_attempt_is_cold():
    assert (
        classify_evidence(attempt_index=0, help_taken=False, taught_this_session=False, timed=False)
        is EvidenceClass.UNASSISTED_COLD
    )


def test_any_help_makes_it_assisted():
    assert (
        classify_evidence(attempt_index=0, help_taken=True, taught_this_session=False, timed=False)
        is EvidenceClass.ASSISTED
    )


def test_a_retry_is_not_cold_because_the_verdict_was_information():
    assert (
        classify_evidence(attempt_index=1, help_taken=False, taught_this_session=False, timed=False)
        is EvidenceClass.ASSISTED
    )


def test_same_session_teaching_makes_it_post_instruction():
    assert (
        classify_evidence(attempt_index=0, help_taken=False, taught_this_session=True, timed=False)
        is EvidenceClass.POST_INSTRUCTION
    )


def test_a_clean_timed_attempt_beats_taught_this_session():
    """Timed beats context — but only when the attempt is uncontaminated."""
    assert (
        classify_evidence(attempt_index=0, help_taken=False, taught_this_session=True, timed=True)
        is EvidenceClass.TIMED_EXAM
    )


def test_help_beats_timing_because_contamination_beats_context():
    assert (
        classify_evidence(attempt_index=0, help_taken=True, taught_this_session=False, timed=True)
        is EvidenceClass.ASSISTED
    )


def test_a_timed_retry_is_not_clean_exam_evidence():
    assert (
        classify_evidence(attempt_index=1, help_taken=False, taught_this_session=False, timed=True)
        is EvidenceClass.ASSISTED
    )


def test_help_beats_post_instruction_because_it_is_stricter():
    assert (
        classify_evidence(attempt_index=0, help_taken=True, taught_this_session=True, timed=False)
        is EvidenceClass.ASSISTED
    )


def test_only_cold_and_timed_evidence_carries_full_weight():
    assert EVIDENCE_WEIGHT[EvidenceClass.UNASSISTED_COLD] == 1.0
    assert EVIDENCE_WEIGHT[EvidenceClass.TIMED_EXAM] == 1.0
    assert EVIDENCE_WEIGHT[EvidenceClass.ASSISTED] == 0.0
    assert 0.0 < EVIDENCE_WEIGHT[EvidenceClass.POST_INSTRUCTION] < 0.25


def test_every_evidence_class_has_a_weight():
    assert set(EVIDENCE_WEIGHT) == set(EvidenceClass)
