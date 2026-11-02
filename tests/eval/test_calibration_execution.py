"""Offline CLI execution preserves authored packets and partial calibration evidence."""
from hashlib import sha256
import builtins
import io
import json
from pathlib import Path
import socket
import stat
import os
import subprocess
import sys

import pytest
import yaml

from learnai.application.providers import ProviderRegistry, ProviderServices
from learnai.eval import calibration
from learnai.eval.artifacts import decode
from learnai.eval.judge import build_judge_messages
from learnai.eval.manifest import canonical_json
from tests.adapters.tutor.openai.test_judge import scored
from tests.eval.test_judge import score_data
from tests.eval.test_quality_calibration import CALIBRATION, ROOT, case, write_collection
from tests.support.provider_contracts import scripted_factories
from tests.support.scripted_openai import ResponseReply, ScriptedOpenAI


@pytest.fixture(autouse=True)
def forbid_ignored_run_reads(monkeypatch):
    """Private operator artifacts must never supply execution-test inputs."""
    ignored_runs = ROOT / 'eval/runs'

    def guarded(original):
        def open_file(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                if Path(os.fsdecode(file)).resolve().is_relative_to(ignored_runs):
                    raise AssertionError('execution tests read ignored eval/runs')
            return original(file, *args, **kwargs)
        return open_file

    monkeypatch.setattr(builtins, 'open', guarded(builtins.open))
    monkeypatch.setattr(io, 'open', guarded(io.open))


@pytest.fixture
def quality_routes(tmp_path):
    data = yaml.safe_load((ROOT / 'config/llm_routes.yaml').read_text(encoding='utf-8'))
    prompts = {'tutor_math@1': 'tutor_math@2', 'rubric_judge@1': 'rubric_judge@2'}
    for route in data['routes'].values():
        if route.get('prompt') in prompts:
            route['prompt'] = prompts[route['prompt']]
    path = tmp_path / 'routes.yaml'
    path.write_text(yaml.safe_dump(data), encoding='utf-8')
    return path


def argv(tmp_path, *, routes, path=CALIBRATION, dry=False):
    return ['--calibration', str(path), '--routes', str(routes), '--out', str(tmp_path / 'runs'),
            *(['--dry-run'] if dry else [])]


def artifact(tmp_path):
    directory, = (tmp_path / 'runs').iterdir()
    return directory, json.loads((directory / 'calibration.json').read_text())


def install_provider(monkeypatch, replies, *, on_judge=None):
    sdk = ScriptedOpenAI(replies)
    constructed = []
    factories = scripted_factories({'openai': sdk}, constructed=constructed)
    for factory in factories.values():
        def no_tutor(**kwargs):
            raise AssertionError('calibration must never construct a tutor')
        factory.create_tutor = no_tutor
    if on_judge is not None:
        factories['openai'].create_judge = on_judge
    monkeypatch.setattr(calibration, 'default_registry', lambda: ProviderRegistry(factories))
    monkeypatch.setenv('OPENAI_API_KEY', 'scripted-key')
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    return sdk, constructed


def test_dry_run_requires_no_keys_clients_network_or_artifacts(tmp_path, quality_routes, monkeypatch, capsys):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('dry run created provider state or network')
    monkeypatch.setattr(ProviderServices, 'validate', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    factories = scripted_factories({})
    for factory in factories.values():
        factory.create_client = forbidden
        factory.create_judge = forbidden
        factory.create_tutor = forbidden
    monkeypatch.setattr(calibration, 'default_registry', lambda: ProviderRegistry(factories))
    assert calibration.main(argv(tmp_path, routes=quality_routes, dry=True)) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'dry_run'
    assert output['judge_cases'] == 7 and output['manual_review_cases'] == 1
    assert not (tmp_path / 'runs').exists()


def test_dry_run_does_not_import_provider_sdks(tmp_path, quality_routes):
    script = '''
import os
import socket
import sys
from pathlib import Path
def guard(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes)):
        if Path(os.fsdecode(args[0])).resolve().is_relative_to(IGNORED_RUNS):
            raise AssertionError('execution tests read ignored eval/runs')
sys.addaudithook(guard)
class NoSDK:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'httpx2'}:
            raise AssertionError('dry run imported SDK: ' + fullname)
sys.meta_path.insert(0, NoSDK())
def forbidden(*args, **kwargs):
    raise AssertionError('dry run accessed network')
socket.create_connection = forbidden
from learnai.eval.calibration import main
raise SystemExit(main(sys.argv[1:]))
'''
    script = 'IGNORED_RUNS = ' + repr(str(ROOT / 'eval/runs')) + '\n' + script
    result = subprocess.run([sys.executable, '-c', script, *argv(tmp_path, routes=quality_routes, dry=True)],
        capture_output=True, text=True, env={key: value for key, value in os.environ.items()
        if key not in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY')})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['judge_cases'] == 7


@pytest.mark.parametrize('change', ['unknown_route', 'missing_prompt', 'bad_prompt'])
def test_dry_run_validates_selected_judge_configuration(tmp_path, quality_routes, change):
    data = yaml.safe_load(quality_routes.read_text(encoding='utf-8'))
    selected = data['routes']['rubric_judge_openai']
    if change == 'unknown_route':
        del data['routes']['rubric_judge_openai']
    elif change == 'missing_prompt':
        selected.pop('prompt')
    else:
        selected['prompt'] = 'rubric_judge@999'
    quality_routes.write_text(yaml.safe_dump(data), encoding='utf-8')
    assert calibration.main(argv(tmp_path, routes=quality_routes, dry=True)) == 2
    assert not (tmp_path / 'runs').exists()


def test_live_is_judge_only_keeps_rejected_prose_and_isolates_labels(tmp_path, quality_routes, monkeypatch):
    sdk, constructed = install_provider(monkeypatch, [scored() for _ in range(7)])
    assert calibration.main(argv(tmp_path, routes=quality_routes)) == 0
    directory, saved = artifact(tmp_path)
    assert constructed == [('openai', 'scripted-key')]
    assert sdk.client.is_closed() and len(sdk.requests) == 7
    assert directory.name.startswith('calibration-')
    assert saved['kind'] == 'tutor_calibration' and saved['schema_version'] == 1
    assert saved['status'] == 'complete'
    assert saved['results']['unsupported-verification-claim']['status'] == 'manual_review_required'
    snapshots = saved['material']['cases']
    assert snapshots[1]['validation']['fields']['accepted'] is False
    assert snapshots[1]['validation']['fields']['reason']['name'] == 'ANSWER_LEAKED'
    for request, snapshot in zip(sdk.requests, snapshots):
        packet = decode(snapshot['packet'])
        payload = json.loads(request['input'][0]['content'])
        assert payload == json.loads(build_judge_messages(packet)[0]['content'])
        assert payload['candidate_response']['message'] == packet.turn.message
        for private in ('expected_scores', 'rationale', 'review_status', 'expected_engine', 'validation', 'accepted'):
            assert private not in json.dumps(payload)
        assert request['instructions'] == saved['material']['base']['prompts']['rubric_judge@2']
    assert len(saved['requests']) == len(saved['traces']) == 7
    assert all(r['phase'] == 'judge' and r['raw_usage'] for r in saved['requests'])
    assert saved['material']['base']['role_dependencies'].keys() == {'judge'}
    assert saved['material']['base']['identities']['judge'].keys() == {'rubric_judge_openai'}
    assert saved['material']['base']['settings']['routes']['rubric_judge_openai']['effective_settings']
    assert saved['material']['calibration']['content'] == CALIBRATION.read_text()
    assert saved['material']['calibration']['sha256'] == sha256(CALIBRATION.read_bytes()).hexdigest()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((directory / 'calibration.json').stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        from learnai.application.artifacts import load_saved_run
        load_saved_run(directory)


def test_agreement_counts_only_confirmed_specified_dimensions_and_keeps_missing(tmp_path, quality_routes, monkeypatch):
    entries = [case(id='confirmed'), case(id='mismatch', expected_scores={'tone': 0}),
               case(id='abstained'), case(id='failed'),
               case(id='proposal', review_status='proposed', expected_scores={'mathematics': 0}),
               case(id='manual', assessment_source='trace_review', expected_scores={})]
    path = write_collection(tmp_path, entries)
    abstention = dict(score_data(), mathematics=None, help_level=None, diagnosis=None, tone=None,
                      status='insufficient_evidence', missing_information=['learner_level'])
    sdk, _ = install_provider(monkeypatch, [scored(dict(score_data(), help_level=2)), scored(), scored(abstention),
                                          ResponseReply(http_status=400), scored()])
    assert calibration.main(argv(tmp_path, routes=quality_routes, path=path)) == 1
    _, saved = artifact(tmp_path)
    assert saved['status'] == 'incomplete'
    summary = saved['summary']
    assert summary['counts'] == dict(total=6, judge_packet=5, trace_review=1, scored=3,
        insufficient_evidence=1, judge_error=1, manual_review_required=1, pending=0,
        running=0, error=0, interrupted=0)
    assert summary['confirmed_agreement'] == dict(expected_dimensions=4, compared_dimensions=2,
        matches=1, ratio=0.5, excluded_dimensions={'insufficient_evidence': 1, 'judge_error': 1})
    assert saved['results']['confirmed']['comparison'] == {'help_level': {'expected': 2, 'actual': 2, 'matches': True}}
    assert saved['results']['proposal']['proposed_observation'] == {'mathematics': {'expected': 0, 'actual': 2}}
    assert 'comparison' not in saved['results']['proposal']
    assert sdk.client.is_closed()


@pytest.mark.parametrize('fault', [RuntimeError('second failed'), KeyboardInterrupt()])
def test_second_case_error_or_interrupt_preserves_first_incrementally_and_closes(tmp_path, quality_routes, monkeypatch, fault):
    path = write_collection(tmp_path, [case(id='first'), case(id='second'), case(id='third')])
    sdk, _ = install_provider(monkeypatch, [scored()])
    registry = calibration.default_registry()
    factory = registry.get('openai')
    original = factory.create_judge
    calls = 0
    def create(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            _, partial = artifact(tmp_path)
            assert partial['status'] == 'running'
            assert partial['results']['first']['status'] == 'scored'
            assert len(partial['requests']) == 1
            raise fault
        return original(**kwargs)
    factory.create_judge = create
    monkeypatch.setattr(calibration, 'default_registry', lambda: registry)
    if isinstance(fault, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            calibration.main(argv(tmp_path, routes=quality_routes, path=path))
    else:
        assert calibration.main(argv(tmp_path, routes=quality_routes, path=path)) == 1
    _, saved = artifact(tmp_path)
    expected_status = 'interrupted' if isinstance(fault, KeyboardInterrupt) else 'error'
    assert saved['status'] == saved['results']['second']['status'] == expected_status
    assert saved['results']['first']['status'] == 'scored'
    assert saved['results']['third']['status'] == 'pending'
    assert len(saved['requests']) == len(saved['traces']) == 1
    assert sdk.client.is_closed()


@pytest.mark.parametrize('failure', ['bad_case', 'no_key', 'unwritable'])
def test_preflight_fails_before_every_client(tmp_path, quality_routes, monkeypatch, failure):
    sdk, constructed = install_provider(monkeypatch, [])
    args = argv(tmp_path, routes=quality_routes)
    if failure == 'bad_case':
        path = write_collection(tmp_path, [case(), case(id='bad', expected_engine={'accepted': False, 'reason': 'ANSWER_LEAKED'})])
        args = argv(tmp_path, routes=quality_routes, path=path)
    elif failure == 'no_key':
        monkeypatch.delenv('OPENAI_API_KEY')
    else:
        (tmp_path / 'runs').write_text('a file cannot hold artifacts')
    assert calibration.main(args) == 2
    assert constructed == []
    sdk.client.close()


def test_reruns_are_unique_and_fingerprint_omits_execution_output_and_time(tmp_path, quality_routes, monkeypatch):
    path = write_collection(tmp_path, [case()])
    for expected in (2, 0):
        install_provider(monkeypatch, [scored(dict(score_data(), help_level=expected))])
        assert calibration.main(argv(tmp_path, routes=quality_routes, path=path)) == 0
    saved = [json.loads((p / 'calibration.json').read_text()) for p in (tmp_path / 'runs').iterdir()]
    assert len(saved) == 2 and saved[0]['calibration_id'] != saved[1]['calibration_id']
    assert saved[0]['configuration_fingerprint'] == saved[1]['configuration_fingerprint']
    assert saved[0]['results'] != saved[1]['results']
    for data in saved:
        assert data['configuration_fingerprint'] == sha256(canonical_json(data['material']).encode()).hexdigest()
    original = saved[0]['configuration_fingerprint']
    for change in ('label', 'candidate'):
        entry = case(expected_scores={'help_level': 1}) if change == 'label' else case(
            candidate={'message': 'Consider the product and sum when finding two factors.', 'rung_used': 'NEXT_STEP'})
        path = write_collection(tmp_path, [entry])
        install_provider(monkeypatch, [scored()])
        assert calibration.main(argv(tmp_path, routes=quality_routes, path=path)) == 0
    fingerprints = {json.loads((p / 'calibration.json').read_text())['configuration_fingerprint']
                    for p in (tmp_path / 'runs').iterdir()}
    assert len(fingerprints) == 3 and original in fingerprints
