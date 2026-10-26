"""Provider-neutral, request-local usage and trace evidence; no SDK imports."""
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
import math
from typing import Any, Literal, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from learnai.adapters.tutor.runtime import TerminationReason


class UsageStatus(str, Enum):
    """Missing/partial observations must never be priced as a known zero."""
    MISSING = "missing"
    PARTIAL = "partial"
    COMPLETE = "complete"


def _plain_json(value: object) -> object:
    """Validate finite plain JSON and copy containers without admitting SDK objects."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError('JSON mapping keys must be strings')
        return {key: _plain_json(item) for key, item in value.items()}
    if type(value) is list:
        return [_plain_json(item) for item in value]
    raise ValueError('evidence must contain only finite plain JSON values')


@dataclass(frozen=True)
class BillingCondition:
    value: str | None
    source: Literal['returned', 'requested', 'documented_default', 'unknown']
    evidence: str

    def __post_init__(self) -> None:
        if self.source not in {'returned', 'requested', 'documented_default', 'unknown'}:
            raise ValueError('invalid billing condition source')
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError('billing condition evidence is required')
        if self.source == 'unknown':
            if self.value is not None:
                raise ValueError('unknown billing condition value must be null')
        elif not isinstance(self.value, str) or not self.value.strip():
            raise ValueError('known billing condition value must be nonblank')


@dataclass(frozen=True)
class UsageObservation:
    counts: Mapping[str, int]
    status: UsageStatus
    reasons: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)
    billing_conditions: Mapping[str, BillingCondition] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, UsageStatus):
            raise ValueError('explicit UsageStatus required')
        if not isinstance(self.counts, Mapping) or any(
            type(key) is not str or type(value) is not int or value < 0
            for key, value in self.counts.items()
        ):
            raise ValueError('counts require string categories and nonnegative integer values')
        if any(type(reason) is not str or not reason.strip() for reason in self.reasons):
            raise ValueError('usage reasons must be nonblank strings')
        if not isinstance(self.details, Mapping):
            raise ValueError('usage details must be a mapping')
        if not isinstance(self.billing_conditions, Mapping) or any(
            type(key) is not str or not isinstance(value, BillingCondition)
            for key, value in self.billing_conditions.items()
        ):
            raise ValueError('invalid billing conditions')
        object.__setattr__(self, 'counts', dict(self.counts))
        object.__setattr__(self, 'reasons', tuple(self.reasons))
        object.__setattr__(self, 'details', _plain_json(self.details))
        object.__setattr__(self, 'billing_conditions', deepcopy(dict(self.billing_conditions)))


def _missing_usage() -> UsageObservation:
    return UsageObservation({}, UsageStatus.MISSING, ('missing usage',))


@dataclass
class ProviderAttempt:
    request_index: int
    usage_status: UsageStatus = UsageStatus.MISSING
    usage: dict[str, Any] | None = None
    provider_request_id: str | None = None
    response_model: str | None = None
    response: dict[str, Any] | None = None
    started_at: str | None = None
    ended_at: str | None = None
    elapsed_seconds: float | None = None
    outcome: str = 'started'
    retry: bool = False
    normalized_usage: UsageObservation = field(default_factory=_missing_usage)

    def finish(self, *, elapsed_seconds: float) -> None:
        self.ended_at = datetime.now(UTC).isoformat()
        self.elapsed_seconds = max(0.0, elapsed_seconds)
        if self.outcome == 'started':
            self.outcome = 'no_usable_response'


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError('JSON mapping keys must be strings')
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return _plain_json(value)


def trace_dict(trace: Any) -> dict[str, Any]:
    for attempt in trace.attempts:
        if attempt.usage_status is not attempt.normalized_usage.status:
            raise ValueError('attempt usage status disagrees with normalized usage status')
        _plain_json(attempt.usage)
        _plain_json(attempt.response)
        # Revalidate mutable owned maps before emission, too.
        UsageObservation(attempt.normalized_usage.counts, attempt.normalized_usage.status,
            attempt.normalized_usage.reasons, attempt.normalized_usage.details,
            attempt.normalized_usage.billing_conditions)
    return _json_value(asdict(trace))


@runtime_checkable
class RequestTrace(Protocol):
    provider: str
    api_family: str
    request_id: str
    route_name: str | None
    model: str
    @property
    def settings(self) -> Mapping[str, object]: ...

    @property
    def attempts(self) -> Sequence[ProviderAttempt]: ...

    @property
    def provider_requests(self) -> Sequence[Mapping[str, object]]: ...

    def to_dict(self) -> dict[str, Any]: ...


TraceSink = Callable[[RequestTrace], None]


@dataclass
class JudgeTrace:
    """Neutral judge observations inspectable without loading a provider SDK."""
    request_id: str
    prompt_ids: tuple[str, ...]
    model: str
    settings: dict[str, Any]
    provider: str
    api_family: str
    route_name: str | None = None
    attempts: list[ProviderAttempt] = field(default_factory=list)
    provider_requests: list[dict[str, Any]] = field(default_factory=list)
    provider_responses: list[dict[str, Any]] = field(default_factory=list)
    usages: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    api_errors: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    model_calls: int = 0
    output_tokens: int = 0
    api_retries: int = 0
    format_retries: int = 0
    termination_reason: 'TerminationReason | None' = None

    def to_dict(self) -> dict[str, Any]:
        return trace_dict(self)
