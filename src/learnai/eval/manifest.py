"""Versioned, captured configuration identity, separate from execution identity."""
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import subprocess
from typing import Any, Iterable, Mapping
from uuid import uuid4

SCHEMA_VERSION = 1
# Explicit project inputs only. Never discover home directories, environment or Git internals.
_INPUT_ROOTS = ('src', 'content', 'prompts', 'config', 'eval/fixtures')
_INPUT_FILES = ('pyproject.toml', 'uv.lock', 'requirements.txt')
_SUFFIXES = {'.py', '.yaml', '.yml', '.md', '.json', '.toml', '.lock', '.txt'}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class RunManifest:
    schema_version: int
    run_id: str
    started_at: str
    ended_at: str | None
    phase: str
    status: str
    selected_ids: tuple[str, ...]
    seeds: tuple[int, ...]
    material: dict[str, Any]
    code_revision: str | None
    dirty: bool | None
    missing_inputs: tuple[str, ...] = ()
    linked_sources: tuple[dict[str, Any], ...] = ()
    rendered_prompts: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), 'configuration_fingerprint': configuration_fingerprint(self)}


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _allowed(relative: Path) -> bool:
    name = relative.as_posix()
    return (not relative.is_absolute() and '..' not in relative.parts
            and not any(part.startswith('.') or part == '__pycache__' for part in relative.parts)
            and relative.suffix in _SUFFIXES
            and (name in _INPUT_FILES
                 or name.startswith('src/') and relative.suffix == '.py'
                 or name.startswith('content/') and relative.suffix in {'.yaml', '.yml'}
                 or name.startswith('prompts/') and relative.suffix == '.md'
                 or name.startswith('eval/fixtures/') and relative.suffix in {'.yaml', '.yml', '.json'}
                 or name == 'config/llm_routes.yaml'
                 or name.startswith('config/selected') and relative.suffix in {'.yaml', '.yml'}))


def build_manifest(*, root: Path, selected_ids: Iterable[str], seeds: Iterable[int],
                   settings: Mapping[str, Any], prompts: Mapping[str, Any],
                   references: Mapping[str, Any], input_paths: Iterable[str | Path] | None = None,
                   linked_sources: Iterable[dict[str, Any]] = (),
                   supplemental_inputs: Mapping[str, str] | None = None) -> RunManifest:
    root = root.resolve()
    sources = tuple(deepcopy(source) for source in linked_sources)
    if input_paths is None:
        paths = [path.relative_to(root) for name in _INPUT_ROOTS for path in (root / name).rglob('*')
                 if path.is_file() and _allowed(path.relative_to(root))]
        paths.extend(Path(name) for name in _INPUT_FILES if (root / name).is_file())
    else:
        paths = [Path(path) for path in input_paths]
    inputs, missing = [], []
    for relative in sorted(set(paths)):
        path = root / relative
        if not _allowed(relative) or not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError(f'input outside project allowlist: {relative}')
        try:
            content = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            missing.append(relative.as_posix())
            continue
        digest = sha256(content.encode('utf-8')).hexdigest()
        inputs.append({'path': relative.as_posix(), 'sha256': digest, 'content': content,
                       'artifact_path': f'inputs/{relative.as_posix()}'})
    for name, content in sorted((supplemental_inputs or {}).items()):
        relative = Path(name)
        if not _allowed(relative):
            raise ValueError(f'supplemental input outside project allowlist: {name}')
        if any(entry['path'] == name for entry in inputs):
            raise ValueError(f'duplicate captured input: {name}')
        inputs.append({'path': name, 'sha256': sha256(content.encode('utf-8')).hexdigest(),
                       'content': content, 'artifact_path': f'inputs/{name}'})
    dependencies = {}
    for name in ('learnai', 'anthropic', 'httpx2', 'sympy', 'PyYAML'):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    revision = _git(root, 'rev-parse', 'HEAD')
    deleted_raw = _git(root, 'ls-files', '--deleted', '--', *_INPUT_ROOTS, *_INPUT_FILES)
    deleted = sorted(name for name in (deleted_raw or '').splitlines() if _allowed(Path(name)))
    relevant = sorted({entry['path'] for entry in inputs} | set(deleted))
    dirty_paths = _git(root, 'status', '--porcelain', '--untracked-files=all', '--', *relevant) if relevant else ''
    ids, seed_values = tuple(selected_ids), tuple(seeds)
    material = dict(schema_version=SCHEMA_VERSION, selected_ids=ids, seeds=seed_values,
        settings=dict(settings), prompts=dict(prompts), references=dict(references), inputs=inputs,
        code_revision=revision, python=platform.python_version(), dependencies=dependencies,
        missing_inputs=missing, deleted_inputs=deleted, saved_packet_inputs=list(sources))
    # Validate before any artifact/client creation, including non-finite settings.
    canonical_json(material)
    return RunManifest(SCHEMA_VERSION, str(uuid4()), datetime.now(UTC).isoformat(), None,
                       'preflight', 'running', ids, seed_values, material, revision,
                       None if dirty_paths is None else bool(dirty_paths), tuple(missing), sources)


def configuration_fingerprint(manifest: RunManifest) -> str:
    material = {**manifest.material, 'schema_version': manifest.schema_version,
                'selected_ids': manifest.selected_ids, 'seeds': manifest.seeds}
    return sha256(canonical_json(material).encode('utf-8')).hexdigest()
