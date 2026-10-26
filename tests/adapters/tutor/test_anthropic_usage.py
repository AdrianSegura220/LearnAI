"""SDK-free Anthropic billing counters remain disjoint and evidence-backed."""
from copy import deepcopy

import pytest

from learnai.adapters.tutor.anthropic.usage import normalize_anthropic_usage
from learnai.adapters.tutor.observations import UsageStatus


def test_unknown_usage_is_not_known_zero():
    value = normalize_anthropic_usage(None, status=UsageStatus.MISSING)
    assert value.counts == {}
    assert value.status is UsageStatus.MISSING
    assert value.reasons


def test_disjoint_counts_preserve_raw_usage_and_nonbillable_output_details():
    raw = {'input_tokens': 100, 'output_tokens': 40, 'cache_read_input_tokens': 200,
           'cache_creation_input_tokens': 300,
           'cache_creation': {'ephemeral_5m_input_tokens': 100, 'ephemeral_1h_input_tokens': 200},
           'output_tokens_details': {'reasoning_tokens': 12}}
    original = deepcopy(raw)
    value = normalize_anthropic_usage(raw, status=UsageStatus.COMPLETE)
    assert value.counts == {'input': 100, 'output': 40, 'cache_read': 200,
                            'cache_write_5m': 100, 'cache_write_1h': 200}
    assert value.status is UsageStatus.COMPLETE
    assert value.details['output_tokens_details'] == {'reasoning_tokens': 12}
    assert raw == original
    raw['output_tokens_details']['reasoning_tokens'] = 999
    assert value.details['output_tokens_details']['reasoning_tokens'] == 12


def test_explicit_zero_and_partial_observations_keep_known_counts():
    raw = {'input_tokens': 0, 'output_tokens': 0}
    complete = normalize_anthropic_usage(raw, status=UsageStatus.COMPLETE)
    assert complete.counts == {'input': 0, 'output': 0, 'cache_read': 0,
                               'cache_write_5m': 0, 'cache_write_1h': 0}
    assert complete.status is UsageStatus.COMPLETE
    partial = normalize_anthropic_usage(raw, status=UsageStatus.PARTIAL)
    assert partial.counts == complete.counts
    assert partial.status is UsageStatus.PARTIAL and partial.reasons


@pytest.mark.parametrize('nested', ['invalid', [], 0, False, None])
def test_malformed_nested_cache_writes_are_incomplete(nested):
    value = normalize_anthropic_usage({'input_tokens': 3, 'output_tokens': 4,
        'cache_creation_input_tokens': 0, 'cache_creation': nested}, status=UsageStatus.COMPLETE)
    assert value.status is UsageStatus.PARTIAL
    assert value.counts == {'input': 3, 'output': 4, 'cache_read': 0}
    assert any('cache creation' in reason for reason in value.reasons)


def test_cache_aggregate_mismatch_does_not_double_count():
    value = normalize_anthropic_usage({'input_tokens': 1, 'output_tokens': 2,
        'cache_creation_input_tokens': 99,
        'cache_creation': {'ephemeral_5m_input_tokens': 5, 'ephemeral_1h_input_tokens': 7}},
        status=UsageStatus.COMPLETE)
    assert value.counts == {'input': 1, 'output': 2, 'cache_read': 0,
                            'cache_write_5m': 5, 'cache_write_1h': 7}
    assert value.status is UsageStatus.PARTIAL
    assert any('aggregate' in reason for reason in value.reasons)


def test_unknown_cache_duration_and_missing_input_do_not_fabricate_zero():
    value = normalize_anthropic_usage({'output_tokens': 2, 'cache_creation_input_tokens': 5},
                                      status=UsageStatus.COMPLETE)
    assert value.counts == {'output': 2, 'cache_read': 0}
    assert value.status is UsageStatus.PARTIAL
    assert any('duration' in reason for reason in value.reasons)


@pytest.mark.parametrize('extra', [{'server_tool_use': {'web_search_requests': 1}},
                                 {'server_tool_use': 'invalid'}, {'mystery_tokens': 1},
                                 {'cache_creation': {'ephemeral_5m_input_tokens': True}}])
def test_unknown_or_invalid_usage_keeps_known_subtotals(extra):
    value = normalize_anthropic_usage({'input_tokens': 3, 'output_tokens': 4, **extra},
                                      status=UsageStatus.COMPLETE)
    assert value.counts['input'] == 3 and value.counts['output'] == 4
    assert value.status is UsageStatus.PARTIAL and value.reasons


def test_returned_billing_condition_overrides_requested():
    value = normalize_anthropic_usage({'input_tokens': 0, 'output_tokens': 0},
        status=UsageStatus.COMPLETE, response_metadata={'service_tier': 'tier-B'},
        request_settings={'service_tier': 'tier-A'})
    condition = value.billing_conditions['service_tier']
    assert condition.value == 'tier-B' and condition.source == 'returned'
    assert 'service_tier' in condition.evidence


def test_missing_condition_is_unknown_without_documented_default():
    value = normalize_anthropic_usage({'input_tokens': 0, 'output_tokens': 0}, status=UsageStatus.COMPLETE)
    condition = value.billing_conditions['inference_geo']
    assert condition.value is None and condition.source == 'unknown'
    assert condition.evidence


def test_requested_standard_only_retains_documented_rule_evidence():
    value = normalize_anthropic_usage({'input_tokens': 0, 'output_tokens': 0},
        status=UsageStatus.COMPLETE, request_settings={'service_tier': 'standard_only'})
    condition = value.billing_conditions['service_tier']
    assert condition.value == 'standard' and condition.source == 'requested'
    assert 'standard_only' in condition.evidence


def test_documented_condition_default_retains_evidence():
    value = normalize_anthropic_usage({'input_tokens': 0, 'output_tokens': 0},
                                      status=UsageStatus.COMPLETE, request_settings={})
    condition = value.billing_conditions['speed']
    assert condition.value == 'standard' and condition.source == 'documented_default'
    assert 'fast-mode' in condition.evidence and 'speed' in condition.evidence
    unknown = normalize_anthropic_usage({'input_tokens': 0, 'output_tokens': 0},
                                        status=UsageStatus.COMPLETE)
    assert unknown.billing_conditions['speed'].source == 'unknown'


def test_returned_usage_conditions_take_precedence_over_response_and_request():
    value = normalize_anthropic_usage({'input_tokens': 0, 'output_tokens': 0, 'service_tier': 'tier-C'},
        status=UsageStatus.COMPLETE, response_metadata={'service_tier': 'tier-B'},
        request_settings={'service_tier': 'tier-A', 'speed': 'fast'})
    assert value.billing_conditions['service_tier'].value == 'tier-C'
    assert value.billing_conditions['speed'].source == 'unknown'


def test_missing_nested_duration_counter_is_unknown_not_zero():
    value = normalize_anthropic_usage({'input_tokens': 1, 'output_tokens': 2,
        'cache_creation_input_tokens': 5, 'cache_creation': {'ephemeral_5m_input_tokens': 5}},
        status=UsageStatus.COMPLETE)
    assert value.counts == {'input': 1, 'output': 2, 'cache_read': 0, 'cache_write_5m': 5}
    assert value.status is UsageStatus.PARTIAL
    assert any('ephemeral_1h_input_tokens' in reason for reason in value.reasons)
