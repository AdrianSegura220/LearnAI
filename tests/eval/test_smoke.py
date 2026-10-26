"""Short terms exercise real engine evidence, delivery and degraded exchanges."""
from dataclasses import replace
from pathlib import Path

import pytest

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.contracts import PRACTICE
from learnai.domain.enums import HelpRung, InterventionTiming
from learnai.domain.history import HistoryKind
from learnai.domain.interaction import InteractionKind, WorkStatus
from learnai.domain.items import Submission
from learnai.domain.turn import TutorTurn
from learnai.eval.smoke import run_persona_smoke
from tests.adapters.tutor.test_adapter import setup
from tests.support.scripted_client import Reply, final


@pytest.fixture(scope="module")
def dependencies():
    cluster = load_cluster(Path(__file__).resolve().parents[2] / "content/quadratics/skills.yaml")
    verifier = SympyVerifier()
    return dict(graph=cluster.graph, misconceptions=cluster.misconceptions,
                items=GeneratorRegistry(QUADRATICS_TEMPLATES),
                verifiers={s.verification_kind: verifier for s in cluster.graph.skills.values()},
                matcher=SympyMisconceptionRules())


IMMEDIATE = replace(PRACTICE, intervention_timing=InterventionTiming.IMMEDIATE)


def test_diligent_corrects_each_readable_cold_error_without_erasing_it(dependencies):
    result = run_persona_smoke(tutor=FakeTutor(), **dependencies)["diligent"]
    assert result["sessions_run"] == 2
    assert result["items_completed"] == 6
    assert result["items_abandoned"] == 0
    assert result["submissions"] == result["attempts"] == 12
    assert result["declines"] == 0
    assert result["cold_wrong"] == 6
    assert result["assisted_correct"] == 6
    assert result["independent_correct"] == 0
    assert result["strength_total"] < 0
    # LET_RUN's first readable wrong answer with working has no tutor opportunity.
    assert result["tutor_requests"] == result["degraded_turns"] == 0


def test_help_seeker_receives_help_before_first_answer_and_earns_no_credit(dependencies):
    tutor = FakeTutor()
    result = run_persona_smoke(tutor=tutor, **dependencies)["help_seeker"]
    assert result["sessions_run"] == 2
    assert result["items_completed"] == result["submissions"] == result["attempts"] == 6
    assert result["declines"] == result["cold_wrong"] == 0
    assert result["assisted_correct"] == 6
    assert result["strength_total"] == 0
    assert result["tutor_requests"] == result["tutor_turns"] == 6
    assert result["help_events"] == result["rungs_used"] == 6
    assert result["degraded_turns"] == result["traced_turns"] == 0
    for context in tutor.contexts_seen:
        assert context.interaction.kind is InteractionKind.TASK_QUESTION
        assert context.interaction.status is WorkStatus.DRAFT
        assert context.interaction.steps and context.interaction.answer.is_blank
        assert context.interaction.question
        assert not context.verification.answer_checked
        assert context.task_progress.submissions == context.task_progress.genuine_attempts == 0
        assert context.task_progress.declines == 0
        scope = context.history_scope
        assert scope.student_id == "help_seeker"
        assert all(r.session_id == scope.session_id and r.student_id == scope.student_id
                   for r in context.history)
        assert context.history[-1].kind is HistoryKind.STUDENT_QUESTION
    assert len({c.history_scope.session_id for c in tutor.contexts_seen}) == 2


def test_delivered_none_rung_contaminates_without_advancing_the_ladder(dependencies):
    tutor = FakeTutor([TutorTurn("Consider your current working.", HelpRung.NONE)] * 6)
    result = run_persona_smoke(tutor=tutor, **dependencies)["help_seeker"]
    assert result["help_events"] == result["tutor_turns"] == 6
    assert result["rungs_used"] == 0
    assert result["assisted_correct"] == 6
    assert result["strength_total"] == 0


class SilentTutor(FakeTutor):
    def respond(self, context, *, feedback=None):
        self.contexts_seen.append(context)
        return None


