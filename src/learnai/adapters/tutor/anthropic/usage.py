"""SDK-free normalization of Anthropic Messages usage and billing evidence."""
from collections.abc import Mapping

from learnai.adapters.tutor.observations import BillingCondition, UsageObservation, UsageStatus

MAPPER_VERSION = 'anthropic-messages@1'
_USAGE_FIELDS = {'input_tokens', 'output_tokens', 'cache_read_input_tokens',
    'cache_creation_input_tokens', 'cache_creation', 'service_tier', 'inference_geo',
    'server_tool_use', 'output_tokens_details', 'speed'}
_CACHE_FIELDS = {'ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens'}


def _conditions(raw: Mapping[str, object], metadata: Mapping[str, object],
                settings: Mapping[str, object] | None) -> dict[str, BillingCondition]:
    conditions = {}
    for name in ('service_tier', 'inference_geo', 'speed'):
        # Usage fields are authoritative; response-level metadata is accepted when
        # usage does not expose that condition. Explicit invalid values stay unknown.
        if name in raw or name in metadata:
            value = raw[name] if name in raw else metadata[name]
            location = f'usage.{name}' if name in raw else f'response.{name}'
            conditions[name] = (BillingCondition(value, 'returned', location)
                if isinstance(value, str) and value.strip()
                else BillingCondition(None, 'unknown', f'{location} missing or invalid'))
        elif name == 'service_tier' and settings is not None and settings.get(name) == 'standard_only':
            conditions[name] = BillingCondition('standard', 'requested',
                'request.service_tier=standard_only restricts execution to standard tier; '
                'https://platform.claude.com/docs/en/api/service-tiers')
        elif name == 'speed' and settings is not None and name not in settings:
            # Only a complete effective request establishes absence of opt-in.
            # Do not infer this default for old traces with unknown settings.
            conditions[name] = BillingCondition('standard', 'documented_default',
                'request.speed omitted: fast mode requires explicit opt-in; '
                'https://platform.claude.com/docs/en/build-with-claude/fast-mode')
        else:
            conditions[name] = BillingCondition(None, 'unknown',
                f'{name} not returned; request/default does not establish actual billing condition')
    return conditions


def normalize_anthropic_usage(
    raw: Mapping[str, object] | None, *, status: UsageStatus,
    response_metadata: Mapping[str, object] | None = None,
    request_settings: Mapping[str, object] | None = None,
) -> UsageObservation:
    """Keep disjoint known counters and mark all unsupported usage incomplete.

    The optional cache counters describe absent caching as zero. A positive
    creation aggregate without duration evidence cannot establish either TTL.
    Billing conditions have separate provenance and do not change token status;
    pricing decides which conditions are required for its applicable rates.
    """
    if not isinstance(status, UsageStatus):
        raise ValueError('explicit UsageStatus required')
    conditions = _conditions(raw or {}, response_metadata or {}, request_settings)
    if raw is None:
        return UsageObservation({}, UsageStatus.MISSING, ('missing usage',),
            {'mapper_version': MAPPER_VERSION}, conditions)
    counts: dict[str, int] = {}
    reasons = []
    if status is not UsageStatus.COMPLETE:
        reasons.append(f'{status.value} usage')
    for name, category in (('input_tokens', 'input'), ('output_tokens', 'output'),
                           ('cache_read_input_tokens', 'cache_read')):
        value = raw.get(name, 0 if name == 'cache_read_input_tokens' else None)
        if type(value) is int and value >= 0:
            counts[category] = value
        else:
            reasons.append(f'missing or invalid {name}')
    aggregate = raw.get('cache_creation_input_tokens', 0)
    valid_aggregate = type(aggregate) is int and aggregate >= 0
    if not valid_aggregate:
        reasons.append('invalid cache creation aggregate')
    nested = raw.get('cache_creation')
    if isinstance(nested, Mapping):
        total = 0
        valid_nested = True
        for name, category in (('ephemeral_5m_input_tokens', 'cache_write_5m'),
                               ('ephemeral_1h_input_tokens', 'cache_write_1h')):
            value = nested.get(name)
            if type(value) is int and value >= 0:
                counts[category] = value
                total += value
            else:
                valid_nested = False
                reasons.append(f'invalid cache creation {name}')
        if valid_nested and valid_aggregate and 'cache_creation_input_tokens' in raw and total != aggregate:
            reasons.append('cache creation aggregate differs from duration counters')
        if nested.keys() - _CACHE_FIELDS:
            reasons.append('unknown usage cache creation category')
    elif 'cache_creation' in raw:
        reasons.append('invalid cache creation metadata')
    elif valid_aggregate and aggregate == 0:
        counts.update(cache_write_5m=0, cache_write_1h=0)
    elif valid_aggregate:
        reasons.append('cache creation duration unknown')
    unknown = raw.keys() - _USAGE_FIELDS
    if unknown:
        reasons.append('unknown usage categories: ' + ', '.join(sorted(unknown)))
    tools = raw.get('server_tool_use')
    if tools is not None and (not isinstance(tools, Mapping) or any(
        type(value) is not int or value != 0 for value in tools.values()
    )):
        reasons.append('unknown server_tool_use rates or counters')
    details = {'mapper_version': MAPPER_VERSION, **{
        key: value for key, value in raw.items()
        if key not in {'input_tokens', 'output_tokens', 'cache_read_input_tokens',
                       'cache_creation_input_tokens', 'cache_creation'}
    }}
    return UsageObservation(counts, UsageStatus.PARTIAL if reasons else UsageStatus.COMPLETE,
                            tuple(reasons), details, conditions)
