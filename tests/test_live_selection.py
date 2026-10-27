"""Exercise repository live opt-in behavior without ever using credentials."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def invoke(*args: str, dummy_keys: bool = False) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'PYTEST_ADDOPTS'}}
    if dummy_keys:
        environment.update(ANTHROPIC_API_KEY='selection-only', OPENAI_API_KEY='selection-only')
        assert '--collect-only' in args  # Dummy credentials must never reach a live body.
    return subprocess.run([sys.executable, '-m', 'pytest', *args], cwd=ROOT,
                          env=environment, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize(('expression', 'count'), [('live', 4), ('live and openai', 2),
                                                  ('live and anthropic', 2)])
def test_explicit_live_collection_has_two_probes_per_provider(expression, count):
    result = invoke('-o', 'addopts=', '-m', expression, '--collect-only', '-q')
    nodes = [line for line in result.stdout.splitlines() if '::test_' in line]
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(nodes) == count, result.stdout


@pytest.mark.parametrize('expression', [None, 'openai', 'anthropic'])
def test_default_excludes_live_even_with_provider_marker_and_dummy_keys(expression):
    args = ['--collect-only', '-q']
    if expression:
        args.extend(['-m', expression])
    result = invoke(*args, dummy_keys=True)
    assert result.returncode in (0, 5), result.stdout + result.stderr
    # Repeated -q switches can group collection by file instead of node id.
    assert '/test_live.py' not in result.stdout, result.stdout


def test_explicit_live_execution_without_either_key_skips_all_four():
    result = invoke('-o', 'addopts=', '-m', 'live', '-q', '-rs')
    assert result.returncode == 0, result.stdout + result.stderr
    assert '4 skipped' in result.stdout, result.stdout
    assert 'ANTHROPIC_API_KEY absent' in result.stdout
    assert 'OPENAI_API_KEY absent' in result.stdout
