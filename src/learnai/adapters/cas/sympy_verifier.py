# src/learnai/adapters/cas/sympy_verifier.py
import itertools
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

import sympy as sp

from learnai.adapters.cas.equivalence import (
    equations_equivalent,
    expressions_equivalent,
    real_solutions,
    solution_sets_equivalent,
)
from learnai.adapters.cas.parse import KNOWN_NAMES, ParseError, evaluated, parse_math
from learnai.adapters.cas.vocabulary import (
    COMPLETED_SQUARE,
    EXACT_NOT_DECIMAL,
    EXPANDED,
    FULLY_FACTORED,
    MATH_CONSTRAINTS,
    InvalidAnswerKeyError,
    UnknownConstraintError,
    UnsupportedAnswerKindError,
)
from learnai.domain.enums import AnswerKind, Verdict
from learnai.domain.items import AnswerSpec, FormConstraint, StepDiff, Submission
from learnai.domain.verification import CheckResult

_SUPPORTED_KINDS = frozenset({AnswerKind.SINGLE_VALUE, AnswerKind.RELATION, AnswerKind.VALUE_SET})

# "x = -3" names the value found. Only a single letter, and only when it does
# not appear on the right: "x = x + 1" is an equation and stays one.
_NAMED_VALUE = re.compile(r"\s*([A-Za-z])\s*=(?!=)(.*)", re.S)

# "±" and "+/-" stand for two values, one with each sign.
_PLUS_MINUS = re.compile(r"±|\+/-")

# Tutor prose arrives with typographic maths; the parser only reads ASCII.
_UNICODE_MATHS = str.maketrans(
    {"−": "-", "–": "-", "×": "*", "·": "*", "⋅": "*", "÷": "/", "²": "^2", "³": "^3"}
)
_ROOT_SIGN = re.compile(r"√\s*(\(|[0-9]+|[A-Za-z])")
_EDGE = ".,;:!?\"'`$"  # sentence punctuation, and the dollars of inline maths


class SympyVerifier:
    """Verifier for `cas_symbolic` skills."""

    @property
    def supported_constraints(self) -> frozenset[FormConstraint]:
        return MATH_CONSTRAINTS

    def check_answer(self, submission: Submission, spec: AnswerSpec) -> CheckResult:
        key = _parse_key(spec)  # content errors raise before the student is judged
        submission.check_shape(spec.kind)
        if submission.is_blank:
            return CheckResult(Verdict.NO_ANSWER)
        try:
            if spec.kind is AnswerKind.VALUE_SET:
                return _check_values(submission, key, spec.form_constraints)
            if spec.kind is AnswerKind.RELATION:
                return _check_relation(submission.fields[0], key)
            return _check_single(submission.fields[0], key, spec.form_constraints)
        except ParseError:
            return CheckResult(Verdict.MALFORMED)

    def key_submission(self, spec: AnswerSpec) -> Submission:
        if spec.kind is AnswerKind.VALUE_SET:
            values = _key_values(spec.expression)
            return Submission(tuple(values)) if values else Submission.none()
        return Submission.of(spec.expression)

    def diff_steps(self, steps: Sequence[str]) -> StepDiff | None:
        """The first step that does not follow from the one before, or None."""
        if len(steps) < 2:
            return None

        parsed: list[Step | None] = []
        for raw in steps:
            try:
                parsed.append(parse_step(raw))
            except ParseError:
                parsed.append(None)

        for i, step in enumerate(parsed):
            previous = steps[i - 1] if i else ""
            if step is None:
                return StepDiff(index=i, previous=previous, current=steps[i], unreadable=True)
            if not i:
                continue
            try:
                follows = _steps_equivalent(parsed[i - 1], step)
            except Exception:
                # Deliberate broad catch: SymPy's solvers raise a zoo of exception
                # types, and unreadable is the cannot-process channel — skipping
                # the transition could falsely claim there is no broken step.
                return StepDiff(index=i, previous=previous, current=steps[i], unreadable=True)
            if not follows:
                return StepDiff(index=i, previous=previous, current=steps[i])
        return None

    def extract_candidate_expressions(self, text: str) -> tuple[str, ...]:
        """Every stretch of maths in a piece of prose, and its parts.

        A word of two or more letters that is not a known function name ends a
        stretch, so "Try rewriting it as (x+1)(x+2) and see." yields
        "(x+1)(x+2)". Each side of an "=" and each item of a comma list is a
        candidate too, since any of them may be the answer on its own.
        """
        text = _ROOT_SIGN.sub(
            lambda m: "sqrt(" if m.group(1) == "(" else f"sqrt({m.group(1)})",
            text.translate(_UNICODE_MATHS),
        )
        found: list[str] = []
        for stretch in _maths_stretches(text):
            pieces = [stretch]
            if "=" in stretch:
                pieces += stretch.split("=")
            pieces += [item for piece in list(pieces) for item in piece.split(",")]
            for piece in pieces:
                piece = piece.strip(_EDGE + " ")
                if piece and piece not in found:
                    found.append(piece)
        return tuple(found)

    def matches_answer(self, expression: str, spec: AnswerSpec) -> bool:
        # Plain equivalence would be too broad: the question x^2 + 3x + 2 equals
        # its answer (x+1)(x+2), and quoting the problem is not a leak.
        if spec.kind is AnswerKind.VALUE_SET:
            key = _parse_key(spec)
            try:
                values = [
                    parse_math(_value_text(v), as_written=True)
                    for v in _expand_plus_minus(expression)
                ]
            except ParseError:
                return False
            return any(
                expressions_equivalent(value, k)
                and all(_satisfies(value, c) for c in spec.form_constraints)
                for value in values
                for k in key
            )
        verdict = self.check_answer(Submission.of(expression), spec).verdict
        return verdict is Verdict.CORRECT


