# src/learnai/adapters/content/types.py
import random
from collections.abc import Callable
from dataclasses import dataclass

from learnai.domain.enums import AnswerKind
from learnai.domain.ids import SkillId, TemplateId
from learnai.domain.items import Block, FormConstraint


@dataclass(frozen=True, slots=True)
class GeneratedProblem:
    statement: tuple[Block, ...]
    prompt_expression: str | None
    """The expression the student is asked to rewrite, if any, as it appears in
    the statement. The contract tests check that typing it back is never
    accepted."""
    answer: str
    form_constraints: tuple[FormConstraint, ...]
    kind: AnswerKind
    worked_steps: tuple[str, ...]
    label: str | None = None
    """The answer field's label when the student computes a value; see AnswerSpec.label."""


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    id: TemplateId
    skill_id: SkillId
    difficulty: float
    """Author-declared, in logits, replaced by empirical values once data exists."""
    generate: Callable[[random.Random], GeneratedProblem]
