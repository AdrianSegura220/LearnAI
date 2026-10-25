"""Request accounting and dated estimates; observed subtotal is never an invoice."""
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RequestRecord:
    request_id: str
    exchange_id: str
    phase: str
    scenario_id: str | None
    requested_model: str
    returned_model: str | None
    settings: dict[str, Any]
    raw_usage: dict[str, Any] | None
    usage_status: str
    session_id: str | None = None
    provider_request_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    elapsed_seconds: float | None = None
    outcome: str = 'unknown'
    retry: bool = False
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    normalized_tokens: dict[str, int] = field(default_factory=dict)


class RequestLedger:
    """Upsert the same attempt; conflicting attempt identities are an error."""
    def __init__(self) -> None:
        self._records: dict[str, RequestRecord] = {}
        self.traces: dict[str, dict[str, Any]] = {}

    @property
    def records(self) -> tuple[RequestRecord, ...]:
        return tuple(self._records.values())

    def record(self, record: RequestRecord) -> None:
        if record.phase not in {'tutor', 'judge', 'smoke'}:
            raise ValueError('unknown request phase')
        if old := self._records.get(record.request_id):
            identity = ('exchange_id', 'phase', 'scenario_id', 'requested_model')
            if any(getattr(old, name) != getattr(record, name) for name in identity):
                raise ValueError('conflicting request identity')
        counts, _ = normalize_usage(record.raw_usage)
        self._records[record.request_id] = deepcopy(replace(record, normalized_tokens=counts))

    def sink(self, *, phase: str, scenario_id: str | None = None) -> Callable[[Any], None]:
        """Shared request-local trace sink for tutor, judge and future smoke."""
        def capture(trace: Any) -> None:
            self.traces[trace.request_id] = {'phase': phase, 'scenario_id': scenario_id,
                                            'trace': deepcopy(trace.to_dict())}
            for attempt in trace.attempts:
                index = attempt.request_index
                response = getattr(attempt, 'response', None)
                self.record(RequestRecord(
                    request_id=f'{trace.request_id}:{index}', exchange_id=trace.request_id,
                    phase=phase, scenario_id=scenario_id, session_id=getattr(trace, 'session_id', None),
                    requested_model=trace.model, returned_model=getattr(attempt, 'response_model', None),
                    settings=trace.settings, provider_request_id=attempt.provider_request_id,
                    started_at=getattr(attempt, 'started_at', None), ended_at=getattr(attempt, 'ended_at', None),
                    elapsed_seconds=getattr(attempt, 'elapsed_seconds', None),
                    raw_usage=attempt.usage, usage_status=attempt.usage_status.value,
                    outcome=getattr(attempt, 'outcome', 'unknown'), retry=attempt.retry,
                    request=trace.provider_requests[index], response=response))
        return capture


@dataclass(frozen=True)
class PriceSnapshot:
    version: str
    date: str
    currency: str
    unit: int
    rates: dict[str, dict[str, Decimal]]
    source_url: str
    retrieved_at: str
    conditions: dict[str, Any]

    def __post_init__(self) -> None:
        if self.unit <= 0 or any(not rate.is_finite() or rate < 0
                               for rates in self.rates.values() for rate in rates.values()):
            raise ValueError('invalid price rate/unit')


@dataclass(frozen=True)
class CostSummary:
    known_subtotal: Decimal
    total: Decimal | None
    complete: bool
    unknown_entries: tuple[str, ...]
    by_phase: dict[str, Decimal]
    retry_subtotal: Decimal
    currency: str


_USAGE_FIELDS = {'input_tokens', 'output_tokens', 'cache_read_input_tokens',
    'cache_creation_input_tokens', 'cache_creation', 'service_tier', 'inference_geo',
    'server_tool_use'}


