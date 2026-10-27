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