def test_silent_exchanges_complete_both_terms_without_fictitious_assistance(dependencies):
    result = run_persona_smoke(tutor=SilentTutor(), contract=IMMEDIATE, **dependencies)
    for persona in result.values():
        assert persona["items_completed"] == 6
        assert persona["tutor_requests"] == persona["degraded_turns"] == persona["silent_turns"] == 6
        assert persona["tutor_turns"] == persona["help_events"] == persona["rungs_used"] == 0
        assert persona["declines"] == persona["exhausted_turns"] == 0
    assert result["help_seeker"]["independent_correct"] == 6
    assert result["help_seeker"]["strength_total"] > 0
    assert result["diligent"]["cold_wrong"] == 6
    assert result["diligent"]["assisted_correct"] == 6


def test_rejected_drafts_exhaust_privately_without_consuming_help(dependencies):
    tutor = FakeTutor([TutorTurn("Private rejected draft.", HelpRung.FULL_REVEAL)] * 24)
    result = run_persona_smoke(tutor=tutor, contract=IMMEDIATE, **dependencies)
    for persona in result.values():
        assert persona["items_completed"] == 6
        assert persona["degraded_turns"] == persona["exhausted_turns"] == 6
        assert persona["silent_turns"] == persona["help_events"] == persona["rungs_used"] == 0
        assert persona["tutor_attempts"] == 12
    assert result["help_seeker"]["strength_total"] > 0
    assert all("Private rejected" not in str(context.history) for context in tutor.contexts_seen)


@pytest.mark.parametrize("reply,metric", [
    (Reply([], status=400), "error_turns"),
    (final(elapsed=16), "exhausted_turns"),
])
def test_real_adapter_failure_traces_are_counted_per_request_and_terms_complete(dependencies, reply, metric):
    tutor, sdk, traces, monotonic = setup([reply] * 4)
    clock = FakeClock()
    before = clock.now()
    result = run_persona_smoke(tutor=tutor, contract=IMMEDIATE, clock=clock,
                               sessions=1, items_per_session=2, **dependencies)
    assert len(traces) == len(sdk.requests) == 4
    for persona in result.values():
        assert persona["items_completed"] == 2
        assert persona[metric] == persona["degraded_turns"] == persona["traced_turns"] == 2
        assert persona["model_calls"] == 2
        assert persona["help_events"] == persona["tutor_turns"] == 0
    assert result["help_seeker"]["strength_total"] > 0
    assert clock.now() == before  # Pedagogical time never follows provider elapsed time.
    assert monotonic.now == (64 if metric == "exhausted_turns" else 0)


@pytest.mark.parametrize("key,declines", [("(", 0), ("", 6)])
def test_bad_key_abandons_bounded_tasks_instead_of_claiming_completions(dependencies, key, declines):
    class BadKey(SympyVerifier):
        def key_submission(self, spec):
            return Submission.of(key)

    values = {**dependencies, "verifiers": {kind: BadKey() for kind in dependencies["verifiers"]}}
    result = run_persona_smoke(tutor=SilentTutor(), **values)
    for persona in result.values():
        assert persona["sessions_run"] == 2
        assert persona["items_completed"] == 0
        assert persona["items_abandoned"] == 6
        assert persona["declines"] == declines
    assert result["diligent"]["attempts"] == 6
    assert result["diligent"]["submissions"] == 6 + declines
    assert result["help_seeker"]["attempts"] == 0
    assert result["help_seeker"]["submissions"] == declines


def test_recovered_provider_retry_is_observed_without_claiming_a_degraded_delivery(dependencies):
    tutor, sdk, traces, _ = setup([Reply([], status=500), final()])
    result = run_persona_smoke(tutor=tutor, sessions=1, items_per_session=1,
                               **dependencies)["help_seeker"]
    assert result["items_completed"] == result["help_events"] == result["tutor_turns"] == 1
    assert result["model_calls"] == 2
    assert result["api_retries"] == result["api_errors"] == 1
    assert result["degraded_turns"] == result["error_turns"] == 0
    assert result["strength_total"] == 0
    assert len(sdk.requests) == 2 and len(traces) == 1


def test_repeated_seed_and_defaults_produce_identical_keyless_results(dependencies):
    first = run_persona_smoke(tutor=FakeTutor(), **dependencies)
    assert first == run_persona_smoke(tutor=FakeTutor(), seed=11, sessions=2,
                                      items_per_session=3, **dependencies)
    assert all(isinstance(value, float) for result in first.values() for value in result.values())
