"""When do two pieces of mathematics mean the same thing?

Expressions are equivalent when they agree wherever both are defined. Isolated
holes are ignored — that (x^2-1)/(x-1) simplifies to x+1 is the exercise, not
an error — but disagreement over a region is not: log(x^2) and 2log(x) differ
for every negative x. Typed decimals are exact: 0.1 means one tenth.

Equations are equivalent when they have the same real solutions, with holes
respected. Evaluation cancels holes, so equation checks need the *written*
form: `parse_math(text, allow_equation=True, as_written=True)`.
"""
import math
import random
from collections.abc import Sequence

import sympy as sp

from learnai.adapters.cas.parse import evaluated

_NUMERIC_TRIALS = 12
_TOLERANCE = 1e-9


def _exact(expr: sp.Basic) -> sp.Basic:
    """Evaluated, with typed decimals read as exact: 0.1 + 0.2 is exactly 0.3."""
    return evaluated(expr, exact_decimals=True)


def _numeric_disagrees(a: sp.Expr, b: sp.Expr) -> bool:
    """Fast rejection: if the two disagree at any sampled point, they are not equal.

    Sampling only ever produces a confident NO. A clean sweep is not proof of
    equality, so a negative result here falls through to the symbolic check.
    A point where either side is undefined is skipped, which is why isolated
    holes never cause a rejection.
    """
    symbols = sorted(a.free_symbols | b.free_symbols, key=str)
    rng = random.Random(20260919)
    for _ in range(_NUMERIC_TRIALS):
        point = {s: sp.Rational(rng.randint(-20, 20), rng.randint(1, 7)) for s in symbols}
        try:
            va = complex(sp.N(a.subs(point)))
            vb = complex(sp.N(b.subs(point)))
        except (TypeError, ValueError, ArithmeticError):
            continue
        if not all(math.isfinite(part) for v in (va, vb) for part in (v.real, v.imag)):
            continue
        if abs(va - vb) > _TOLERANCE * max(1.0, abs(va), abs(vb)):
            return True
    return False


def expressions_equivalent(a: sp.Expr, b: sp.Expr) -> bool:
    a, b = _exact(a), _exact(b)
    if a == b:
        return True
    if _numeric_disagrees(a, b):
        return False
    decided = (a - b).equals(0)
    if decided is None:
        # Symbolic equality is undecidable in general. Many sampled points agreed,
        # so accept: a false accept here costs a student nothing, a false reject
        # marks correct work wrong, which is the failure that loses their trust.
        return True
    return bool(decided)


def real_solutions(eq: sp.Eq, var: sp.Symbol) -> frozenset[sp.Expr] | None:
    """The real solutions of a written equation, or None when they cannot be listed.

    Solved on the evaluated form, then filtered against the written one: a root
    survives only where both written sides are defined and real. The filter is
    what stops (x-1)^2/(x-1) = 0 claiming the solution 1 — SymPy's solver only
    ever sees x - 1 = 0, because evaluation has already cancelled the hole.
    """
    found = sp.solveset(_exact(eq.lhs) - _exact(eq.rhs), var, domain=sp.S.Reals)
    if found is sp.S.EmptySet:
        return frozenset()
    if not isinstance(found, sp.FiniteSet):
        return None  # infinitely many (sin x = 0), or not in closed form
    return frozenset(root for root in found if _defined_at(eq, var, root))


def _defined_at(eq: sp.Eq, var: sp.Symbol, point: sp.Expr) -> bool:
    for side in (eq.lhs, eq.rhs):
        value = _value_at(side, var, point)
        if not (value.is_finite and value.is_real):
            return False
    return True


def _value_at(expr: sp.Basic, var: sp.Symbol, point: sp.Expr) -> sp.Basic:
    """Substitute and evaluate bottom-up, so every child is a number before its parent is built.

    Plain `subs` rebuilds the parent first, and SymPy then merges
    (x-1)^-1 * (x-1)^2 into x-1 before x-1 has become 0 — cancelling the very
    hole this is meant to find.
    """
    if expr == var:
        return point
    if isinstance(expr, sp.Float):
        return _exact(expr)
    if not expr.args:
        return expr
    return expr.func(*(_value_at(arg, var, point) for arg in expr.args))


def equations_equivalent(a: sp.Eq, b: sp.Eq) -> bool:
    """Same real solutions, holes respected. Pass written forms (see module docstring).

    Falls back to proportionality — one side a nonzero constant multiple of the
    other — when the solutions cannot be compared: several variables, solutions
    that cannot be listed, or no real solutions on either side (where comparing
    two empty sets would accept any slip between x^2 + 1 = 0 and x^2 + 4 = 0).
    Proportional equations do share their solutions, but the fallback rejects
    genuine rewrites such as (x-1)^2 = 0 to x - 1 = 0 and is blind to holes.
    See spec D12.
    """
    variables = a.free_symbols | b.free_symbols
    if len(variables) == 1:
        (var,) = variables
        sa, sb = real_solutions(a, var), real_solutions(b, var)
        if sa is not None and sb is not None and (sa or sb):
            return solution_sets_equivalent(list(sa), list(sb))
    return _proportional(a, b)


def _proportional(a: sp.Eq, b: sp.Eq) -> bool:
    da = sp.simplify(_exact(a.lhs) - _exact(a.rhs))
    db = sp.simplify(_exact(b.lhs) - _exact(b.rhs))
    if db == 0:
        return bool(da == 0)
    ratio = sp.simplify(da / db)
    return not ratio.free_symbols and ratio != 0


def solution_sets_equivalent(a: Sequence[sp.Expr], b: Sequence[sp.Expr]) -> bool:
    if len(a) != len(b):
        return False
    remaining = list(b)
    for root in a:
        match = next((r for r in remaining if expressions_equivalent(root, r)), None)
        if match is None:
            return False
        remaining.remove(match)
    return True
