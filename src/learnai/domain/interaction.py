"""Raw current work and deterministic findings, each bound to a work revision."""
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.ids import MisconceptionId, TaskId
from learnai.domain.items import FormConstraint, Item, StepDiff, Submission
from learnai.domain.misconceptions import MisconceptionMatcher, diagnose
from learnai.domain.skills import Misconception

if TYPE_CHECKING:
    from learnai.domain.ports import Verifier


class InteractionKind(Enum):
    SUBMISSION = "submission"
    TASK_QUESTION = "task_question"
    HELP_REQUEST = "help_request"


class WorkStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    REVISED = "revised"


class ResponseJob(Enum):
    BRIEF = "brief"
    NORMAL = "normal"
    SUBSTANTIAL = "substantial"
    COMPLEX = "complex"


@dataclass(frozen=True, slots=True)
class StudentInteraction:
    task_id: TaskId
    revision: int
    kind: InteractionKind
    status: WorkStatus
    steps: tuple[str, ...]
    answer: Submission
    question: str | None = None
    referenced_step: int | None = None

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("work revision must be nonnegative")
        if self.referenced_step is not None and not 0 <= self.referenced_step < len(self.steps):
            raise ValueError("referenced step must exist in current work")


@dataclass(frozen=True, slots=True)
class VerificationSnapshot:
    revision: int
    answer_checked: bool
    steps_checked: bool
    verdict: Verdict | None
    step_diff: StepDiff | None
    diagnosis: MisconceptionId | None
    failed_constraints: tuple[FormConstraint, ...] = ()

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("work revision must be nonnegative")
        if not self.answer_checked and self.verdict is not None:
            raise ValueError("unchecked final answer cannot have a verdict")


@dataclass(frozen=True, slots=True)
class TaskProgress:
    submissions: int
    genuine_attempts: int
    declines: int
    delivered_rungs: tuple[HelpRung, ...]
    independence_spent: bool
    last_checked_revision: int | None


def prepare_verification(
    interaction: StudentInteraction,
    *,
    item: Item,
    verifier: "Verifier",
    catalogue: Sequence[Misconception],
    matcher: MisconceptionMatcher,
    check_answer: bool,
    check_steps: bool,
) -> VerificationSnapshot:
    """Check only requested work; a bad step never grades an unchecked answer.

    Final submissions retain the established policy: check steps only for wrong,
    non-declined answers. Equivalent partial factoring can fail form constraints
    without a broken step, while still naming a misconception on its final move.
    """
    verdict: Verdict | None = None
    failed_constraints: tuple[FormConstraint, ...] = ()
    if check_answer:
        interaction.answer.check_shape(item.answer_spec.kind)
        if interaction.answer.is_blank:
            verdict = Verdict.NO_ANSWER
        else:
            result = verifier.check_answer(interaction.answer, item.answer_spec)
            verdict = result.verdict
            failed_constraints = result.failed_constraints
    steps_checked = check_steps and bool(interaction.steps)
    if check_answer and verdict is not Verdict.WRONG:
        steps_checked = False
    diff = verifier.diff_steps(interaction.steps) if steps_checked else None
    diagnosis = diagnose(diff, catalogue, matcher)
    if steps_checked and check_answer and diff is None and len(interaction.steps) >= 2:
        last = StepDiff(len(interaction.steps) - 1, interaction.steps[-2], interaction.steps[-1])
        diagnosis = diagnosis or diagnose(last, catalogue, matcher)
    return VerificationSnapshot(interaction.revision, check_answer, steps_checked,
                                verdict, diff, diagnosis, failed_constraints)
