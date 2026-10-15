# src/learnai/domain/engine.py
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from learnai.domain.contracts import ModeContract
from learnai.domain.enums import (
    Confidence,
    EvidenceClass,
    HelpRung,
    InterventionTiming,
    Verdict,
)
from learnai.domain.events import AttemptRecorded, HelpTaken
from learnai.domain.evidence import classify_evidence
from learnai.domain.graph import SkillGraph
from learnai.domain.help import (
    next_rung,
    permitted_rung,
    record_attempt,
    record_help,
    record_submission,
)
from learnai.domain.ids import (
    CourseId,
    MisconceptionId,
    SessionId,
    SkillId,
    StudentId,
    VerificationKind,
)
from learnai.domain.items import StepDiff, Submission
from learnai.domain.mastery import SkillState, is_fresh
from learnai.domain.misconceptions import MisconceptionMatcher, diagnose
from learnai.domain.parameters import (
    DEFAULT_PARAMETERS,
    MasteryParameters,
    resolve_parameters,
)
from learnai.domain.planner import plan_session
from learnai.domain.ports import Clock, EvidenceLog, ItemSource, Tutor, Verifier
from learnai.domain.projection import apply_event
from learnai.domain.session import Session, Task, TaskState, advance, replace_task
from learnai.domain.verification import CheckResult
from learnai.domain.skills import Misconception
from learnai.domain.turn import (
    SkillPack,
    StudentSummary,
    TurnContext,
    TutorTurn,
    validate_turn,
)

MAX_TUTOR_RETRIES = 2


class UnregisteredVerifierError(LookupError):
    """A skill names a verification kind that no registered Verifier serves."""


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    verdict: Verdict
    step_diff: StepDiff | None
    diagnosis: MisconceptionId | None
    evidence_class: EvidenceClass | None
    """None when nothing was recorded: an unreadable answer is not evidence."""
    tutor_turn: TutorTurn | None
    task_completed: bool


