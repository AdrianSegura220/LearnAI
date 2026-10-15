import pytest

from learnai.adapters.cas.sympy_verifier import SympyVerifier

V = SympyVerifier()


def test_correct_expression_work_has_no_diff():
    assert V.diff_steps(["(x+1)(x+2)", "x^2 + 3x + 2", "x^2 + 3x + 2"]) is None


def test_correct_equation_work_has_no_diff():
    assert V.diff_steps(["2x + 4 = 10", "2x = 6", "x = 3"]) is None


def test_arithmetic_slip_is_localised():
    diff = V.diff_steps(["2x + 4 = 10", "2x = 6", "x = 8"])
    assert diff is not None
    assert diff.index == 2
    assert diff.previous == "2x = 6"
    assert diff.current == "x = 8"
    assert not diff.unreadable


def test_the_first_break_is_reported_not_the_last():
    diff = V.diff_steps(["x + 1 = 5", "x = 9", "x = 100"])
    assert diff is not None and diff.index == 1


def test_expansion_error_is_localised():
    diff = V.diff_steps(["(x+3)^2", "x^2 + 9"])
    assert diff is not None and diff.index == 1


def test_switching_between_expression_and_equation_breaks():
    diff = V.diff_steps(["2x = 6", "2x"])
    assert diff is not None and diff.index == 1


def test_a_single_step_can_never_break():
    assert V.diff_steps(["x = 3"]) is None


@pytest.mark.parametrize(
    "steps",
    [
        ["x^2 - 4x + 3 = 0", "(x-1)(x-3) = 0", "x = 1, x = 3"],
        ["(x-1)(x-3) = 0", "x - 1 = 0 or x - 3 = 0"],
        ["(x-1)(x-3) = 0", "x = 1 or 3"],
        ["x^2 = 9", "x = ±3"],
        ["x^2 = 9", "x = +/-3"],
        ["x^2 + 5x + 3 = 0", "x = (-5 ± sqrt(13))/2"],
        ["x^2 + 6x + 5", "= x^2 + 6x + 9 - 4", "= (x + 3)^2 - 4"],
    ],
)
def test_correct_work_in_the_notations_students_use_has_no_diff(steps):
    assert V.diff_steps(steps) is None


def test_a_lost_root_is_caught():
    diff = V.diff_steps(["(x-1)(x-3) = 0", "x = 1"])
    assert diff is not None and diff.index == 1 and not diff.unreadable


def test_a_plus_minus_with_the_wrong_value_is_caught():
    diff = V.diff_steps(["x^2 = 9", "x = ±9"])
    assert diff is not None and diff.index == 1


def test_an_unparseable_step_is_reported_as_unreadable_not_wrong():
    diff = V.diff_steps(["2x = 6", "x =* 3"])
    assert diff is not None and diff.index == 1 and diff.unreadable


def test_an_unreadable_first_step_is_reported_at_its_own_index():
    diff = V.diff_steps(["x =* 3", "x = 3"])
    assert diff is not None and diff.index == 0 and diff.unreadable
    assert diff.previous == ""


def test_a_decimal_comma_is_never_read_as_two_values():
    diff = V.diff_steps(["2x = 1", "x = 0,5"])
    assert diff is not None and diff.unreadable


def test_a_chain_of_equals_signs_is_unreadable_for_now():
    diff = V.diff_steps(["(x+1)(x+2)", "(x+1)(x+2) = x^2 + 2x + x + 2 = x^2 + 3x + 2"])
    assert diff is not None and diff.unreadable


def test_a_solver_crash_does_not_escape_the_boundary(monkeypatch):
    # No parse-valid input deterministically crashes the solver, so inject the fault.
    def boom(*args, **kwargs):
        raise OverflowError("solver exploded")

    monkeypatch.setattr("learnai.adapters.cas.sympy_verifier.real_solutions", boom)

    diff = V.diff_steps(["x^2 = 9", "x = ±3"])
    assert diff is not None and diff.index == 1 and diff.unreadable
    assert diff.previous == "x^2 = 9" and diff.current == "x = ±3"
