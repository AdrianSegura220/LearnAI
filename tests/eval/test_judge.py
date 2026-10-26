"""Judge packet isolation, strict scores, and offline real-SDK boundary tests."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from learnai.adapters.tutor.anthropic.prompt import build_prompt
from learnai.adapters.tutor.anthropic.routing import BudgetProfile, Route, load_routes
from learnai.adapters.tutor.prompts import load_prompt
from learnai.adapters.tutor.runtime import UsageStatus
from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.history import HistoryKind
from learnai.domain.interaction import VerificationSnapshot
from learnai.domain.items import Submission
from learnai.domain.turn import TutorTurn
from learnai.eval.judge import (
    JudgeError, JudgePacket, JudgeReference, JudgeScores, build_judge_messages,
    parse_scores,
)
from learnai.adapters.tutor.anthropic.judge import run_judge
from tests.adapters.tutor.test_rendering import make_context, record
from tests.support.scripted_client import FakeMonotonic, Reply, ScriptedAnthropic

ROOT = Path(__file__).resolve().parents[2]
PROFILE = BudgetProfile(8, 15, 8, 16, 8192, 50000, 1024)


class ScriptedJudge(ScriptedAnthropic):
    """Reuse tutor script sequencing, adapting its tool-only test assertions.

    Production judge requests have no tools. Capture the actual wire request
    before providing empty tools to the existing transport's validator.
    """
    def __init__(self, replies, **kwargs):
        super().__init__(replies, **kwargs)
        self.wire_requests = []

    def _validate(self, request):
        self.wire_requests.append(deepcopy(request))
        request.setdefault("tools", [])
        request.setdefault("tool_choice", {"type": "none"})
        return super()._validate(request)


def packet(**changes):
    context = make_context(
        verification=VerificationSnapshot(1, True, False, Verdict.WRONG, None, None),
        history=(record("prior-hint", kind=HistoryKind.TUTOR_DELIVERED,
                        message="Try multiplying the factors back out."),),
    )
    reference = JudgeReference(
        Submission.of("(x+1)*(x+2)"),
        ("Find two integers with product 2 and sum 3.", "Expand to verify the factors."),
        "curated:factoring@1; item-active; hand-checked",
        "Compare the product and sum; accept completing the square too.",
        ("Multiplying constants alone omits the cross terms.",),
        ("Answer why the second line works; avoid repeating the earlier hint.",),
    )
    return replace(JudgePacket(context, TutorTurn("Expand to check your factors.", HelpRung.NUDGE),
                               reference, None, ()), **changes)


def score_data(**changes):
    return dict(mathematics=2, help_level=1, diagnosis=2, tone=2,
                reasons=["The hint addresses the student's factorisation question."],
                status="scored", missing_information=[], **changes)


def reply(data=None, **kwargs):
    return Reply([{"type": "text", "text": json.dumps(score_data() if data is None else data)}], **kwargs)


def setup(replies, *, route=None):
    clock = FakeMonotonic()
    sdk = ScriptedJudge(replies, clock=clock)
    route = route or Route("rubric_judge", "anthropic", "scripted", thinking="adaptive", effort="high",
                           prompt="rubric_judge@1", max_tokens=2048)
    traces = []
    options = dict(budget_profiles={route.budget_profile: PROFILE}, monotonic=clock,
                   count_tokens=lambda text: len(text) // 4, sleep=clock.sleep, trace_sink=traces.append)
    return sdk, {route.name: route}, options, traces, clock


def test_packet_preserves_student_moment():
    data = json.loads(build_judge_messages(packet())[0]["content"])
    situation = data["student_situation"]
    moment = situation["moment"]
    assert moment["exercise"]["instructions"] == "Factor fully:\nx^2 + 3*x + 2\nShow working."
    assert moment["exercise"]["form_constraints"] == ["fully_factored"]
    work = moment["interaction"]
    assert work["question"] == "Why does my second line work?"
    assert work["steps"] == ["x^2 + 3*x + 2", "(x+1)*(x+2)"]
    assert work["answer"]["fields"] == ["  (x+1)*(x+2)  ", ""]
    assert work["revision"] == 2 and work["status"] == "DRAFT"
    assert not work["verification"]["answer_checked"]
    assert work["historical_verification"]["revision"] == 1
    assert work["historical_verification"]["verdict"] == "WRONG"
    assert moment["progress"]["last_checked_revision"] == 1
    assert moment["permitted_rung"] == "NUDGE"
    assert situation["history"][0]["message"] == "Try multiplying the factors back out."
    assert situation["history"][0]["id"] == "prior-hint"
    assert situation["history_scope"] == {"student_id": "student", "session_id": "session"}
    assert data["candidate_response"]["message"] == "Expand to check your factors."


def test_reference_is_evaluator_only():
    p = packet()
    before = build_prompt(p.context, "policy", input_budget=50000, count_tokens=len)
    messages = build_judge_messages(p)
    data = json.loads(messages[0]["content"])
    reference = data["evaluator_reference"]
    assert reference["answer"] == {"fields": ["(x+1)*(x+2)"], "claims_none": False}
    assert reference["provenance"] == "curated:factoring@1; item-active; hand-checked"
    assert reference["reasoning"] == ["Find two integers with product 2 and sum 3.", "Expand to verify the factors."]
    assert "completing the square" in reference["teaching_notes"]
    assert reference["criteria"] == ["Answer why the second line works; avoid repeating the earlier hint."]
    student = json.dumps(data["student_situation"])
    for text in (p.reference.provenance, *p.reference.reasoning, p.reference.teaching_notes,
                 *p.reference.criteria, *p.reference.misconception_explanations):
        assert text not in student
        assert text not in str(before)
    assert build_prompt(p.context, "policy", input_budget=50000, count_tokens=len) == before
    assert "SECRET_REFERENCE" not in str(messages) and "SECRET_WORKED_SOLUTION" not in str(messages)
    with pytest.raises(FrozenInstanceError):
        p.reference.provenance = "altered"


def test_unknown_information_is_explicit():
    p = packet(reference=replace(packet().reference, reasoning=()))
    data = json.loads(build_judge_messages(p)[0]["content"])
    assert data["student_situation"]["learner_level"] is None
    assert "learner_level" in data["missing_information"]
    assert "reference.reasoning" in data["missing_information"]
    assert data["evaluator_reference"]["reasoning"] == []
    assert "age" not in data["student_situation"]
    # Optional gaps do not deterministically force whole-turn abstention.
    assert parse_scores(json.dumps(score_data())).status == "scored"


def test_rubric_uses_ceiling_and_allows_no_diagnosis():
    # Explicit task-required prompt contract; this does not measure judge quality.
    prompt = load_prompt("rubric_judge@1").text.lower()
    for requirement in ("ceiling", "no diagnosis", "unverified is not wrong", "alternative",
                        "age", "warmth", "insufficient_evidence", "engine acceptance",
                        "data", "instructions", "private", "reference", "missing_information"):
        assert requirement in prompt


@pytest.mark.parametrize("value", [0, 1, 2])
def test_score_schema_accepts_each_integer(value):
    data = score_data()
    for name in ("mathematics", "help_level", "diagnosis", "tone"):
        data[name] = value
    scores = parse_scores("```json\n" + json.dumps(data) + "\n```")
    assert (scores.mathematics, scores.help_level, scores.diagnosis, scores.tone) == (value,) * 4
    assert scores.reasons == ("The hint addresses the student's factorisation question.",)


def test_score_schema_accepts_named_whole_turn_abstention():
    data = score_data()
    data.update(mathematics=None, help_level=None, diagnosis=None, tone=None,
                status="insufficient_evidence", missing_information=["reference.answer"],
                reasons=["There is no defensible correctness reference."])
    result = parse_scores(json.dumps(data))
    assert result.status == "insufficient_evidence" and result.mathematics is None
    assert result.missing_information == ("reference.answer",)


@pytest.mark.parametrize("field,value", [
    ("mathematics", True), ("help_level", False), ("diagnosis", 1.0), ("tone", "2"),
    ("mathematics", -1), ("tone", 3), ("help_level", None), ("status", "maybe"),
    ("status", []), ("reasons", "good"), ("reasons", []), ("reasons", [""]),
    ("reasons", [2]), ("missing_information", "age"), ("missing_information", [False]),
    ("missing_information", ["  "]),
])
def test_score_schema_rejects_wrong_types_ranges_and_status(field, value):
    data = score_data()
    data[field] = value
    with pytest.raises(JudgeError):
        parse_scores(json.dumps(data))


@pytest.mark.parametrize("key", list(score_data()))
def test_score_schema_requires_every_key(key):
    data = score_data()
    del data[key]
    with pytest.raises(JudgeError):
        parse_scores(json.dumps(data))


@pytest.mark.parametrize("data", [
    {**score_data(), "extra": 1},
    {**score_data(), "status": "insufficient_evidence", "mathematics": None,
     "missing_information": ["reference.answer"]},
    {**score_data(), "mathematics": None, "help_level": None, "diagnosis": None, "tone": None},
    {**score_data(), "status": "insufficient_evidence", "mathematics": None,
     "help_level": None, "diagnosis": None, "tone": None},
    [], None, 2,
])
def test_score_schema_rejects_unknown_keys_and_inconsistent_nulls(data):
    with pytest.raises(JudgeError):
        parse_scores(json.dumps(data))


@pytest.mark.parametrize("text", ["not json", "{} trailing", '{"mathematics":2,"mathematics":0}', "`````", ""])
def test_score_schema_rejects_malformed_text(text):
    with pytest.raises(JudgeError):
        parse_scores(text)


def test_run_judge_uses_packet_route_and_versioned_prompt(tmp_path):
    prompt_dir = tmp_path / "custom_judge"
    prompt_dir.mkdir()
    (prompt_dir / "v2.md").write_text("CONFIGURED VERSION TWO RUBRIC", encoding="utf-8")
    route = replace(load_routes(ROOT / "config/llm_routes.yaml")["rubric_judge"], prompt="custom_judge@2")
    sdk, routes, options, traces, _ = setup([reply()], route=route)
    result = run_judge(sdk.client, routes, packet=packet(), prompts_root=tmp_path, **options)
    assert result == JudgeScores(2, 1, 2, 2, ("The hint addresses the student's factorisation question.",))
    request = sdk.requests[0]
    assert request["model"] == route.model
    assert request["system"] == "CONFIGURED VERSION TWO RUBRIC"
    assert json.loads(request["messages"][0]["content"])["candidate_response"]["message"] == "Expand to check your factors."
    assert request["max_tokens"] == route.max_tokens
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"]["effort"] == "high"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "tools" not in sdk.wire_requests[0] and "tool_choice" not in sdk.wire_requests[0]
    assert "temperature" not in request
    assert traces[0].prompt_ids == ("custom_judge@2",)
    assert traces[0].attempts[0].usage_status is UsageStatus.PARTIAL
    assert "cache creation duration unknown" in traces[0].attempts[0].normalized_usage.reasons
    assert traces[0].attempts[0].usage["cache_read_input_tokens"] == 80
    assert traces[0].attempts[0].provider_request_id == "req-1"
    assert traces[0].attempts[0].response_model == route.model


@pytest.mark.parametrize("bad_route", ["missing", "absent_prompt", "temperature"])
def test_run_judge_configuration_failure_is_error_before_api(bad_route, tmp_path):
    sdk, routes, options, traces, _ = setup([])
    if bad_route == "missing":
        routes = {}
    elif bad_route == "absent_prompt":
        routes = {"rubric_judge": replace(routes["rubric_judge"], prompt=None)}
    else:
        routes = {"rubric_judge": replace(routes["rubric_judge"], temperature=0)}
    with pytest.raises(JudgeError):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert not sdk.requests
    with pytest.raises(JudgeError):
        run_judge(sdk.client, setup([])[1], packet=packet(), prompts_root=tmp_path, **options)


def test_api_error_is_operational_failure_with_missing_usage_trace():
    sdk, routes, options, traces, _ = setup([Reply([], status=400)])
    with pytest.raises(JudgeError, match="api_error"):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert len(traces) == 1 and len(traces[0].attempts) == 1
    assert traces[0].attempts[0].usage_status is UsageStatus.MISSING
    assert traces[0].attempts[0].usage is None
    assert traces[0].attempts[0].provider_request_id == "req-1"


def test_api_and_format_retries_share_trace_and_budget():
    sdk, routes, options, traces, clock = setup([Reply([], status=500), reply({}), reply()])
    result = run_judge(sdk.client, routes, packet=packet(), **options)
    assert result.status == "scored"
    trace = traces[0]
    assert trace.model_calls == 3 and trace.api_retries == 1 and trace.format_retries == 1
    assert [a.usage_status for a in trace.attempts] == [UsageStatus.MISSING, UsageStatus.PARTIAL, UsageStatus.PARTIAL]
    assert trace.output_tokens == 80
    assert len(trace.provider_requests) == 3 and len(trace.provider_responses) == 2
    assert clock.sleeps == [0.25]
    assert len(sdk.requests[2]["messages"]) == 3
    assert sdk.timeouts[2]["read"] == pytest.approx(14.75)


def test_deadline_rejects_late_scores_but_retains_usage():
    sdk, routes, options, traces, _ = setup([reply(elapsed=16)])
    with pytest.raises(JudgeError, match="deadline"):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert traces[0].output_tokens == 40
    assert traces[0].attempts[0].usage_status is UsageStatus.PARTIAL
    assert "cache creation duration unknown" in traces[0].attempts[0].normalized_usage.reasons


def test_format_exhaustion_is_error_not_abstention():
    sdk, routes, options, traces, _ = setup([reply({}), reply({}), reply({})])
    with pytest.raises(JudgeError, match="format_exhausted"):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert len(traces[0].attempts) == 3 and traces[0].output_tokens == 120


def test_round_trip_limit_prevents_retry_with_one_shared_allowance():
    sdk, routes, options, traces, _ = setup([Reply([], status=500), reply()])
    options["budget_profiles"] = {"normal": replace(PROFILE, max_round_trips=1)}
    with pytest.raises(JudgeError, match="round_trip_limit"):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert len(sdk.requests) == 1 and traces[0].model_calls == 1


def test_context_limit_fails_before_provider_call():
    sdk, routes, options, traces, _ = setup([])
    options["budget_profiles"] = {"normal": replace(PROFILE, context_input_tokens=10)}
    with pytest.raises(JudgeError, match="context_limit"):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert not sdk.requests and not traces[0].attempts


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_truncated_or_refused_output_is_operational_failure(stop_reason):
    sdk, routes, options, traces, _ = setup([reply(stop_reason=stop_reason)])
    with pytest.raises(JudgeError):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert len(traces[0].attempts) == 1


def test_nested_sink_keeps_request_local_trace():
    sdk, routes, options, traces, _ = setup([reply(), reply()])
    def sink(trace):
        traces.append(trace)
        if len(traces) == 1:
            run_judge(sdk.client, routes, packet=packet(turn=TutorTurn("Nested response.", HelpRung.NUDGE)), **options)
    options["trace_sink"] = sink
    run_judge(sdk.client, routes, packet=packet(), **options)
    assert len(traces) == 2 and traces[0].request_id != traces[1].request_id
    assert [t.attempts[0].provider_request_id for t in traces] == ["req-1", "req-2"]
    assert all(t.model_calls == 1 and t.output_tokens == 40 for t in traces)


def test_streaming_judge_preserves_observed_usage_with_unknown_cache_duration():
    route = Route("rubric_judge", "anthropic", "scripted", prompt="rubric_judge@1", stream=True)
    sdk, routes, options, traces, _ = setup([reply()], route=route)
    assert run_judge(sdk.client, routes, packet=packet(), **options).mathematics == 2
    assert sdk.requests[0]["stream"] is True
    assert traces[0].attempts[0].usage_status is UsageStatus.PARTIAL
    assert "cache creation duration unknown" in traces[0].attempts[0].normalized_usage.reasons
    assert traces[0].output_tokens == 40
    assert traces[0].events[-1]["type"] == "message_stop"


@pytest.mark.parametrize("options_override", [dict(stream_error=True), dict(stream_truncated=True), dict(stream_elapsed=16)])
def test_stream_failure_keeps_partial_usage_without_retrying(options_override):
    route = Route("rubric_judge", "anthropic", "scripted", prompt="rubric_judge@1", stream=True)
    sdk, routes, options, traces, _ = setup([reply(**options_override)], route=route)
    with pytest.raises(JudgeError):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert len(sdk.requests) == 1
    assert traces[0].attempts[0].usage_status is UsageStatus.PARTIAL
    assert traces[0].attempts[0].usage["output_tokens"] == 2
    assert traces[0].attempts[0].normalized_usage.counts["output"] == 2
    assert traces[0].attempts[0].normalized_usage.status is UsageStatus.PARTIAL
    assert traces[0].output_tokens == 2


def test_usage_retains_vendor_fields_and_marks_partial_input_observation():
    import httpx2
    class PartialUsage(ScriptedJudge):
        def _handle(self, request):
            response = super()._handle(request)
            data = json.loads(response.content)
            del data["usage"]["input_tokens"]
            data["usage"]["cache_creation"] = {"ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 0}
            return httpx2.Response(200, json=data, headers=response.headers)
    sdk = PartialUsage([reply()])
    _, routes, options, traces, _ = setup([])
    assert run_judge(sdk.client, routes, packet=packet(), **options).status == "scored"
    attempt = traces[0].attempts[0]
    assert attempt.usage_status is UsageStatus.PARTIAL
    assert attempt.normalized_usage.status is UsageStatus.PARTIAL
    assert attempt.normalized_usage.counts == {"output": 40, "cache_read": 80,
                                               "cache_write_5m": 20, "cache_write_1h": 0}
    assert "input_tokens" not in attempt.usage
    assert attempt.usage["cache_creation"] == {"ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 0}


def test_absent_usage_is_not_known_zero_or_abstention():
    import httpx2
    class MissingUsage(ScriptedJudge):
        def _handle(self, request):
            response = super()._handle(request)
            data = json.loads(response.content)
            del data["usage"]
            return httpx2.Response(200, json=data, headers=response.headers)
    sdk = MissingUsage([reply()])
    _, routes, options, traces, _ = setup([])
    with pytest.raises(JudgeError, match="usage"):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert traces[0].attempts[0].usage_status is UsageStatus.MISSING
    assert traces[0].attempts[0].usage is None


def test_output_allowance_caps_format_retry_request():
    sdk, routes, options, traces, _ = setup([reply({}, output_tokens=1000), reply(output_tokens=100)])
    options["budget_profiles"] = {"normal": replace(PROFILE, max_output_tokens=1500, finalization_reserve_tokens=100)}
    assert run_judge(sdk.client, routes, packet=packet(), **options).status == "scored"
    assert [r["max_tokens"] for r in sdk.wire_requests] == [1500, 500]
    assert traces[0].output_tokens == 1100


def test_exhausted_output_allowance_prevents_format_retry():
    sdk, routes, options, traces, _ = setup([reply({}, output_tokens=1500)])
    options["budget_profiles"] = {"normal": replace(PROFILE, max_output_tokens=1500, finalization_reserve_tokens=100)}
    with pytest.raises(JudgeError, match="output_limit"):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert len(sdk.requests) == 1 and traces[0].output_tokens == 1500


def test_api_retry_exhaustion_stays_operational_error():
    sdk, routes, options, traces, _ = setup([Reply([], status=429)] * 3)
    with pytest.raises(JudgeError, match="network_exhausted"):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert len(traces[0].attempts) == 3 and traces[0].api_retries == 2
    assert all(a.usage is None for a in traces[0].attempts)


def test_scorer_uses_returned_model_not_assumed_requested_model_for_observations():
    import httpx2
    class ReturnedModel(ScriptedJudge):
        def _handle(self, request):
            response = super()._handle(request)
            data = json.loads(response.content)
            data["model"] = "provider-returned-version"
            return httpx2.Response(200, json=data, headers=response.headers)
    sdk = ReturnedModel([reply()])
    _, routes, options, traces, _ = setup([])
    run_judge(sdk.client, routes, packet=packet(), **options)
    assert traces[0].attempts[0].response_model == "provider-returned-version"
    assert traces[0].model == "scripted"


def test_malformed_provider_text_is_judge_error_with_observed_attempt():
    sdk, routes, options, traces, _ = setup([Reply([{"type": "text"}])])
    with pytest.raises(JudgeError, match="api_error"):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert len(traces[0].attempts) == 1
    assert traces[0].attempts[0].usage_status is UsageStatus.PARTIAL
    assert "cache creation duration unknown" in traces[0].attempts[0].normalized_usage.reasons


def test_missing_provider_content_is_operational_failure():
    import httpx2
    class MissingContent(ScriptedJudge):
        def _handle(self, request):
            response = super()._handle(request)
            data = json.loads(response.content)
            del data["content"]
            return httpx2.Response(200, json=data, headers=response.headers)
    sdk = MissingContent([reply()])
    _, routes, options, traces, _ = setup([])
    with pytest.raises(JudgeError, match="api_error"):
        run_judge(sdk.client, routes, packet=packet(), **options)
    assert traces[0].output_tokens == 40


@pytest.mark.parametrize("stream", [False, True])
def test_provider_wire_schema_omits_unsupported_numerical_constraints(stream):
    route = Route("rubric_judge", "anthropic", "scripted", prompt="rubric_judge@1", stream=stream)
    sdk, routes, options, _, _ = setup([reply()], route=route)
    assert run_judge(sdk.client, routes, packet=packet(), **options).mathematics == 2
    schema = sdk.wire_requests[0]["output_config"]["format"]["schema"]
    unsupported = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}

    def check_schema(value):
        if isinstance(value, dict):
            assert not unsupported.intersection(value), "unsupported numerical schema constraint on wire"
            for child in value.values():
                check_schema(child)
        elif isinstance(value, list):
            for child in value:
                check_schema(child)

    check_schema(schema)
    for dimension in ("mathematics", "help_level", "diagnosis", "tone"):
        assert schema["properties"][dimension]["type"] == ["integer", "null"]


def test_judge_response_metadata_reaches_neutral_normalization():
    import httpx2
    from learnai.adapters.tutor.observations import JudgeTrace, RequestTrace
    from learnai.adapters.tutor.anthropic.judge import JudgeTrace as CompatibilityTrace

    class MetadataJudge(ScriptedJudge):
        def _handle(self, request):
            response = super()._handle(request)
            data = response.json()
            data['service_tier'] = 'returned-tier'
            return httpx2.Response(response.status_code, json=data, headers=response.headers)

    _, routes, options, traces, clock = setup([])
    sdk = MetadataJudge([reply()], clock=clock)
    assert run_judge(sdk.client, routes, packet=packet(), **options).status == 'scored'
    trace = traces[0]
    assert CompatibilityTrace is JudgeTrace
    assert isinstance(trace, RequestTrace)
    assert trace.provider == 'anthropic' and trace.api_family == 'messages'
    observation = trace.attempts[0].normalized_usage
    assert observation.counts == {'input': 100, 'output': 40, 'cache_read': 80}
    assert observation.billing_conditions['service_tier'].value == 'returned-tier'
    assert observation.billing_conditions['service_tier'].source == 'returned'
