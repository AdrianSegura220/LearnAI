"""Disjoint Responses usage accounting without SDK or commercial price assumptions."""
from collections.abc import Mapping

from learnai.adapters.tutor.observations import BillingCondition, UsageObservation, UsageStatus

MAPPER_VERSION = 'openai-responses@1'
_USAGE_FIELDS = {'input_tokens', 'input_tokens_details', 'output_tokens', 'output_tokens_details', 'total_tokens'}


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
    counts = {}
    def valid(value):
        return type(value) is int and value >= 0
    total_input, output = raw.get('input_tokens'), raw.get('output_tokens')
    if valid(output):
        counts['output'] = output
    else:
        reasons.append('missing or invalid output_tokens')
    details = raw.get('input_tokens_details')
    cached = details.get('cached_tokens') if isinstance(details, Mapping) else None
    write_unknown = False
    if isinstance(details, Mapping):
        if details.keys() - {'cached_tokens', 'cache_write_tokens'}:
            reasons.append('unknown input token detail categories')
        if 'cache_write_tokens' in details and (not valid(details['cache_write_tokens']) or details['cache_write_tokens'] != 0):
            reasons.append('unsupported cache write token subset')
            write_unknown = True
    if not valid(total_input):
        reasons.append('missing or invalid input_tokens')
    if not valid(cached):
        reasons.append('missing or invalid cached_tokens subset')
    elif valid(total_input) and cached > total_input:
        reasons.append('cached_tokens exceeds inclusive input_tokens')
    else:
        counts['cache_read'] = cached
        if valid(total_input) and not write_unknown:
            counts['input'] = total_input - cached
    out_details = raw.get('output_tokens_details')
    if out_details is not None:
        if not isinstance(out_details, Mapping):
            reasons.append('invalid output_tokens_details')
        else:
            reasoning = out_details.get('reasoning_tokens')
            if not valid(reasoning) or (valid(output) and reasoning > output):
                reasons.append('missing or invalid reasoning_tokens subset')
            if out_details.keys() - {'reasoning_tokens'}:
                reasons.append('unknown output token detail categories')
    if 'total_tokens' in raw and (not valid(raw['total_tokens']) or
        (valid(total_input) and valid(output) and raw['total_tokens'] != total_input + output)):
        reasons.append('invalid inclusive total_tokens')
    if unknown := raw.keys() - _USAGE_FIELDS:
        reasons.append('unknown usage categories: ' + ', '.join(sorted(unknown)))
    return UsageObservation(counts, UsageStatus.PARTIAL if reasons else UsageStatus.COMPLETE,
        tuple(reasons), {'mapper_version': MAPPER_VERSION, **dict(raw)}, conditions)
