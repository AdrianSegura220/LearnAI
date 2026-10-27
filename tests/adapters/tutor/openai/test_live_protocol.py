"""Offline checks for live-probe trace interpretation; no live body is executed."""
from dataclasses import replace

import pytest

from learnai.adapters.tutor.openai.config import resolve_config
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES

from tests.adapters.tutor.openai.test_adapter import setup
from tests.adapters.tutor.openai.test_live import _assert_accepted_protocol
from tests.adapters.tutor.test_adapter_engine import draft
from tests.domain.test_engine import build
from tests.support.scripted_openai import ResponseReply, call, current_usage, final


@pytest.mark.parametrize('api_profile', ['legacy', 'current', 'reasoning'])
def test_live_protocol_accepts_api_retry_before_engine_correction(api_profile):
    tutor, sdk, traces = setup([ResponseReply(http_status=500),
        final('Rejected reveal.', 'FULL_REVEAL'), final('Compare your current line.')],
        options={'api_profile': api_profile})
    tutor.config = resolve_config(replace(tutor.config.route, effort=None), role='tutor',
        profiles=DEFAULT_BUDGET_PROFILES, prompts_root=PROMPTS_ROOT)
    try:
        engine, session, _ = build(tutor)
        _, turn = engine.ask_question(session, {}, draft(session))
        assert turn is not None
        assert traces[0].api_retries == 1 and traces[0].validation_retries == 1
        _assert_accepted_protocol(tutor, traces[0])
    finally:
        sdk.client.close()


def test_live_protocol_accepts_reduced_output_cap_after_tool_turns():
    replies = [ResponseReply([call('get_student_summary', call_id=f'call-{index}',
        id=f'fc-{index}')], usage=current_usage(output_tokens=1900)) for index in range(3)]
    tutor, sdk, traces = setup([*replies, final(usage=current_usage())],
        options={'api_profile': 'current'})
    try:
        engine, session, _ = build(tutor)
        _, turn = engine.ask_question(session, {}, draft(session))
        assert turn is not None and turn == traces[0].accepted
        assert [request['max_output_tokens'] for request in sdk.requests] == [2048, 2048, 2048, 1468]
        for request, response in zip(sdk.requests, sdk.responses, strict=True):
            assert response['usage']['output_tokens'] <= request['max_output_tokens']
        _assert_accepted_protocol(tutor, traces[0])
    finally:
        sdk.client.close()
