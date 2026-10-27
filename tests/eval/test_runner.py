"""Evaluation executes engine opportunities and retains request-local observations."""
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

import pytest

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.adapters.tutor.runtime import TerminationReason, UsageStatus
from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.interaction import InteractionKind, WorkStatus
from learnai.domain.items import Submission
from learnai.domain.turn import TutorTurn
from learnai.eval.fixtures import FixtureError, HistoricalAction, load_scenarios_dir, parse_scenario
from learnai.eval.replay import prepare_scenario
from learnai.eval.runner import NonTutoredReason, build_context, run_scenario, run_scenarios
from tests.adapters.tutor.test_adapter import setup
from tests.eval.test_fixture_corpus import raw_case
from tests.support.scripted_client import Reply, final, tool

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = load_scenarios_dir(ROOT / "eval/fixtures")


@pytest.fixture(scope="module")
def dependencies():
    cluster = load_cluster(ROOT / "content/quadratics/skills.yaml")
    return dict(graph=cluster.graph, items=GeneratorRegistry(QUADRATICS_TEMPLATES),
                catalogue=cluster.misconceptions, verifier=SympyVerifier(),
                matcher=SympyMisconceptionRules())


def runner_dependencies(dependencies):
    values = dict(dependencies)
    verifier = values.pop("verifier")
    values["verifiers"] = {s.verification_kind: verifier for s in values["graph"].skills.values()}
    return values


def scenario_named(name):
    return next(s for s in SCENARIOS if s.id == name)


def edited_scenario(scenario, **changes):
    edited = replace(scenario, **changes)
    object.__setattr__(edited, "provided_fields", scenario.provided_fields)
    return edited


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_context_matches_engine_captured_opportunity_for_entire_corpus(dependencies, scenario):
    actual = build_context(scenario, **dependencies)
    engine = prepare_scenario(scenario, **dependencies)
    assert actual == engine.context
    if actual is not None:
        assert actual.interaction == scenario.interaction
        assert actual.task_progress == engine.progress
        assert actual.history == engine.session.history
        assert actual.history_scope.session_id == scenario.session_id
        assert actual.current_interaction_id == engine.session.history[-1].id


def test_correct_completion_has_no_tutor_exchange_and_no_error(dependencies):
    outcome = run_scenario(parse_scenario(raw_case()), tutor=FakeTutor(), **runner_dependencies(dependencies))
    assert outcome.context is None and outcome.turn is None and outcome.trace is None
    assert outcome.non_tutored_reason is NonTutoredReason.COMPLETED
    assert outcome.error is None and outcome.attempts == 0
    assert outcome.usage["input"] == 0


@pytest.mark.parametrize("name,reason", [
    ("extra-malformed-submit", NonTutoredReason.MALFORMED),
])
def test_engine_no_opportunity_does_not_force_tutor_call(dependencies, name, reason):
    tutor = FakeTutor()
    outcome = run_scenario(scenario_named(name), tutor=tutor, **runner_dependencies(dependencies))
    assert outcome.context is None and outcome.turn is None
    assert outcome.non_tutored_reason is reason
    assert outcome.error is None and outcome.attempts == 0
    assert tutor.contexts_seen == []


def test_first_wrong_submission_with_work_has_no_engine_opportunity(dependencies):
    raw = raw_case(steps=["(x + 2)(x + 5)", "x^2+10"], answer="x^2+10",
        expected_verdict="WRONG", expected_step_check=True,
        expected_diagnosis="mc.foil.drops.cross",
        expected_broken_transition=["(x + 2)(x + 5)", "x^2+10"],
        expected_error_kinds=["equivalence"])
    tutor = FakeTutor()
    result = run_scenario(parse_scenario(raw), tutor=tutor, **runner_dependencies(dependencies))
    assert result.context is None and result.turn is None and result.attempts == 0
    assert result.non_tutored_reason is NonTutoredReason.NO_OPPORTUNITY
    assert result.error is None and tutor.contexts_seen == []


def test_correct_draft_question_is_unchecked_and_preserved_exactly_once(dependencies):
    raw = raw_case(interaction_kind="TASK_QUESTION", work_status="DRAFT", question="Why is this right?",
        permitted_rung="NAME_METHOD", expected_verdict="UNCHECKED", expected_step_check=True)
    raw["expected_progress"] = dict(submissions=0, genuine_attempts=0, declines=0,
        delivered_rungs=[], independence_spent=False, last_checked_revision=0)
    tutor = FakeTutor()
    result = run_scenario(parse_scenario(raw), tutor=tutor, **runner_dependencies(dependencies))
    assert result.turn is not None and result.error is None
    assert result.context is tutor.contexts_seen[0]
    assert result.context.last_verdict is None
    assert not result.context.verification.answer_checked
    assert result.context.verification.verdict is None
    assert result.context.verification.steps_checked
    assert result.context.interaction.question == "Why is this right?"
    assert sum(t.text.count("Why is this right?") for t in result.context.transcript) == 1


