# tests/adapters/test_sympy_verifier.py
import pytest

from learnai.adapters.cas.sympy_verifier import SympyVerifier
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
from learnai.domain.items import AnswerSpec, FormConstraint, Submission, SubmissionShapeError

V = SympyVerifier()


def verdict(answer: str | Submission, spec: AnswerSpec) -> Verdict:
    submission = answer if isinstance(answer, Submission) else Submission.of(answer)
    return V.check_answer(submission, spec).verdict


def test_equivalent_answer_in_any_representation_is_correct():
    spec = AnswerSpec("1/2")
    for submitted in ("1/2", "0.5", "2/4"):
        assert verdict(submitted, spec) is Verdict.CORRECT


def test_wrong_answer_is_wrong():
    assert verdict("x + 3", AnswerSpec("x + 1")) is Verdict.WRONG


def test_unparseable_answer_is_malformed_not_wrong():
    assert verdict("x +* 2", AnswerSpec("x + 1")) is Verdict.MALFORMED


def test_a_blank_submission_is_no_answer():
    assert verdict("  ", AnswerSpec("x + 1")) is Verdict.NO_ANSWER


def test_naming_the_value_found_is_accepted():
    """A student asked for the vertex's x-coordinate writes "x = -3"."""
    assert verdict("x = -3", AnswerSpec("-3")) is Verdict.CORRECT


def test_an_equation_in_a_value_field_is_not_mistaken_for_a_named_value():
    assert verdict("x = x + 1", AnswerSpec("1")) is Verdict.MALFORMED


# -- form constraints judge what was written, not what SymPy normalises it to --


@pytest.mark.parametrize("written", ["(x+1)(x+2)", "4(x+2)", "2(x+1)(x+2)", "x^2 + 1", "-(x-1)(x+3)"])
def test_fully_factored_accepts_complete_factorisations(written):
    from learnai.adapters.cas.parse import parse_math

    key = AnswerSpec(str(parse_math(written)), (FULLY_FACTORED,))
    assert verdict(written, key) is Verdict.CORRECT


@pytest.mark.parametrize("written", ["x^2 + 3x + 2", "(2x+2)(x+2)", "(x^2 - 1)(x + 3)", "4x + 8"])
def test_fully_factored_rejects_what_can_still_be_factored(written):
    from learnai.adapters.cas.parse import parse_math

    key = AnswerSpec(str(parse_math(written)), (FULLY_FACTORED,))
    result = V.check_answer(Submission.of(written), key)
    assert result.verdict is Verdict.WRONG
    assert result.failed_constraints == (FULLY_FACTORED,)


def test_expanded_form_is_required_when_the_constraint_says_so():
    spec = AnswerSpec("x^2 + 3*x + 2", (EXPANDED,))
    assert verdict("x^2 + 3x + 2", spec) is Verdict.CORRECT
    assert verdict("(x+1)(x+2)", spec) is Verdict.WRONG
    assert verdict("x^2 + 2x + x + 2", spec) is Verdict.WRONG, "like terms must be combined"


def test_the_question_typed_back_is_not_expanded():
    """Evaluation would distribute 2(x+1) into 2x + 2; the student wrote no expansion."""
    assert verdict("2(x+1)", AnswerSpec("2*x + 2", (EXPANDED,))) is Verdict.WRONG


def test_completed_square_form_is_required_when_the_constraint_says_so():
    spec = AnswerSpec("(x + 3)**2 - 4", (COMPLETED_SQUARE,))
    assert verdict("(x+3)^2 - 4", spec) is Verdict.CORRECT

    result = V.check_answer(Submission.of("x^2 + 6x + 5"), spec)
    assert result.verdict is Verdict.WRONG
    assert result.failed_constraints == (COMPLETED_SQUARE,)


def test_a_product_of_two_brackets_is_not_a_completed_square():
    spec = AnswerSpec("(x + 3)**2 - 4", (COMPLETED_SQUARE,))
    assert verdict("(x+3)(x+3) - 4", spec) is Verdict.WRONG


def test_exact_form_rejects_a_decimal_for_an_exact_value():
    result = V.check_answer(Submission.of("0.5"), AnswerSpec("1/2", (EXACT_NOT_DECIMAL,)))
    assert result.verdict is Verdict.WRONG
    assert result.failed_constraints == (EXACT_NOT_DECIMAL,)


# -- answer kinds ---------------------------------------------------------------


def test_value_list_answers_ignore_order():
    spec = AnswerSpec("-1, 2", kind=AnswerKind.VALUE_SET)
    assert verdict(Submission.of("2", "-1"), spec) is Verdict.CORRECT
    assert verdict(Submission.of("-1"), spec) is Verdict.WRONG


def test_value_list_fields_may_name_their_values_and_leave_a_spare_blank():
    spec = AnswerSpec("2, -3", kind=AnswerKind.VALUE_SET)
    assert verdict(Submission.of("x = 2", "x = -3", ""), spec) is Verdict.CORRECT


def test_plus_minus_in_a_value_field_stands_for_both_values():
    spec = AnswerSpec("3, -3", kind=AnswerKind.VALUE_SET)
    assert verdict(Submission.of("±3"), spec) is Verdict.CORRECT
    assert verdict(Submission.of("x = ±3"), spec) is Verdict.CORRECT


