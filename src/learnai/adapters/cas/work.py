"""Task-bound coefficient calculations and explicitly scoped partial work.

The strict differ still answers whether consecutive equations are equivalent.
These checks distinguish ancillary calculations and partial branches from that
claim, without treating a final subset of roots as a complete solution.
"""
from collections.abc import Callable, Sequence
import re

import sympy as sp

from learnai.adapters.cas.equivalence import equations_equivalent, expressions_equivalent
from learnai.adapters.cas.parse import MAX_INPUT_LENGTH, ParseError, evaluated, parse_math
from learnai.adapters.cas.sympy_verifier import Alternatives, Step, _steps_equivalent, parse_step
from learnai.domain.items import Formula, Item, StepDiff
from learnai.domain.verification import WorkCheck

_ASSIGNMENTS = re.compile(r'\s*[abc]\s*=')
_A, _B, _C = sp.symbols('a b c')
_DISCRIMINANT = _B**2 - 4*_A*_C


def _coefficients(source: Step) -> dict[sp.Symbol, sp.Expr] | None:
    if not isinstance(source, sp.Eq) or len(source.free_symbols) != 1:
        return None
    var, = source.free_symbols
    if var in {_A, _B, _C}:
        return None  # coefficient notation would collide with the unknown
    try:
        polynomial = sp.Poly(evaluated(source.lhs) - evaluated(source.rhs), var)
        if polynomial.degree() == 2:
            return dict(zip((_A, _B, _C), polynomial.all_coeffs(), strict=True))
    except sp.PolynomialError:
        pass
    return None


def _quadratic(item: Item) -> tuple[sp.Eq, dict[sp.Symbol, sp.Expr]] | None:
    formulas = [block.source for block in item.statement if isinstance(block, Formula)]
    if len(formulas) != 1:
        return None
    try:
        source = parse_math(formulas[0], allow_equation=True, as_written=True)
        bindings = _coefficients(source)
        return (source, bindings) if bindings is not None else None
    except (ParseError, sp.PolynomialError):
        return None


def _substitute(step: Step, bindings: dict) -> Step:
    if isinstance(step, Alternatives):
        return Alternatives(tuple(_substitute(part, bindings) for part in step.parts))
    if step in bindings:
        return bindings[step]
    if not step.free_symbols & bindings.keys():
        return step
    # Rebuilding with xreplace evaluates parents and can cancel undefined
    # factors. Retain the written tree for the strict equation checker.
    return step.func(*(_substitute(arg, bindings) for arg in step.args), evaluate=False)


def _factor_branch(previous: Step, current: Step, source: sp.Eq) -> bool:
    if not isinstance(previous, sp.Eq) or not isinstance(current, sp.Eq):
        return False
    if not equations_equivalent(source, previous):
        return False
    product = previous.lhs if previous.rhs == 0 else previous.rhs if previous.lhs == 0 else None
    if not isinstance(product, sp.Mul):
        return False
    factors = [part for part in product.args if part.free_symbols]
    if len(factors) < 2:
        return False
    return any(equations_equivalent(sp.Eq(factor, 0, evaluate=False), current) for factor in factors)


def check_work(steps: Sequence[str], *, item: Item, allow_partial: bool,
               strict: Callable[[Sequence[str]], StepDiff | None]) -> WorkCheck:
    context = _quadratic(item)
    formulas = [block.source for block in item.statement if isinstance(block, Formula)]
    expression_item = len(formulas) == 1 and '=' not in formulas[0]
    if context is None and not (expression_item and any(text.count('=') > 1 for text in steps)):
        return WorkCheck(strict(steps))
    source, bindings = context if context is not None else (None, {})
    notes: list[str] = []
    previous: Step | None = None
    ancillary = False
    partial = False
    for index, text in enumerate(steps):
        def failure(unreadable: bool = False) -> WorkCheck:
            return WorkCheck(StepDiff(index, steps[index-1] if index else '', text, unreadable), tuple(notes))
        try:
            if len(text) > MAX_INPUT_LENGTH:
                raise ParseError('work line too long')
            if not ancillary and source is not None and isinstance(previous, sp.Eq):
                # Coefficients belong to the most recent verified equation form.
                # An unrelated first line must never replace the exercise context.
                updated = _coefficients(previous)
                if updated is not None and equations_equivalent(source, previous):
                    bindings = updated
            pieces = text.split(',')
            if bindings and len(pieces) > 1 and all(_ASSIGNMENTS.match(piece) for piece in pieces):
                assignments = [parse_math(piece, allow_equation=True, as_written=True) for piece in pieces]
                if ({entry.lhs for entry in assignments} != {_A, _B, _C}
                        or len(assignments) != 3):
                    raise ParseError('coefficient declarations must name a, b and c exactly once')
                if any(entry.rhs.free_symbols or not expressions_equivalent(entry.rhs, bindings[entry.lhs])
                       for entry in assignments):
                    return failure()
                notes.append('Coefficient assignments checked against the exercise or a verified equivalent equation; they are definitions, not alternative solutions.')
                ancillary = True
                continue
            # Recognize the standard discriminant calculation by its symbolic
            # left-hand expression, then check every equality under item bindings.
            terms = text.split('=')
            if len(terms) >= 2 and terms[0].strip() and ',' not in text:
                first = parse_math(terms[0], as_written=True)
                if bindings and expressions_equivalent(first, _DISCRIMINANT):
                    values = [parse_math(term, as_written=True).xreplace(bindings) for term in terms]
                    if any(not expressions_equivalent(a, b) for a, b in zip(values, values[1:])):
                        return failure()
                    notes.append('The discriminant calculation was checked using coefficients from the exercise or a verified equivalent equation; it does not by itself solve the equation.')
                    ancillary = True
                    continue
                if len(terms) > 2 or not first.free_symbols:
                    values = [parse_math(term, as_written=True) for term in terms]
                    if expression_item or all(not value.free_symbols for value in values):
                        if any(not expressions_equivalent(a, b) for a, b in zip(values, values[1:])):
                            return failure()
                        if expression_item:
                            anchor = previous if previous is not None else parse_math(formulas[0], as_written=True)
                            if not _steps_equivalent(anchor, values[0]):
                                return failure()
                            previous = values[-1]
                        else:
                            ancillary = True
                        notes.append('Every link in the calculation chain was checked; this calculation alone does not establish task completion.')
                        continue
            current = _substitute(parse_step(text), bindings) if ancillary else parse_step(text)
            if ancillary:
                # A subsequent solution claim is checked against the task, not
                # against a coefficient declaration or a discriminant value.
                if not isinstance(current, (sp.Eq, Alternatives)):
                    raise ParseError('unsupported transition from ancillary calculation')
                parts = current.parts if isinstance(current, Alternatives) else (current,)
                if source is None or any(part.free_symbols != source.free_symbols for part in parts):
                    raise ParseError('unsupported ancillary definition rather than a solution equation')
                if source is None or not _steps_equivalent(source, current):
                    return failure()
                notes.append('The subsequent solution equation was checked against the exercise, separately from the ancillary calculation.')
                ancillary = False
            elif previous is not None and not _steps_equivalent(previous, current):
                if allow_partial and not partial and source is not None and _factor_branch(previous, current, source):
                    partial = True
                    notes.append('This follows one valid factor branch only; the remaining branches still need consideration. This does not establish a complete solution set.')
                else:
                    return failure()
            previous = current
        except Exception:
            # Parsing/solver inability is not evidence of incorrect mathematics.
            return failure(unreadable=True)
    return WorkCheck(None, tuple(notes))
