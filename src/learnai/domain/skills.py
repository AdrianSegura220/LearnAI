# src/learnai/domain/skills.py
from dataclasses import dataclass

from learnai.domain.enums import ConceptKind, PrereqStrength
from learnai.domain.ids import ConceptId, MisconceptionId, SkillId, VerificationKind


@dataclass(frozen=True, slots=True)
class Concept:
    """Declarative knowledge, shared by every skill that needs it.

    Deliberately not owned by one skill. The Nyquist-Shannon theorem serves
    sampling-rate calculation, aliasing identification, reconstruction and
    filter choice; giving it a single owner would mean duplicating it per skill,
    and duplicating a concept duplicates its *memory state* — the student would
    rehearse one theorem on four independent schedules and be told they had
    forgotten something they demonstrably know. `Skill.concept_ids` carries the
    relationship, many-to-many.
    """

    id: ConceptId
    subject_id: str
    kind: ConceptKind
    prompt: str
    answer: str
    introduced_by: SkillId | None = None
    """Where a Learn session should first teach it. An ordering hint, not
    ownership. Unused until Slice 3."""


@dataclass(frozen=True, slots=True)
class Misconception:
    """A wrong belief, shared by every skill it afflicts.

    Same reasoning as Concept: `(a+b)^2 -> a^2+b^2` shows up in expanding a
    square and in completing the square. One belief, one catalogue entry, one
    rule registration, and one entry in the student's active-misconception set.
    """

    id: MisconceptionId
    subject_id: str
    name: str
    description: str
    signature: str
    """Key into the rewrite-rule registry in domain.misconceptions."""


@dataclass(frozen=True, slots=True)
class Skill:
    id: SkillId
    subject_id: str
    name: str
    can_do_statement: str
    verification_kind: VerificationKind
    concept_ids: tuple[ConceptId, ...]
    misconception_ids: tuple[MisconceptionId, ...]
    teaching_notes: str = ""
    """How to teach this skill — the tutor's cached skill-pack content.
    The loader requires it non-empty; the domain default keeps the field
    additive for direct constructions in tests."""


@dataclass(frozen=True, slots=True)
class PrereqEdge:
    from_skill: SkillId
    to_skill: SkillId
    strength: PrereqStrength
