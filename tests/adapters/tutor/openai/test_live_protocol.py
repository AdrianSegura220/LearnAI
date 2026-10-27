"""Offline checks for live-probe trace interpretation; no live body is executed."""
from tests.adapters.tutor.openai.test_adapter import setup
from tests.adapters.tutor.openai.test_live import _assert_accepted_protocol
from tests.adapters.tutor.test_adapter_engine import draft
from tests.domain.test_engine import build
from tests.support.scripted_openai import ResponseReply, final


def test_live_protocol_accepts_api_retry_before_engine_correction():
    tutor, sdk, traces = setup([ResponseReply(http_status=500),
        final('Rejected reveal.', 'FULL_REVEAL'), final('Compare your current line.')])
    try:
        engine, session, _ = build(tutor)
        _, turn = engine.ask_question(session, {}, draft(session))
        assert turn is not None
        assert traces[0].api_retries == 1 and traces[0].validation_retries == 1
        _assert_accepted_protocol(tutor, traces[0])
    finally:
        sdk.client.close()
