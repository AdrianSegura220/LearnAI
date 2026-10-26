"""Fixed-version saved-run dispatch; artifacts never choose Python imports."""
from pathlib import Path

from learnai.eval.artifacts import SavedRun, read_json, read_run_v2
from learnai.adapters.tutor.anthropic.legacy import read_run_v1

_READERS = {1: read_run_v1, 2: read_run_v2}


def load_saved_run(directory: Path) -> SavedRun:
    if not (directory / 'manifest.json').resolve().is_relative_to(directory.resolve()):
        raise ValueError('manifest path escapes source run')
    manifest = read_json(directory / 'manifest.json')
    version = manifest.get('schema_version') if isinstance(manifest, dict) else None
    if type(version) is not int or version not in _READERS:
        raise ValueError('unsupported saved run schema version')
    return _READERS[version](directory)
