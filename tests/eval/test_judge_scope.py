"""Mixed storage snapshots stay private on both native SDK rejudge paths."""
from dataclasses import replace
import json

import pytest

from learnai.adapters.tutor.context import render_context, select_context
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.routing import load_budget_profiles, load_routes
from learnai.application.artifacts import load_saved_run
from learnai.domain.turn import TranscriptEntry
from learnai.eval.accounting import PriceBook, RequestLedger
from learnai.eval.artifacts import encode
from learnai.eval.judge import build_judge_messages
from learnai.eval.manifest import build_manifest, canonical_json
from learnai.eval.report import write_report
from tests.adapters.tutor.test_rendering import record
from tests.eval.test_judge import ScriptedJudge, packet, reply
from tests.adapters.tutor.openai.test_judge import scored
from tests.support.provider_contracts import scripted_factories, write_routes
from tests.support.scripted_openai import ScriptedOpenAI


@pytest.mark.parametrize('provider', ['anthropic', 'openai'])
@pytest.mark.parametrize('foreign_scope', ['student_id', 'session_id'])
@pytest.mark.parametrize('identity', ['unique', 'duplicate-current', 'foreign-current'])
@pytest.mark.parametrize('foreign_first', [False, True])
def test_saved_mixed_scope_packet_is_filtered_on_native_judge_wire(
    provider, foreign_scope, identity, foreign_first, tmp_path, monkeypatch,
):
    from learnai.eval.__main__ import main

    p = packet()
    current = record('current-question', message='PERMITTED_CURRENT', skill='permitted-current-skill')
    foreign_id = 'foreign-only' if identity == 'unique' else 'current-question'
    foreign = replace(record(foreign_id, message='FOREIGN_PRIVATE_HISTORY', skill='FOREIGN_METADATA'),
                      **{foreign_scope: 'foreign-actor'})
    permitted = (*p.context.history, record('allowed', message='PERMITTED_HISTORY'))
    if identity != 'foreign-current':
        permitted += (current,)
    history = (foreign, *permitted) if foreign_first else (*permitted, foreign)
    context = replace(p.context, history=history, transcript=(
        TranscriptEntry('student', 'PERMITTED_TRANSCRIPT', 'allowed'),
        TranscriptEntry('student', 'LEGACY_UNRECORDED_TRANSCRIPT', 'legacy-unrecorded'),
        TranscriptEntry('student', 'FOREIGN_PRIVATE_TRANSCRIPT', foreign_id),
    ))
    p = replace(p, context=context)
    original = canonical_json(encode(p))
    manifest = build_manifest(root=tmp_path, selected_ids=('case',), seeds=(),
                              settings={}, prompts={}, references={})
    source = write_report(tmp_path / 'source', manifest=manifest, outcomes={}, scores={},
        judge_packets={'case': p}, ledger=RequestLedger(), prices=PriceBook(()), persona_smoke={})
    before = {path.relative_to(source): path.read_bytes() for path in source.rglob('*') if path.is_file()}
    sdk = ScriptedJudge([reply()]) if provider == 'anthropic' else ScriptedOpenAI([scored()])
    monkeypatch.setenv(provider.upper() + '_API_KEY', 'scripted-key')
    monkeypatch.delenv(('OPENAI' if provider == 'anthropic' else 'ANTHROPIC') + '_API_KEY', raising=False)
    routes = write_routes(tmp_path, tutor_provider='anthropic', judge_provider=provider)
    factories = scripted_factories({provider: sdk})
    config = factories[provider].resolve_config(
        load_routes(routes)['rubric_judge'], role='judge', profiles=load_budget_profiles(routes),
        prompts_root=PROMPTS_ROOT,
    )
    prepared = factories[provider].prepare_judge(config, packet=p)
    assert prepared.admitted
    assert main(['rejudge', str(source), '--routes', str(routes), '--out', str(tmp_path / 'rejudged')],
                provider_factories=factories) == 0
    body = sdk.wire_requests[0] if provider == 'anthropic' else sdk.requests[0]
    payload = json.loads(body['messages' if provider == 'anthropic' else 'input'][0]['content'])
    tutor = render_context(context, select_context(context, input_budget=100000, count_tokens=len))
    for rendered in (json.dumps(payload), json.dumps(prepared.payload), tutor):
        assert 'FOREIGN_' not in rendered
        assert 'PERMITTED_HISTORY' in rendered
        assert 'LEGACY_UNRECORDED_TRANSCRIPT' in rendered
    situation = payload['student_situation']
    assert any(entry['text'] == 'PERMITTED_TRANSCRIPT' for entry in situation['transcript'])
    for moment in (situation['moment'], json.loads(tutor)['moment']):
        assert moment['interaction']['steps'] == list(context.interaction.steps)
        assert moment['interaction']['answer']['fields'] == list(context.interaction.answer.fields)
        assert moment['interaction']['question'] == context.interaction.question
        if identity == 'foreign-current':
            assert moment['current_interaction_id'] is moment['current_record'] is None
        else:
            assert moment['current_interaction_id'] == 'current-question'
            assert moment['current_record']['skill_id'] == 'permitted-current-skill'
    assert payload['candidate_response'] == {
        'message': p.turn.message, 'rung_used': 'NUDGE', 'diagnosis': None, 'proposals': [],
    }
    if identity != 'foreign-current':
        assert any(entry['message'] == 'PERMITTED_CURRENT' for entry in situation['history'])
    assert canonical_json(encode(p)) == original
    assert load_saved_run(source).packets['case'] == p
    assert {path.relative_to(source): path.read_bytes() for path in source.rglob('*') if path.is_file()} == before
    assert sdk.client.is_closed()


def test_legacy_unscoped_judge_packet_retains_history_and_transcript():
    p = packet()
    foreign = replace(record('legacy', message='LEGACY_HISTORY'), student_id='other')
    p = replace(p, context=replace(p.context, history_scope=None, history=(foreign,),
                transcript=(TranscriptEntry('student', 'LEGACY_TRANSCRIPT', foreign.id),)))
    payload = json.loads(build_judge_messages(p)[0]['content'])['student_situation']
    assert payload['history'][0]['message'] == 'LEGACY_HISTORY'
    assert payload['transcript'][0]['text'] == 'LEGACY_TRANSCRIPT'
