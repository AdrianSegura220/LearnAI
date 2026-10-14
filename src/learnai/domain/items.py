# src/learnai/domain/items.py
from dataclasses import dataclass
from typing import NewType

from learnai.domain.enums import AnswerKind, ProvenanceKind, VettingLevel
from learnai.domain.ids import ItemId, SkillId, TemplateId

FormConstraint = NewType("FormConstraint", str)
"""A required form for an answer, e.g. "fully_factored".

Deliberately opaque: the domain knows an answer may carry form requirements and
that the Verifier judges them, but never what any particular one means. Each
subject adapter owns its own vocabulary and declares it via
`Verifier.supported_constraints`, so adding physics or chemistry never edits
the core. See spec §6.2.
"""


@dataclass(frozen=True, slots=True)
class AnswerSpec:
    expression: str
    """The answer key, in the Verifier adapter's own format."""

    form_constraints: tuple[FormConstraint, ...] = ()
    kind: AnswerKind = AnswerKind.SINGLE_VALUE
    """How the verifier compares a submission with `expression`; see AnswerKind."""

    label: str | None = None
    """What the answer field is labelled with — "x =", "Width (cm):". Display
    only: grading never reads it. Written in the item's language, like its
    statement. None when the field holds the transformed expression itself."""


MULTI_FIELD_KINDS = frozenset({AnswerKind.VALUE_SET})
"""Kinds answered with any number of fields. Every other kind takes exactly one."""


class SubmissionShapeError(ValueError):
    """A submission cannot be an answer of the item's kind.

    Always a client bug — the input widget follows the kind — never a student
    error, so it is raised rather than graded.
    """


@dataclass(frozen=True, slots=True)
class Submission:
    """What the student entered: one string per answer field.

    The domain owns the shape, which the item's AnswerKind decides — one field,
    or a list of values that may be empty. It never interprets a field: whether
    one holds "(x+1)(x+2)" or "the Treaty of Versailles" is the Verifier
    adapter's to judge, exactly as with form constraints.
    """

    fields: tuple[str, ...]
    claims_none: bool = False
    """The student asserts there are no values — "no real solutions", "none of
    these". That is an answer; leaving every field blank is a decline."""

    @classmethod
    def of(cls, *fields: str) -> "Submission":
        return cls(fields)

    @classmethod
    def none(cls) -> "Submission":
        return cls((), claims_none=True)

    @property
    def is_blank(self) -> bool:
        """A decline: nothing entered and nothing claimed."""
        return not self.claims_none and all(not f.strip() for f in self.fields)

    @property
    def entries(self) -> tuple[str, ...]:
        """The fields that hold something. A value list's spare blank field is not an answer."""
        return tuple(f for f in self.fields if f.strip())

    def check_shape(self, kind: AnswerKind) -> None:
        if kind in MULTI_FIELD_KINDS:
            if self.claims_none and self.entries:
                raise SubmissionShapeError("claims there are no values, but lists some")
            return
        if self.claims_none or len(self.fields) != 1:
            raise SubmissionShapeError(f"a {kind.value} answer takes exactly one field")


@dataclass(frozen=True, slots=True)
class Provenance:
    kind: ProvenanceKind
    template_id: TemplateId | None = None
    seed: int | None = None

    @classmethod
    def generated(cls, template_id: TemplateId, seed: int) -> "Provenance":
        return cls(kind=ProvenanceKind.GENERATED, template_id=template_id, seed=seed)

    @classmethod
    def authored(cls) -> "Provenance":
        return cls(kind=ProvenanceKind.AUTHORED)


@dataclass(frozen=True, slots=True)
class Text:
    """Prose, in the item's language. Never holds notation: that is a Formula."""

    text: str


@dataclass(frozen=True, slots=True)
class Formula:
    """Notation the item's verifier reads: "x^2 + 3x + 2", later "H2O".

    Written exactly as a student types it, so what a student is shown is what
    they can enter (spec P7). Opaque to the domain, like a form constraint:
    rendering it — KaTeX, for the CAS adapter — is an adapter's job.
    """

    source: str


Block = Text | Formula
"""One piece of an item's statement. A Media block joins later (spec D19)."""


@dataclass(frozen=True, slots=True)
class Item:
    id: ItemId
    skill_id: SkillId
    provenance: Provenance
    statement: tuple[Block, ...]
    """Text and Formula blocks, in reading order."""
    answer_spec: AnswerSpec
    worked_steps: tuple[str, ...]
    difficulty: float
    vetting_level: VettingLevel


@dataclass(frozen=True, slots=True)
class StepDiff:
    """The first step in the student's work that does not follow from the one before.

    `steps[index - 1] -> steps[index]` is the transition; index 0 occurs only
    for an unreadable first step, whose `previous` is empty.
    """

    index: int
    previous: str
    current: str
    unreadable: bool = False
    """The step could not be read at all, so the problem is notation, not
    necessarily reasoning: the tutor should ask what the student meant rather
    than say the line is wrong (P7)."""