def test_explicit_decline_has_no_fictitious_work(dependencies):
    context = build_context(scenario_named("decline-expand.binomial"), **dependencies)
    assert context.last_verdict is Verdict.NO_ANSWER
    assert context.interaction.kind is InteractionKind.SUBMISSION
    assert context.interaction.answer.is_blank
    assert context.interaction.steps == () and context.step_diff is None


def test_value_set_answer_remains_structured(dependencies):
    scenario = edited_scenario(scenario_named("leak-solve.factoring"), answer=Submission.of("9", "-7"))
    context = build_context(scenario, **dependencies)
    assert context.interaction.answer.fields == ("9", "-7")
    assert not context.verification.answer_checked


def test_runner_retains_actual_validation_attempts_and_exact_context(dependencies):
    tutor = FakeTutor([TutorTurn("private rejected", HelpRung.FULL_REVEAL),
                       TutorTurn("Check the signs.", HelpRung.NUDGE)])
    result = run_scenario(scenario_named("leak-expand.binomial"), tutor=tutor,
                          **runner_dependencies(dependencies))
    assert result.turn.message == "Check the signs." and result.attempts == 2
    assert result.context is tutor.contexts_seen[0] is tutor.contexts_seen[1]
    assert result.context.task_progress.submissions == 0
    assert result.trace is None and result.error is None
    assert result.non_tutored_reason is None


class SilentTutor(FakeTutor):
    def respond(self, context, *, feedback=None):
        self.contexts_seen.append(context)
        return None


def test_silent_exchange_is_operational_failure_with_actual_attempt(dependencies):
    result = run_scenario(scenario_named("leak-expand.binomial"), tutor=SilentTutor(),
                          **runner_dependencies(dependencies))
    assert result.turn is None and result.attempts == 1
    assert result.error == "silent" and result.non_tutored_reason is None
    assert result.context is not None and result.trace is None


def test_silence_after_rejected_draft_is_not_mislabeled_validation_exhaustion(dependencies):
    class RejectedThenSilent(FakeTutor):
        def respond(self, context, *, feedback=None):
            return TutorTurn("Rejected.", HelpRung.FULL_REVEAL) if feedback is None else None

    result = run_scenario(scenario_named("leak-expand.binomial"), tutor=RejectedThenSilent(),
                          **runner_dependencies(dependencies))
    assert result.attempts == 2 and result.turn is None
    assert result.error == "silent"


def test_validation_exhaustion_has_real_attempt_count(dependencies):
    tutor = FakeTutor([TutorTurn("Rejected one.", HelpRung.FULL_REVEAL),
                       TutorTurn("Rejected two.", HelpRung.FULL_REVEAL)])
    result = run_scenario(scenario_named("leak-expand.binomial"), tutor=tutor,
                          **runner_dependencies(dependencies))
    assert result.attempts == 2 and result.turn is None
    assert result.error == "validation_exhausted" and result.non_tutored_reason is None


def test_question_after_form_failure_retains_fallback_without_resubmitting(dependencies):
    original = scenario_named("diagnosis-partial-1")
    action = HistoricalAction("submit", original.now - timedelta(days=1), original.task_id,
        original.template_id, original.seed, original.interaction, original.confidence)
    scenario = edited_scenario(original, interaction_kind=InteractionKind.TASK_QUESTION,
        work_status=WorkStatus.SUBMITTED, question="Why isn't this fully factored?",
        permitted_rung=HelpRung.NAME_METHOD, history_actions=(action,))
    tutor = FakeTutor()
    result = run_scenario(scenario, tutor=tutor, **runner_dependencies(dependencies))
    assert result.context is tutor.contexts_seen[0]
    assert result.context.step_diff is None
    assert result.context.diagnosis == "mc.gcf.partial"
    assert result.context.verification.failed_constraints == ("fully_factored",)
    assert result.context.last_verdict is Verdict.WRONG
    assert result.context.task_progress.submissions == 1
    assert len(result.context.history) == 2
    assert result.context == prepare_scenario(scenario, **dependencies).context


def test_selection_preflight_finishes_before_any_tutor_exchange(dependencies):
    tutor = FakeTutor()
    bad = edited_scenario(scenario_named("leak-expand.binomial"), expected_statement="wrong exercise")
    with pytest.raises(FixtureError, match="statement"):
        run_scenarios((scenario_named("leak-expand.binomial"), bad), tutor=tutor,
                      **runner_dependencies(dependencies))
    assert tutor.contexts_seen == []


