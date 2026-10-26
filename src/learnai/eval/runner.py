"""Evaluate real engine opportunities through one validated tutor exchange.

Fixture expectations are checked before execution and never sent to a tutor.
Token totals are observed counters; completeness lives alongside those counters
and in the full request-local trace, so missing usage is not a known zero.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum

from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.runtime import TurnTrace
from learnai.domain.engine import MAX_TUTOR_RETRIES
from learnai.domain.enums import Verdict
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId, VerificationKind
from learnai.domain.items import Item
from learnai.domain.misconceptions import MisconceptionMatcher
from learnai.domain.ports import Tutor, TutorExchange, Verifier
from learnai.domain.skills import Misconception
from learnai.domain.turn import TurnContext, TurnFeedback, TutorTurn, ValidationResult, request_validated_turn
from learnai.eval.fixtures import Scenario, validate_corpus
from learnai.eval.replay import PreparedScenario, prepare_scenario


class NonTutoredReason(str, Enum):
    COMPLETED = "completed"
    MALFORMED = "malformed"
    NO_OPPORTUNITY = "no_opportunity"


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    scenario: Scenario
    item: Item
    turn: TutorTurn | None
    attempts: int
    usage: dict[str, int]
    error: str | None = None
    trace: TurnTrace | None = None
    context: TurnContext | None = None
    non_tutored_reason: NonTutoredReason | None = None


def build_context(scenario: Scenario, *, graph: SkillGraph, items: GeneratorRegistry,
                  catalogue: Mapping[MisconceptionId, Misconception],
                  matcher: MisconceptionMatcher, verifier: Verifier) -> TurnContext | None:
    """Return the exact current engine-captured context, or no opportunity."""
    validate_corpus((scenario,), graph=graph, items=items, catalogue=catalogue,
                    matcher=matcher, verifier=verifier)
    return prepare_scenario(scenario, graph=graph, items=items, catalogue=catalogue,
                            matcher=matcher, verifier=verifier).context


class _RequestTutor:
    """Capture the exchange itself without changing a shared adapter or sink."""
    def __init__(self, tutor: Tutor) -> None:
        self.tutor = tutor
        self.exchange: _RequestExchange | None = None

    def begin_turn(self, context: TurnContext) -> TutorExchange:
        self.exchange = _RequestExchange(self.tutor.begin_turn(context))
        return self.exchange

    def respond(self, context: TurnContext, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        return self.tutor.respond(context, feedback=feedback)

    @property
    def trace(self) -> TurnTrace | None:
        value = getattr(self.exchange.inner, "trace", None) if self.exchange is not None else None
        return value if isinstance(value, TurnTrace) else None


class _RequestExchange:
    def __init__(self, inner: TutorExchange) -> None:
        self.inner = inner
        self.finish_reason: str | None = None

    def respond(self, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        return self.inner.respond(feedback=feedback)

    def expired(self) -> bool:
        return self.inner.expired()

    @property
    def stop_reason(self) -> str | None:
        return self.inner.stop_reason

    def record_validation(self, result: ValidationResult) -> None:
        self.inner.record_validation(result)

    def finish(self, *, accepted: TutorTurn | None, reason: str) -> None:
        self.finish_reason = reason
        self.inner.finish(accepted=accepted, reason=reason)


def _usage(trace: TurnTrace | None) -> dict[str, int]:
    totals = dict(input=0, output=0, cache_read=0, cache_write_5m=0, cache_write_1h=0,
                  complete_usage_attempts=0, partial_usage_attempts=0, missing_usage_attempts=0)
    if trace is not None:
        for attempt in trace.attempts:
            usage = attempt.normalized_usage
            totals[f"{usage.status.value}_usage_attempts"] += 1
            for category, count in usage.counts.items():
                totals[category] = totals.get(category, 0) + count
    return totals


def _run(prepared: PreparedScenario, *, tutor: Tutor, graph: SkillGraph,
         verifier: Verifier) -> ScenarioOutcome:
    context = prepared.context
    if context is None:
        reason = NonTutoredReason.NO_OPPORTUNITY
        if prepared.outcome is not None:
            if prepared.outcome.task_completed:
                reason = NonTutoredReason.COMPLETED
            elif prepared.outcome.verdict is Verdict.MALFORMED:
                reason = NonTutoredReason.MALFORMED
        return ScenarioOutcome(prepared.scenario, prepared.task.item, None, 0, _usage(None),
                               context=None, non_tutored_reason=reason)
    request = _RequestTutor(tutor)
    turn, attempts = request_validated_turn(request, context, graph, verifier,
                                           max_attempts=MAX_TUTOR_RETRIES)
    trace = request.trace
    error = None
    if turn is None:
        if trace is not None and trace.termination_reason is not None:
            error = trace.termination_reason.value
        elif request.exchange is not None:
            error = request.exchange.stop_reason or request.exchange.finish_reason
        else:
            error = "silent"
    return ScenarioOutcome(prepared.scenario, prepared.task.item, turn, attempts,
                           _usage(trace), error, trace, context)


def run_scenario(scenario: Scenario, *, tutor: Tutor, graph: SkillGraph,
                 items: GeneratorRegistry, catalogue: Mapping[MisconceptionId, Misconception],
                 verifiers: Mapping[VerificationKind, Verifier],
                 matcher: MisconceptionMatcher) -> ScenarioOutcome:
    return run_scenarios((scenario,), tutor=tutor, graph=graph, items=items,
                         catalogue=catalogue, verifiers=verifiers, matcher=matcher)[0]


def run_scenarios(scenarios: Iterable[Scenario], *, tutor: Tutor, graph: SkillGraph,
                  items: GeneratorRegistry, catalogue: Mapping[MisconceptionId, Misconception],
                  verifiers: Mapping[VerificationKind, Verifier],
                  matcher: MisconceptionMatcher) -> tuple[ScenarioOutcome, ...]:
    """Preflight the entire selection before starting any current tutor request."""
    selected = tuple(scenarios)
    for scenario in selected:
        verifier = verifiers[graph.skills[scenario.skill_id].verification_kind]
        validate_corpus((scenario,), graph=graph, items=items, catalogue=catalogue,
                        verifier=verifier, matcher=matcher)
    outcomes = []
    for scenario in selected:
        verifier = verifiers[graph.skills[scenario.skill_id].verification_kind]
        prepared = prepare_scenario(scenario, graph=graph, items=items, catalogue=catalogue,
                                    verifier=verifier, matcher=matcher)
        outcomes.append(_run(prepared, tutor=tutor, graph=graph, verifier=verifier))
    return tuple(outcomes)
