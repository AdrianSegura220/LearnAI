"""Disjoint Responses usage accounting without SDK or commercial price assumptions."""
from collections.abc import Mapping

from learnai.adapters.tutor.observations import BillingCondition, UsageObservation, UsageStatus

MAPPER_VERSION = 'openai-responses@2'
_USAGE_FIELDS = {'input_tokens', 'input_tokens_details', 'output_tokens', 'output_tokens_details', 'total_tokens'}
_WRITE_FIELDS = {'ttl_30m_tokens': 'cache_write_30m', 'ttl_12h_tokens': 'cache_write_12h'}


def _valid(value: object) -> bool:
    return type(value) is int and value >= 0


def _cache_writes(details: Mapping[str, object], inclusive: object, cached: int | None,
                  counts: dict[str, int], reasons: list[str]) -> int | None:
    """Return a proven write total, preserving only independently bounded buckets.

    Legacy absent write evidence implies no new categories. A returned zero
    aggregate proves zero writes; a positive aggregate never establishes TTL.
    Conflicts leave input unknown and never select one contradictory source.
    """
    has_aggregate = 'cache_write_tokens' in details
    has_nested = 'cache_write_tokens_details' in details
    if not has_aggregate and not has_nested:
        return 0
    aggregate = details.get('cache_write_tokens')
    valid_aggregate = _valid(aggregate)
    remaining = inclusive - (cached or 0) if _valid(inclusive) else None
    aggregate_bounded = valid_aggregate and (remaining is None or aggregate <= remaining)
    if has_aggregate and not valid_aggregate:
        reasons.append('invalid cache_write_tokens aggregate')
    elif has_aggregate and not aggregate_bounded:
        reasons.append('cache_write_tokens exceeds inclusive input subset')
    if not has_nested:
        if aggregate_bounded and aggregate == 0:
            counts.update(cache_write_30m=0, cache_write_12h=0)
            return 0
        if valid_aggregate:
            reasons.append('cache write duration unknown')
        return None
    nested = details['cache_write_tokens_details']
    if not isinstance(nested, Mapping):
        reasons.append('invalid cache_write_tokens_details')
        return None
    complete = True
    for name, category in _WRITE_FIELDS.items():
        value = nested.get(name)
        if not _valid(value):
            reasons.append(f'missing or invalid cache write {name}')
            complete = False
        elif (remaining is not None and value > remaining) or (valid_aggregate and value > aggregate):
            reasons.append(f'cache write {name} exceeds input or aggregate subset')
            complete = False
        else:
            counts[category] = value
    total = sum(counts.get(category, 0) for category in _WRITE_FIELDS.values())
    if (remaining is not None and total > remaining) or (valid_aggregate and total > aggregate):
        # Each bucket could fit alone, but retaining both would overcount known
        # usage. The response provides no basis for choosing which one to trust.
        for category in _WRITE_FIELDS.values():
            counts.pop(category, None)
        reasons.append('cache write duration sum exceeds input or aggregate subset')
        complete = False
    if nested.keys() - _WRITE_FIELDS.keys():
        reasons.append('unknown cache write duration categories')
        complete = False
    if has_aggregate and (not aggregate_bounded or total != aggregate):
        if valid_aggregate and total != aggregate:
            reasons.append('cache write aggregate differs from duration counters')
        complete = False
    return total if complete else None


def _conditions(metadata: Mapping[str, object], settings: Mapping[str, object]) -> dict[str, BillingCondition]:
    returned = metadata.get('service_tier')
    requested = settings.get('service_tier')
    if returned in ('default', 'flex', 'priority'):
        evidence = 'response.service_tier (actual processing mode)'
        if requested is not None and requested != returned:
            evidence += f'; mismatch with request.service_tier={requested}'
        tier = BillingCondition(returned, 'returned', evidence)
    else:
        # Even an explicit request can be served by a different tier. Do not
        # treat the request or the project-dependent auto default as execution.
        tier = BillingCondition(None, 'unknown', 'response.service_tier missing or unsupported; '
            'request does not establish actual mode; '
            'https://developers.openai.com/api/reference/resources/responses/methods/create')
    return {'service_tier': tier, 'inference_geo': BillingCondition(None, 'unknown',
        'Responses does not establish billing geography from model or request; endpoint evidence unavailable')}


def normalize_openai_usage(raw: Mapping[str, object] | None, *, status: UsageStatus,
        response_metadata: Mapping[str, object] | None = None,
        request_settings: Mapping[str, object] | None = None) -> UsageObservation:
    if not isinstance(status, UsageStatus):
        raise ValueError('explicit UsageStatus required')
    conditions = _conditions(response_metadata or {}, request_settings or {})
    if raw is None:
        return UsageObservation({}, UsageStatus.MISSING, ('missing usage',),
            {'mapper_version': MAPPER_VERSION}, conditions)
    reasons = [] if status is UsageStatus.COMPLETE else [f'{status.value} usage']
    counts: dict[str, int] = {}
    total_input, output = raw.get('input_tokens'), raw.get('output_tokens')
    if _valid(output):
        counts['output'] = output
    else:
        reasons.append('missing or invalid output_tokens')
    details = raw.get('input_tokens_details')
    cached = details.get('cached_tokens') if isinstance(details, Mapping) else None
    known_details = True
    if isinstance(details, Mapping):
        if details.keys() - {'cached_tokens', 'cache_write_tokens', 'cache_write_tokens_details'}:
            reasons.append('unknown input token detail categories')
            known_details = False
    if not _valid(total_input):
        reasons.append('missing or invalid input_tokens')
    if not _valid(cached):
        reasons.append('missing or invalid cached_tokens subset')
    elif _valid(total_input) and cached > total_input:
        reasons.append('cached_tokens exceeds inclusive input_tokens')
    else:
        counts['cache_read'] = cached
    if isinstance(details, Mapping):
        writes = _cache_writes(details, total_input, counts.get('cache_read'), counts, reasons)
        if _valid(total_input) and 'cache_read' in counts and writes is not None and known_details:
            counts['input'] = total_input - cached - writes
    out_details = raw.get('output_tokens_details')
    if out_details is not None:
        if not isinstance(out_details, Mapping):
            reasons.append('invalid output_tokens_details')
        else:
            reasoning = out_details.get('reasoning_tokens')
            if not _valid(reasoning) or (_valid(output) and reasoning > output):
                reasons.append('missing or invalid reasoning_tokens subset')
            if out_details.keys() - {'reasoning_tokens'}:
                reasons.append('unknown output token detail categories')
    if 'total_tokens' in raw and (not _valid(raw['total_tokens']) or
        (_valid(total_input) and _valid(output) and raw['total_tokens'] != total_input + output)):
        reasons.append('invalid inclusive total_tokens')
    if unknown := raw.keys() - _USAGE_FIELDS:
        reasons.append('unknown usage categories: ' + ', '.join(sorted(unknown)))
    return UsageObservation(counts, UsageStatus.PARTIAL if reasons else UsageStatus.COMPLETE,
        tuple(reasons), {'mapper_version': MAPPER_VERSION, **dict(raw)}, conditions)
