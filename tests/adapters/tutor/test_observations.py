"""Provider-neutral observations validate and snapshot their plain JSON evidence."""
from dataclasses import FrozenInstanceError
import json

import pytest

from learnai.adapters.tutor.observations import (
    BillingCondition, JudgeTrace, ProviderAttempt, RequestTrace, UsageObservation, UsageStatus,
)


def test_observation_copies_inputs_and_freezes_fields():
    counts = {'input': 3}
    details = {'raw': {'values': [1]}}
    conditions = {'tier': BillingCondition('A', 'returned', 'response.tier')}
    observation = UsageObservation(counts, UsageStatus.COMPLETE, details=details,
                                   billing_conditions=conditions)
    counts['input'] = 99
    details['raw']['values'].append(2)
    conditions.clear()
    assert observation.counts == {'input': 3}
    assert observation.details == {'raw': {'values': [1]}}
    assert observation.billing_conditions['tier'].value == 'A'
    with pytest.raises(FrozenInstanceError):
        observation.status = UsageStatus.MISSING


@pytest.mark.parametrize('count', [True, -1, 1.5, '1', None])
def test_counts_reject_non_integer_or_negative_values(count):
    with pytest.raises(ValueError):
        UsageObservation({'input': count}, UsageStatus.COMPLETE)


def test_status_is_explicit_and_defaults_are_fresh():
    with pytest.raises(ValueError):
        UsageObservation({}, 'complete')
    first = UsageObservation({}, UsageStatus.MISSING)
    second = UsageObservation({}, UsageStatus.MISSING)
    first.details['value'] = 1
    first.billing_conditions['tier'] = BillingCondition(None, 'unknown', 'not returned')
    assert second.details == {} and second.billing_conditions == {}


@pytest.mark.parametrize('details', [{'value': object()}, {1: 'value'}, {'n': float('inf')},
                                    {'n': float('nan')}, {'nested': [object()]}])
def test_details_reject_non_json_evidence(details):
    with pytest.raises(ValueError):
        UsageObservation({}, UsageStatus.MISSING, details=details)


@pytest.mark.parametrize('value,source,evidence', [
    (None, 'returned', 'response.tier'), ('A', 'unknown', 'not returned'),
    (' ', 'requested', 'request.tier'), ('A', 'returned', ''),
    ('A', 'guessed', 'response.tier'),
])
def test_billing_condition_requires_value_and_evidence_for_its_provenance(value, source, evidence):
    with pytest.raises(ValueError):
        BillingCondition(value, source, evidence)


def test_trace_emission_snapshots_observations_and_raw_usage():
    raw = {'input_tokens': 3, 'output_tokens': 0}
    attempt = ProviderAttempt(0, usage_status=UsageStatus.COMPLETE, usage=raw,
        normalized_usage=UsageObservation({'input': 3, 'output': 0}, UsageStatus.COMPLETE))
    trace = JudgeTrace('request', ('rubric@1',), 'fiction-model', {},
                       provider='fiction', api_family='messages', attempts=[attempt])
    assert isinstance(trace, RequestTrace)
    snapshot = trace.to_dict()
    raw['input_tokens'] = 20
    attempt.normalized_usage.counts['input'] = 20
    assert snapshot['attempts'][0]['usage']['input_tokens'] == 3
    assert snapshot['attempts'][0]['normalized_usage']['counts']['input'] == 3
    assert json.loads(json.dumps(snapshot))['provider'] == 'fiction'


def test_trace_identity_is_required_and_attempt_status_agrees_on_emission():
    with pytest.raises(TypeError):
        JudgeTrace('request', (), 'fiction-model', {})
    trace = JudgeTrace('request', (), 'fiction-model', {}, provider='fiction', api_family='messages',
        attempts=[ProviderAttempt(0, usage_status=UsageStatus.COMPLETE)])
    with pytest.raises(ValueError, match='status'):
        trace.to_dict()


def test_trace_emission_rejects_non_json_raw_usage():
    trace = JudgeTrace('request', (), 'fiction-model', {}, provider='fiction', api_family='messages',
                      attempts=[ProviderAttempt(0, usage={'bad': object()})])
    with pytest.raises(ValueError):
        trace.to_dict()
