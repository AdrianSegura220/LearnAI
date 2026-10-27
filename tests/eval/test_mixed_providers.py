"""Both SDKs must preserve phase order and the exact accepted candidate/moment pair."""
import json

import pytest

from learnai.eval.artifacts import load_packets
from learnai.eval.judge import build_judge_messages
from tests.support.provider_contracts import PAIR_CASES, run_scripted_pair


@pytest.mark.parametrize('tutor_provider,judge_provider', [
    ('anthropic', 'anthropic'), ('anthropic', 'openai'),
    ('openai', 'anthropic'), ('openai', 'openai'),
])
def test_two_cases_keep_phase_order_and_candidate_pairing(tutor_provider, judge_provider, tmp_path, monkeypatch):
    run = run_scripted_pair(tutor_provider=tutor_provider, judge_provider=judge_provider,
                            tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert run.exit_code == 0
    assert tuple(run.outcomes) == PAIR_CASES
    assert run.request_roles == ('tutor', 'tutor', 'judge', 'judge')
    assert run.request_providers == (tutor_provider, tutor_provider, judge_provider, judge_provider)
    assert len({record.request_id for record in run.records}) == 4
    assert tuple(record.phase for record in run.records) == run.request_roles
    assert tuple(record.provider for record in run.records) == run.request_providers
    saved = load_packets(run.run)
    for index, case_id in enumerate(run.outcomes):
        packet = run.packets[case_id]
        assert packet.context is run.outcomes[case_id].context
        assert packet.turn is run.outcomes[case_id].turn
        assert run.wire_judge_payloads[index] == json.loads(build_judge_messages(packet)[0]['content'])
        assert saved[case_id] == packet
        assert run.records[index].route_name == 'tutor_dialogue'
        assert run.records[index + 2].route_name == 'rubric_judge'
    assert all(sdk.client.is_closed() for provider, sdk in run.sdks.items()
               if provider in (tutor_provider, judge_provider))


@pytest.mark.parametrize('tutor_provider,judge_provider,phase_costs,total,complete', [
    ('anthropic', 'anthropic', ('0.00088', '0.00088'), '0.00176', False),
    ('anthropic', 'openai', ('0.00088', '0.00116'), '0.00204', False),
    ('openai', 'anthropic', ('0.00116', '0.00088'), '0.00204', False),
    ('openai', 'openai', ('0.00116', '0.00116'), '0.00232', True),
])
def test_actual_role_dependencies_schema_identities_and_literal_phase_costs(
    tutor_provider, judge_provider, phase_costs, total, complete, tmp_path, monkeypatch,
):
    from importlib.metadata import version
    run = run_scripted_pair(tutor_provider=tutor_provider, judge_provider=judge_provider,
                            tmp_path=tmp_path, monkeypatch=monkeypatch)
    material = json.loads((run.run / 'manifest.json').read_text())['material']
    for role, provider, name in [('tutor', tutor_provider, 'tutor_dialogue'),
                                 ('judge', judge_provider, 'rubric_judge')]:
        identity = material['identities'][role][name]
        assert identity['provider'] == provider
        assert identity['api_family'] == ('responses' if provider == 'openai' else 'messages')
        assert identity['usage_mapper_id'] == ('openai-responses@2' if provider == 'openai' else 'anthropic-messages@1')
        assert material['role_dependencies'][role] == {provider: version(provider), 'httpx2': version('httpx2')}
        assert set(identity['schema_hashes']) == ({'final_output'} if role == 'judge' else
            {'final_output', 'canonical_read_tools', 'wire_read_tools'})
    assert {p['provider'] for p in material['pricing_snapshots']['snapshots']} == {'anthropic', 'openai'}
    report = json.loads((run.run / 'report.json').read_text())
    assert report['cost']['by_phase'] == dict(tutor=phase_costs[0], judge=phase_costs[1], smoke='0')
    assert report['cost']['known_subtotal'] == total
    assert report['cost']['complete'] is complete
    assert report['cost']['total'] == (total if complete else None)
    assert {record.requested_model for record in run.records} == {'same-model'}


@pytest.mark.parametrize('tutor_provider,judge_provider', [('anthropic', 'openai'), ('openai', 'anthropic')])
def test_missing_second_provider_key_prevents_every_client(tutor_provider, judge_provider, tmp_path, monkeypatch):
    from learnai.eval.__main__ import main
    from tests.support.provider_contracts import ROOT, scripted_factories, write_routes
    monkeypatch.setenv(tutor_provider.upper() + '_API_KEY', 'scripted-key')
    monkeypatch.delenv(judge_provider.upper() + '_API_KEY', raising=False)
    constructed = []
    routes = write_routes(tmp_path, tutor_provider=tutor_provider, judge_provider=judge_provider)
    assert main(['run', '--fixtures', str(ROOT / 'eval/fixtures'), '--routes', str(routes),
        '--out', str(tmp_path / 'runs'), '--only', ','.join(PAIR_CASES), '--no-smoke'],
        provider_factories=scripted_factories({}, constructed=constructed)) == 2
    assert constructed == [] and not (tmp_path / 'runs').exists()


@pytest.mark.parametrize('judge_provider', ['anthropic', 'openai'])
def test_later_judge_failure_retains_outcomes_scores_requests_and_closes_both(judge_provider, tmp_path, monkeypatch):
    from learnai.eval.__main__ import main
    from tests.eval.test_judge import ScriptedJudge, reply
    from tests.support.scripted_client import final as af, Reply
    from tests.support.scripted_openai import ScriptedOpenAI, final as of, ResponseReply
    from tests.adapters.tutor.openai.test_judge import scored
    from tests.support.provider_contracts import ROOT, scripted_factories, write_routes
    tutor_provider = 'openai' if judge_provider == 'anthropic' else 'anthropic'
    scripts = {tutor_provider: [of(), of()] if tutor_provider == 'openai' else [af(), af()],
               judge_provider: [reply(), Reply([], status=400)] if judge_provider == 'anthropic'
                   else [scored(), ResponseReply(http_status=400)]}
    sdks = {'anthropic': ScriptedJudge(scripts['anthropic']), 'openai': ScriptedOpenAI(scripts['openai'])}
    for provider in sdks:
        monkeypatch.setenv(provider.upper() + '_API_KEY', 'scripted-key')
    routes = write_routes(tmp_path, tutor_provider=tutor_provider, judge_provider=judge_provider)
    assert main(['run', '--fixtures', str(ROOT / 'eval/fixtures'), '--routes', str(routes),
        '--out', str(tmp_path / 'runs'), '--only', ','.join(PAIR_CASES), '--no-smoke'],
        provider_factories=scripted_factories(sdks)) == 1
    run = next((tmp_path / 'runs').iterdir())
    data = json.loads((run / 'report.json').read_text())
    assert data['counts']['accepted'] == 2 and data['counts']['scored'] == data['counts']['judge_error'] == 1
    assert data['cost']['complete'] is False
    assert json.loads((run / 'manifest.json').read_text())['status'] == 'incomplete'
    records = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert [r['phase'] for r in records] == ['tutor', 'tutor', 'judge', 'judge']
    assert records[-1]['provider'] == judge_provider and records[-1]['usage_status'] == 'missing'
    assert len(load_packets(run)) == 2
    assert all(sdk.client.is_closed() and not sdk.replies for sdk in sdks.values())


def test_frozen_v1_rejudged_by_openai_with_only_its_key_and_source_unchanged(tmp_path, monkeypatch):
    from hashlib import sha256
    from learnai.application.artifacts import load_saved_run
    from learnai.eval.__main__ import main
    from tests.support.provider_contracts import ROOT, scripted_factories, write_routes
    from tests.support.scripted_openai import ScriptedOpenAI
    from tests.adapters.tutor.openai.test_judge import scored
    source = ROOT / 'tests/fixtures/eval_v1/run'
    checksums = json.loads((source.parent / 'checksums.json').read_text())
    def hashes():
        return {path: sha256((source / path).read_bytes()).hexdigest() for path in checksums}
    assert hashes() == checksums
    saved = load_saved_run(source)
    sdk = ScriptedOpenAI([scored()])
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'scripted-key')
    routes = write_routes(tmp_path, tutor_provider='anthropic', judge_provider='openai')
    constructed = []
    assert main(['rejudge', str(source), '--routes', str(routes), '--out', str(tmp_path / 'rejudged')],
        provider_factories=scripted_factories({'openai': sdk}, constructed=constructed)) == 0
    assert constructed == [('openai', 'scripted-key')] and len(sdk.requests) == 1
    expected = next(iter(saved.packets.values()))
    assert json.loads(sdk.requests[0]['input'][0]['content']) == json.loads(build_judge_messages(expected)[0]['content'])
    linked = load_saved_run(next((tmp_path / 'rejudged').iterdir()))
    assert all(r.phase == 'judge' and r.provider == 'openai' for r in linked.records)
    assert linked.manifest['material']['role_dependencies'].keys() == {'judge'}
    assert hashes() == checksums and sdk.client.is_closed()


