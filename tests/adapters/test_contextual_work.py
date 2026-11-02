"""Contextual work checks retain the strict equation-equivalence boundary."""
import pytest

from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.domain.enums import AnswerKind, VettingLevel
from learnai.domain.items import AnswerSpec, Formula, Item, Provenance


def item(equation='2x^2 - 3x - 2 = 0', answer='-1/2, 2'):
    return Item('test', 'quad.formula.apply', Provenance.authored(),
        (Formula(equation),), AnswerSpec(answer, kind=AnswerKind.VALUE_SET), (),
        0.0, VettingLevel.HUMAN_REVIEWED)


V = SympyVerifier()


@pytest.mark.parametrize('steps,exercise', [
    (['a = 2, b = -3, c = -2', 'x = (-(-3) +/- sqrt((-3)^2 - 4*2*(-2)))/(2*2)'], item()),
    (['a = 1, b = -4, c = -5', 'b^2 - 4ac = (-4)^2 - 4(1)(-5)'], item('x^2 - 4x - 5 = 0', '-1, 5')),
    (['b^2 - 4ac = 36 - 36 = 0', 'x = (6 +/- sqrt(0))/2'], item('x^2 - 6x + 9 = 0', '3')),
    (['a = 3, b = 1, c = -2', 'x = (-1 +/- sqrt(1 - 4*3*(-2)))/(2*3)'], item('3x^2 + x - 2 = 0', '-1, 2/3')),
])
def test_valid_mixed_work_is_checked_in_its_item_context(steps, exercise):
    checked = V.check_work(steps, item=exercise, allow_partial=True)
    assert checked.step_diff is None
    assert checked.notes


@pytest.mark.parametrize('steps,index', [
    (['a = 2, b = 3, c = -2'], 0),
    (['a = 2, b = -3, c = -2', 'b^2 - 4ac = 9 - 16'], 1),
    (['a = 2, b = -3, c = -2', 'x = (-3 +/- sqrt(25))/4'], 1),
    (['b^2 - 4ac = 9 + 16 = 24'], 0),
])
def test_wrong_bindings_calculations_and_formula_claims_remain_errors(steps, index):
    checked = V.check_work(steps, item=item(), allow_partial=True)
    assert checked.step_diff is not None
    assert checked.step_diff.index == index and not checked.step_diff.unreadable


def test_draft_factor_branch_is_partial_not_a_complete_solution():
    exercise = item('x^2 - 6x + 8 = 0', '2, 4')
    steps = ['x^2 - 6x + 8 = 0', '(x - 2)(x - 4) = 0', 'x - 2 = 0']
    checked = V.check_work(steps, item=exercise, allow_partial=True)
    assert checked.step_diff is None
    assert any('branch' in note and 'remaining' in note for note in checked.notes)
    assert V.diff_steps(steps) is not None
    assert V.check_work(steps, item=exercise, allow_partial=False).step_diff is not None


def test_nonfactor_does_not_become_a_valid_branch():
    checked = V.check_work(['(x - 2)(x - 4) = 0', 'x - 3 = 0'],
                           item=item('x^2 - 6x + 8 = 0', '2, 4'), allow_partial=True)
    assert checked.step_diff is not None and not checked.step_diff.unreadable


def test_malformed_mixed_work_remains_unreadable():
    checked = V.check_work(['a = 2, b = -3, c = -2', 'x =* 2'], item=item(), allow_partial=True)
    assert checked.step_diff is not None and checked.step_diff.unreadable


def test_expression_calculation_chain_checks_every_link():
    exercise = item('(x+1)(x+2)', 'x^2+3x+2')
    correct = ['(x+1)(x+2)', '(x+1)(x+2) = x^2+2x+x+2 = x^2+3x+2']
    assert V.check_work(correct, item=exercise, allow_partial=True).step_diff is None
    incorrect = ['(x+1)(x+2)', '(x+1)(x+2) = x^2+3x+1 = x^2+3x+2']
    diff = V.check_work(incorrect, item=exercise, allow_partial=True).step_diff
    assert diff is not None and not diff.unreadable and diff.index == 1


def test_numeric_calculation_chain_checks_every_link():
    assert V.check_work(['2*3 = 6 = 3+3'], item=item(), allow_partial=True).step_diff is None
    diff = V.check_work(['2*3 = 7 = 3+3'], item=item(), allow_partial=True).step_diff
    assert diff is not None and not diff.unreadable


def test_wrong_branch_final_answer_still_fails():
    from learnai.domain.items import Submission
    from learnai.domain.enums import Verdict
    assert V.check_answer(Submission.of('2'), item('x^2 - 6x + 8 = 0', '2,4').answer_spec).verdict is Verdict.WRONG


def test_unsupported_relational_chain_is_not_called_a_math_error():
    diff = V.check_work(['x^2 = 9 = 3^2'], item=item('x^2=9','-3,3'), allow_partial=True).step_diff
    assert diff is not None and diff.unreadable


def test_coefficients_can_describe_a_valid_rearranged_equation():
    steps = ['2x^2 - 3x - 2 = 0', 'x^2 - 1.5x - 1 = 0',
             'a = 1, b = -1.5, c = -1', 'b^2 - 4ac = 2.25 + 4 = 6.25',
             'x = (1.5 +/- sqrt(6.25))/2']
    assert V.check_work(steps, item=item(), allow_partial=True).step_diff is None


@pytest.mark.parametrize('equation,coefficients', [
    ('x^2 - 1.5x - 1 = 0', 'a = 1, b = 1.5, c = -1'),
    ('x^2 - 7x - 1 = 0', 'a = 1, b = -7, c = -1'),
])
def test_wrong_or_unrelated_equation_cannot_supply_trusted_coefficients(equation, coefficients):
    diff = V.check_work([equation, coefficients], item=item(), allow_partial=True).step_diff
    assert diff is not None and not diff.unreadable


@pytest.mark.parametrize('continuation,valid', [('x = 2', True), ('x = -2', False)])
def test_local_branch_continuation_keeps_its_scope(continuation, valid):
    checked = V.check_work(['(x - 2)(x - 4) = 0', 'x - 2 = 0', continuation],
                           item=item('x^2 - 6x + 8 = 0', '2,4'), allow_partial=True)
    assert (checked.step_diff is None) is valid
    assert any('remaining' in note for note in checked.notes)


def test_numeric_equality_after_coefficients_is_a_calculation():
    checked = V.check_work(['a=2, b=-3, c=-2', '(-3)^2=9'], item=item(), allow_partial=True)
    assert checked.step_diff is None and checked.notes
    wrong = V.check_work(['a=2, b=-3, c=-2', '(-3)^2=-9'], item=item(), allow_partial=True)
    assert wrong.step_diff is not None and not wrong.step_diff.unreadable


def test_unsupported_ancillary_definition_is_not_an_invented_math_error():
    diff = V.check_work(['b^2-4ac=25', 'D=25'], item=item(), allow_partial=True).step_diff
    assert diff is not None and diff.unreadable


def test_coefficient_substitution_preserves_undefined_denominators():
    steps = ['a=2,b=-3,c=-2',
             'x = ((-b +/- sqrt(b^2-4ac))/(2a))*(x-2)/(x-2)']
    diff = V.check_work(steps, item=item(), allow_partial=False).step_diff
    assert diff is not None and not diff.unreadable