def test_trace_keeps_tools_rejections_accepted_text_and_all_usage(dependencies):
    tutor, sdk, traces, _ = setup([Reply([tool("get_student_summary")]),
        final("PRIVATE REJECTED", "FULL_REVEAL"), final("Check your first expansion.")])
    result = run_scenario(scenario_named("leak-expand.binomial"), tutor=tutor,
                          **runner_dependencies(dependencies))
    assert result.attempts == 2 and result.turn.message == "Check your first expansion."
    assert result.trace is traces[0] and result.trace.accepted is result.turn
    assert result.trace.termination_reason is TerminationReason.ACCEPTED
    assert [v.accepted for v in result.trace.validation_results] == [False, True]
    assert len(result.trace.tool_results) == 3 and len(result.trace.provider_requests) == 3
    assert "PRIVATE REJECTED" in json.dumps(result.trace.to_dict())
    assert "PRIVATE REJECTED" not in repr(result.context.history)
    assert result.usage == dict(input=300, output=120,
        cache_read=240, cache_write_5m=0, cache_write_1h=0,
        complete_usage_attempts=0, partial_usage_attempts=3, missing_usage_attempts=0)
    assert result.trace.usages[0]["cache_creation_input_tokens"] == 20
    assert all(a.usage_status is UsageStatus.PARTIAL for a in result.trace.attempts)
    assert len(tutor.usages) == len(sdk.requests) == 3


def test_reused_adapter_returns_matching_trace_and_usage_delta(dependencies):
    tutor, _, traces, _ = setup([final("First."), final("Second.", output_tokens=70)])
    results = run_scenarios((scenario_named("leak-expand.binomial"), scenario_named("leak-expand.square")),
                            tutor=tutor, **runner_dependencies(dependencies))
    assert results[0].trace is traces[0] and results[1].trace is traces[1]
    assert results[0].trace.request_id != results[1].trace.request_id
    assert [r.usage["output"] for r in results] == [40, 70]
    assert [r.usage["input"] for r in results] == [100, 100]
    assert len(tutor.usages) == 2


def test_nested_request_during_finish_cannot_replace_outer_trace(dependencies):
    tutor, _, traces, _ = setup([final("Outer."), final("Inner.", output_tokens=70)])
    nested = []

    def sink(trace):
        traces.append(trace)
        if len(traces) == 1:
            nested.append(run_scenario(scenario_named("leak-expand.square"), tutor=tutor,
                                       **runner_dependencies(dependencies)))

    tutor.trace_sink = sink
    outer = run_scenario(scenario_named("leak-expand.binomial"), tutor=tutor,
                         **runner_dependencies(dependencies))
    assert outer.trace is traces[0] and nested[0].trace is traces[1]
    assert outer.trace.task_id == outer.scenario.task_id
    assert nested[0].trace.task_id == nested[0].scenario.task_id
    assert outer.usage["output"] == 40 and nested[0].usage["output"] == 70
    assert outer.trace.request_id != nested[0].trace.request_id
    assert outer.trace.attempts[0].normalized_usage.counts == {"input": 100, "output": 40, "cache_read": 80}
    assert nested[0].trace.attempts[0].normalized_usage.counts == {"input": 100, "output": 70, "cache_read": 80}


@pytest.mark.parametrize("reply,status,observed_output", [
    (Reply([], status=400), UsageStatus.MISSING, 0),
    (Reply([], stream_error=True), UsageStatus.PARTIAL, 2),
])
def test_failed_provider_attempt_usage_is_explicitly_incomplete(dependencies, reply, status, observed_output):
    tutor, _, traces, _ = setup([reply], stream=status is UsageStatus.PARTIAL)
    result = run_scenario(scenario_named("leak-expand.binomial"), tutor=tutor,
                          **runner_dependencies(dependencies))
    assert result.trace is traces[0] and result.turn is None and result.attempts == 1
    assert result.error == ("api_error" if status is UsageStatus.MISSING else "network_exhausted")
    assert result.non_tutored_reason is None
    assert result.trace.attempts[0].usage_status is status
    assert result.usage[f"{status.value}_usage_attempts"] == 1
    assert result.usage["complete_usage_attempts"] == 0
    assert result.usage["output"] == observed_output


def test_deadline_uses_adapter_clock_without_changing_study_time(dependencies):
    tutor, _, traces, clock = setup([final(elapsed=16)])
    scenario = scenario_named("leak-expand.binomial")
    result = run_scenario(scenario, tutor=tutor, **runner_dependencies(dependencies))
    assert result.error == "deadline" and result.turn is None
    assert result.trace is traces[0] and result.trace.elapsed_seconds == clock.now == 16
    assert result.context.history[-1].at == scenario.now

