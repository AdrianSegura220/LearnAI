"""Request accounting and dated estimates; observed subtotal is never an invoice."""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from learnai.adapters.tutor.observations import TraceSink, UsageObservation, UsageStatus


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
    provider: str
    api_family: str
    normalized_usage: UsageObservation
    schema_version: int = 2
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
        return deepcopy(tuple(self._records.values()))

    def record(self, record: RequestRecord) -> None:
        if record.phase not in {'tutor', 'judge', 'smoke'}:
            raise ValueError('unknown request phase')
        if old := self._records.get(record.request_id):
            identity = ('exchange_id', 'phase', 'scenario_id', 'requested_model', 'provider', 'api_family', 'session_id')
            if any(getattr(old, name) != getattr(record, name) for name in identity):
                raise ValueError('conflicting request identity')
        if (not record.provider or not record.api_family or record.schema_version != 2
                or not isinstance(record.normalized_usage, UsageObservation)
                or record.usage_status != record.normalized_usage.status.value):
            raise ValueError('invalid normalized request observation')
        usage = record.normalized_usage
        validated = UsageObservation(usage.counts, usage.status, usage.reasons, usage.details, usage.billing_conditions)
        self._records[record.request_id] = deepcopy(replace(record, normalized_usage=validated,
            normalized_tokens=dict(validated.counts)))

    def sink(self, *, phase: str, scenario_id: str | None = None) -> TraceSink:
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
                    provider=trace.provider, api_family=trace.api_family, normalized_usage=attempt.normalized_usage,
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
    provider: str
    version: str
    date: str
    currency: str
    unit: int
    rates: dict[str, dict[str, Decimal]]
    source_url: str
    retrieved_at: str
    conditions: dict[str, Any]

    def __post_init__(self) -> None:
        if (any(not isinstance(getattr(self, name), str) or not getattr(self, name).strip()
                for name in ('provider', 'version', 'currency', 'source_url'))
                or type(self.unit) is not int or self.unit <= 0
                or not isinstance(self.rates, dict) or not isinstance(self.conditions, dict)
                or any(not isinstance(name, str) or not name.strip() or not isinstance(value, str)
                       or not value.strip() for name, value in self.conditions.items())
                or any(not isinstance(model, str) or not model.strip() or not isinstance(rates, dict)
                       for model, rates in self.rates.items())
                or any(not isinstance(category, str) or not category.strip()
                       or not isinstance(rate, Decimal) or not rate.is_finite() or rate < 0
                       for rates in self.rates.values() for category, rate in rates.items())):
            raise ValueError('invalid price rate/unit/identity/conditions')
        object.__setattr__(self, 'rates', deepcopy(self.rates))
        object.__setattr__(self, 'conditions', deepcopy(self.conditions))