def test_openai_v2_artifact_rejudged_by_anthropic_with_only_its_key(tmp_path, monkeypatch):
    from hashlib import sha256
    from learnai.application.artifacts import load_saved_run
    from learnai.eval.__main__ import main
    from tests.eval.test_judge import ScriptedJudge, reply
    from tests.support.provider_contracts import scripted_factories, write_routes
    original = run_scripted_pair(tutor_provider='openai', judge_provider='openai',
                                 tmp_path=tmp_path / 'original', monkeypatch=monkeypatch)
    before = {p.relative_to(original.run): sha256(p.read_bytes()).hexdigest()
              for p in original.run.rglob('*') if p.is_file()}
    sdk = ScriptedJudge([reply(), reply()])
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'scripted-key')
    routes = write_routes(tmp_path, tutor_provider='openai', judge_provider='anthropic')
    constructed = []
    assert main(['rejudge', str(original.run), '--routes', str(routes), '--out', str(tmp_path / 'rejudged')],
        provider_factories=scripted_factories({'anthropic': sdk}, constructed=constructed)) == 0
    assert constructed == [('anthropic', 'scripted-key')]
    expected = [json.loads(build_judge_messages(p)[0]['content']) for p in load_saved_run(original.run).packets.values()]
    assert [json.loads(r['messages'][0]['content']) for r in sdk.wire_requests] == expected
    linked = load_saved_run(next((tmp_path / 'rejudged').iterdir()))
    assert all(r.phase == 'judge' and r.provider == 'anthropic' for r in linked.records)
    assert {p.relative_to(original.run): sha256(p.read_bytes()).hexdigest()
            for p in original.run.rglob('*') if p.is_file()} == before
    assert sdk.client.is_closed()


