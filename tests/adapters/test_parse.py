import time

import pytest
import sympy as sp

from learnai.adapters.cas.parse import ParseError, evaluated, parse_math, write_math

x, y = sp.symbols("x y")


def test_implicit_multiplication_is_accepted():
    assert parse_math("2x") == 2 * x


def test_adjacent_letters_are_separate_variables():
    assert parse_math("2xy") == 2 * x * y


def test_a_known_name_is_found_inside_a_letter_run():
    assert parse_math("xsin(x)") == x * sp.sin(x)


def test_caret_means_exponentiation():
    assert parse_math("x^2") == x**2


def test_allowed_function_resolves():
    assert parse_math("sqrt(8)") == sp.sqrt(8)


def test_equation_is_parsed_when_permitted():
    parsed = parse_math("2x = 10", allow_equation=True)
    assert isinstance(parsed, sp.Eq)
    assert parsed.lhs == 2 * x and parsed.rhs == 10


def test_a_trivially_true_equation_stays_an_equation():
    """Eq(x, x) would otherwise collapse to True and break every caller expecting an Eq."""
    assert isinstance(parse_math("x = x", allow_equation=True), sp.Eq)


def test_equation_is_rejected_when_not_permitted():
    with pytest.raises(ParseError):
        parse_math("2x = 10")


def test_the_written_form_is_kept_on_request():
    """Form constraints judge what the student wrote, not what SymPy normalises it to."""
    written = parse_math("4(x+2)", as_written=True)
    assert written != 4 * x + 8
    assert evaluated(written) == 4 * x + 8
    assert parse_math("4(x+2)") == 4 * x + 8


@pytest.mark.parametrize(
    "hostile",
    [
        "__import__('os').system('echo pwned')",
        "().__class__.__bases__",
        "lambda: 1",
        "eval('1+1')",
        "open('/etc/passwd')",
        "pi.func",
        "x[0]",
        "x; y",
        "x()",
        "2(())",
    ],
)
def test_hostile_input_is_rejected(hostile):
    with pytest.raises(ParseError):
        parse_math(hostile)


@pytest.mark.parametrize("name", ["print(x)", "vars(x)", "exit(x)", "Symbol(x)", "lambda(x)"])
def test_names_never_reach_python(name):
    """Letters outside the known names become variables, so no builtin is ever called."""
    parsed = parse_math(name)
    assert isinstance(parsed, sp.Expr)
    assert parsed.free_symbols <= set(sp.symbols("a b c d e i l m n o p r s t v x y S"))


@pytest.mark.parametrize("tower", ["9^9^9", "2^(10^10)", "((x+1)^100)^100", "x^(99*99*99)"])
def test_power_towers_are_refused_before_evaluation(tower):
    started = time.monotonic()
    with pytest.raises(ParseError):
        parse_math(tower)
    assert time.monotonic() - started < 1.0


def test_ordinary_powers_of_powers_are_accepted():
    assert parse_math("(x^2)^3") == x**6


@pytest.mark.parametrize("ambiguous", ["2 3", "1 1/2", "0.5 2"])
def test_a_space_between_numbers_is_refused_not_guessed(ambiguous):
    """23 or 2*3? A mixed number, or 1 times 1/2? Guessing marks someone wrong."""
    with pytest.raises(ParseError):
        parse_math(ambiguous)


def test_a_space_before_a_letter_is_still_multiplication():
    assert parse_math("2 x") == 2 * x


def test_typed_decimals_stay_visible_to_form_checks():
    """Equivalence reads 0.5 exactly; a form constraint must still see a decimal was typed."""
    assert parse_math("0.5").atoms(sp.Float)


def test_overlong_input_is_rejected():
    with pytest.raises(ParseError):
        parse_math("x+" * 2000 + "1")


def test_unparseable_input_raises_parse_error():
    with pytest.raises(ParseError):
        parse_math("x +* 2")


WRITTEN = [
    (x**2 - 5 * x + 4, "x^2 - 5x + 4"),
    (sp.factor(x**2 - 5 * x + 4), "(x - 4)(x - 1)"),
    (sp.factor(4 * x + 14), "2(2x + 7)"),
    (sp.factor(30 * x**2 - 25 * x), "5x(6x - 5)"),
    ((x + 3) ** 2 - 4, "(x + 3)^2 - 4"),
    (-3 + sp.sqrt(5), "-3 + sqrt(5)"),
    (sp.pi * (x + 1), "pi*(x + 1)"),  # a name keeps its star: "pi(" would read as a call
]


@pytest.mark.parametrize(("expr", "text"), WRITTEN)
def test_maths_is_written_the_way_students_type_it(expr, text):
    assert write_math(expr) == text


@pytest.mark.parametrize(("expr", "text"), WRITTEN)
def test_written_maths_reads_back_to_the_same_tree(expr, text):
    """Form included: a key written for students still passes its own form constraint."""
    assert parse_math(write_math(expr), as_written=True) == parse_math(sp.sstr(expr), as_written=True)


def test_an_equation_is_written_with_an_equals_sign():
    assert write_math(sp.Eq(x**2 + x - 42, 0)) == "x^2 + x - 42 = 0"