@dataclass(frozen=True)
class PriceBook:
    snapshots: tuple[PriceSnapshot, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.snapshots, tuple) or any(not isinstance(value, PriceSnapshot) for value in self.snapshots):
            raise ValueError('price book requires a tuple of snapshots')
        object.__setattr__(self, 'snapshots', deepcopy(self.snapshots))
        for index, left in enumerate(self.snapshots):
            for right in self.snapshots[index + 1:]:
                if left.provider != right.provider or not left.rates.keys() & right.rates.keys():
                    continue
                # Overlapping predicates can select two rates for the same attempt.
                if all(left.conditions[key] == right.conditions[key]
                       for key in left.conditions.keys() & right.conditions.keys()):
                    raise ValueError('ambiguous price snapshots')

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible dated evidence for material capture, without conversion."""
        snapshots = []
        for snapshot in self.snapshots:
            entry = asdict(snapshot)
            entry['rates'] = {model: {category: str(rate) for category, rate in rates.items()}
                              for model, rates in snapshot.rates.items()}
            snapshots.append(entry)
        return {'schema_version': 2, 'snapshots': snapshots}


@dataclass(frozen=True)
class CostSummary:
    known_subtotal: Decimal | None
    total: Decimal | None
    complete: bool
    unknown_entries: tuple[str, ...]
    by_phase: dict[str, Decimal] | None
    retry_subtotal: Decimal | None
    currency: str | None
    known_by_currency: Mapping[str, Decimal]


def estimate_cost(ledger: RequestLedger, prices: PriceBook) -> CostSummary:
    by_phase = dict.fromkeys(('tutor', 'judge', 'smoke'), Decimal(0))
    retries, unknown = Decimal(0), []
    known: dict[str, Decimal] = {}
    applicable_currencies: set[str] = set()
    for record in ledger.records:
        usage = record.normalized_usage
        reasons = list(usage.reasons)
        if usage.status is not UsageStatus.COMPLETE:
            reasons.append(f'{usage.status.value} usage')
        candidates = [snapshot for snapshot in prices.snapshots
                      if snapshot.provider == record.provider and record.returned_model in snapshot.rates]
        matches = [snapshot for snapshot in candidates if all(
            (condition := usage.billing_conditions.get(name)) is not None
            and condition.source != 'unknown' and condition.value == expected
            for name, expected in snapshot.conditions.items())]
        subtotal = Decimal(0)
        if not candidates:
            reasons.append(f'unknown model/rates: {record.provider}/{record.returned_model!r}')
        elif not matches:
            reasons.append('unknown or conflicting billing condition')
            # Known contradictory conditions make a snapshot irrelevant to this attempt.
            applicable_currencies.update(snapshot.currency for snapshot in candidates if all(
                (condition := usage.billing_conditions.get(name)) is None
                or condition.source == 'unknown' or condition.value == expected
                for name, expected in snapshot.conditions.items()))
        elif len(matches) != 1:
            raise ValueError('ambiguous price snapshots')
        else:
            snapshot = matches[0]
            applicable_currencies.add(snapshot.currency)
            rates = snapshot.rates[record.returned_model]
            for category, tokens in usage.counts.items():
                if tokens and category not in rates:
                    reasons.append(f'unknown rate: {category}')
                elif tokens:
                    subtotal += Decimal(tokens) * rates[category] / Decimal(snapshot.unit)
            known[snapshot.currency] = known.get(snapshot.currency, Decimal(0)) + subtotal
        by_phase[record.phase] += subtotal
        if record.retry:
            retries += subtotal
        unknown.extend(f'{record.request_id}: {reason}' for reason in dict.fromkeys(reasons))
    multiple = len(applicable_currencies) > 1
    if multiple:
        unknown.append('incompatible currencies; no currency conversion supplied')
    currency = next(iter(applicable_currencies)) if len(applicable_currencies) == 1 else None
    scalar = None if multiple else sum(known.values(), Decimal(0))
    return CostSummary(scalar, None if unknown else scalar, not unknown, tuple(unknown),
        None if multiple else by_phase, None if multiple else retries, currency, known)


def load_prices(path: Path) -> PriceBook:
    try:
        config = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            raise ValueError('pricing configuration must be a mapping')
        if 'pricing' not in config:
            return PriceBook(())
        raw = config['pricing']
        if raw.get('schema_version') == 2:
            entries = raw['snapshots']
            if not isinstance(entries, list):
                raise ValueError('snapshots must be a list')
        elif 'schema_version' not in raw:
            entries = [dict(raw, provider='anthropic')]
        else:
            raise ValueError('unsupported pricing schema version')
        return PriceBook(tuple(PriceSnapshot(provider=entry['provider'], version=entry['version'],
            date=entry['date'], currency=entry['currency'], unit=entry['unit'],
            source_url=entry['source_url'], retrieved_at=entry['retrieved_at'], conditions=entry['conditions'],
            rates={model: {category: Decimal(str(rate)) for category, rate in rates.items()}
                   for model, rates in entry['rates'].items()}) for entry in entries))
    except (OSError, UnicodeError, KeyError, TypeError, AttributeError, InvalidOperation, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f'invalid pricing snapshot: {exc}') from exc