def _maths_stretches(text: str) -> Iterator[str]:
    current: list[str] = []
    for token in text.split():
        core = token.strip(_EDGE + "()")
        if core.isalpha() and len(core) > 1 and core.lower() not in KNOWN_NAMES:
            if current:
                yield " ".join(current).strip(_EDGE + " ")
            current = []
        else:
            current.append(token)
    if current:
        yield " ".join(current).strip(_EDGE + " ")


def _parse_key(spec: AnswerSpec) -> object:
    if spec.kind not in _SUPPORTED_KINDS:
        raise UnsupportedAnswerKindError(spec.kind)
    if unknown := set(spec.form_constraints) - MATH_CONSTRAINTS:
        raise UnknownConstraintError(sorted(unknown))
    try:
        if spec.kind is AnswerKind.VALUE_SET:
            return [parse_math(v) for v in _key_values(spec.expression)]
        if spec.kind is AnswerKind.RELATION:
            if spec.form_constraints:
                raise InvalidAnswerKeyError("form constraints apply to values, not relations")
            key = parse_math(spec.expression, allow_equation=True, as_written=True)
            if not isinstance(key, sp.Eq):
                raise InvalidAnswerKeyError(f"relation key {spec.expression!r} is not an equation")
            return key
        return parse_math(spec.expression)
    except ParseError as exc:
        raise InvalidAnswerKeyError(f"answer key {spec.expression!r} does not parse") from exc


def _key_values(expression: str) -> list[str]:
    return [v for v in (part.strip() for part in expression.split(",")) if v]


def _expand_plus_minus(text: str) -> list[str]:
    """'(-5 ± sqrt(13))/2' stands for two values: one with +, one with -."""
    pieces = _PLUS_MINUS.split(text)
    if len(pieces) > 3:
        raise ParseError("more than two ± signs in one entry")
    return [
        "".join(piece + sign for piece, sign in zip(pieces, (*signs, "")))
        for signs in itertools.product("+-", repeat=len(pieces) - 1)
    ]


def _value_text(field: str) -> str:
    """'x = -3' reads as '-3': naming the value found is not part of the value."""
    named = _NAMED_VALUE.fullmatch(field)
    if named is None:
        return field
    try:
        value = parse_math(named.group(2))
    except ParseError:
        return field
    return named.group(2) if sp.Symbol(named.group(1)) not in value.free_symbols else field


def _check_single(
    field: str, key: sp.Expr, constraints: tuple[FormConstraint, ...]
) -> CheckResult:
    written = parse_math(_value_text(field), as_written=True)
    if not expressions_equivalent(written, key):
        return CheckResult(Verdict.WRONG)
    failed = tuple(c for c in constraints if not _satisfies(written, c))
    return CheckResult(Verdict.WRONG, failed) if failed else CheckResult(Verdict.CORRECT)


