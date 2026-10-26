"""Keyless real-engine replay. Private scripts never become delivered history."""
from collections.abc import Mapping
from dataclasses import dataclass

from learnai.adapters.clock import FakeClock
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.domain.contracts import PRACTICE
from learnai.domain.engine import PracticeEngine, SubmitOutcome
from learnai.domain.events import EvidenceEvent
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import CourseId, MisconceptionId, SkillId, TaskId
from learnai.domain.interaction import InteractionKind, StudentInteraction, TaskProgress
from learnai.domain.mastery import SkillState
from learnai.domain.misconceptions import MisconceptionMatcher
from learnai.domain.ports import Verifier
from learnai.domain.session import Session, Task, TaskState
from learnai.domain.skills import Misconception
from learnai.domain.turn import TurnContext, TurnFeedback, TutorTurn, ValidationResult
from learnai.eval.fixtures import FixtureError, Scenario


@dataclass(frozen=True, slots=True)
class PreparedScenario:
    """State after current operation, before any current tutor delivery.

    context is the exact opportunity captured from PracticeEngine (or None).
    outcome is populated for submits only. task stays available after completion.
    """
    scenario: Scenario
    engine: PracticeEngine
    session: Session
    states: dict[SkillId, SkillState]
    task: Task
    context: TurnContext | None
    outcome: SubmitOutcome | None
    progress: TaskProgress
    evidence: tuple[EvidenceEvent, ...]


