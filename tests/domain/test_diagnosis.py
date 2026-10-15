# tests/domain/test_diagnosis.py
from learnai.domain.ids import MisconceptionId
from learnai.domain.items import StepDiff
from learnai.domain.misconceptions import diagnose
from learnai.domain.skills import Misconception


class StubMatcher:
    def __init__(self, matching: set[str]) -> None:
        self.matching = matching
        self.calls: list[str] = []

    def exhibits(self, signature: str, previous: str, current: str) -> bool:
        self.calls.append(signature)
        return signature in self.matching


def mc(mid: str, signature: str) -> Misconception:
    return Misconception(
        id=MisconceptionId(mid),
        subject_id="math",
        name=mid,
        description="",
        signature=signature,
    )


DIFF = StepDiff(index=1, previous="(x+3)^2", current="x^2 + 9")


def test_returns_the_matching_misconception():
    matcher = StubMatcher({"sig_b"})
    found = diagnose(DIFF, [mc("m_a", "sig_a"), mc("m_b", "sig_b")], matcher)
    assert found == MisconceptionId("m_b")


def test_returns_none_when_nothing_matches():
    assert diagnose(DIFF, [mc("m_a", "sig_a")], StubMatcher(set())) is None


def test_returns_none_for_no_diff():
    assert diagnose(None, [mc("m_a", "sig_a")], StubMatcher({"sig_a"})) is None


def test_first_declared_match_wins_and_stops_evaluating():
    matcher = StubMatcher({"sig_a", "sig_b"})
    found = diagnose(DIFF, [mc("m_a", "sig_a"), mc("m_b", "sig_b")], matcher)
    assert found == MisconceptionId("m_a")
    assert matcher.calls == ["sig_a"]