def test_a_repeated_root_counts_once():
    spec = AnswerSpec("3", kind=AnswerKind.VALUE_SET)
    assert verdict(Submission.of("3", "3"), spec) is Verdict.CORRECT


def test_claiming_there_are_no_values_is_an_answer():
    assert verdict(Submission.none(), AnswerSpec("", kind=AnswerKind.VALUE_SET)) is Verdict.CORRECT
    assert verdict(Submission.none(), AnswerSpec("2", kind=AnswerKind.VALUE_SET)) is Verdict.WRONG


def test_value_list_constraints_apply_to_every_value():
    spec = AnswerSpec("1 + sqrt(2), 1 - sqrt(2)", (EXACT_NOT_DECIMAL,), kind=AnswerKind.VALUE_SET)
    assert verdict(Submission.of("1 - sqrt(2)", "1 + sqrt(2)"), spec) is Verdict.CORRECT
    assert verdict(Submission.of("2.414213", "-0.414213"), spec) is Verdict.WRONG


def test_equation_answers_compare_solution_sets():
    spec = AnswerSpec("x = 5", kind=AnswerKind.RELATION)
    assert verdict("2x = 10", spec) is Verdict.CORRECT
    assert verdict("x = 8", spec) is Verdict.WRONG
    assert verdict("5", spec) is Verdict.MALFORMED


def test_a_submission_of_the_wrong_shape_is_a_client_bug():
    with pytest.raises(SubmissionShapeError):
        V.check_answer(Submission.of("1", "2"), AnswerSpec("x + 1"))


def test_an_unsupported_answer_kind_raises_rather_than_guessing():
    """A kind this verifier cannot compare must never fall through to expressions.

    Every member is handled today, so the guard is exercised by passing a value
    the type system forbids — which is exactly the state a newly added member
    is in before someone writes its branch.
    """
    spec = AnswerSpec("x + 1", kind="ordered_sequence")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAnswerKindError):
        V.check_answer(Submission.of("x + 1"), spec)


# -- content errors are raised, never graded as the student's mistake -----------


def test_the_verifier_declares_the_vocabulary_it_can_judge():
    assert V.supported_constraints == MATH_CONSTRAINTS


def test_an_unknown_constraint_fails_loudly_even_when_the_answer_is_wrong():
    spec = AnswerSpec("x + 1", (FormConstraint("balanced_equation"),))
    with pytest.raises(UnknownConstraintError):
        V.check_answer(Submission.of("x + 9"), spec)


def test_an_answer_key_that_does_not_parse_is_a_content_error():
    with pytest.raises(InvalidAnswerKeyError):
        V.check_answer(Submission.of("x + 1"), AnswerSpec("x +* 1"))


def test_the_key_submission_is_what_a_student_would_enter():
    assert V.key_submission(AnswerSpec("-1, 2", kind=AnswerKind.VALUE_SET)) == Submission.of("-1", "2")
    assert V.key_submission(AnswerSpec("", kind=AnswerKind.VALUE_SET)) == Submission.none()
    assert V.key_submission(AnswerSpec("x + 1")) == Submission.of("x + 1")


# -- what the leak guard sees ----------------------------------------------------


@pytest.mark.parametrize(
    "prose,expected",
    [
        ("Try rewriting it as (x+1)(x+2) and see.", "(x+1)(x+2)"),
        ("So the roots are x = 2 and x = 3.", "3"),
        ("It factors as x² + 3x + 2 = (x + 1)(x + 2).", "(x + 1)(x + 2)"),
        ("It factors as x² + 3x + 2 = (x + 1)(x + 2).", "x^2 + 3x + 2"),
        ("The roots are 2, 3.", "2"),
        ("Inline maths like $(x+1)(x+2)$ is read too.", "(x+1)(x+2)"),
        ("Take √2 as given.", "sqrt(2)"),
    ],
)
def test_extracts_candidate_expressions_from_prose(prose, expected):
    assert expected in V.extract_candidate_expressions(prose)


def test_prose_words_are_never_candidates():
    assert V.extract_candidate_expressions("Take your time and read the question.") == ()


def test_a_leak_is_what_would_be_marked_correct():
    spec = AnswerSpec("(x + 1)*(x + 2)", (FULLY_FACTORED,))
    assert V.matches_answer("(x+2)(x+1)", spec)
    assert not V.matches_answer("x^2 + 3x + 2", spec), "quoting the question is not a leak"
    assert not V.matches_answer("x + 7", spec)


def test_revealing_any_one_root_is_a_leak():
    spec = AnswerSpec("2, 3", kind=AnswerKind.VALUE_SET)
    assert V.matches_answer("2", spec)
    assert V.matches_answer("x = 3", spec)
    assert not V.matches_answer("6", spec)


def test_an_equivalent_equation_leaks_a_relation():
    spec = AnswerSpec("x = 5", kind=AnswerKind.RELATION)
    assert V.matches_answer("2x = 10", spec)
    assert not V.matches_answer("x = 6", spec)
