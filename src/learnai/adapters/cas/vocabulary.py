# src/learnai/adapters/cas/vocabulary.py
"""Everything this adapter names that the domain treats as opaque.

The core knows a skill has a verification kind and that an answer may carry
form requirements; it never knows what "cas_symbolic" or "fully_factored"
mean. This module is the only place the mathematical vocabulary is named, and
`sympy_verifier._satisfies` is the only place it is interpreted.

Answer keys use this adapter's format: a value in the parser's syntax, an
equation for a RELATION, and for a VALUE_SET the values separated by commas,
with an empty key meaning there are none.
"""
from learnai.domain.ids import VerificationKind
from learnai.domain.items import FormConstraint

CAS_SYMBOLIC = VerificationKind("cas_symbolic")

FULLY_FACTORED = FormConstraint("fully_factored")
EXPANDED = FormConstraint("expanded")
EXACT_NOT_DECIMAL = FormConstraint("exact_not_decimal")
"""Written without a decimal point. Decimals compare exactly (Task 4), so a
rounded answer is already wrong by value: this rejects only a right answer
written as a decimal, such as 0.25 for 1/4. It belongs on items that ask for a
fraction or a surd, never on "give an exact value", which 0.25 is."""
COMPLETED_SQUARE = FormConstraint("completed_square")

# No "simplified": it has no single meaning — lowest terms, rationalised
# denominators and collected terms are separate school rules, each of which
# becomes its own constraint when an item needs it.
MATH_CONSTRAINTS: frozenset[FormConstraint] = frozenset(
    {FULLY_FACTORED, EXPANDED, EXACT_NOT_DECIMAL, COMPLETED_SQUARE}
)


class UnsupportedAnswerKindError(ValueError):
    """This verifier has no comparison for that answer kind.

    Raised rather than falling back to single-value comparison: a future
    ORDERED_SEQUENCE reaching the expression branch would be compared as one
    expression and quietly return wrong verdicts.
    """


class UnknownConstraintError(KeyError):
    """An item demands a form this verifier cannot judge.

    Raised rather than ignored: silently skipping an unknown constraint would
    mark a wrongly-formed answer correct, which is worse than a loud failure.
    """


class InvalidAnswerKeyError(ValueError):
    """An item's answer key does not parse, or asks for something it cannot.

    A content error, raised so it is fixed, never graded as the student's
    MALFORMED. The generator contract tests catch it before an item ships.
    """