def normalize_usage(raw: dict[str, Any] | None) -> tuple[dict[str, int], list[str]]:
    """Anthropic disjoint input counters; nested creation replaces its aggregate."""
    if raw is None:
        return {}, ['missing usage']
    counts, reasons = {}, []
    for field, category in (('input_tokens', 'input'), ('output_tokens', 'output'),
                            ('cache_read_input_tokens', 'cache_read')):
        value = raw.get(field, 0 if field == 'cache_read_input_tokens' else None)
        if type(value) is int and value >= 0:
            counts[category] = value
        else:
            reasons.append(f'missing or invalid {field}')
    nested = raw.get('cache_creation')
    aggregate = raw.get('cache_creation_input_tokens', 0)
    if type(aggregate) is not int or aggregate < 0:
        reasons.append('invalid cache creation aggregate')
    if isinstance(nested, dict):
        total = 0
        for field, category in (('ephemeral_5m_input_tokens', 'cache_write_5m'),
                                ('ephemeral_1h_input_tokens', 'cache_write_1h')):
            value = nested.get(field, 0)
            if type(value) is int and value >= 0:
                counts[category] = value
                total += value
            else:
                reasons.append(f'invalid {field}')
        if 'cache_creation_input_tokens' in raw and total != aggregate:
            reasons.append('cache creation aggregate differs from duration counters')
        if nested.keys() - {'ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens'}:
            reasons.append('unknown usage cache creation category')
    elif aggregate:
        reasons.append('cache creation duration unknown')
    if raw.keys() - _USAGE_FIELDS:
        reasons.append('unknown usage categories: ' + ', '.join(sorted(raw.keys() - _USAGE_FIELDS)))
    tool_use = raw.get('server_tool_use')
    if tool_use is not None and (not isinstance(tool_use, dict) or any(tool_use.values())):
        reasons.append('unknown server_tool_use rates or counters')
    return counts, reasons


def estimate_cost(ledger: RequestLedger, prices: PriceSnapshot) -> CostSummary:
    by_phase = dict.fromkeys(('tutor', 'judge', 'smoke'), Decimal(0))
    retries, unknown = Decimal(0), []
    for record in ledger.records:
        counts, reasons = normalize_usage(record.raw_usage)
        if record.usage_status != 'complete':
            reasons.append(f'{record.usage_status} usage')
        rates = prices.rates.get(record.returned_model or '')
        if rates is None:
            reasons.append(f'unknown model: {record.returned_model!r}')
        conditions_match = True
        for name, expected in prices.conditions.items():
            actual = (record.raw_usage or {}).get(name, record.settings.get(name, expected))
            if actual is not None and actual != expected:
                conditions_match = False
                reasons.append(f'unsupported billing condition {name}={actual!r}')
        subtotal = Decimal(0)
        if rates is not None and conditions_match:
            for category, tokens in counts.items():
                if not tokens:
                    continue
                if category not in rates:
                    reasons.append(f'unknown rate: {category}')
                else:
                    subtotal += Decimal(tokens) * rates[category] / Decimal(prices.unit)
        by_phase[record.phase] += subtotal
        if record.retry:
            retries += subtotal
        unknown.extend(f'{record.request_id}: {reason}' for reason in dict.fromkeys(reasons))
    total = sum(by_phase.values(), Decimal(0))
    return CostSummary(total, None if unknown else total, not unknown, tuple(unknown), by_phase, retries,
                       prices.currency)


def load_prices(path: Path) -> PriceSnapshot:
    try:
        raw = yaml.safe_load(path.read_text(encoding='utf-8'))['pricing']
        return PriceSnapshot(version=raw['version'], date=raw['date'], currency=raw['currency'],
            unit=raw['unit'], source_url=raw['source_url'], retrieved_at=raw['retrieved_at'],
            conditions=raw['conditions'], rates={model: {category: Decimal(str(rate))
                for category, rate in rates.items()} for model, rates in raw['rates'].items()})
    except (OSError, UnicodeError, KeyError, TypeError, AttributeError, InvalidOperation, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f'invalid pricing snapshot: {exc}') from exc
