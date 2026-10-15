# src/learnai/domain/evidence.py
from learnai.domain.enums import EvidenceClass

EVIDENCE_WEIGHT: dict[EvidenceClass, float] = {
    EvidenceClass.UNASSISTED_COLD: 1.0,
    EvidenceClass.TIMED_EXAM: 1.0,
    EvidenceClass.POST_INSTRUCTION: 0.1,
    EvidenceClass.ASSISTED: 0.0,
}


def classify_evidence(
    *, attempt_index: int, help_taken: bool, taught_this_session: bool, timed: bool
) -> EvidenceClass:
    """Decide what an attempt is worth.

    Contamination beats context: help or a retry demotes to ASSISTED even in a
    timed task. `TIMED_EXAM` is awarded only to a clean first attempt, because
    its full weight claims unassisted performance under time pressure, and a
    hint taken during an exam — or a retry after a verdict — is neither.

    `attempt_index` is zero-based: only the very first submission on a task can
    be cold, because every later one follows a verdict the student learned from.
    """
    if help_taken or attempt_index > 0:
        return EvidenceClass.ASSISTED
    if timed:
        return EvidenceClass.TIMED_EXAM
    if taught_this_session:
        return EvidenceClass.POST_INSTRUCTION
    return EvidenceClass.UNASSISTED_COLD
