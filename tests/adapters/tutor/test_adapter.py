"""SDK-boundary regressions: history, pairing, shared budgets and private traces."""
from dataclasses import replace
import json
import logging

import pytest

from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
from learnai.adapters.tutor.anthropic.routing import BudgetProfile, Route
from learnai.adapters.tutor.runtime import TerminationReason
from learnai.domain.enums import HelpRung
from learnai.domain.turn import RejectionReason, TurnFeedback, ValidationResult, request_validated_turn
from tests.adapters.tutor.test_rendering import make_context, record
from tests.domain.test_engine import CLUSTER, build
from tests.domain.test_interaction import question
from tests.support.scripted_client import FakeMonotonic, Reply, ScriptedAnthropic, final, tool

PROFILE = BudgetProfile(8, 15, 8, 16, 8192, 40000, 1024)
THINKING = {"type": "thinking", "thinking": "Provider supplied", "signature": "opaque-signature"}


def setup(replies, *, profile=PROFILE, clock=None, count_tokens=lambda text: len(text) // 4, stream=False):
    clock = clock or FakeMonotonic()
    sdk = ScriptedAnthropic(replies, clock=clock)
    traces = []
    route = Route("tutor_dialogue", "anthropic", "scripted", thinking="adaptive", effort="medium",
                  prompt="tutor_math@1", max_tokens=2048, stream=stream)
    tutor = AnthropicTutor({route.name: route}, sdk.client, GeneratorRegistry(()), {},
        budget_profiles={"normal": profile}, monotonic=clock, count_tokens=count_tokens,
        trace_sink=traces.append, sleep=clock.sleep)
    return tutor, sdk, traces, clock


def results(request):
    return [b for m in request["messages"] if isinstance(m["content"], list)
            for b in m["content"] if b["type"] == "tool_result"]


def test_two_tool_round_trips_preserve_original_history_and_results():
    tutor, sdk, traces, _ = setup([
        Reply([THINKING, tool("check_expression", {"expression": "x+x", "reference": "2*x"})]),
        Reply([tool("get_student_summary")]), final()])
    assert tutor.respond(make_context()).message == "Compare your two lines."
    third = sdk.requests[2]
    assert third["messages"][0] == sdk.requests[0]["messages"][0]
    assert "Why does my second line work?" in third["messages"][0]["content"]
    assert third["messages"][1]["content"][0] == THINKING
    assert [r["tool_use_id"] for r in results(third)] == ["tool-1-1", "tool-2-0"]
    assert json.loads(results(third)[0]["content"])["equivalent"] is True
    assert traces[0].model_calls == 3 and traces[0].tool_calls == 2
    assert len(tutor.usages) == 3


def test_validation_retry_keeps_the_same_tool_exchange():
    tutor, sdk, traces, _ = setup([Reply([tool("check_expression", {"expression": "x", "reference": "x"})]),
        final("PRIVATE_REJECTED", "FULL_REVEAL"), final("Look at your earlier line.")])
    engine, session, _ = build(tutor)
    changed, delivered = engine.ask_question(session, {}, question(session.current_task))
    assert delivered.message == "Look at your earlier line."
    retry = sdk.requests[2]
    assert retry["messages"][0] == sdk.requests[0]["messages"][0]
    assert [r["tool_use_id"] for r in results(retry)] == ["tool-1-0", "tool-2-0"]
    assert results(retry)[1]["is_error"] is True
    assert "RUNG_EXCEEDED" in json.dumps(retry["messages"])
    assert len(traces) == 1 and traces[0].validation_retries == 1
    assert [r.accepted for r in traces[0].validation_results] == [False, True]
    assert "PRIVATE_REJECTED" not in str(changed.history)


def test_format_and_budget_errors_settle_pending_tool_calls():
    tutor, sdk, traces, _ = setup([Reply([THINKING, tool("submit_turn", {"message": 3})]),
        Reply([THINKING, tool("get_student_summary")], elapsed=9), final(submit=False)])
    assert tutor.respond(make_context()) is not None
    third = sdk.requests[2]
    assert [r["tool_use_id"] for r in results(third)] == ["tool-1-1", "tool-2-1"]
    assert all(r["is_error"] for r in results(third))
    assert third["messages"][1]["content"][0] == THINKING
    assert third["messages"][4]["content"][0] == THINKING
    assert traces[0].format_retries == 1


def test_soft_threshold_reserves_final_response():
    tutor, sdk, traces, _ = setup([Reply([tool("get_student_summary")], elapsed=9), final(submit=False)])
    assert tutor.respond(make_context()) is not None
    assert sdk.requests[1]["tool_choice"] == {"type": "none"}
    assert sdk.requests[1]["tools"] == sdk.requests[0]["tools"]
    assert sdk.requests[1]["output_config"]["format"]["type"] == "json_schema"
    assert sdk.requests[1]["max_tokens"] >= PROFILE.finalization_reserve_tokens
    assert results(sdk.requests[1])[0]["is_error"] is True


def test_hard_budget_is_shared_across_all_retry_layers():
    profile = replace(PROFILE, soft_seconds=3, hard_seconds=8)
    tutor, sdk, traces, clock = setup([final("PRIVATE_REJECTED", "FULL_REVEAL", elapsed=7),
        Reply([], status=500), final(elapsed=1, submit=False)], profile=profile)
    engine, session, domain_clock = build(tutor)
    before = domain_clock.now()
    _, delivered = engine.ask_question(session, {}, question(session.current_task))
    assert delivered is None
    assert len(sdk.requests) <= 3
    assert all(max(timeout.values()) <= 1 for timeout in sdk.timeouts[1:])
    assert sum(clock.sleeps) <= 1
    assert domain_clock.now() == before
    assert traces[0].termination_reason is TerminationReason.DEADLINE
    assert traces[0].accepted is None


def test_parallel_calls_are_distinct_from_model_round_trips():
    profile = replace(PROFILE, max_tool_calls=2, max_round_trips=2)
    tutor, sdk, traces, _ = setup([Reply([tool("get_student_summary") for _ in range(3)]), final(submit=False)], profile=profile)
    assert tutor.respond(make_context()) is not None
    paired = results(sdk.requests[1])
    assert [r["is_error"] for r in paired] == [False, False, True]
    assert traces[0].model_calls == 2 and traces[0].tool_calls == 2
    assert sdk.requests[1]["tool_choice"]["type"] == "none"


def test_total_token_reserve_includes_thinking_and_retries():
    profile = replace(PROFILE, max_output_tokens=2500, finalization_reserve_tokens=500)
    tutor, sdk, traces, _ = setup([
        Reply([THINKING, tool("get_student_summary")], output_tokens=1800),
        Reply([THINKING, tool("submit_turn", {})], output_tokens=200), final(output_tokens=400, submit=False)], profile=profile)
    assert tutor.respond(make_context()) is not None
    assert [r["max_tokens"] for r in sdk.requests] == [2000, 200, 500]
    assert sdk.requests[2]["tool_choice"]["type"] == "none"
    assert sum(u.output_tokens for u in tutor.usages) == 2400
    assert traces[0].output_tokens == 2400


def test_concurrent_exchange_history_is_isolated():
    a = make_context(history=(record("a", message="A_PRIVATE"),))
    b_scope = replace(a.history_scope, student_id="b", session_id="b-session")
    b = replace(a, history_scope=b_scope, history=(replace(record("b", message="B_PRIVATE"),
        student_id="b", session_id="b-session"),))
    tutor, sdk, traces, _ = setup([final("A draft", "FULL_REVEAL"),
        Reply([tool("get_session_history")]), final("B reply"),
        Reply([tool("get_session_history")]), final("A reply")])
    ea, eb = tutor.begin_turn(a), tutor.begin_turn(b)
    rejected = ea.respond()
    ea.record_validation(ValidationResult(False, RejectionReason.RUNG_EXCEEDED))
    accepted_b = eb.respond()
    eb.finish(accepted=accepted_b, reason="accepted")
    accepted_a = ea.respond(feedback=TurnFeedback(RejectionReason.RUNG_EXCEEDED, None, rejected))
    ea.finish(accepted=accepted_a, reason="accepted")
    assert "A_PRIVATE" not in json.dumps(sdk.requests[2])
    assert "B_PRIVATE" not in json.dumps(sdk.requests[4])
    assert json.loads(results(sdk.requests[2])[0]["content"])["records"][0]["id"] == "b"
    assert json.loads(results(sdk.requests[4])[-1]["content"])["records"][0]["id"] == "a"
    assert [t.model_calls for t in traces] == [2, 3]
    assert traces[0].request_id != traces[1].request_id


def test_context_overflow_never_sends_truncated_work(caplog):
    tutor, sdk, traces, _ = setup([], profile=replace(PROFILE, context_input_tokens=100), count_tokens=len)
    with caplog.at_level(logging.WARNING):
        assert tutor.respond(make_context()) is None
    assert not sdk.requests
    assert traces[0].termination_reason is TerminationReason.CONTEXT_LIMIT
    assert traces[0].model_calls == 0
    assert "context_limit" in caplog.text


def test_trace_reconstructs_inputs_and_final_delivery():
    tutor, sdk, traces, _ = setup([Reply([tool("get_student_summary")]),
        final("PRIVATE_REJECTED", "FULL_REVEAL"), final("Compare your lines.")])
    engine, session, _ = build(tutor)
    interaction = question(session.current_task)
    updated, turn = engine.ask_question(session, {}, interaction)
    trace = traces[0]
    assert trace.revision == interaction.revision
    assert trace.source_ids and trace.context_view is not None
    assert trace.initial_context == sdk.requests[0]["messages"][0]["content"]
    assert trace.provider_requests == sdk.requests
    assert trace.provider_responses[0]["content"] == sdk.responses[0]["content"]
    assert trace.tool_results[0] == results(sdk.requests[1])[0]
    assert [r.accepted for r in trace.validation_results] == [False, True]
    assert trace.accepted == turn
    assert "PRIVATE_REJECTED" not in str(updated.transcript)
    assert trace.prompt_ids == ("tutor_math@1",)
    assert trace.model == "scripted"
    assert json.loads(json.dumps(trace.to_dict()))["accepted"]["message"] == turn.message


@pytest.mark.parametrize("kind", ["network", "format", "validation"])
def test_failures_degrade_without_student_evidence(kind, caplog):
    replies = {"network": [Reply([], status=500) for _ in range(5)],
               "format": [Reply([tool("submit_turn", {})]) for _ in range(5)],
               "validation": [final("PRIVATE", "FULL_REVEAL") for _ in range(5)]}[kind]
    tutor, sdk, traces, _ = setup(replies)
    engine, session, _ = build(tutor)
    before = session.current_task.help_state
    with caplog.at_level(logging.WARNING):
        updated, delivered = engine.ask_question(session, {}, question(session.current_task))
    assert delivered is None
    assert updated.current_task.help_state == before
    assert len(traces) == 1 and traces[0].accepted is None
    assert traces[0].termination_reason.value == kind + "_exhausted"
    assert caplog.text.count("tutor response unavailable") == 1
    assert len(sdk.requests) <= 3


def test_tool_errors_and_mixed_submit_are_settled_without_executing_reads():
    tutor, sdk, traces, _ = setup([Reply([tool("unknown_read")]),
        Reply([tool("submit_turn", {"message": "ignore", "rung_used": "NUDGE"}), tool("get_student_summary")]), final()])
    assert tutor.respond(make_context()) is not None
    paired = results(sdk.requests[2])
    assert len(paired) == 3 and all(r["is_error"] for r in paired)
    assert json.loads(paired[0]["content"])["code"] == "unknown_tool"
    assert traces[0].tool_calls == 1


def test_full_continuation_input_is_counted_including_tools_and_format():
    seen = []
    def counter(text):
        seen.append(text)
        return 100000 if "LARGE_TOOL_REPLY" in text else len(text) // 4
    tutor, sdk, traces, _ = setup([Reply([tool("get_session_history")])], count_tokens=counter)
    # Retrieval is full even when selection omitted older records.
    ctx = make_context(history=(record("older", task="old", message="LARGE_TOOL_REPLY"),))
    assert tutor.respond(ctx) is None
    assert len(sdk.requests) == 1
    assert traces[0].termination_reason is TerminationReason.CONTEXT_LIMIT
    assert any('"input_schema"' in text and '"output_config"' in text for text in seen)


def test_route_and_prompt_fail_fast_and_cache_prefix_stays_stable():
    tutor, sdk, _, _ = setup([Reply([tool("get_student_summary")]), final()])
    assert tutor.respond(make_context()) is not None
    assert sdk.requests[0]["system"] == sdk.requests[1]["system"]
    assert sdk.requests[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sdk.requests[0]["thinking"] == {"type": "adaptive"}
    assert sdk.requests[0]["output_config"]["effort"] == "medium"
    assert tutor.usages[0].cache_read_input_tokens == 80
    with pytest.raises(ValueError, match="unknown route"):
        AnthropicTutor({}, sdk.client, GeneratorRegistry(()), {}, route_name="missing")


def test_stream_preserves_raw_thinking_tools_events_and_usage():
    tutor, sdk, traces, _ = setup([Reply([THINKING, tool("get_student_summary")]), final(submit=False)], stream=True)
    assert tutor.respond(make_context()).message == "Compare your two lines."
    assert sdk.requests[1]["messages"][1]["content"][0] == THINKING
    assert any(e["type"] == "content_block_delta" and e["delta"]["type"] == "signature_delta" for e in tutor.events_seen)
    assert len(tutor.usages) == 2 and sum(u.output_tokens for u in tutor.usages) == 80
    assert len(traces[0].provider_responses) == 2


def test_expired_stream_closes_and_accounts_observed_usage_without_delivery():
    tutor, sdk, traces, _ = setup([Reply([THINKING, tool("get_student_summary")], stream_elapsed=16)], stream=True)
    assert tutor.respond(make_context()) is None
    assert traces[0].termination_reason is TerminationReason.DEADLINE
    assert len(sdk.requests) == 1
    assert tutor.usages[0].output_tokens == 2
    assert traces[0].output_tokens == 2


def test_disconnected_stream_is_typed_and_keeps_observed_usage(caplog):
    tutor, sdk, traces, _ = setup([Reply([THINKING], stream_error=True)], stream=True)
    with caplog.at_level(logging.WARNING):
        assert tutor.respond(make_context()) is None
    assert len(sdk.requests) == 1
    assert traces[0].termination_reason is TerminationReason.NETWORK_EXHAUSTED
    assert tutor.usages[0].output_tokens == 2
    assert "network_exhausted" in caplog.text


@pytest.mark.parametrize(("stop_reason", "expected"), [("refusal", TerminationReason.REFUSAL),
    ("max_tokens", TerminationReason.TRUNCATED)])
def test_provider_stop_reasons_never_deliver_even_parseable_text(stop_reason, expected):
    reply = final(submit=False, output_tokens=120)
    reply.stop_reason = stop_reason
    tutor, sdk, traces, _ = setup([reply])
    assert tutor.respond(make_context()) is None
    assert traces[0].termination_reason is expected
    assert traces[0].output_tokens == 120
    assert len(sdk.requests) == 1


def test_api_bad_request_is_not_retried_and_sdk_hidden_retries_are_disabled():
    tutor, sdk, traces, _ = setup([Reply([], status=400)])
    assert tutor.respond(make_context()) is None
    assert len(sdk.requests) == 1
    assert traces[0].termination_reason is TerminationReason.API_ERROR
    tutor, sdk, traces, _ = setup([Reply([], status=500) for _ in range(10)])
    tutor = AnthropicTutor(tutor.routes, sdk.client.with_options(max_retries=8), GeneratorRegistry(()), {},
        budget_profiles={"normal": PROFILE}, monotonic=sdk.clock, sleep=sdk.clock.sleep, trace_sink=traces.append)
    assert tutor.respond(make_context()) is None
    assert len(sdk.requests) == 3
    assert traces[0].model_calls == 3


def test_parallel_reads_count_three_individual_calls():
    tutor, sdk, traces, _ = setup([Reply([tool("get_student_summary") for _ in range(3)]), final()])
    assert tutor.respond(make_context()) is not None
    assert traces[0].tool_calls == 3 and traces[0].model_calls == 2
    assert len(results(sdk.requests[1])) == 3
    assert all(not r["is_error"] for r in results(sdk.requests[1]))


def test_deadline_during_tool_settles_all_calls_and_never_continues(monkeypatch):
    from learnai.adapters.tutor.tools import Toolbox
    tutor, sdk, traces, clock = setup([Reply([tool("get_student_summary") for _ in range(2)])])
    original = Toolbox.execute
    def slow_tool(self, name, arguments, context):
        clock.advance(16)
        return original(self, name, arguments, context)
    monkeypatch.setattr(Toolbox, "execute", slow_tool)
    assert tutor.respond(make_context()) is None
    assert traces[0].termination_reason is TerminationReason.DEADLINE
    assert traces[0].tool_calls == 1 and len(traces[0].tool_results) == 2
    assert traces[0].tool_results[1]["is_error"] is True
    assert len(sdk.requests) == 1


def test_deadline_during_engine_validation_suppresses_accepted_draft(monkeypatch):
    import learnai.domain.turn as domain_turn
    tutor, sdk, traces, clock = setup([final()])
    engine, session, _ = build(tutor)
    original = domain_turn.validate_turn
    def slow_validate(*args):
        result = original(*args)
        clock.advance(16)
        return result
    monkeypatch.setattr(domain_turn, "validate_turn", slow_validate)
    _, delivered = engine.ask_question(session, {}, question(session.current_task))
    assert delivered is None
    assert traces[0].termination_reason is TerminationReason.DEADLINE
    assert traces[0].validation_results[0].accepted
    assert traces[0].accepted is None
    assert traces[0].tool_results[0]["is_error"] is True


def test_round_trip_ceiling_stops_format_retries_before_an_extra_call():
    profile = replace(PROFILE, max_round_trips=2)
    tutor, sdk, traces, _ = setup([Reply([tool("submit_turn", {})]),
        Reply([{"type": "text", "text": "invalid json"}])], profile=profile)
    assert tutor.respond(make_context()) is None
    assert traces[0].termination_reason is TerminationReason.ROUND_TRIP_LIMIT
    assert len(sdk.requests) == 2
    assert sdk.requests[1]["tool_choice"]["type"] == "none"
    assert traces[0].tool_results[0]["is_error"] is True


def test_provider_output_overrun_is_accounted_but_never_delivered():
    tutor, sdk, traces, _ = setup([final(output_tokens=9000)])
    assert tutor.respond(make_context()) is None
    assert traces[0].termination_reason is TerminationReason.OUTPUT_LIMIT
    assert traces[0].output_tokens == 9000
    assert len(sdk.requests) == 1
    assert traces[0].tool_results[0]["is_error"] is True


def test_prompts_and_profiles_fail_before_any_provider_call(tmp_path):
    tutor, sdk, _, _ = setup([])
    with pytest.raises(ValueError, match="cannot read prompt"):
        AnthropicTutor(tutor.routes, sdk.client, GeneratorRegistry(()), {}, prompts_root=tmp_path)
    with pytest.raises(ValueError, match="unknown budget profile"):
        AnthropicTutor(tutor.routes, sdk.client, GeneratorRegistry(()), {}, budget_profiles={})
    assert not sdk.requests


def test_response_job_selects_route_and_direct_override_remains_available():
    from learnai.domain.interaction import ResponseJob
    tutor, sdk, traces, _ = setup([final()])
    normal = tutor.routes["tutor_dialogue"]
    brief = replace(normal, name="tutor_brief", effort="low", budget_profile="brief")
    routes = {normal.name: normal, brief.name: brief}
    tutor = AnthropicTutor(routes, sdk.client, GeneratorRegistry(()), {}, trace_sink=traces.append,
        monotonic=sdk.clock, sleep=sdk.clock.sleep)
    assert tutor.respond(make_context(response_job=ResponseJob.BRIEF)) is not None
    assert sdk.requests[0]["output_config"]["effort"] == "low"
    assert traces[0].elapsed_seconds == 0
    with pytest.raises(ValueError, match="tutor_complex"):
        tutor.begin_turn(make_context(response_job=ResponseJob.COMPLEX))
    sdk = ScriptedAnthropic([final()])
    tutor = AnthropicTutor(routes, sdk.client, GeneratorRegistry(()), {}, route_name="tutor_brief")
    assert tutor.respond(make_context(response_job=ResponseJob.COMPLEX)) is not None
    assert sdk.requests[0]["output_config"]["effort"] == "low"


def test_attempt_usage_completeness_distinguishes_missing_from_complete_zero():
    tutor, sdk, traces, _ = setup([Reply([], status=500), final(output_tokens=0)])
    assert tutor.respond(make_context()) is not None
    attempts = traces[0].to_dict()["attempts"]
    assert [a["usage_status"] for a in attempts] == ["missing", "complete"]
    assert [a["request_index"] for a in attempts] == [0, 1]
    assert attempts[0]["usage"] is None
    assert attempts[1]["usage"]["output_tokens"] == 0
    assert attempts[1]["provider_request_id"] == "req-2"


def test_partial_zero_stream_usage_is_not_treated_as_complete_zero():
    tutor, sdk, traces, _ = setup([Reply([THINKING], stream_error=True, initial_output_tokens=0)], stream=True)
    assert tutor.respond(make_context()) is None
    attempt = traces[0].to_dict()["attempts"][0]
    assert attempt["usage_status"] == "partial"
    assert attempt["usage"]["output_tokens"] == 0
    assert tutor.usages[0].output_tokens == 0


def test_stream_eof_without_message_stop_has_partial_usage_and_is_not_retried():
    tutor, sdk, traces, _ = setup([Reply([THINKING], stream_truncated=True)], stream=True)
    assert tutor.respond(make_context()) is None
    assert len(sdk.requests) == 1
    assert traces[0].termination_reason is TerminationReason.NETWORK_EXHAUSTED
    assert traces[0].model_calls == 1
    assert traces[0].to_dict()["attempts"][0]["usage_status"] == "partial"