class _ScriptTutor:
    def __init__(self) -> None:
        self.script: tuple[TutorTurn | None, ...] = ()
        self.index = 0
        self.capture = False
        self.context: TurnContext | None = None

    def begin_turn(self, context: TurnContext) -> "_Exchange":
        self.context = context
        return _Exchange(self, context)

    def respond(self, context: TurnContext, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        if self.capture:
            return None
        if self.index >= len(self.script):
            raise FixtureError("historical tutor script exhausted or unspecified")
        turn = self.script[self.index]
        self.index += 1
        return turn


class _Exchange:
    def __init__(self, tutor: _ScriptTutor, context: TurnContext) -> None:
        self.tutor, self.context = tutor, context

    def respond(self, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        return self.tutor.respond(self.context, feedback=feedback)

    def expired(self) -> bool:
        return False

    def record_validation(self, result: ValidationResult) -> None:
        pass

    @property
    def stop_reason(self) -> str | None:
        return None

    def finish(self, *, accepted: TutorTurn | None, reason: str) -> None:
        pass


def prepare_scenario(scenario: Scenario, *, graph: SkillGraph, items: GeneratorRegistry,
                     catalogue: Mapping[MisconceptionId, Misconception], verifier: Verifier,
                     matcher: MisconceptionMatcher) -> PreparedScenario:
    """Replay all actions and capture the current real tutoring opportunity.

    Expectations are deliberately unread here. Historical scripts must be consumed
    exactly. A silent capture of the current request records no delivered assistance.
    """
    try:
        return _prepare(scenario, graph=graph, items=items, catalogue=catalogue,
                        verifier=verifier, matcher=matcher)
    except (ValueError, KeyError, IndexError) as exc:
        raise FixtureError(f"{scenario.id}: {exc}") from exc


def _validate_submission_revision(task: Task, interaction: StudentInteraction) -> None:
    """Bind a candidate to the engine's next revision before it can be rejected.

    MALFORMED does not persist this revision, so post-operation stored work
    cannot serve as the candidate's revision check.
    """
    previous = task.current_interaction
    changed = previous is not None and (
        previous.steps != interaction.steps or previous.answer != interaction.answer)
    if interaction.revision != task.work_revision + int(changed):
        raise FixtureError("submission candidate revision differs from engine advancement")


def _prepare(scenario: Scenario, *, graph: SkillGraph, items: GeneratorRegistry,
             catalogue: Mapping[MisconceptionId, Misconception], verifier: Verifier,
             matcher: MisconceptionMatcher) -> PreparedScenario:
    initial = scenario.history_actions[0].at if scenario.history_actions else scenario.now
    clock = FakeClock(initial)
    log, tutor = InMemoryEvidenceLog(), _ScriptTutor()
    engine = PracticeEngine(graph=graph, misconceptions=catalogue, item_source=items,
        verifiers={skill.verification_kind: verifier for skill in graph.skills.values()},
        tutor=tutor, matcher=matcher, evidence_log=log, clock=clock, contract=PRACTICE)
    # The declared task sequence must be achievable through actual completion.
    tasks: dict[TaskId, Task] = {}
    for action in scenario.history_actions:
        if action.task_id not in tasks:
            item = items.instantiate(action.template_id, action.seed)
            tasks[action.task_id] = Task(action.task_id, scenario.session_id, item, item.skill_id,
                                        TaskState.ACTIVE)
    if scenario.task_id not in tasks:
        item = items.instantiate(scenario.template_id, scenario.seed)
        tasks[scenario.task_id] = Task(scenario.task_id, scenario.session_id, item, item.skill_id,
                                      TaskState.ACTIVE)
    session = Session(scenario.session_id, scenario.student_id, CourseId("eval"), PRACTICE,
                      tuple(tasks.values()), 0, initial)
    states = {skill: SkillState(scenario.student_id, skill, strength=scenario.strength,
        stability=1.0 if scenario.is_fresh else 0.0,
        last_success_at=initial if scenario.is_fresh else None,
        last_reviewed_at=initial, calibration_gap=scenario.calibration_gap,
        active_misconceptions=scenario.prior_misconceptions) for skill in {t.skill_id for t in tasks.values()}}
    for action in scenario.history_actions:
        if session.current_task is None or session.current_task.id != action.task_id:
            raise FixtureError("history action task is not the engine's active task")
        clock.set(action.at)
        tutor.script, tutor.index = action.tutor_script, 0
        if action.operation == "submit":
            assert action.interaction is not None and action.confidence is not None
            _validate_submission_revision(session.current_task, action.interaction)
            session, states, _ = engine.submit(session, states, action.interaction.steps,
                                               action.interaction.answer, action.confidence)
        elif action.operation == "ask_question":
            assert action.interaction is not None
            session, _ = engine.ask_question(session, states, action.interaction,
                                             response_job=action.response_job)
        else:
            session, _ = engine.request_help(session, states)
        if tutor.index != len(tutor.script):
            raise FixtureError("historical tutor script has unconsumed replies")
    if session.current_task is None or session.current_task.id != scenario.task_id:
        raise FixtureError("current task is not the engine's active task")
    clock.set(scenario.now)
    tutor.capture, tutor.context = True, None
    outcome = None
    if scenario.interaction_kind is InteractionKind.SUBMISSION:
        _validate_submission_revision(session.current_task, scenario.interaction)
        session, states, outcome = engine.submit(session, states, scenario.steps,
                                                  scenario.answer, scenario.confidence)
    elif scenario.interaction_kind is InteractionKind.TASK_QUESTION:
        session, _ = engine.ask_question(session, states, scenario.interaction,
                                         response_job=scenario.response_job)
    else:
        session, _ = engine.request_help(session, states)
    task = next(t for t in session.plan if t.id == scenario.task_id)
    if scenario.interaction_kind is not InteractionKind.SUBMISSION and task.work_revision != scenario.work_revision:
        raise FixtureError("current revision differs from engine advancement")
    if scenario.interaction_kind is InteractionKind.HELP_REQUEST and task.current_interaction != scenario.interaction:
        raise FixtureError("help-request work differs from engine stored work")
    checked = task.last_verification
    progress = TaskProgress(task.help_state.submissions, task.help_state.attempts,
        task.help_state.submissions - task.help_state.attempts, task.help_state.rungs_used,
        task.help_state.help_taken or task.help_state.submissions > 0,
        checked.revision if checked and (checked.answer_checked or checked.steps_checked) else None)
    return PreparedScenario(scenario, engine, session, states, task, tutor.context,
                            outcome, progress, log.events())
