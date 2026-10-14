# src/learnai/domain/enums.py
from enum import Enum, IntEnum


class PrereqStrength(Enum):
    HARD = "hard"
    SOFT = "soft"


class ConceptKind(Enum):
    """Subject-neutral taxonomy of declarative knowledge.

    A history CLAIM is a cause, a maths CLAIM is a theorem; a chemistry RULE is
    a law, a maths RULE is a formula. Naming the general shape keeps the core
    usable for subjects that have no theorems.
    """

    DEFINITION = "definition"
    CLAIM = "claim"
    RULE = "rule"
    PROCEDURE = "procedure"
    FACT = "fact"


class AnswerKind(Enum):
    """How an answer is compared. Subject-neutral by construction.

    RELATION covers a maths equation and a balanced chemical equation alike:
    both are judged by what they assert, not by their surface form.
    """

    SINGLE_VALUE = "single_value"
    RELATION = "relation"
    VALUE_SET = "value_set"
    """An unordered collection, compared as a set."""


class HelpRung(IntEnum):
    """Ordered: comparison operators express the ladder."""

    NONE = 0
    NUDGE = 1
    NEXT_STEP = 2
    NAME_METHOD = 3
    FULL_REVEAL = 4


class EvidenceClass(Enum):
    UNASSISTED_COLD = "unassisted_cold"
    TIMED_EXAM = "timed_exam"
    POST_INSTRUCTION = "post_instruction"
    ASSISTED = "assisted"


class Confidence(IntEnum):
    NO_IDEA = 0
    """Declined to answer. Distinct from guessing, which submits something."""

    GUESSING = 1
    UNSURE = 2
    FAIRLY_SURE = 3
    CERTAIN = 4


class VettingLevel(IntEnum):
    LLM_ONLY = 0
    HUMAN_REVIEWED = 1
    MACHINE_VERIFIED = 2
    """The answer key is derived by code, not written by a human or a model."""


class ProvenanceKind(Enum):
    """Where an item came from.

    Closed on purpose: each new source changes how far an answer key can be
    trusted, so adding one should be a decision rather than a new string. The
    spec anticipates an LLM_BATCH member; it arrives with batch generation.
    """

    GENERATED = "generated"
    """From a template and a seed; the pair reproduces the item exactly."""

    AUTHORED = "authored"


class InterventionTiming(Enum):
    LET_RUN = "let_run"
    IMMEDIATE = "immediate"
    BY_ERROR_TYPE = "by_error_type"
    NEVER = "never"


class RevealPrice(Enum):
    NONE = "none"
    SELF_EXPLAIN = "self_explain"
    FRESH_VARIANT_COLD = "fresh_variant_cold"


class Verdict(Enum):
    CORRECT = "correct"
    WRONG = "wrong"
    MALFORMED = "malformed"
    NO_ANSWER = "no_answer"
    """The student declined. Same competence signal as wrong, different pedagogy."""
