"""Request-local allowances and private, replayable tutor traces."""
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from learnai.adapters.tutor.anthropic.routing import BudgetProfile
from learnai.adapters.tutor.context import ContextView
from learnai.domain.turn import TutorTurn, ValidationResult


class TerminationReason(str, Enum):
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    DEADLINE = "deadline"
    CONTEXT_LIMIT = "context_limit"
    ROUND_TRIP_LIMIT = "round_trip_limit"
    OUTPUT_LIMIT = "output_limit"
    NETWORK_EXHAUSTED = "network_exhausted"
    API_ERROR = "api_error"
    FORMAT_EXHAUSTED = "format_exhausted"
    VALIDATION_EXHAUSTED = "validation_exhausted"
    REFUSAL = "refusal"
    TRUNCATED = "truncated"
    SILENT = "silent"


DEFAULT_BUDGET_PROFILES = {
    "brief": BudgetProfile(3, 8, 4, 8, 4096, 16000, 512),
    "normal": BudgetProfile(8, 15, 8, 16, 8192, 16000, 1024),
    "substantial": BudgetProfile(20, 30, 12, 24, 16384, 24000, 1024),
    "complex": BudgetProfile(30, 60, 20, 40, 32768, 32000, 2048),
}


class ResponseBudget:
    """One monotonic deadline; failed API attempts also consume model calls."""
    def __init__(self, profile: BudgetProfile, *, monotonic: Callable[[], float]) -> None:
        self.profile = profile
        self.monotonic = monotonic
        self.started_at = monotonic()
        self.deadline = self.started_at + profile.hard_seconds
        self.model_calls = 0
        self.tool_calls = 0
        self.output_tokens = 0

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self.monotonic() - self.started_at)

    @property
    def remaining_output_tokens(self) -> int:
        return max(0, self.profile.max_output_tokens - self.output_tokens)

    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - self.monotonic())

    def expired(self) -> bool:
        return self.remaining_seconds() <= 0

    def can_explore(self) -> bool:
        return (self.can_execute_tool()
                and self.model_calls < self.profile.max_round_trips - 1)

    def can_execute_tool(self) -> bool:
        return (not self.expired() and self.elapsed_seconds < self.profile.soft_seconds
                and self.tool_calls < self.profile.max_tool_calls
                and self.remaining_output_tokens > self.profile.finalization_reserve_tokens)

    def record_model_call(self, output_tokens: int) -> None:
        self.model_calls += 1
        self.record_output_tokens(output_tokens)

    def record_output_tokens(self, output_tokens: int) -> None:
        if type(output_tokens) is not int or output_tokens < 0:
            raise ValueError("output_tokens must be a nonnegative integer")
        self.output_tokens += output_tokens

    def record_tool_calls(self, count: int) -> None:
        if type(count) is not int or count < 0:
            raise ValueError("tool count must be a nonnegative integer")
        self.tool_calls += count


def conservative_token_count(text: str) -> int:
    """UTF-8 bytes plus framing margin: deliberately overestimates text tokens.

    Counts full serialized requests, including tool/schema scaffolding. This is
    local admission control, not a billing estimate or a provider count request.
    """
    return len(text.encode("utf-8")) + 256


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


class UsageStatus(str, Enum):
    """Missing/partial observations must never be priced as a known zero."""
    MISSING = "missing"
    PARTIAL = "partial"
    COMPLETE = "complete"


@dataclass
class ProviderAttempt:
    request_index: int
    usage_status: UsageStatus = UsageStatus.MISSING
    usage: dict[str, Any] | None = None
    provider_request_id: str | None = None


@dataclass
class TurnTrace:
    """Private operational data. Never a source for delivered session history."""
    request_id: str
    student_id: str | None
    session_id: str | None
    task_id: str | None
    item_id: str
    revision: int | None
    prompt_ids: tuple[str, ...]
    model: str
    settings: dict[str, Any]
    context_view: ContextView | None = None
    source_ids: tuple[str, ...] = ()
    initial_context: str | None = None
    provider_requests: list[dict[str, Any]] = field(default_factory=list)
    provider_responses: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    validation_results: list[ValidationResult] = field(default_factory=list)
    usages: list[dict[str, Any]] = field(default_factory=list)
    api_errors: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[ProviderAttempt] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    api_retries: int = 0
    format_retries: int = 0
    validation_retries: int = 0
    output_tokens: int = 0
    termination_reason: TerminationReason | None = None
    accepted: TutorTurn | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_value(asdict(self))
