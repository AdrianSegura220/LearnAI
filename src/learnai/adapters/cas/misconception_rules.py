# src/learnai/adapters/cas/misconception_rules.py
from collections.abc import Callable

import sympy as sp

from learnai.adapters.cas.equivalence import expressions_equivalent
from learnai.adapters.cas.parse import ParseError
from learnai.adapters.cas.sympy_verifier import Alternatives, Step, parse_step

X = sp.Symbol("x")
_A, _B = (sp.Wild(n, exclude=[0]) for n in ("wa", "wb"))

Rule = Callable[[sp.Basic, sp.Basic], bool]


def _comparable(previous: sp.Basic, current: sp.Basic) -> bool:
    """Whether both sides are expressions, which every rule below but the
    zero-product one needs. A claim — an equation, or a list of them — is a
    Basic but not an Expr, and handing one over would raise inside the rule
    instead of declining to match."""
    return isinstance(previous, sp.Expr) and isinstance(current, sp.Expr)


def _square_distributes(previous: sp.Basic, current: sp.Basic) -> bool:
    if not _comparable(previous, current):
        return False
    match = previous.match((_A + _B) ** 2)
    if not match:
        return False
    wrong = match[_A] ** 2 + match[_B] ** 2
    return expressions_equivalent(sp.expand(current), sp.expand(wrong))


def _drops_cross_terms(previous: sp.Basic, current: sp.Basic) -> bool:
    """One diagonal of the multiplication grid, cross terms dropped.

    Which two products are "first" and "last" depends on the order the student
    wrote the terms in each factor, which parsing does not preserve — so either
    diagonal is this belief, not just the one canonical argument order happens
    to pick. The grid is read directly rather than Wild-matched: a match returns
    one assignment, never all, so which diagonal it picks is not stable.
    """
    if not _comparable(previous, current):
        return False
    if not previous.is_Mul or len(previous.args) != 2:
        return False
    f1, f2 = previous.args
    if not (f1.is_Add and len(f1.args) == 2 and f2.is_Add and len(f2.args) == 2):
        return False
    if expressions_equivalent(sp.expand(current), sp.expand(previous)):
        return False  # correct work, or cross terms that cancel: (x+2)(x-2)
    (t1, t2), (u1, u2) = f1.args, f2.args
    diagonals = (t1 * u1 + t2 * u2, t1 * u2 + t2 * u1)
    return any(expressions_equivalent(sp.expand(current), sp.expand(d)) for d in diagonals)


def _incomplete_common_factor(previous: sp.Basic, current: sp.Basic) -> bool:
    """Still algebraically correct, but a further common factor remains."""
    if not _comparable(previous, current):
        return False
    if not current.is_Mul:
        return False  # expanded or untouched work is not a partial factoring
    if not expressions_equivalent(sp.expand(previous), sp.expand(current)):
        return False
    return sp.factor(current) != current


def _factor_sign_flip(previous: sp.Basic, current: sp.Basic) -> bool:
    """Right magnitudes, wrong signs: the answer factors previous(-x) instead."""
    if not _comparable(previous, current):
        return False
    if expressions_equivalent(sp.expand(previous), sp.expand(current)):
        return False
    reflected = sp.expand(previous.subs(X, -X))
    return expressions_equivalent(sp.expand(current), reflected)


def _sum_of_squares_factored(previous: sp.Basic, current: sp.Basic) -> bool:
    if not _comparable(previous, current):
        return False
    if not previous.is_Add or len(previous.args) != 2:
        return False
    if not all(term.is_number or term.is_Pow for term in previous.args):
        return False
    if any(term.is_number and term < 0 for term in previous.args):
        return False
    return bool(current.is_Mul or (current.is_Pow and current.exp == 2))


def _zero_product_without_zero(previous: sp.Basic, current: sp.Basic) -> bool:
    """Sets each factor equal to a non-zero right-hand side."""
    if not isinstance(previous, sp.Eq) or previous.rhs == 0:
        return False
    factors = sp.factor(previous.lhs)
    if not factors.is_Mul:
        return False
    naive_roots: set[sp.Expr] = set()
    for factor in factors.args:
        if factor.free_symbols:
            naive_roots.update(sp.solve(sp.Eq(factor, previous.rhs), X))
    if not naive_roots:
        return False
    claimed = _claimed_values(current)
    return bool(claimed) and claimed <= {sp.nsimplify(r) for r in naive_roots}


def _claimed_values(current: sp.Basic) -> set[sp.Expr]:
    """The values a step claims, for comparison with the naive roots.

    A step may claim several at once — "x = 7, x = 8" — which the shared
    reader flattens into one Tuple of equations.
    """
    if isinstance(current, sp.Eq):
        return {sp.nsimplify(current.rhs)}
    if isinstance(current, sp.Tuple):
        values: set[sp.Expr] = set()
        for entry in current:
            values |= _claimed_values(entry)
        return values
    return set()


_RULES: dict[str, Rule] = {
    "square_distributes_over_sum": _square_distributes,
    "product_of_sums_drops_cross": _drops_cross_terms,
    "incomplete_common_factor": _incomplete_common_factor,
    "factor_sign_flip": _factor_sign_flip,
    "sum_of_squares_factored": _sum_of_squares_factored,
    "zero_product_without_zero": _zero_product_without_zero,
}

IMPLEMENTED_SIGNATURES = frozenset(_RULES)

DEFERRED_SIGNATURES = frozenset(
    {
        "ignores_leading_coefficient",
        "completes_without_compensating",
        "formula_b_not_negated",
        "discriminant_cases_reversed",
        "vertex_sign_flip",
        "negative_root_kept",
    }
)


class SympyMisconceptionRules:
    """Matcher for `cas_symbolic` skills.

    A deferred or unknown signature returns False, and so does a step the
    shared reader cannot parse or a rule cannot handle: diagnosis degrades to
    "novel error" and the tutor still receives the localised step.
    """

    def exhibits(self, signature: str, previous: str, current: str) -> bool:
        rule = _RULES.get(signature)
        if rule is None:
            return False
        try:
            prev_step = parse_step(previous)
        except ParseError:
            return False
        try:
            cur_step = parse_step(current)
        except ParseError:
            return False
        try:
            return bool(rule(_as_basic(prev_step), _as_basic(cur_step)))
        except (TypeError, ValueError, NotImplementedError, sp.SympifyError):
            return False


def _as_basic(step: Step) -> sp.Basic:
    """A step listing several claims becomes one Tuple, so every rule can
    pattern-match whatever it is handed."""
    return sp.Tuple(*step.parts) if isinstance(step, Alternatives) else step
