# tests/domain/test_items.py
import pytest

from learnai.domain.enums import AnswerKind, ProvenanceKind, VettingLevel
from learnai.domain.ids import ItemId, SkillId, TemplateId
from learnai.domain.items import (
    AnswerSpec,
    FormConstraint,
    Formula,
    Item,
    Provenance,
    StepDiff,
    Submission,
    SubmissionShapeError,
    Text,
)


def test_generated_provenance_is_reproducible_from_template_and_seed():
    p = Provenance.generated(TemplateId("quad.factor.monic.v1"), seed=4242)
    assert p.kind is ProvenanceKind.GENERATED
    assert (p.template_id, p.seed) == (TemplateId("quad.factor.monic.v1"), 4242)


def test_authored_provenance_has_no_seed():
    p = Provenance.authored()
    assert p.kind is ProvenanceKind.AUTHORED
    assert p.template_id is None and p.seed is None


def test_item_is_immutable():
    item = Item(
        id=ItemId("i1"),
        skill_id=SkillId("quad.factor.monic"),
        provenance=Provenance.generated(TemplateId("t"), 1),
        statement=(Text("Factor "), Formula("x^2 + 3x + 2")),
        answer_spec=AnswerSpec(
            "(x + 1)(x + 2)", (FormConstraint("fully_factored"),), AnswerKind.SINGLE_VALUE
        ),
        worked_steps=("x^2 + 3x + 2", "(x + 1)(x + 2)"),
        difficulty=0.0,
        vetting_level=VettingLevel.MACHINE_VERIFIED,
    )
    try:
        item.difficulty = 1.0  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("Item must be frozen")


def test_prose_and_notation_are_different_blocks_even_with_the_same_characters():
    """Only the author knows where notation starts; the domain reads neither."""
    assert Formula("x^2") != Text("x^2")
    assert Formula("x^2").source == Text("x^2").text


def test_a_form_constraint_is_just_an_opaque_token():
    """The domain must not know what 'fully_factored' means — only the verifier does."""
    token = FormConstraint("anything_the_adapter_understands")
    assert AnswerSpec("x", (token,)).form_constraints == (token,)


def test_answer_kind_defaults_to_single_value():
    spec = AnswerSpec("x + 1")
    assert spec.kind is AnswerKind.SINGLE_VALUE
    assert spec.form_constraints == ()


def test_step_diff_records_the_first_broken_transition():
    d = StepDiff(index=2, previous="2*x = 10", current="x = 8")
    assert d.index == 2
    assert not d.unreadable, "a step that was read and found wrong is not unreadable"


def test_a_label_is_optional_and_display_only():
    assert AnswerSpec("x + 1").label is None
    assert AnswerSpec("3", label="x =").label == "x ="


def test_a_single_value_answer_takes_exactly_one_field():
    Submission.of("x + 1").check_shape(AnswerKind.SINGLE_VALUE)
    with pytest.raises(SubmissionShapeError):
        Submission.of("1", "2").check_shape(AnswerKind.SINGLE_VALUE)
    with pytest.raises(SubmissionShapeError):
        Submission.none().check_shape(AnswerKind.RELATION)


def test_a_value_list_may_hold_any_number_of_values_or_claim_there_are_none():
    Submission.of("2", "-3").check_shape(AnswerKind.VALUE_SET)
    Submission.none().check_shape(AnswerKind.VALUE_SET)
    with pytest.raises(SubmissionShapeError):
        Submission(("2",), claims_none=True).check_shape(AnswerKind.VALUE_SET)


def test_blank_fields_are_a_decline_but_claiming_none_is_an_answer():
    assert Submission.of("  ").is_blank
    assert Submission.of("", "").is_blank
    assert not Submission.none().is_blank
    assert Submission.of("2", " ").entries == ("2",)
