"""The one entry point for untrusted mathematical text.

SymPy's parser ends in Python's `eval`, so safety here is by construction, not
by blocklist: only a small alphabet is admitted, every name is resolved before
SymPy sees it, and powers are bounded before anything is evaluated.
"""
import re
import warnings

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

MAX_INPUT_LENGTH = 512

MAX_EXPONENT_LOAD = 1000
"""Largest combined power along any chain of nested powers: (x^2)^3 carries 6.

Bounds the size of anything later evaluated or expanded. Without it "9^9^9",
five characters, evaluates for longer than any request may take.
"""

_ALLOWED = re.compile(r"[0-9A-Za-z\s.+\-*/^()=]*")
_DOT_NOT_BEFORE_DIGIT = re.compile(r"\.(?!\d)")
_NUMBER_SPACE_NUMBER = re.compile(r"[\d.]\s+[\d.]")
_LETTER_RUN = re.compile(r"[A-Za-z]+")
_TIMES_BEFORE_LETTER_OR_BRACKET = re.compile(r"(?<=[0-9)])\*(?=[A-Za-z(])")
_LETTER_TIMES_BRACKET = re.compile(r"(?<![A-Za-z])([A-Za-z])\*\(")

_FUNCTIONS = {
    "sqrt": sp.sqrt, "abs": sp.Abs, "exp": sp.exp, "log": sp.log, "ln": sp.log,
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
}
_CONSTANTS = {"pi": sp.pi}
_KNOWN = sorted(_FUNCTIONS.keys() | _CONSTANTS.keys(), key=len, reverse=True)

KNOWN_NAMES: frozenset[str] = frozenset(_KNOWN)
"""Every multi-letter name the parser reads as maths rather than as single-letter variables."""

_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)

# What SymPy's generated code may reference besides the per-call names. The
# explicit empty __builtins__ stops eval from inserting the real ones.
_GLOBALS = {
    "__builtins__": {},
    "Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational,
    "Add": sp.Add, "Mul": sp.Mul, "Pow": sp.Pow,
}


class ParseError(ValueError):
    """Raised when input is unsafe, malformed, or not permitted in this position."""


def parse_math(text: str, *, allow_equation: bool = False, as_written: bool = False) -> sp.Basic:
    """Parse untrusted mathematical text. Never call SymPy's parser directly elsewhere.

    Returns the evaluated form by default, which is what equivalence needs.
    `as_written=True` returns the tree exactly as typed, which is what form
    constraints and hole-respecting equation checks need.
    """
    stripped = text.strip()
    if not stripped:
        raise ParseError("empty input")
    if len(stripped) > MAX_INPUT_LENGTH:
        raise ParseError("input too long")
    if not _ALLOWED.fullmatch(stripped):
        raise ParseError("input contains a character outside the maths alphabet")
    if _DOT_NOT_BEFORE_DIGIT.search(stripped):
        raise ParseError("a dot may only appear inside a decimal number")
    # Refuse rather than guess: "2 3" may be 23 or 2*3, and "1 1/2" is a mixed
    # number that implicit multiplication would read as 1/2. A structured maths
    # editor removes the ambiguity at the source (spec D1).
    if _NUMBER_SPACE_NUMBER.search(stripped):
        raise ParseError("a space between two numbers is ambiguous")

    if "=" in stripped:
        if not allow_equation:
            raise ParseError("an equation is not permitted in this position")
        lhs, _, rhs = stripped.partition("=")
        if "=" in rhs:
            raise ParseError("more than one equals sign")
        written: sp.Basic = sp.Eq(_parse_side(lhs), _parse_side(rhs), evaluate=False)
    else:
        written = _parse_side(stripped)
    if as_written:
        return written
    try:
        return evaluated(written)
    except Exception as exc:  # anything SymPy raises here is still bad input
        raise ParseError(f"could not evaluate {text!r}") from exc