def _check_relation(field: str, key: sp.Eq) -> CheckResult:
    written = parse_math(field, allow_equation=True, as_written=True)
    if not isinstance(written, sp.Eq):
        return CheckResult(Verdict.MALFORMED)
    return CheckResult(Verdict.CORRECT if equations_equivalent(written, key) else Verdict.WRONG)


def _check_values(
    submission: Submission, key: list[sp.Expr], constraints: tuple[FormConstraint, ...]
) -> CheckResult:
    if submission.claims_none:
        return CheckResult(Verdict.CORRECT if not key else Verdict.WRONG)
    written = [
        parse_math(_value_text(value), as_written=True)
        for field in submission.entries
        for value in _expand_plus_minus(field)
    ]
    # A set: a repeated root is one solution, however many times it is entered.
    if not solution_sets_equivalent(_distinct(written), _distinct(key)):
        return CheckResult(Verdict.WRONG)
    failed = tuple(c for c in constraints if not all(_satisfies(v, c) for v in written))
    return CheckResult(Verdict.WRONG, failed) if failed else CheckResult(Verdict.CORRECT)


def _distinct(values: Sequence[sp.Expr]) -> list[sp.Expr]:
    kept: list[sp.Expr] = []
    for value in values:
        if not any(expressions_equivalent(value, seen) for seen in kept):
            kept.append(value)
    return kept


# -- form constraints, judged on what the student wrote ------------------------


def _factors(expr: sp.Basic) -> Iterator[sp.Basic]:
    """The multiplicands of a written product, however the parser nested them."""
    if isinstance(expr, sp.Mul):
        for arg in expr.args:
            yield from _factors(arg)
    else:
        yield expr


def _terms(expr: sp.Basic) -> Iterator[sp.Basic]:
    """The summands of a written sum, however the parser nested them."""
    if isinstance(expr, sp.Add):
        for arg in expr.args:
            yield from _terms(arg)
    else:
        yield expr


def _is_fully_factored(written: sp.Expr) -> bool:
    """Every factor is irreducible over the rationals, with no whole number left inside it.

    4(x+2) passes; (2x+2)(x+2) does not, since the 2 inside the first factor is
    still common; x^2 + 1 passes, since it cannot be factored over the rationals.
    """
    for factor in _factors(written):
        base = factor.base if isinstance(factor, sp.Pow) else factor
        if base.is_number:
            continue
        try:
            content, irreducibles = sp.factor_list(evaluated(base))
        except sp.PolynomialError:
            continue  # not a polynomial: nothing left to factor at school level
        if abs(content) != 1 or len(irreducibles) != 1 or irreducibles[0][1] != 1:
            return False
    return True


def _is_expanded(written: sp.Expr) -> bool:
    """No product or power of a sum remains, and like terms are combined."""
    for node in sp.preorder_traversal(written):
        if isinstance(node, sp.Mul) and any(isinstance(f, sp.Add) for f in _factors(node)):
            return False
        if isinstance(node, sp.Pow) and isinstance(node.base, sp.Add):
            if node.exp.is_Integer and node.exp > 1:
                return False
    combined = sp.Add.make_args(sp.expand(evaluated(written)))
    return len(list(_terms(written))) == len(combined)


def _is_square_of_sum(term: sp.Basic) -> bool:
    factors = list(_factors(term))
    squares = [
        f for f in factors if isinstance(f, sp.Pow) and isinstance(f.base, sp.Add) and f.exp == 2
    ]
    return len(squares) == 1 and all(f.is_number for f in factors if f is not squares[0])


def _is_completed_square(written: sp.Expr) -> bool:
    """a(x + p)^2 + q: one squared sum, optionally times a number, and at most one number beside it."""
    squares = numbers = others = 0
    for term in _terms(written):
        if term.is_number:
            numbers += 1
        elif _is_square_of_sum(term):
            squares += 1
        else:
            others += 1
    return squares == 1 and numbers <= 1 and others == 0


