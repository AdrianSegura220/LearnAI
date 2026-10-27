from learnai.adapters.tutor.observations import UsageStatus
from learnai.adapters.tutor.openai.usage import normalize_openai_usage
import pytest


def test_openai_usage_counts_cached_and_reasoning_subsets_once():
    result = normalize_openai_usage({'input_tokens': 1000,
        'input_tokens_details': {'cached_tokens': 300}, 'output_tokens': 200,
        'output_tokens_details': {'reasoning_tokens': 80}}, status=UsageStatus.COMPLETE)
    assert result.counts == {'input': 700, 'cache_read': 300, 'output': 200}
    assert result.status is UsageStatus.COMPLETE


@pytest.mark.parametrize('raw,known', [
    (None, {}),
    ({'input_tokens': 10, 'output_tokens': 0}, {'output': 0}),
    ({'input_tokens': 10, 'input_tokens_details': {'cached_tokens': 11}, 'output_tokens': 0}, {'output': 0}),
    ({'input_tokens': 10, 'input_tokens_details': {'cached_tokens': True}, 'output_tokens': 2}, {'output': 2}),
])
def test_unknown_subsets_preserve_only_known_disjoint_counts(raw, known):
    result = normalize_openai_usage(raw, status=UsageStatus.COMPLETE)
    assert result.counts == known
    assert result.status is not UsageStatus.COMPLETE
    assert result.reasons


@pytest.mark.parametrize('update', [
    {'unexpected_tokens': 4},
    {'output_tokens_details': {'reasoning_tokens': 999}},
    {'input_tokens_details': {'cached_tokens': 1, 'future_tokens': 3}},
    {'input_tokens_details': {'cached_tokens': 1, 'cache_write_tokens': 2}},
    {'total_tokens': 9999},
])
def test_unknown_or_malformed_categories_are_incomplete(update):
    raw = {'input_tokens': 10, 'input_tokens_details': {'cached_tokens': 1},
           'output_tokens': 4, 'output_tokens_details': {'reasoning_tokens': 2}, **update}
    result = normalize_openai_usage(raw, status=UsageStatus.COMPLETE)
    assert result.status is UsageStatus.PARTIAL and result.reasons
    assert result.counts['output'] == 4


def test_billing_conditions_preserve_returned_requested_mismatch_and_unknown():
    result = normalize_openai_usage(None, status=UsageStatus.MISSING,
        response_metadata={'service_tier': 'flex'}, request_settings={'service_tier': 'default'})
    condition = result.billing_conditions['service_tier']
    assert condition.value == 'flex' and condition.source == 'returned'
    assert 'mismatch' in condition.evidence
    missing = normalize_openai_usage(None, status=UsageStatus.MISSING)
    assert missing.billing_conditions['service_tier'].source == 'unknown'
    assert missing.billing_conditions['inference_geo'].value is None


def test_mixed_cache_writes_are_disjoint_and_reasoning_is_counted_once():
    raw = {'input_tokens': 12000, 'input_tokens_details': {'cached_tokens': 4000,
        'cache_write_tokens': 7000, 'cache_write_tokens_details': {
            'ttl_30m_tokens': 3000, 'ttl_12h_tokens': 4000}},
        'output_tokens': 200, 'output_tokens_details': {'reasoning_tokens': 80}, 'total_tokens': 12200}
    result = normalize_openai_usage(raw, status=UsageStatus.COMPLETE)
    assert result.counts == {'input': 1000, 'cache_read': 4000, 'cache_write_30m': 3000,
        'cache_write_12h': 4000, 'output': 200}
    assert result.status is UsageStatus.COMPLETE
    assert result.details == {'mapper_version': 'openai-responses@2', **raw}


