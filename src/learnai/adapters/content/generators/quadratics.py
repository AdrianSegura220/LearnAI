# src/learnai/adapters/content/generators/quadratics.py
"""The twelve quadratics templates, each building its problem backwards from the answer."""
import math
import random
from collections.abc import Sequence

import sympy as sp

from learnai.adapters.cas.parse import write_math
from learnai.adapters.cas.vocabulary import COMPLETED_SQUARE, EXPANDED, FULLY_FACTORED
from learnai.adapters.content.types import GeneratedProblem, TemplateSpec
from learnai.domain.enums import AnswerKind
from learnai.domain.ids import SkillId, TemplateId
from learnai.domain.items import Block, FormConstraint, Formula, Text

X = sp.Symbol("x")
Y = sp.Symbol("y")


def _nonzero(rng: random.Random, lo: int = -9, hi: int = 9) -> int:
    value = 0
    while value == 0:
        value = rng.randint(lo, hi)
    return value


def _statement(*parts: str | sp.Basic) -> tuple[Block, ...]:
    """Prose stays Text; every SymPy object becomes a Formula in student notation."""
    return tuple(Text(part) if isinstance(part, str) else Formula(write_math(part)) for part in parts)


def _signed(n: int) -> str:
    return f"+ {n}" if n >= 0 else f"- {-n}"


def _solutions_line(roots: Sequence[sp.Expr]) -> str:
    """The last line of solving: "x = -7 or x = 6"."""
    return " or ".join(write_math(sp.Eq(X, root)) for root in roots)


def _rewrite(
    instruction: str,
    prompt: sp.Expr,
    answer: sp.Expr,
    constraint: FormConstraint,
    *,
    via: tuple[str, ...] = (),
) -> GeneratedProblem:
    """An item whose answer is its prompt rewritten into a required form."""
    return GeneratedProblem(
        statement=_statement(f"{instruction}: ", prompt),
        prompt_expression=write_math(prompt),
        answer=write_math(answer),
        form_constraints=(constraint,),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(write_math(prompt), *via, write_math(answer)),
    )


def expand_binomial(rng: random.Random) -> GeneratedProblem:
    a = _nonzero(rng)
    b = _nonzero(rng)
    while b == a:
        b = _nonzero(rng)
    prompt = (X + a) * (X + b)
    return _rewrite("Expand and simplify", prompt, sp.expand(prompt), EXPANDED)


def expand_square(rng: random.Random) -> GeneratedProblem:
    prompt = (X + _nonzero(rng)) ** 2
    return _rewrite("Expand and simplify", prompt, sp.expand(prompt), EXPANDED)


def factor_common(rng: random.Random) -> GeneratedProblem:
    coefficient = rng.randint(2, 6)
    power = rng.randint(0, 1)
    p = rng.randint(2, 7)
    q = _nonzero(rng)
    while math.gcd(p, q) != 1:
        q = _nonzero(rng)
    prompt = sp.expand(coefficient * X**power * (p * X + q))
    return _rewrite("Factor completely", prompt, sp.factor(prompt), FULLY_FACTORED)


def factor_monic(rng: random.Random) -> GeneratedProblem:
    r1 = _nonzero(rng)
    r2 = _nonzero(rng)
    while r2 == -r1:  # x^2 - r^2 is a difference of squares: another skill's item
        r2 = _nonzero(rng)
    prompt = sp.expand((X - r1) * (X - r2))
    return _rewrite("Factor", prompt, sp.factor(prompt), FULLY_FACTORED)


def factor_difference_of_squares(rng: random.Random) -> GeneratedProblem:
    a = rng.randint(1, 6)
    b = rng.randint(1, 9)
    while math.gcd(a, b) != 1:  # a common factor would exercise quad.factor.common first
        b = rng.randint(1, 9)
    prompt = a**2 * X**2 - b**2
    return _rewrite("Factor", prompt, sp.factor(prompt), FULLY_FACTORED)


def _primitive_binomial(rng: random.Random) -> sp.Expr:
    """px + q with no common factor, so a product of two has none either (Gauss's lemma)."""
    p = rng.randint(2, 5)
    q = _nonzero(rng, -7, 7)
    while math.gcd(p, q) != 1:
        q = _nonzero(rng, -7, 7)
    return p * X + q


def factor_nonmonic(rng: random.Random) -> GeneratedProblem:
    prompt = sp.expand(_primitive_binomial(rng) * _primitive_binomial(rng))
    return _rewrite("Factor", prompt, sp.factor(prompt), FULLY_FACTORED)


def solve_by_factoring(rng: random.Random) -> GeneratedProblem:
    r1, r2 = _nonzero(rng), _nonzero(rng)
    lhs = sp.expand((X - r1) * (X - r2))
    roots = sorted({r1, r2})
    return GeneratedProblem(
        statement=_statement("Solve for x: ", sp.Eq(lhs, 0)),
        prompt_expression=None,
        answer=", ".join(str(r) for r in roots),
        form_constraints=(),
        kind=AnswerKind.VALUE_SET,
        worked_steps=(
            write_math(sp.Eq(lhs, 0)),
            write_math(sp.Eq(sp.factor(lhs), 0)),
            _solutions_line(roots),
        ),
        label="x =",
    )


