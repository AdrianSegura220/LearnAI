# tests/domain/test_leakguard.py
import pytest

from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.domain.enums import HelpRung
from learnai.domain.items import AnswerSpec
from learnai.domain.leakguard import detect_leak

VERIFIER = SympyVerifier()
SPEC = AnswerSpec("(x + 1)*(x + 2)")


def inspect(draft: str, rung: HelpRung = HelpRung.NUDGE):
    return detect_leak(VERIFIER, draft, SPEC, rung)


@pytest.mark.parametrize(
    "draft",
    [
        "The answer is (x+1)(x+2).",
        "You should end up with x^2 + 3x + 2 once expanded.",
        "Try (x + 1)(x + 2) and check by expanding.",
        "Well, (x+2)(x+1) works.",
    ],
)
def test_a_draft_containing_the_answer_is_caught(draft):
    verdict = inspect(draft)
    assert verdict.leaked
    assert verdict.offending_expression is not None


@pytest.mark.parametrize(
    "draft",
    [
        "What two numbers multiply to give the constant term?",
        "Think about the pair of factors of 2.",
        "You have the right method. Check the sign on your second factor.",
        "Remember that expanding (a + b)(c + d) gives four products.",
    ],
)
def test_a_genuine_hint_is_not_a_leak(draft):
    assert not inspect(draft).leaked


def test_nothing_leaks_when_a_full_reveal_is_permitted():
    verdict = inspect("The answer is (x+1)(x+2).", HelpRung.FULL_REVEAL)
    assert not verdict.leaked


def test_prose_with_no_mathematics_is_not_a_leak():
    assert not inspect("Take your time and read the question again.").leaked


def test_unparseable_fragments_do_not_crash_the_guard():
    assert not inspect("Try +++ or ***(((").leaked
