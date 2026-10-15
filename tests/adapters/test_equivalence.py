import pytest

from learnai.adapters.cas.equivalence import (
    equations_equivalent,
    expressions_equivalent,
    solution_sets_equivalent,
)
from learnai.adapters.cas.parse import parse_math


def expr(text: str):
    return parse_math(text)


def eq(text: str):
    return parse_math(text, allow_equation=True, as_written=True)


@pytest.mark.parametrize(
    "a,b",
    [
        ("1/2", "0.5"),
        ("2/4", "1/2"),
        ("(x+1)(x+2)", "x^2 + 3x + 2"),
        ("2sin(x)cos(x)", "sin(2x)"),
        ("sqrt(8)", "2sqrt(2)"),
        ("x + x", "2x"),
        ("(x^2 - 1)/(x - 1)", "x + 1"),  # an isolated hole is not a difference
        ("0.1 + 0.2", "0.3"),  # decimals are exact, not binary approximations
        ("0.3", "3/10"),
    ],
)
def test_equivalent_expressions_are_accepted(a, b):
    assert expressions_equivalent(expr(a), expr(b))


@pytest.mark.parametrize(
    "a,b",
    [
        ("x + 1", "x + 2"),
        ("(x+1)(x+2)", "x^2 + 3x + 3"),
        ("x^2", "x^3"),
        ("log(x^2)", "2log(x)"),  # differ for every negative x
        ("sqrt(x^2)", "x"),
    ],
)
def test_inequivalent_expressions_are_rejected(a, b):
    assert not expressions_equivalent(expr(a), expr(b))


@pytest.mark.parametrize(
    "a,b",
    [
        ("2x = 10", "x = 5"),
        ("x + 3 = 7", "2x + 6 = 14"),
        ("(x-1)^2 = 0", "x - 1 = 0"),  # a repeated root is still one solution
        ("(x^2 - 1)/(x - 1) = 0", "x + 1 = 0"),  # the hole at 1 is not a solution anyway
        ("x^2 + 9 = 0", "x^2 = -9"),  # no real solutions: falls back to proportionality
        ("y = 2x + 1", "2y = 4x + 2"),  # two variables: falls back to proportionality
        ("0.5x = 1", "x = 2"),
    ],
)
def test_equations_with_the_same_solutions_are_equivalent(a, b):
    assert equations_equivalent(eq(a), eq(b))


@pytest.mark.parametrize(
    "a,b",
    [
        ("2x = 10", "x = 8"),
        ("x^2 = 4", "x = 2"),  # a square root taken without the negative branch
        ("x^2 = 2x", "x = 2"),  # dividing by x loses the root 0
        ("x/(x-2) = 2/(x-2)", "x = 2"),  # multiplying through admits a root the original excludes
        ("(x-1)^2/(x-1) = 0", "x - 1 = 0"),  # the only candidate root is the hole
        ("sqrt(x) = -2", "x = 4"),  # squaring admits a root
        ("x^2 + 1 = 0", "x^2 + 4 = 0"),  # both empty, still not the same equation
        ("x = 2", "y = 2"),
    ],
)
def test_equations_with_different_solutions_are_not_equivalent(a, b):
    assert not equations_equivalent(eq(a), eq(b))


def test_decimals_are_exact_before_any_arithmetic():
    """In binary, 0.1*3 - 0.3 is 5.6e-17. Read as typed, it is exactly zero."""
    assert expressions_equivalent(parse_math("0.1*3 - 0.3", as_written=True), expr("0"))


def test_solution_sets_ignore_order_and_representation():
    assert solution_sets_equivalent([expr("-1"), expr("2")], [expr("2"), expr("-2/2")])


def test_solution_sets_of_different_size_differ():
    assert not solution_sets_equivalent([expr("1")], [expr("1"), expr("2")])
