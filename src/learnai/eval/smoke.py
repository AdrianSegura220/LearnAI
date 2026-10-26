"""Deterministic students; tutor delivery and mastery remain engine decisions."""
from collections.abc import Mapping
from dataclasses import replace

from learnai.adapters.clock import FakeClock
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.adapters.tutor.runtime import TerminationReason, TurnTrace
from learnai.domain.contracts import ModeContract, PRACTICE
from learnai.domain.engine import PracticeEngine
from learnai.domain.enums import Confidence, EvidenceClass, Verdict
from learnai.domain.events import AttemptRecorded, HelpTaken
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import CourseId, MisconceptionId, SessionId, SkillId, StudentId, VerificationKind
from learnai.domain.interaction import InteractionKind, StudentInteraction, WorkStatus
from learnai.domain.items import Formula, Item, Submission
from learnai.domain.mastery import SkillState
from learnai.domain.misconceptions import MisconceptionMatcher
from learnai.domain.ports import Clock, ItemSource, Tutor, TutorExchange, Verifier
from learnai.domain.session import TaskState, advance, replace_task
from learnai.domain.skills import Misconception
from learnai.domain.turn import TurnContext, TurnFeedback, TutorTurn, ValidationResult


_EXHAUSTED = frozenset({
    TerminationReason.DEADLINE, TerminationReason.CONTEXT_LIMIT,
    TerminationReason.ROUND_TRIP_LIMIT, TerminationReason.OUTPUT_LIMIT,
    TerminationReason.NETWORK_EXHAUSTED, TerminationReason.FORMAT_EXHAUSTED,
    TerminationReason.VALIDATION_EXHAUSTED,
})


