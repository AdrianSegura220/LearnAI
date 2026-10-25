"""Strict typed packets for saved-response rejudging; never import artifact names."""
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from learnai.domain import enums, history, interaction, items, skills, turn
from learnai.eval import fixtures, judge
from learnai.eval.manifest import canonical_json

# All constructors are trusted local definitions; artifact text cannot select imports.
_MODULES = (enums, history, interaction, items, skills, turn, fixtures, judge)
_TYPES = {f'{value.__module__}.{value.__name__}': value for module in _MODULES
          for value in vars(module).values() if isinstance(value, type)
          and value.__module__ == module.__name__
          and (is_dataclass(value) or issubclass(value, Enum))}


def encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return {'$enum': f'{type(value).__module__}.{type(value).__name__}', 'name': value.name}
    if is_dataclass(value):
        name = f'{type(value).__module__}.{type(value).__name__}'
        if name not in _TYPES:
            raise ValueError(f'unsupported artifact type: {name}')
        return {'$type': name, 'fields': {field.name: encode(getattr(value, field.name)) for field in fields(value)}}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError('artifact datetime must be timezone aware')
        return {'$datetime': value.isoformat()}
    if isinstance(value, tuple):
        return {'$tuple': [encode(entry) for entry in value]}
    if isinstance(value, frozenset):
        return {'$frozenset': sorted((encode(entry) for entry in value), key=canonical_json)}
    if isinstance(value, list):
        return [encode(entry) for entry in value]
    if isinstance(value, dict):
        return {key: encode(entry) for key, entry in value.items()}
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError(f'unsupported artifact value: {type(value).__name__}')


def decode(value: Any) -> Any:
    if isinstance(value, list):
        return [decode(entry) for entry in value]
    if not isinstance(value, dict):
        return value
    if '$type' in value:
        cls = _TYPES.get(value['$type'])
        if cls is None or not is_dataclass(cls):
            raise ValueError('unknown artifact type')
        names = {field.name for field in fields(cls)}
        if set(value) != {'$type', 'fields'} or not isinstance(value['fields'], dict) or set(value['fields']) != names:
            raise ValueError('artifact fields do not match versioned type')
        restored = {name: decode(entry) for name, entry in value['fields'].items()}
        result = cls(**{field.name: restored[field.name] for field in fields(cls) if field.init})
        for field in fields(cls):
            if not field.init:
                object.__setattr__(result, field.name, restored[field.name])
        return result
    if '$enum' in value:
        cls = _TYPES.get(value['$enum'])
        if cls is None or not issubclass(cls, Enum) or set(value) != {'$enum', 'name'}:
            raise ValueError('unknown enum artifact type')
        try:
            return cls[value['name']]
        except (KeyError, TypeError) as exc:
            raise ValueError('unknown artifact enum member') from exc
    if '$datetime' in value:
        result = datetime.fromisoformat(value['$datetime'])
        if set(value) != {'$datetime'} or result.tzinfo is None:
            raise ValueError('invalid artifact datetime')
        return result
    for marker, constructor in (('$tuple', tuple), ('$frozenset', frozenset)):
        if marker in value:
            if set(value) != {marker} or not isinstance(value[marker], list):
                raise ValueError('invalid artifact sequence')
            return constructor(decode(entry) for entry in value[marker])
    if any(key.startswith('$') for key in value):
        raise ValueError('unknown artifact marker')
    return {key: decode(entry) for key, entry in value.items()}


def read_json(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f'nonfinite JSON value: {value}')
    try:
        return json.loads(path.read_text(encoding='utf-8'), parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'cannot read artifact {path}: {exc}') from exc


def load_packets(directory: Path) -> dict[str, judge.JudgePacket]:
    """Validate every saved packet and hash before any rejudging client exists."""
    report = read_json(directory / 'report.json')
    packets = {}
    for case_id, entry in report.get('judge_packets', {}).items():
        relative = Path(entry['path'])
        target = directory / relative
        if relative.is_absolute() or not target.resolve().is_relative_to(directory.resolve()):
            raise ValueError('packet path escapes source run')
        raw = read_json(target)
        if sha256(canonical_json(raw).encode('utf-8')).hexdigest() != entry['sha256']:
            raise ValueError(f'packet hash mismatch: {case_id}')
        packet = decode(raw)
        if not isinstance(packet, judge.JudgePacket):
            raise ValueError('saved packet has wrong type')
        packets[case_id] = packet
    eligible = set(report.get('eligible_ids', ()))
    if not packets or set(packets) != eligible:
        raise ValueError('source artifact has incomplete eligible packets')
    return packets