class PracticeEngine:
    """Orchestrates one task's lifecycle. Every decision here is deterministic."""

    def __init__(
        self,
        *,
        graph: SkillGraph,
        misconceptions: Mapping[MisconceptionId, Misconception],
        item_source: ItemSource,
        verifiers: Mapping[VerificationKind, Verifier],
        tutor: Tutor,
        matcher: MisconceptionMatcher,
        evidence_log: EvidenceLog,
        clock: Clock,
        contract: ModeContract,
        parameters: MasteryParameters = DEFAULT_PARAMETERS,
        parameter_overrides: Mapping[SkillId, MasteryParameters] | None = None,
    ) -> None:
        self.graph = graph
        self.misconceptions = misconceptions
        self.item_source = item_source
        self.verifiers = dict(verifiers)
        needed = {skill.verification_kind for skill in graph.skills.values()}
        if missing := needed - self.verifiers.keys():
            raise UnregisteredVerifierError(
                f"no verifier registered for verification kinds {sorted(missing)}"
            )
        self._tutor = tutor
        self.matcher = matcher
        self.evidence_log = evidence_log
        self.clock = clock
        self.contract = contract
        self.parameters = parameters
        self.parameter_overrides = dict(parameter_overrides or {})

    # -- session lifecycle ---------------------------------------------------

    def start_session(
        self,
        *,
        student_id: StudentId,
        course_id: CourseId,
        course_skills: Sequence[SkillId],
        states: dict[SkillId, SkillState],
        budget_items: int,
        session_id: SessionId,
        seed: int,
    ) -> Session:
        return plan_session(
            session_id=session_id,
            student_id=student_id,
            course_id=course_id,
            contract=self.contract,
            graph=self.graph,
            states=states,
            course_skills=course_skills,
            item_source=self.item_source,
            budget_items=budget_items,
            now=self.clock.now(),
            seed=seed,
            params=self.parameters,
        )

    # -- the loop ------------------------------------------------------------

    def submit(
        self,
        session: Session,
        states: dict[SkillId, SkillState],
        steps: Sequence[str],
        answer: Submission,
        confidence: Confidence,
    ) -> tuple[Session, dict[SkillId, SkillState], SubmitOutcome]:
        """Submit an answer, or decline by leaving every field blank.

        An answer that cannot be read changes nothing and comes back MALFORMED.

        A decline costs exactly what a wrong answer costs — it is the same
        competence signal, and making it cheaper would teach students to stop
        trying. What differs is the tutor's opening move and the calibration
        reading, which for an honest decline is near-perfect.
        """
        task = session.current_task
        if task is None:
            raise ValueError("session has no active task")

        answer.check_shape(task.item.answer_spec.kind)  # a wrong shape is a client bug
        declined = answer.is_blank
        params = self._params_for(task.skill_id)
        verifier = self._verifier_for(task.skill_id)
        if declined:
            confidence = Confidence.NO_IDEA
            result = CheckResult(Verdict.NO_ANSWER)
        else:
            result = verifier.check_answer(answer, task.item.answer_spec)

        if result.verdict is Verdict.MALFORMED:
            # Unreadable is never wrong (spec P7). A missing bracket records no
            # evidence, counts no attempt toward a reveal, spends no tutor call,
            # and above all leaves the cold attempt unused: the student fixes the
            # notation, with the parser's suggestions, and submits again.
            return session, states, SubmitOutcome(
                verdict=Verdict.MALFORMED,
                step_diff=None,
                diagnosis=None,
                evidence_class=None,
                tutor_turn=None,
                task_completed=False,
            )
        correct = result.verdict is Verdict.CORRECT

        # A decline is scored at the guess baseline, not at zero, so that saying
        # "I don't know" never costs more in expectation than guessing would.
        if declined:
            outcome = params.guess_baseline.get(task.item.answer_spec.kind, 0.0)
        else:
            outcome = 1.0 if correct else 0.0

        step_diff: StepDiff | None = None
        diagnosis: MisconceptionId | None = None
        if not correct and not declined and steps:
            step_diff = verifier.diff_steps(steps)
            diagnosis = diagnose(step_diff, self._catalogue(task.skill_id), self.matcher)
            if step_diff is None and len(steps) >= 2:
                # No equivalence break, yet wrong: a form constraint failed,
                # and the belief may still name itself on the final transition
                # — partial factoring is algebraically correct work.
                last = StepDiff(index=len(steps) - 1, previous=steps[-2], current=steps[-1])
                diagnosis = diagnosis or diagnose(
                    last, self._catalogue(task.skill_id), self.matcher
                )
        if not correct and not declined:
            # Keep the last break on the task: it is the tutor's walk-back
            # material when the student asks for help before another failure.
            task = replace(task, last_step_diff=step_diff, last_diagnosis=diagnosis)

        # Every readable submission spends the cold attempt — a decline too,
        # since the tutor answers it. Malformed returned before this point.
        evidence_class = classify_evidence(
            attempt_index=task.help_state.submissions,
            help_taken=task.help_state.help_taken,
            taught_this_session=task.skill_id in session.skills_taught,
            timed=self.contract.timed,
        )

        event = AttemptRecorded(
            at=self.clock.now(),
            student_id=session.student_id,
            skill_id=task.skill_id,
            item_id=task.item.id,
            task_id=task.id,
            item_difficulty=task.item.difficulty,
            outcome=outcome,
            evidence_class=evidence_class,
            confidence=confidence,
            contract_weight=self.contract.evidence_weight,
        )
        self.evidence_log.append(event)
        states = apply_event(
            states, event, self.graph, self.parameters, self.parameter_overrides
        )

        task = replace(task, help_state=record_submission(task.help_state))
        if not declined:
            task = replace(task, help_state=record_attempt(task.help_state))
        tutor_turn: TutorTurn | None = None
        working_shown = not declined and any(step.strip() for step in steps)
        if not correct and self._should_intervene(
            diagnosis=diagnosis,
            has_work=working_shown,
            attempts=task.help_state.attempts,
        ):
            # Unprompted feedback opens at the bottom of the ladder. The ceiling is
            # what the student may climb to on request, not where the tutor starts.
            tutor_turn = self._ask_tutor(
                session,
                task,
                states,
                step_diff,
                diagnosis,
                rung_override=HelpRung.NUDGE,
                last_verdict=result.verdict,
            )

        task = replace(
            task, state=TaskState.COMPLETED if correct else TaskState.ACTIVE
        )
        session = replace_task(session, task)
        if correct:
            session = advance(session)

        return (
            session,
            states,
            SubmitOutcome(
                verdict=result.verdict,
                step_diff=step_diff,
                diagnosis=diagnosis,
                evidence_class=evidence_class,
                tutor_turn=tutor_turn,
                task_completed=correct,
            ),
        )

    def request_help(
        self, session: Session, states: dict[SkillId, SkillState]
    ) -> tuple[Session, TutorTurn | None]:
        task = session.current_task
        if task is None:
            raise ValueError("session has no active task")

        rung = next_rung(self.contract, task.help_state)
        if rung is None:
            return session, None

        turn = self._ask_tutor(
            session,
            task,
            states,
            step_diff=task.last_step_diff,
            diagnosis=task.last_diagnosis,
            rung_override=rung,
        )
        if turn is None:
            # Nothing reached the student: no rung is consumed and no help is
            # recorded. A request the tutor could not answer must not mark the
            # task assisted, or climb the ladder for help that was never seen.
            return session, None
        if turn.rung_used <= HelpRung.NONE:
            # A turn that used no rung gave no ladder help; deliver the message
            # but record nothing, so help_taken stays honest.
            return replace_task(session, task), turn
        self.evidence_log.append(
            HelpTaken(
                at=self.clock.now(),
                student_id=session.student_id,
                skill_id=task.skill_id,
                item_id=task.item.id,
                task_id=task.id,
                rung=turn.rung_used,
            )
        )
        task = replace(task, help_state=record_help(task.help_state, turn.rung_used))
        return replace_task(session, task), turn

    # -- internals -----------------------------------------------------------

    def _verifier_for(self, skill_id: SkillId) -> Verifier:
        # Construction guarantees every skill's kind is registered.
        return self.verifiers[self.graph.skills[skill_id].verification_kind]

    def _params_for(self, skill_id: SkillId) -> MasteryParameters:
        return resolve_parameters(skill_id, self.parameters, self.parameter_overrides)

    def _should_intervene(
        self, *, diagnosis: MisconceptionId | None, has_work: bool, attempts: int
    ) -> bool:
        """Whether the tutor speaks about a wrong step, unprompted (spec §8.4).

        NEVER never speaks. IMMEDIATE answers every failure at once. BY_ERROR_TYPE
        speaks only when the error was recognised. LET_RUN — practice — renders
        "stays quiet for a step or two" as one beat: a first failure that shows
        working is the student's to find, and the tutor walks back on the
        failure that follows it. A decline or a workless answer has nothing to
        let run, so it is answered immediately — that is where a decline's
        opening orientation comes from.
        """
        timing = self.contract.intervention_timing
        if timing is InterventionTiming.NEVER:
            return False
        if timing is InterventionTiming.IMMEDIATE:
            return True
        if timing is InterventionTiming.BY_ERROR_TYPE:
            return diagnosis is not None
        return not has_work or attempts >= 2

    def _catalogue(self, skill_id: SkillId) -> tuple[Misconception, ...]:
        skill = self.graph.skills[skill_id]
        return tuple(self.misconceptions[m] for m in skill.misconception_ids)

    def _build_context(
        self,
        task: Task,
        states: dict[SkillId, SkillState],
        step_diff: StepDiff | None,
        diagnosis: MisconceptionId | None,
        rung_override: HelpRung | None = None,
        last_verdict: Verdict | None = None,
    ) -> TurnContext:
        skill = self.graph.skills[task.skill_id]
        state = states.get(task.skill_id)
        now = self.clock.now()
        return TurnContext(
            skill_pack=SkillPack(
                skill_id=skill.id,
                can_do_statement=skill.can_do_statement,
                teaching_notes="",
                misconceptions=self._catalogue(task.skill_id),
            ),
            item=task.item,
            student_summary=StudentSummary(
                strength=state.strength if state else 0.0,
                is_fresh=is_fresh(state, now, self._params_for(task.skill_id)) if state else False,
                calibration_gap=state.calibration_gap if state else 0.0,
                prior_misconceptions=state.active_misconceptions if state else (),
            ),
            step_diff=step_diff,
            diagnosis=diagnosis,
            last_verdict=last_verdict,
            permitted_rung=(
                min(rung_override, permitted_rung(self.contract, task.help_state))
                if rung_override is not None
                else permitted_rung(self.contract, task.help_state)
            ),
        )

    def _ask_tutor(
        self,
        session: Session,
        task: Task,
        states: dict[SkillId, SkillState],
        step_diff: StepDiff | None,
        diagnosis: MisconceptionId | None,
        rung_override: HelpRung | None = None,
        last_verdict: Verdict | None = None,
    ) -> TutorTurn | None:
        """Ask, validate, and retry. A turn that fails validation never reaches the student."""
        context = self._build_context(
            task, states, step_diff, diagnosis, rung_override, last_verdict
        )
        for _ in range(MAX_TUTOR_RETRIES):
            turn = self._tutor.respond(context)
            verifier = self._verifier_for(task.skill_id)
            if validate_turn(turn, context, self.graph, verifier).accepted:
                return turn
        return None