_FORM_CHECKS: dict[FormConstraint, Callable[[sp.Expr], bool]] = {
    FULLY_FACTORED: _is_fully_factored,
    EXPANDED: _is_expanded,
    EXACT_NOT_DECIMAL: lambda written: not written.atoms(sp.Float),
    COMPLETED_SQUARE: _is_completed_square,
}
assert set(_FORM_CHECKS) == MATH_CONSTRAINTS, "declared vocabulary and checks disagree"


def _satisfies(written: sp.Expr, constraint: FormConstraint) -> bool:
    """Judge a form constraint on the written form: 4(x+2) must still look factored."""
    check = _FORM_CHECKS.get(constraint)
    if check is None:
        raise UnknownConstraintError(constraint)
    return check(written)


@dataclass(frozen=True)
class Alternatives:
    """A step listing equations any of which may hold: "x = 1 or x = 3", "x = ±3"."""

    parts: tuple[sp.Eq, ...]

    @property
    def free_symbols(self) -> set[sp.Symbol]:
        return set().union(*(part.free_symbols for part in self.parts))


Step = sp.Basic | Alternatives

_OR = re.compile(r"\s+or\s+", re.IGNORECASE)


def parse_step(text: str) -> Step:
    """Read one line of working, in the notations students actually use.

    Public: the one reader for a line of student working. Task 8's rules read
    steps through it too, so a belief fires on exactly the notations the
    differ accepts and the comma policy lives in one place.

    A line opening with "=" continues the previous expression. A line listing
    alternatives — joined by "or", written with "±" or "+/-", or separated by
    commas when every part is an equation — is the set of its equations, and a
    bare value inherits the letter before it: "x = 1 or 3" is "x = 1 or x = 3".
    """
    text = text.strip()
    if text.startswith("="):
        return parse_math(text[1:], as_written=True)

    parts = [part.strip() for part in _OR.split(text)]
    if len(parts) == 1 and "," in text:
        pieces = [piece.strip() for piece in text.split(",")]
        if all("=" in piece for piece in pieces):  # never split a decimal comma
            parts = pieces
    if len(parts) == 1 and not _PLUS_MINUS.search(text):
        return parse_math(text, allow_equation=True, as_written=True)

    named = _NAMED_VALUE.fullmatch(parts[0])
    equations: list[sp.Eq] = []
    for part in parts:
        if "=" not in part and named is not None:
            part = f"{named.group(1)} = {part}"
        for variant in _expand_plus_minus(part):
            equation = parse_math(variant, allow_equation=True, as_written=True)
            if not isinstance(equation, sp.Eq):
                raise ParseError(f"{part!r} is not an equation")
            equations.append(equation)
    return Alternatives(tuple(equations)) if len(equations) > 1 else equations[0]


def _is_claim(step: Step) -> bool:
    return isinstance(step, (sp.Eq, Alternatives))


def _equations(step: Step) -> tuple[sp.Eq, ...]:
    return step.parts if isinstance(step, Alternatives) else (step,)


def _solutions(step: Step, var: sp.Symbol) -> frozenset[sp.Expr] | None:
    found = [real_solutions(equation, var) for equation in _equations(step)]
    if any(f is None for f in found):
        return None
    return frozenset().union(*found)


def _steps_equivalent(a: Step, b: Step) -> bool:
    """Expressions compare by value; equations and lists by their real solutions.

    A move between an expression and an equation changes what is claimed, so
    it is never a valid step.
    """
    if _is_claim(a) != _is_claim(b):
        return False
    if not _is_claim(a):
        return expressions_equivalent(a, b)
    if isinstance(a, sp.Eq) and isinstance(b, sp.Eq):
        return equations_equivalent(a, b)
    variables = a.free_symbols | b.free_symbols
    if len(variables) == 1:
        (var,) = variables
        sa, sb = _solutions(a, var), _solutions(b, var)
        if sa is not None and sb is not None and (sa or sb):
            return solution_sets_equivalent(list(sa), list(sb))
    # Solutions cannot be listed: fall back to matching the equations pairwise.
    remaining = list(_equations(b))
    for equation in _equations(a):
        match = next((r for r in remaining if equations_equivalent(equation, r)), None)
        if match is None:
            return False
        remaining.remove(match)
    return not remaining