def evaluated(expr: sp.Basic, *, exact_decimals: bool = False) -> sp.Basic:
    """The evaluated form of a written expression, rebuilt bottom-up.

    Evaluation normalises, and in doing so forgets: it distributes 4(x+2) into
    4x + 8, and cancels (x-1)^2/(x-1) to x - 1, erasing the hole at 1.

    `exact_decimals` reads each typed decimal as the exact number it denotes —
    0.1 is one tenth, not the nearest binary fraction — before any arithmetic,
    so 0.1 + 0.2 is exactly 0.3. Parsing keeps decimals as SymPy Floats so that
    form checks can still see that a decimal was typed; equivalence asks for
    exact values.
    """
    if isinstance(expr, sp.Float):
        return sp.Rational(str(expr)) if exact_decimals else expr
    if isinstance(expr, sp.Eq):
        return sp.Eq(
            evaluated(expr.lhs, exact_decimals=exact_decimals),
            evaluated(expr.rhs, exact_decimals=exact_decimals),
            evaluate=False,
        )
    if not expr.args:
        return expr
    return expr.func(*(evaluated(arg, exact_decimals=exact_decimals) for arg in expr.args))


def write_math(expr: sp.Basic) -> str:
    """Write an expression or equation the way a student types it.

    `x^2 + 3x`, `2(2x + 7)`, `(x - 4)(x - 1)`: carets for powers, and no star
    where students leave multiplication implicit — after a number or a closing
    bracket, and between a lone letter and a bracket. A name such as pi keeps
    its star, since "pi(" would read as a call. The text reads back through
    parse_math to the same tree as SymPy's own printing, form included.
    """
    if isinstance(expr, sp.Eq):
        return f"{write_math(expr.lhs)} = {write_math(expr.rhs)}"
    text = sp.sstr(expr).replace("**", "^")
    text = _TIMES_BEFORE_LETTER_OR_BRACKET.sub("", text)
    return _LETTER_TIMES_BRACKET.sub(r"\1(", text)


def _parse_side(text: str) -> sp.Expr:
    rewritten, names = _resolve_names(text)
    try:
        with warnings.catch_warnings():
            # A deprecation raised while parsing means the input built something
            # odd — "x()" is x times an empty Tuple — so treat it as unparseable
            # rather than rely on a path SymPy has scheduled for removal.
            warnings.simplefilter("error", DeprecationWarning)
            expr = parse_expr(
                rewritten,
                local_dict=names,
                global_dict=dict(_GLOBALS),
                transformations=_TRANSFORMATIONS,
                evaluate=False,
            )
    except Exception as exc:  # SymPy raises a wide variety here
        raise ParseError(f"could not parse {text!r}") from exc
    # Every node, not just the root: "x()" parses to x times an empty Tuple.
    if not all(isinstance(node, sp.Expr) for node in sp.preorder_traversal(expr)):
        raise ParseError(f"{text!r} is not a mathematical expression")
    _exponent_load(expr)
    return expr


def _resolve_names(text: str) -> tuple[str, dict[str, object]]:
    """Rewrite each run of letters into names, and say what every name means.

    Known names match longest-first; any other letter is its own variable, so
    "xy" is x*y and "xsin(x)" is x*sin(x). Every name in the rewritten text is
    in the returned table, so SymPy never resolves one itself: a student's
    "print" is the product p*r*i*n*t, never Python's print.
    """
    table: dict[str, object] = {}

    def rewrite(match: re.Match[str]) -> str:
        run, names, i = match.group(), [], 0
        while i < len(run):
            name = next((k for k in _KNOWN if run.startswith(k, i)), run[i])
            names.append(name)
            i += len(name)
        for name in names:
            if name in _FUNCTIONS:
                table[name] = _FUNCTIONS[name]
            elif name in _CONSTANTS:
                table[name] = _CONSTANTS[name]
            else:
                table[name] = sp.Symbol(name)
        return " ".join(names)

    return _LETTER_RUN.sub(rewrite, text), table


def _exponent_load(expr: sp.Basic) -> float:
    """The combined power carried by `expr`, refusing anything over the limit.

    Children are checked before their parent, so a symbol-free exponent is
    only evaluated once every power inside it is known to be small.
    """
    loads = [_exponent_load(arg) for arg in expr.args]
    load = max(loads, default=1.0)
    if isinstance(expr, sp.Pow) and not expr.exp.free_symbols:
        magnitude = abs(evaluated(expr.exp))
        if not magnitude.is_finite or magnitude > MAX_EXPONENT_LOAD:
            raise ParseError("exponent too large")
        load = max(1.0, float(magnitude)) * loads[0]
    if load > MAX_EXPONENT_LOAD:
        raise ParseError("powers nested too deeply")
    return load
