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
from learnai.domain.history import HistoryKind, HistoryRecord
from learnai.domain.interaction import (
    InteractionKind, ResponseJob, StudentInteraction, VerificationSnapshot, WorkStatus,
    prepare_verification,
)
from learnai.domain.mastery import SkillState
from learnai.domain.misconceptions import MisconceptionMatcher
from learnai.domain.parameters import (
    DEFAULT_PARAMETERS,
    MasteryParameters,
    resolve_parameters,
)
from learnai.domain.planner import plan_session
from learnai.domain.ports import Clock, EvidenceLog, ItemSource, Tutor, Verifier
from learnai.domain.projection import apply_event
from learnai.domain.session import Session, Task, TaskState, advance, replace_task
from learnai.domain.skills import Misconception
from learnai.domain.turn import (
    TranscriptEntry,
    build_turn_context,
    TutorTurn,
    request_validated_turn,
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
        enabled_response_jobs: frozenset[ResponseJob] = frozenset({
            ResponseJob.BRIEF, ResponseJob.NORMAL, ResponseJob.SUBSTANTIAL,
        }),
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
        self.enabled_response_jobs = frozenset(enabled_response_jobs)

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
        current = task.current_interaction
        changed = current is not None and (current.steps != tuple(steps) or current.answer != answer)
        revision = task.work_revision + int(changed)
        interaction = StudentInteraction(task.id, revision, InteractionKind.SUBMISSION,
                                         WorkStatus.SUBMITTED, tuple(steps), answer)
        result = prepare_verification(
            interaction, item=task.item, verifier=self._verifier_for(task.skill_id),
            catalogue=self._catalogue(task.skill_id), matcher=self.matcher,
            check_answer=True, check_steps=True,
        )
        if declined:
            confidence = Confidence.NO_IDEA

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

        step_diff = result.step_diff
        diagnosis = result.diagnosis
        task = replace(task, work_revision=revision, current_interaction=interaction,
                       last_verification=result, last_step_diff=step_diff,
                       last_diagnosis=diagnosis)

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
        session = replace_task(session, task)
        session = self._record_interaction(session, task, interaction, HistoryKind.SUBMISSION,
                                           verdict=result.verdict, evidence_class=evidence_class)
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
                rung_override=HelpRung.NUDGE,
            )
            if tutor_turn is not None:
                session, task = self._deliver(session, task, tutor_turn, HistoryKind.TUTOR_DELIVERED)

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

    def ask_question(
        self, session: Session, states: dict[SkillId, SkillState],
        interaction: StudentInteraction, *, response_job: ResponseJob = ResponseJob.NORMAL,
    ) -> tuple[Session, TutorTurn | None]:
        task = session.current_task
        if task is None:
            raise ValueError("session has no active task")
        self._validate_interaction(task, interaction)
        if interaction.kind is not InteractionKind.TASK_QUESTION:
            raise ValueError("ask_question requires a task-question interaction")
        if response_job not in self.enabled_response_jobs:
            raise ValueError("response job is not enabled")
        if self.contract.timed:
            raise ValueError("timed contracts do not allow task questions")
        checked = prepare_verification(
            interaction, item=task.item, verifier=self._verifier_for(task.skill_id),
            catalogue=self._catalogue(task.skill_id), matcher=self.matcher,
            check_answer=False, check_steps=True,
        )
        previous = task.last_verification
        if previous is not None and previous.revision == interaction.revision and previous.answer_checked:
            checked = (previous if previous.steps_checked else replace(
                checked, answer_checked=True, verdict=previous.verdict,
                failed_constraints=previous.failed_constraints,
            ))
        task = replace(task, work_revision=interaction.revision, current_interaction=interaction,
                       last_verification=(checked if checked.answer_checked or checked.steps_checked else previous),
                       last_step_diff=checked.step_diff, last_diagnosis=checked.diagnosis)
        session = replace_task(session, task)
        session = self._record_interaction(session, task, interaction, HistoryKind.STUDENT_QUESTION)
        turn = self._ask_tutor(session, task, states, response_job=response_job)
        if turn is not None:
            session, task = self._deliver(session, task, turn, HistoryKind.TUTOR_DELIVERED)
        return session, turn

    def request_help(
        self, session: Session, states: dict[SkillId, SkillState]
    ) -> tuple[Session, TutorTurn | None]:
        task = session.current_task
        if task is None:
            raise ValueError("session has no active task")
        rung = next_rung(self.contract, task.help_state)
        if rung is None:
            return session, None
        current = task.current_interaction
        interaction = StudentInteraction(
            task.id, task.work_revision, InteractionKind.HELP_REQUEST,
            current.status if current else WorkStatus.DRAFT,
            current.steps if current else (), current.answer if current else Submission.of(""),
        )
        task = replace(task, current_interaction=interaction)
        session = replace_task(session, task)
        session = self._record_interaction(session, task, interaction, HistoryKind.HELP_REQUEST)
        turn = self._ask_tutor(session, task, states, rung_override=rung)
        if turn is not None:
            session, task = self._deliver(session, task, turn, HistoryKind.HELP_DELIVERED)
        return session, turn

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

    def _validate_interaction(self, task: Task, interaction: StudentInteraction) -> None:
        if interaction.task_id != task.id:
            raise ValueError("interaction does not belong to the active task")
        if interaction.revision < task.work_revision:
            raise ValueError("stale work revision")
        interaction.answer.check_shape(task.item.answer_spec.kind)
        previous = task.current_interaction
        if previous is not None and interaction.revision == task.work_revision:
            if interaction.steps != previous.steps or interaction.answer != previous.answer:
                raise ValueError("changed work requires a greater revision")

    def _record_interaction(
        self, session: Session, task: Task, interaction: StudentInteraction, kind: HistoryKind,
        *, verdict: Verdict | None = None, evidence_class: EvidenceClass | None = None,
    ) -> Session:
        record = HistoryRecord(
            id=f"{session.id}:{len(session.history) + 1}", at=self.clock.now(),
            student_id=session.student_id, session_id=session.id, task_id=task.id,
            item_id=task.item.id, skill_id=task.skill_id, revision=interaction.revision,
            kind=kind, interaction=interaction, verdict=verdict, evidence_class=evidence_class,
        )
        transcript = session.transcript
        if kind is not HistoryKind.HELP_REQUEST:
            text = "\n".join((*interaction.steps, *interaction.answer.fields,
                               *((interaction.question,) if interaction.question is not None else ())))
            transcript += (TranscriptEntry("student", text, record.id, task.id,
                                            interaction.revision, record.at),)
        return replace(session, history=session.history + (record,), transcript=transcript)

    def _deliver(
        self, session: Session, task: Task, turn: TutorTurn, kind: HistoryKind,
    ) -> tuple[Session, Task]:
        # One delivered response is one assistance fact, independent of how its
        # history and transcript views are rendered or retrieved.
        at = self.clock.now()
        self.evidence_log.append(HelpTaken(at, session.student_id, task.skill_id,
                                         task.item.id, task.id, turn.rung_used))
        help_state = replace(task.help_state, assistance_received=True)
        if turn.rung_used > HelpRung.NONE:
            help_state = record_help(help_state, turn.rung_used)
        task = replace(task, help_state=help_state)
        related = next((r.id for r in reversed(session.history)
                        if r.task_id == task.id and r.interaction is not None), None)
        record = HistoryRecord(
            id=f"{session.id}:{len(session.history) + 1}", at=at,
            student_id=session.student_id, session_id=session.id, task_id=task.id,
            item_id=task.item.id, skill_id=task.skill_id, revision=task.work_revision,
            kind=kind, message=turn.message, rung=turn.rung_used,
            related_record_ids=(related,) if related else (),
        )
        session = replace(session, history=session.history + (record,),
                          transcript=session.transcript + (TranscriptEntry(
                              "tutor", turn.message, record.id, task.id, task.work_revision, at),))
        return replace_task(session, task), task

    def _ask_tutor(
        self, session: Session, task: Task, states: dict[SkillId, SkillState],
        rung_override: HelpRung | None = None,
        response_job: ResponseJob = ResponseJob.NORMAL,
    ) -> TutorTurn | None:
        assert task.current_interaction is not None
        verification = task.last_verification
        if verification is None or verification.revision != task.work_revision:
            verification = VerificationSnapshot(task.work_revision, False, False, None, None, None)
        ceiling = permitted_rung(self.contract, task.help_state)
        context = build_turn_context(
            session=session, task=task, states=states, interaction=task.current_interaction,
            verification=verification, graph=self.graph,
            catalogue=self.misconceptions, now=self.clock.now(),
            permitted_rung=min(rung_override, ceiling) if rung_override is not None else ceiling,
            parameters=self._params_for(task.skill_id), response_job=response_job,
        )
        turn, _ = request_validated_turn(self._tutor, context, self.graph,
                                         self._verifier_for(task.skill_id),
                                         max_attempts=MAX_TUTOR_RETRIES)
        return turn