def complete_the_square(rng: random.Random) -> GeneratedProblem:
    p = _nonzero(rng, -7, 7)
    q = rng.randint(-20, 20)
    answer = (X + p) ** 2 + q
    halfway = f"{write_math((X + p) ** 2)} - {p * p} {_signed(p * p + q)}"
    return _rewrite(
        "Rewrite by completing the square", sp.expand(answer), answer, COMPLETED_SQUARE, via=(halfway,)
    )


def apply_quadratic_formula(rng: random.Random) -> GeneratedProblem:
    for _ in range(200):
        a = rng.randint(1, 3)
        b = _nonzero(rng)
        c = _nonzero(rng)
        discriminant = b * b - 4 * a * c
        if discriminant > 0 and not sp.sqrt(discriminant).is_Integer:
            break
    else:  # pragma: no cover - the search succeeds within a few draws in practice
        a, b, c, discriminant = 1, 1, -1, 5
    equation = sp.Eq(a * X**2 + b * X + c, 0)
    roots = sp.solve(equation, X)
    return GeneratedProblem(
        statement=_statement("Solve exactly using the quadratic formula: ", equation),
        prompt_expression=None,
        answer=", ".join(write_math(r) for r in roots),
        form_constraints=(),
        kind=AnswerKind.VALUE_SET,
        worked_steps=(
            write_math(equation),
            f"x = ({-b} ± sqrt({discriminant}))/{2 * a}",
            _solutions_line(roots),
        ),
        label="x =",
    )


def count_real_roots(rng: random.Random) -> GeneratedProblem:
    # The answer is chosen first, so no answer is right by default. The
    # equation is then built from a perfect square a(x - r)^2, which has one
    # root: lowering its constant gives two roots, raising it gives none. The
    # three cases look alike, so only b^2 - 4ac tells them apart.
    count = rng.choice((0, 1, 2))
    a = rng.randint(1, 3)
    r = _nonzero(rng, -5, 5)
    shift = 0 if count == 1 else rng.randint(1, 9)
    constant = a * r * r + (shift if count == 0 else -shift)
    equation = sp.Eq(a * X**2 - 2 * a * r * X + constant, 0)
    return GeneratedProblem(
        statement=_statement("How many distinct real roots does ", equation, " have? Answer 0, 1, or 2."),
        prompt_expression=None,
        answer=str(count),
        form_constraints=(),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(),
        label="Number of real roots:",
    )


def vertex_x_coordinate(rng: random.Random) -> GeneratedProblem:
    a = _nonzero(rng, -4, 4)
    b = _nonzero(rng)
    c = rng.randint(-9, 9)
    return GeneratedProblem(
        statement=_statement(
            "Find the x-coordinate of the vertex of ",
            sp.Eq(Y, a * X**2 + b * X + c),
            ". Give an exact value.",
        ),
        prompt_expression=None,
        answer=write_math(sp.Rational(-b, 2 * a)),
        form_constraints=(),  # "exact" rules out -2.33 for -7/3; -0.25 for -1/4 is exact
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(),
        label="x =",
    )


def rectangle_area_word_problem(rng: random.Random) -> GeneratedProblem:
    width = rng.randint(2, 12)
    extra = rng.randint(1, 9)
    area = width * (width + extra)
    return GeneratedProblem(
        statement=_statement(
            f"A rectangle is {extra} cm longer than it is wide. "
            f"Its area is {area} cm². Find its width in cm."
        ),
        prompt_expression=None,
        answer=str(width),
        form_constraints=(),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(),
        label="Width (cm):",
    )


QUADRATICS_TEMPLATES: tuple[TemplateSpec, ...] = (
    TemplateSpec(TemplateId("quad.expand.binomial.v1"), SkillId("quad.expand.binomial"), -1.0, expand_binomial),
    TemplateSpec(TemplateId("quad.expand.square.v1"), SkillId("quad.expand.square"), -0.5, expand_square),
    TemplateSpec(TemplateId("quad.factor.common.v1"), SkillId("quad.factor.common"), -0.5, factor_common),
    TemplateSpec(TemplateId("quad.factor.monic.v1"), SkillId("quad.factor.monic"), 0.0, factor_monic),
    TemplateSpec(TemplateId("quad.factor.diffsquares.v1"), SkillId("quad.factor.diffsquares"), 0.0, factor_difference_of_squares),
    TemplateSpec(TemplateId("quad.factor.nonmonic.v1"), SkillId("quad.factor.nonmonic"), 1.0, factor_nonmonic),
    TemplateSpec(TemplateId("quad.solve.factoring.v1"), SkillId("quad.solve.factoring"), 0.5, solve_by_factoring),
    TemplateSpec(TemplateId("quad.completesquare.v1"), SkillId("quad.completesquare"), 1.0, complete_the_square),
    TemplateSpec(TemplateId("quad.formula.apply.v1"), SkillId("quad.formula.apply"), 1.0, apply_quadratic_formula),
    TemplateSpec(TemplateId("quad.discriminant.v1"), SkillId("quad.discriminant"), 0.5, count_real_roots),
    TemplateSpec(TemplateId("quad.vertex.v1"), SkillId("quad.vertex"), 0.5, vertex_x_coordinate),
    TemplateSpec(TemplateId("quad.word.area.v1"), SkillId("quad.word.area"), 1.5, rectangle_area_word_problem),
)
