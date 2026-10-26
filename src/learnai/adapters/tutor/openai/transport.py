"""Responses SDK calls, bounded retries, stream completion and attempt evidence."""
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
import time

import httpx2
from openai import APIConnectionError, APIError, APIStatusError, OpenAI

from learnai.adapters.tutor.observations import ProviderAttempt, UsageStatus
from learnai.adapters.tutor.openai.usage import normalize_openai_usage
from learnai.adapters.tutor.runtime import ResponseBudget, TerminationReason

MAX_API_ATTEMPTS = 3


class ResponsesTransport:
    """One transport shares the role's budget and trace; it never owns role policy."""
    def __init__(self, client: OpenAI, budget: ResponseBudget, trace, *,
                 count_tokens: Callable[[str], int], sleep: Callable[[float], None] = time.sleep):
        self.client = client.with_options(max_retries=0)
        self.budget, self.trace = budget, trace
        self.count_tokens, self.sleep = count_tokens, sleep
        self.stop_reason: TerminationReason | None = None

    def available(self) -> bool:
        if self.stop_reason is not None:
            return False
        if self.budget.expired():
            self.stop_reason = TerminationReason.DEADLINE
        elif self.budget.model_calls >= self.budget.profile.max_round_trips:
            self.stop_reason = TerminationReason.ROUND_TRIP_LIMIT
        elif self.budget.remaining_output_tokens <= 0:
            self.stop_reason = TerminationReason.OUTPUT_LIMIT
        return self.stop_reason is None

    def call(self, payload: Callable[[], dict], *, retry: bool = False) -> dict | None:
        import json
        for attempt_index in range(MAX_API_ATTEMPTS):
            if not self.available():
                return None
            body = payload()
            if self.count_tokens(json.dumps(body, ensure_ascii=False, separators=(',', ':'))) + body['max_output_tokens'] > self.budget.profile.context_input_tokens:
                self.stop_reason = TerminationReason.CONTEXT_LIMIT
                return None
            if self.budget.expired():
                self.stop_reason = TerminationReason.DEADLINE
                return None
            self.trace.provider_requests.append(deepcopy(body))
            observed = ProviderAttempt(len(self.trace.provider_requests) - 1,
                started_at=datetime.now(UTC).isoformat(), retry=retry or attempt_index > 0,
                normalized_usage=normalize_openai_usage(None, status=UsageStatus.MISSING, request_settings=body))
            self.trace.attempts.append(observed)
            self.budget.record_model_call(0)
            started = self.budget.monotonic()
            try:
                response = self.client.responses.create(**body, timeout=self.budget.remaining_seconds())
                if body['stream']:
                    raw = self._stream(response, observed, body)
                    if raw is None:
                        return None
                else:
                    raw = response.model_dump(mode='json', exclude_unset=True)
                    observed.provider_request_id = getattr(response, '_request_id', None)
                    self._record(raw, observed, body, complete=True)
            except (APIConnectionError, APIStatusError) as exc:
                status = getattr(exc, 'status_code', None)
                observed.outcome = type(exc).__name__
                observed.provider_request_id = getattr(exc, 'request_id', None)
                self.trace.api_errors.append({'type': type(exc).__name__, 'status_code': status,
                    'request_id': observed.provider_request_id, 'attempt': self.budget.model_calls})
                if self.budget.expired():
                    self.stop_reason = TerminationReason.DEADLINE
                    return None
                if status is not None and status not in (408, 409, 429) and status < 500:
                    self.stop_reason = TerminationReason.API_ERROR
                    return None
                if attempt_index == MAX_API_ATTEMPTS - 1:
                    self.stop_reason = TerminationReason.NETWORK_EXHAUSTED
                    return None
                if not self.available():
                    return None
                self.trace.api_retries += 1
                self.sleep(min(0.25 * 2 ** attempt_index, self.budget.remaining_seconds()))
                continue
            finally:
                observed.finish(elapsed_seconds=self.budget.monotonic() - started)
            if self.budget.expired():
                self.stop_reason = TerminationReason.DEADLINE
                return None
            if self.budget.output_tokens > self.budget.profile.max_output_tokens:
                self.stop_reason = TerminationReason.OUTPUT_LIMIT
                return None
            return raw
        return None

    def _record(self, raw: dict, attempt: ProviderAttempt, body: dict, *, complete: bool) -> None:
        usage = raw.get('usage')
        attempt.usage = deepcopy(usage) if isinstance(usage, dict) else None
        attempt.response, attempt.response_model = deepcopy(raw), raw.get('model')
        attempt.normalized_usage = normalize_openai_usage(attempt.usage,
            status=UsageStatus.COMPLETE if complete else UsageStatus.PARTIAL,
            response_metadata=raw, request_settings=body)
        attempt.usage_status = attempt.normalized_usage.status
        attempt.outcome = raw.get('status') if complete else 'partial_response'
        self.trace.provider_responses.append(deepcopy(raw))
        if attempt.usage is not None:
            self.trace.usages.append(deepcopy(attempt.usage))
        output = attempt.normalized_usage.counts.get('output')
        # Missing terminal usage cannot grant unbounded formatting/tool retries.
        # Reserve the call's full allowed output locally, keeping billing unknown.
        debit = output if output is not None else (body['max_output_tokens'] if complete else 0)
        self.budget.record_output_tokens(debit)

    def _stream(self, stream, attempt: ProviderAttempt, body: dict) -> dict | None:
        attempt.provider_request_id = stream.response.headers.get('x-request-id')
        snapshot = None
        terminal = False
        try:
            with stream:
                for event in stream:
                    data = event.model_dump(mode='json', exclude_unset=True)
                    self.trace.events.append(deepcopy(data))
                    if isinstance(data.get('response'), dict):
                        snapshot = data['response']
                    terminal = data['type'] in ('response.completed', 'response.incomplete', 'response.failed')
                    if self.budget.expired():
                        self.stop_reason = TerminationReason.DEADLINE
                        break
                    if terminal:
                        break
        except (httpx2.TransportError, APIError) as exc:
            self.trace.api_errors.append({'type': type(exc).__name__,
                'status_code': getattr(exc, 'status_code', None),
                'request_id': attempt.provider_request_id, 'attempt': self.budget.model_calls})
        if terminal and snapshot is not None and self.stop_reason is None:
            self._record(snapshot, attempt, body, complete=True)
            return snapshot
        if snapshot is not None:
            self._record(snapshot, attempt, body, complete=False)
        else:
            attempt.outcome = 'partial_response'
        if self.stop_reason is None:
            self.stop_reason = TerminationReason.NETWORK_EXHAUSTED
        return None
