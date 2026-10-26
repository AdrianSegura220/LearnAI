"""Strict typed packets for saved-response rejudging; never import artifact names."""
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from learnai.domain import enums, history, interaction, items, skills, turn
from learnai.eval import fixtures, judge
from learnai.eval.manifest import canonical_json

# All constructors are trusted local definitions; artifact text cannot select imports.
_MODULES = (enums, history, interaction, items, skills, turn, fixtures, judge)
_TYPES = {f'{value.__module__}.{value.__name__}': value for module in _MODULES
          for value in vars(module).values() if isinstance(value, type)
          and value.__module__ == module.__name__
          and (is_dataclass(value) or issubclass(value, Enum))}


@lru_cache(maxsize=None)
def _hints(cls: type) -> dict[str, Any]:
    # Only locally allowlisted classes reach this function, never artifact names.
    return get_type_hints(cls)


def _matches(value: Any, expected: Any) -> bool:
    if expected is Any:
        return True
    if hasattr(expected, '__supertype__'):  # Domain NewType ids/constraints.
        return _matches(value, expected.__supertype__)
    origin, args = get_origin(expected), get_args(expected)
    if origin in (Union, UnionType):
        return any(_matches(value, member) for member in args)
    if origin is Literal:
        return any(type(value) is type(member) and value == member for member in args)
    if origin is tuple:
        if type(value) is not tuple:
            return False
        if len(args) == 2 and args[1] is Ellipsis:
            return all(_matches(entry, args[0]) for entry in value)
        return len(value) == len(args) and all(_matches(entry, kind) for entry, kind in zip(value, args))
    if origin in (list, frozenset):
        return type(value) is origin and all(_matches(entry, args[0]) for entry in value)
    if origin is dict:
        return type(value) is dict and all(_matches(key, args[0]) and _matches(entry, args[1])
                                          for key, entry in value.items())
    if expected is float:
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    if expected is datetime:
        return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None
    return type(value) is expected


def _semantics(value: Any) -> None:
    if isinstance(value, items.Submission) and value.claims_none and value.entries:
        raise ValueError('artifact submission claims none while listing values')
    if isinstance(value, (interaction.StudentInteraction, interaction.VerificationSnapshot, history.HistoryRecord)):
        if value.revision < 0:
            raise ValueError('artifact revision must be nonnegative')
    if isinstance(value, items.StepDiff) and value.index < 0:
        raise ValueError('artifact step index must be nonnegative')
    if isinstance(value, interaction.TaskProgress):
        if (min(value.submissions, value.genuine_attempts, value.declines) < 0
                or value.genuine_attempts + value.declines != value.submissions
                or value.last_checked_revision is not None and value.last_checked_revision < 0):
            raise ValueError('invalid artifact task progress')
    if isinstance(value, turn.TranscriptEntry) and value.speaker not in ('student', 'tutor'):
        raise ValueError('invalid artifact transcript speaker')
    if isinstance(value, judge.JudgePacket):
        if not value.turn.message.strip() or value.turn.rung_used > value.context.permitted_rung:
            raise ValueError('invalid saved accepted tutor turn')
        if value.context.skill_pack.skill_id != value.context.item.skill_id:
            raise ValueError('artifact skill pack does not match item')
        if value.reference.answer is not None:
            value.reference.answer.check_shape(value.context.item.answer_spec.kind)


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
        for name, kind in _hints(cls).items():
            if name in restored and not _matches(restored[name], kind):
                raise ValueError(f'invalid artifact field type: {cls.__name__}.{name}')
        try:
            result = cls(**{field.name: restored[field.name] for field in fields(cls) if field.init})
        except (TypeError, AttributeError, KeyError, IndexError, ValueError) as exc:
            raise ValueError(f'invalid artifact {cls.__name__}: {exc}') from exc
        for field in fields(cls):
            if not field.init:
                object.__setattr__(result, field.name, restored[field.name])
        _semantics(result)
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
        try:
            result = datetime.fromisoformat(value['$datetime'])
        except (TypeError, ValueError) as exc:
            raise ValueError('invalid artifact datetime') from exc
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
    if not isinstance(report, dict) or not isinstance(report.get('judge_packets'), dict):
        raise ValueError('invalid source packet index')
    packets = {}
    for case_id, entry in report['judge_packets'].items():
        if (not isinstance(case_id, str) or not case_id or not isinstance(entry, dict)
                or not isinstance(entry.get('path'), str) or not isinstance(entry.get('sha256'), str)):
            raise ValueError('invalid source packet entry')
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
        try:
            canonical_json(judge.build_judge_messages(packet))
        except (TypeError, AttributeError, KeyError, IndexError, ValueError) as exc:
            raise ValueError(f'unrenderable saved packet: {case_id}: {exc}') from exc
        packets[case_id] = packet
    eligible_ids = report.get('eligible_ids')
    if (not isinstance(eligible_ids, list) or any(not isinstance(case, str) for case in eligible_ids)
            or len(eligible_ids) != len(set(eligible_ids))):
        raise ValueError('invalid eligible packet ids')
    eligible = set(eligible_ids)
    if not packets or set(packets) != eligible:
        raise ValueError('source artifact has incomplete eligible packets')
    return packets