class _ObservedTutor:
    """Observe finalized exchanges without replacing the adapter's trace sink."""

    def __init__(self, tutor: Tutor) -> None:
        self.tutor = tutor
        self.counts = dict.fromkeys((
            "tutor_requests", "tutor_turns", "tutor_attempts", "degraded_turns",
            "silent_turns", "exhausted_turns", "error_turns", "traced_turns",
            "model_calls", "api_errors", "api_retries", "format_retries", "validation_retries",
        ), 0.0)

    def begin_turn(self, context: TurnContext) -> TutorExchange:
        exchange = self.tutor.begin_turn(context)
        self.counts["tutor_requests"] += 1
        return _ObservedExchange(exchange, self.counts)

    def respond(self, context: TurnContext, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        return self.tutor.respond(context, feedback=feedback)


class _ObservedExchange:
    def __init__(self, inner: TutorExchange, counts: dict[str, float]) -> None:
        self.inner = inner
        self.counts = counts

    def respond(self, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        self.counts["tutor_attempts"] += 1
        return self.inner.respond(feedback=feedback)

    def expired(self) -> bool:
        return self.inner.expired()

    @property
    def stop_reason(self) -> str | None:
        return self.inner.stop_reason

    def record_validation(self, result: ValidationResult) -> None:
        self.inner.record_validation(result)

    def finish(self, *, accepted: TutorTurn | None, reason: str) -> None:
        self.inner.finish(accepted=accepted, reason=reason)
        trace = getattr(self.inner, "trace", None)
        if isinstance(trace, TurnTrace):
            self.counts["traced_turns"] += 1
            reason = trace.termination_reason or reason
            for name in ("model_calls", "api_retries", "format_retries", "validation_retries"):
                self.counts[name] += getattr(trace, name)
            self.counts["api_errors"] += len(trace.api_errors)
        self.counts["tutor_turns" if accepted is not None else "degraded_turns"] += 1
        if accepted is None:
            self.counts["silent_turns"] += reason == TerminationReason.SILENT
            self.counts["exhausted_turns"] += reason in _EXHAUSTED
            self.counts["error_turns"] += reason == TerminationReason.API_ERROR


def _cold_error(item: Item, verifier: Verifier) -> Submission:
    """Use a readable numerical error only after the actual checker confirms it."""
    for value in ("0", "1", "-1"):
        answer = Submission.of(value)
        if verifier.check_answer(answer, item.answer_spec).verdict is Verdict.WRONG:
            return answer
    raise ValueError(f"no readable cold error for smoke item {item.id}")


def run_persona_smoke(
    *, tutor: Tutor, graph: SkillGraph,
    misconceptions: Mapping[MisconceptionId, Misconception], items: ItemSource,
    verifiers: Mapping[VerificationKind, Verifier], matcher: MisconceptionMatcher,
    clock: Clock | None = None, contract: ModeContract = PRACTICE,
    sessions: int = 2, items_per_session: int = 3, seed: int = 11,
) -> dict[str, dict[str, float]]:
    """Run short independent terms, retaining actual completion and evidence counts.

    ``tutor_turns`` counts delivered responses, ``tutor_requests`` counts logical
    exchanges, and ``tutor_attempts`` counts candidate-response calls (including
    validation retries). Provider calls/retries come only from available traces.
    ``attempts`` excludes declines; ``rungs_used`` excludes delivered NONE rungs.
    No opportunity to speak is neither silence nor a degraded response.
    """
    results: dict[str, dict[str, float]] = {}
    study_clock = clock if clock is not None else FakeClock()
    for persona in ("diligent", "help_seeker"):
        observed = _ObservedTutor(tutor)
        log = InMemoryEvidenceLog()
        states: dict[SkillId, SkillState] = {}
        counts = dict.fromkeys(("sessions_run", "items_completed", "items_abandoned",
                                "submissions", "attempts", "declines", "rungs_used"), 0.0)
        engine = PracticeEngine(graph=graph, misconceptions=misconceptions,
            item_source=items, verifiers=verifiers, tutor=observed, matcher=matcher,
            evidence_log=log, clock=study_clock, contract=contract)
        for index in range(sessions):
            session = engine.start_session(student_id=StudentId(persona),
                course_id=CourseId("persona-smoke"), course_skills=tuple(sorted(graph.skills)),
                states=states, budget_items=items_per_session,
                session_id=SessionId(f"smoke:{persona}:{index}"), seed=seed + index)
            counts["sessions_run"] += 1
            while not session.is_finished:
                task = session.current_task
                assert task is not None
                verifier = verifiers[graph.skills[task.skill_id].verification_kind]
                working = tuple(block.source for block in task.item.statement if isinstance(block, Formula))[:1]
                if persona == "diligent":
                    wrong = _cold_error(task.item, verifier)
                    session, states, _ = engine.submit(session, states,
                        steps=(*working, *wrong.fields), answer=wrong, confidence=Confidence.UNSURE)
                else:
                    interaction = StudentInteraction(task.id, task.work_revision,
                        InteractionKind.TASK_QUESTION, WorkStatus.DRAFT, working,
                        Submission.of(""), question="What should I consider next in this working?")
                    session, _ = engine.ask_question(session, states, interaction)
                session, states, outcome = engine.submit(session, states,
                    steps=task.item.worked_steps, answer=verifier.key_submission(task.item.answer_spec),
                    confidence=Confidence.CERTAIN)
                if not outcome.task_completed:
                    # Same bounded skip as the term simulator: never claim a bad
                    # key completed, and never loop forever on an active task.
                    active = session.current_task
                    assert active is not None
                    session = advance(replace_task(session, replace(active, state=TaskState.ABANDONED)))
            for finished in session.plan:
                counts["items_completed"] += finished.state is TaskState.COMPLETED
                counts["items_abandoned"] += finished.state is TaskState.ABANDONED
                counts["submissions"] += finished.help_state.submissions
                counts["attempts"] += finished.help_state.attempts
                counts["declines"] += finished.help_state.submissions - finished.help_state.attempts
                counts["rungs_used"] += len(finished.help_state.rungs_used)
        attempts = [event for event in log.events() if isinstance(event, AttemptRecorded)]
        results[persona] = {**counts, **observed.counts,
            "help_events": float(sum(isinstance(event, HelpTaken) for event in log.events())),
            "cold_wrong": float(sum(not event.correct and event.evidence_class is EvidenceClass.UNASSISTED_COLD
                                    for event in attempts)),
            "assisted_correct": float(sum(event.correct and event.evidence_class is EvidenceClass.ASSISTED
                                          for event in attempts)),
            "independent_correct": float(sum(event.correct and event.evidence_class in {
                EvidenceClass.UNASSISTED_COLD, EvidenceClass.TIMED_EXAM} for event in attempts)),
            "strength_total": float(sum(state.strength for state in states.values())),
        }
    return results