def test_tutor_provider_treatment_is_distinct_from_changed_judge_identity(tmp_path, monkeypatch):
    from dataclasses import replace
    from learnai.application.artifacts import load_saved_run
    from learnai.eval.report import compare_runs, TutorTreatment
    left = run_scripted_pair(tutor_provider='anthropic', judge_provider='anthropic',
                            tmp_path=tmp_path / 'left', monkeypatch=monkeypatch)
    right = run_scripted_pair(tutor_provider='openai', judge_provider='anthropic',
                             tmp_path=tmp_path / 'right', monkeypatch=monkeypatch)
    a, b = load_saved_run(left.run), load_saved_run(right.run)
    treatment = TutorTreatment(('tutor_dialogue',), allow_tutor_dependency_changes=True)
    assert compare_runs(a, b, treatment=treatment)['controlled_tutor_comparison']['eligible']
    # Read-only comparison, including the composition classifier, must stay SDK-free.
    import os
    import subprocess
    import sys
    code = '''
import sys
class BlockSDK:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'httpx2'}:
            raise AssertionError('SDK imported by comparison: ' + fullname)
sys.meta_path.insert(0, BlockSDK())
from pathlib import Path
from learnai.application.artifacts import load_saved_run
from learnai.eval.report import compare_runs, TutorTreatment
left, right = [load_saved_run(Path(path)) for path in sys.argv[1:]]
assert compare_runs(left, right, treatment=TutorTreatment(('tutor_dialogue',), True))['controlled_tutor_comparison']['eligible']
'''
    process = subprocess.run([sys.executable, '-c', code, str(left.run), str(right.run)],
        capture_output=True, text=True, env={k: v for k, v in os.environ.items()
        if k not in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY')})
    assert process.returncode == 0, process.stderr
    changed = replace(b, records=tuple(replace(r, returned_model='judge-alias-resolved')
                      if r.phase == 'judge' else r for r in b.records))
    result = compare_runs(a, changed, treatment=treatment)
    assert not result['controlled_tutor_comparison']['eligible']
    assert result['provider_returned_models']['changed']


def test_mixed_cli_smoke_is_a_separate_phase_and_pricing_was_captured_before_clients(tmp_path, monkeypatch):
    import yaml
    from learnai.eval.__main__ import main
    from tests.eval.test_judge import ScriptedJudge, reply
    from tests.support.scripted_openai import ScriptedOpenAI, final
    from tests.support.provider_contracts import ROOT, scripted_factories, write_routes
    sdks = {'openai': ScriptedOpenAI([final(), *[final() for _ in range(6)]]),
            'anthropic': ScriptedJudge([reply()])}
    routes = write_routes(tmp_path, tutor_provider='openai', judge_provider='anthropic')
    factories = scripted_factories(sdks)
    original = factories['openai'].create_client
    def change_after_snapshot(*, api_key):
        raw = yaml.safe_load(routes.read_text())
        raw['pricing']['snapshots'][1]['rates']['same-model']['input'] = '999999'
        routes.write_text(yaml.safe_dump(raw))
        return original(api_key=api_key)
    factories['openai'].create_client = change_after_snapshot
    for provider in sdks:
        monkeypatch.setenv(provider.upper() + '_API_KEY', 'scripted-key')
    assert main(['run', '--fixtures', str(ROOT / 'eval/fixtures'), '--routes', str(routes),
        '--out', str(tmp_path / 'runs'), '--only', PAIR_CASES[0]], provider_factories=factories) == 0
    run = next((tmp_path / 'runs').iterdir())
    records = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert [(r['phase'], r['provider']) for r in records] == [
        ('tutor', 'openai'), ('judge', 'anthropic'), *[('smoke', 'openai')] * 6]
    report = json.loads((run / 'report.json').read_text())
    assert report['cost']['by_phase'] == {'tutor':'0.00058', 'judge':'0.00044', 'smoke':'0.00348'}
    assert report['cost']['known_subtotal'] == '0.00450'
    material = json.loads((run / 'manifest.json').read_text())['material']
    assert material['pricing_snapshots']['snapshots'][1]['rates']['same-model']['input'] == '5'
    assert report['persona_smoke']['status'] == 'complete'
    assert all(s.client.is_closed() for s in sdks.values())


def test_mixed_retry_costs_reconcile_with_every_actual_request(tmp_path, monkeypatch):
    from learnai.eval.__main__ import main
    from tests.eval.test_judge import ScriptedJudge
    from tests.support.scripted_client import final
    from tests.support.scripted_openai import ScriptedOpenAI, ResponseReply
    from tests.adapters.tutor.openai.test_judge import scored
    from tests.support.provider_contracts import ROOT, scripted_factories, write_routes
    sdks = {'anthropic': ScriptedJudge([final()]), 'openai': ScriptedOpenAI([
        scored({'invalid': True}), ResponseReply(http_status=500), scored()])}
    for provider in sdks:
        monkeypatch.setenv(provider.upper() + '_API_KEY', 'scripted-key')
    routes = write_routes(tmp_path, tutor_provider='anthropic', judge_provider='openai')
    assert main(['run', '--fixtures', str(ROOT / 'eval/fixtures'), '--routes', str(routes),
        '--out', str(tmp_path / 'runs'), '--only', PAIR_CASES[0], '--no-smoke'],
        provider_factories=scripted_factories(sdks)) == 0
    run = next((tmp_path / 'runs').iterdir())
    records = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert [r['retry'] for r in records] == [False, False, True, True]
    assert [r['usage_status'] for r in records] == ['partial', 'complete', 'missing', 'complete']
    report = json.loads((run / 'report.json').read_text())
    assert report['cost']['by_phase'] == {'tutor':'0.00044', 'judge':'0.00116', 'smoke':'0'}
    assert report['cost']['known_subtotal'] == '0.00160'
    assert report['cost']['retry_subtotal'] == '0.00058'
    assert report['cost']['total'] is None
    assert all(s.client.is_closed() for s in sdks.values())


def test_tutor_treatment_preserves_hidden_nested_and_same_provider_wire_edits(tmp_path, monkeypatch):
    from copy import deepcopy
    from dataclasses import replace
    from learnai.application.artifacts import load_saved_run
    from learnai.eval.report import compare_runs, TutorTreatment
    left = run_scripted_pair(tutor_provider='anthropic', judge_provider='anthropic',
                            tmp_path=tmp_path / 'left', monkeypatch=monkeypatch)
    right = run_scripted_pair(tutor_provider='openai', judge_provider='anthropic',
                             tmp_path=tmp_path / 'right', monkeypatch=monkeypatch)
    a, b = load_saved_run(left.run), load_saved_run(right.run)
    treatment = TutorTreatment(('tutor_dialogue',), True)
    assert compare_runs(a, b, treatment=treatment)['controlled_tutor_comparison']['eligible']
    mutations = [
        (('store',), True), (('include',), []), (('truncation',), 'auto'),
        (('reasoning', 'future_option'), 'hidden'), (('text', 'format', 'future_option'), True),
        (('max_output_tokens',), 999), (('unknown_option',), 1),
    ]
    for path, value in mutations:
        changed = replace(b, manifest=deepcopy(b.manifest))
        target = changed.manifest['material']['settings']['routes']['tutor_dialogue']['effective_settings']
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        assert not compare_runs(b, changed, treatment=treatment)['controlled_tutor_comparison']['eligible'], path
        assert not compare_runs(a, changed, treatment=treatment)['controlled_tutor_comparison']['eligible'], path
    changed = replace(a, manifest=deepcopy(a.manifest))
    changed.manifest['material']['settings']['routes']['tutor_dialogue']['effective_settings']['output_config']['future_option'] = True
    assert not compare_runs(a, changed, treatment=treatment)['controlled_tutor_comparison']['eligible']
    changed = replace(b, manifest=deepcopy(b.manifest))
    changed.manifest['material']['identities']['tutor']['tutor_dialogue']['schema_hashes']['canonical_read_tools'] = 'changed'
    assert not compare_runs(a, changed, treatment=treatment)['controlled_tutor_comparison']['eligible']

    for path in (('reasoning', 'effort'), ('store',), ('text', 'format', 'schema')):
        changed = replace(b, manifest=deepcopy(b.manifest))
        target = changed.manifest['material']['settings']['routes']['tutor_dialogue']['effective_settings']
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
        assert not compare_runs(a, changed, treatment=treatment)['controlled_tutor_comparison']['eligible'], path