@pytest.mark.parametrize('write_fields,known,status', [
    ({}, {'input': 80, 'cache_read': 20, 'output': 5}, UsageStatus.COMPLETE),
    ({'cache_write_tokens': 0}, {'input': 80, 'cache_read': 20, 'cache_write_30m': 0,
        'cache_write_12h': 0, 'output': 5}, UsageStatus.COMPLETE),
    ({'cache_write_tokens': 40}, {'cache_read': 20, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens': True}, {'cache_read': 20, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens': -1}, {'cache_read': 20, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens': 40, 'cache_write_tokens_details': {'ttl_30m_tokens': 10}},
        {'cache_read': 20, 'cache_write_30m': 10, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens_details': {'ttl_30m_tokens': 10, 'ttl_12h_tokens': 30}},
        {'input': 40, 'cache_read': 20, 'cache_write_30m': 10, 'cache_write_12h': 30, 'output': 5},
        UsageStatus.COMPLETE),
    ({'cache_write_tokens': 50, 'cache_write_tokens_details': {'ttl_30m_tokens': 10, 'ttl_12h_tokens': 30}},
        {'cache_read': 20, 'cache_write_30m': 10, 'cache_write_12h': 30, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens': '40', 'cache_write_tokens_details': {'ttl_30m_tokens': 10, 'ttl_12h_tokens': 30}},
        {'cache_read': 20, 'cache_write_30m': 10, 'cache_write_12h': 30, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens_details': {'ttl_30m_tokens': 10, 'ttl_12h_tokens': False}},
        {'cache_read': 20, 'cache_write_30m': 10, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens_details': {'ttl_30m_tokens': -1, 'ttl_12h_tokens': 30}},
        {'cache_read': 20, 'cache_write_12h': 30, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens': 30, 'cache_write_tokens_details': {'ttl_30m_tokens': 40, 'ttl_12h_tokens': 10}},
        {'cache_read': 20, 'cache_write_12h': 10, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens': 100, 'cache_write_tokens_details': {'ttl_30m_tokens': 90, 'ttl_12h_tokens': 10}},
        {'cache_read': 20, 'cache_write_12h': 10, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens_details': {'ttl_30m_tokens': 50, 'ttl_12h_tokens': 40}},
        {'cache_read': 20, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens': 40, 'cache_write_tokens_details': {'ttl_30m_tokens': 30, 'ttl_12h_tokens': 30}},
        {'cache_read': 20, 'output': 5}, UsageStatus.PARTIAL),
    ({'cache_write_tokens_details': {'ttl_30m_tokens': 10, 'ttl_12h_tokens': 30, 'future': 2}},
        {'cache_read': 20, 'cache_write_30m': 10, 'cache_write_12h': 30, 'output': 5}, UsageStatus.PARTIAL),
])
def test_write_evidence_preserves_only_independently_known_disjoint_subtotals(write_fields, known, status):
    raw = {'input_tokens': 100, 'input_tokens_details': {'cached_tokens': 20, **write_fields},
        'output_tokens': 5}
    result = normalize_openai_usage(raw, status=UsageStatus.COMPLETE,
        request_settings={'prompt_cache_options': {'mode': 'implicit', 'ttl': '12h'}})
    assert result.counts == known
    assert result.status is status
    assert result.details['input_tokens_details'] == raw['input_tokens_details']


@pytest.mark.parametrize('nested', [None, False, [], 'invalid', 0])
@pytest.mark.parametrize('aggregate', [None, 0, 40])
def test_present_malformed_write_details_never_establish_uncached_input(nested, aggregate):
    details = {'cached_tokens': 20, 'cache_write_tokens_details': nested}
    if aggregate is not None:
        details['cache_write_tokens'] = aggregate
    result = normalize_openai_usage({'input_tokens': 100, 'input_tokens_details': details,
        'output_tokens': 5}, status=UsageStatus.COMPLETE)
    assert result.counts == {'cache_read': 20, 'output': 5}
    assert result.status is UsageStatus.PARTIAL


@pytest.mark.parametrize('input_tokens,cached,expected', [
    (None, 20, {'cache_read': 20, 'cache_write_30m': 10, 'cache_write_12h': 30, 'output': 5}),
    (100, None, {'cache_write_30m': 10, 'cache_write_12h': 30, 'output': 5}),
    (100, 101, {'cache_write_30m': 10, 'cache_write_12h': 30, 'output': 5}),
])
def test_independent_write_counts_survive_missing_input_or_invalid_read(input_tokens, cached, expected):
    result = normalize_openai_usage({'input_tokens': input_tokens, 'input_tokens_details': {
        'cached_tokens': cached, 'cache_write_tokens': 40,
        'cache_write_tokens_details': {'ttl_30m_tokens': 10, 'ttl_12h_tokens': 30}},
        'output_tokens': 5}, status=UsageStatus.COMPLETE)
    assert result.counts == expected
    assert result.status is UsageStatus.PARTIAL


def test_unknown_input_detail_prevents_invented_uncached_total():
    result = normalize_openai_usage({'input_tokens': 100, 'input_tokens_details': {
        'cached_tokens': 20, 'future_tokens': 4}, 'output_tokens': 5}, status=UsageStatus.COMPLETE)
    assert result.counts == {'cache_read': 20, 'output': 5}
    assert result.status is UsageStatus.PARTIAL
