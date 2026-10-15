# tests/adapters/test_misconception_rules.py
import pathlib

import pytest

from learnai.adapters.cas.misconception_rules import (
    DEFERRED_SIGNATURES,
    IMPLEMENTED_SIGNATURES,
    SympyMisconceptionRules,
)
from learnai.adapters.content.loader import load_cluster

RULES = SympyMisconceptionRules()
CLUSTER = pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"


@pytest.mark.parametrize(
    "signature,previous,current",
    [
        ("square_distributes_over_sum", "(x+3)^2", "x^2 + 9"),
        ("product_of_sums_drops_cross", "(x+2)(x+5)", "x^2 + 10"),
        ("incomplete_common_factor", "12x^2 + 18x", "2*(6x^2 + 9x)"),
        ("factor_sign_flip", "x^2 + 3x + 2", "(x-1)(x-2)"),
        ("sum_of_squares_factored", "x^2 + 9", "(x+3)(x+3)"),
        ("zero_product_without_zero", "(x-1)(x-2) = 6", "x = 7, x = 8"),
    ],
)
def test_each_implemented_rule_fires_on_its_own_error(signature, previous, current):
    assert RULES.exhibits(signature, previous, current)


@pytest.mark.parametrize("signature", sorted(IMPLEMENTED_SIGNATURES))
def test_no_rule_fires_on_correct_work(signature):
    assert not RULES.exhibits(signature, "(x+3)^2", "x^2 + 6x + 9")


def test_deferred_signatures_return_false_rather_than_raising():
    for signature in DEFERRED_SIGNATURES:
        assert RULES.exhibits(signature, "(x+3)^2", "x^2 + 9") is False


def test_unknown_signature_returns_false():
    assert RULES.exhibits("not_a_real_signature", "x", "y") is False


def test_unparseable_input_returns_false_rather_than_raising():
    assert RULES.exhibits("square_distributes_over_sum", "x +* 2", "y") is False


def test_dropped_cross_terms_fire_on_either_written_order():
    """"(2+x)" and "(x+2)" parse to the same product, so the belief must fire
    whichever diagonal the student's term order selects."""
    assert RULES.exhibits("product_of_sums_drops_cross", "(2+x)(x+5)", "x^2 + 10")
    assert RULES.exhibits("product_of_sums_drops_cross", "(x+2)(x+5)", "7x")


def test_correct_work_where_cross_terms_cancel_is_not_the_belief():
    """(x+2)(x-2) = x^2 - 4 is the full expansion and also one diagonal."""
    assert not RULES.exhibits("product_of_sums_drops_cross", "(x+2)(x-2)", "x^2 - 4")


def test_the_same_error_in_or_notation_is_the_same_belief():
    assert RULES.exhibits("zero_product_without_zero", "(x-1)(x-2) = 6", "x = 7 or x = 8")


CANONICAL_ERRORS = {
    "square_distributes_over_sum": ("(x+3)^2", "x^2 + 9"),
    "product_of_sums_drops_cross": ("(x+2)(x+5)", "x^2 + 10"),
    "incomplete_common_factor": ("12x^2 + 18x", "2*(6x^2 + 9x)"),
    "factor_sign_flip": ("x^2 + 3x + 2", "(x-1)(x-2)"),
    "sum_of_squares_factored": ("x^2 + 9", "(x+3)(x+3)"),
    "zero_product_without_zero": ("(x-1)(x-2) = 6", "x = 7, x = 8"),
}


@pytest.mark.parametrize("signature", sorted(CANONICAL_ERRORS))
def test_a_canonical_error_fires_exactly_one_rule(signature):
    """The guard behind first-match-wins: the rules stay disjoint, so the
    content's declaration order is priority between specific beliefs, not a
    tie-break between overlapping ones."""
    previous, current = CANONICAL_ERRORS[signature]
    fired = [s for s in sorted(IMPLEMENTED_SIGNATURES) if RULES.exhibits(s, previous, current)]
    assert fired == [signature]


def test_every_content_signature_is_classified():
    cluster = load_cluster(CLUSTER)
    declared = {m.signature for m in cluster.misconceptions.values()}
    classified = IMPLEMENTED_SIGNATURES | DEFERRED_SIGNATURES
    assert declared <= classified, f"unclassified signatures: {declared - classified}"
    assert not (IMPLEMENTED_SIGNATURES & DEFERRED_SIGNATURES)
