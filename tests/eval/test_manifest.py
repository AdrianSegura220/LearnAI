"""Captured configurations describe inputs independently of an execution."""
from dataclasses import replace
import json
import subprocess

import pytest

from learnai.eval.manifest import build_manifest, configuration_fingerprint


def test_fingerprint_ignores_execution_but_preserves_material_order_and_settings(tmp_path):
    first = build_manifest(root=tmp_path, selected_ids=('a', 'b'), seeds=(7, 8),
        settings={'model': 'fiction-alias', 'budget': {'output': 300}},
        prompts={'tutor@1': 'exact policy'}, references={'a': ['x=2']}, input_paths=())
    second = replace(first, run_id='different', started_at='2030-01-01T00:00:00+00:00',
        ended_at='2030-01-02T00:00:00+00:00', status='complete', phase='finished')
    assert configuration_fingerprint(first) == configuration_fingerprint(second)
    for changes in ({'selected_ids': ('b', 'a')}, {'seeds': (8, 7)},
                    {'prompts': {'tutor@1': 'changed policy'}},
                    {'references': {'a': ['x=3']}},
                    {'settings': {'model': 'different', 'budget': {'output': 300}}}):
        changed = build_manifest(root=tmp_path, selected_ids=changes.get('selected_ids', ('a', 'b')),
            seeds=changes.get('seeds', (7, 8)), settings=changes.get('settings', first.material['settings']),
            prompts=changes.get('prompts', first.material['prompts']),
            references=changes.get('references', first.material['references']), input_paths=())
        assert configuration_fingerprint(first) != configuration_fingerprint(changed)
    reordered = replace(first, material=dict(reversed(list(first.material.items()))))
    assert configuration_fingerprint(first) == configuration_fingerprint(reordered)
    with pytest.raises(ValueError):
        configuration_fingerprint(replace(first, material={'bad': float('nan')}))


def test_source_capture_reconstructs_dirty_and_untracked_material_without_private_files(tmp_path, monkeypatch):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'src').mkdir()
    tracked = tmp_path / 'src/example.py'
    tracked.write_text('original = 1\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'src/example.py'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.email=a@example.test', '-c', 'user.name=A',
                    'commit', '-qm', 'initial'], check=True)
    tracked.write_text('original = 2\n')
    (tmp_path / 'src/new.py').write_text('new = True\n')
    (tmp_path / '.env').write_text('ANTHROPIC_API_KEY=secret-file-value\n')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'secret-environment-value')
    manifest = build_manifest(root=tmp_path, selected_ids=(), seeds=(), settings={}, prompts={}, references={})
    assert manifest.code_revision and manifest.dirty is True
    captured = {entry['path']: entry for entry in manifest.material['inputs']}
    assert captured['src/example.py']['content'] == 'original = 2\n'
    assert captured['src/new.py']['content'] == 'new = True\n'
    assert captured['src/new.py']['artifact_path'].startswith('inputs/')
    assert 'secret-' not in json.dumps(manifest.to_dict())
    missing = build_manifest(root=tmp_path, selected_ids=(), seeds=(), settings={}, prompts={}, references={},
                             input_paths=('content/absent.yaml',))
    assert missing.missing_inputs == ('content/absent.yaml',)
    with pytest.raises(ValueError, match='allowlist'):
        build_manifest(root=tmp_path, selected_ids=(), seeds=(), settings={}, prompts={}, references={},
                       input_paths=('.env',))


def test_explicit_external_inputs_have_content_hash_and_local_snapshot_path(tmp_path):
    captured = build_manifest(root=tmp_path, selected_ids=('a',), seeds=(1,), settings={}, prompts={},
        references={}, input_paths=(), supplemental_inputs={'config/selected.yaml': 'routes: {}\n'})
    entry = captured.material['inputs'][0]
    assert entry['path'] == 'config/selected.yaml' and entry['content'] == 'routes: {}\n'
    assert len(entry['sha256']) == 64 and entry['artifact_path'] == 'inputs/config/selected.yaml'


def test_deleted_tracked_source_is_explicit_and_private_config_is_not_captured(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'src').mkdir()
    source = tmp_path / 'src/deleted.py'
    source.write_text('obsolete = True\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'src/deleted.py'], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.email=a@example.test', '-c', 'user.name=A',
                    'commit', '-qm', 'initial'], check=True)
    source.unlink()
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/credentials.yaml').write_text('key: private-secret\n')
    captured = build_manifest(root=tmp_path, selected_ids=(), seeds=(), settings={}, prompts={}, references={})
    assert captured.material['deleted_inputs'] == ['src/deleted.py']
    assert 'private-secret' not in json.dumps(captured.to_dict())


def test_selected_order_and_budget_defaults_on_manifest_are_material(tmp_path):
    original = build_manifest(root=tmp_path, selected_ids=('a', 'b'), seeds=(1, 2), settings={}, prompts={},
                              references={}, input_paths=())
    assert configuration_fingerprint(original) != configuration_fingerprint(replace(original, selected_ids=('b', 'a')))
    (tmp_path / 'src').mkdir()
    path = tmp_path / 'src/behavior.py'
    path.write_text('default_budget = 100\n')
    first = build_manifest(root=tmp_path, selected_ids=(), seeds=(), settings={}, prompts={}, references={})
    path.write_text('default_budget = 200\n')
    second = build_manifest(root=tmp_path, selected_ids=(), seeds=(), settings={}, prompts={}, references={})
    assert configuration_fingerprint(first) != configuration_fingerprint(second)


def test_verified_saved_packet_hashes_are_material_rejudge_inputs(tmp_path):
    first = build_manifest(root=tmp_path, selected_ids=('source:case',), seeds=(), settings={'operation': 'rejudge'},
        prompts={}, references={}, input_paths=(), linked_sources=({'run_id': 'source',
            'packets': {'case': 'candidate-and-moment-a'}},))
    second = build_manifest(root=tmp_path, selected_ids=('source:case',), seeds=(), settings={'operation': 'rejudge'},
        prompts={}, references={}, input_paths=(), linked_sources=({'run_id': 'source',
            'packets': {'case': 'candidate-and-moment-b'}},))
    assert first.material['saved_packet_inputs'] == [{'run_id': 'source', 'packets': {'case': 'candidate-and-moment-a'}}]
    assert configuration_fingerprint(first) != configuration_fingerprint(second)
