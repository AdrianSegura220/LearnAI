"""One provider attempt incurs cost once; unobserved tokens are never free."""
from dataclasses import replace
from decimal import Decimal

import pytest

from learnai.eval.accounting import PriceBook, PriceSnapshot, RequestLedger, RequestRecord, estimate_cost


def snapshot():
    return PriceSnapshot('anthropic', 'synthetic@1', '2026-10-26', 'USD', 1000000,
        {'fiction-model': {'input': Decimal('2'), 'cache_read': Decimal('1'),
                          'cache_write_5m': Decimal('3'), 'cache_write_1h': Decimal('6'),
                          'output': Decimal('4')}}, 'https://example.test/pricing', '2026-10-26',
        {'service_tier': 'standard', 'inference_geo': 'not_available'})


def prices():
    return PriceBook((snapshot(),))


def record(request_id='a', *, usage=None, phase='tutor', **changes):
    raw = dict(input_tokens=100, cache_read_input_tokens=200, cache_creation_input_tokens=300,
               cache_creation={'ephemeral_5m_input_tokens': 300, 'ephemeral_1h_input_tokens': 0}, output_tokens=400)
    return RequestRecord(request_id=request_id, exchange_id='exchange', phase=phase, scenario_id='case',
        provider='anthropic', api_family='messages', normalized_usage=normalized(raw if usage is None else usage),
        requested_model='fiction-alias', returned_model='fiction-model', settings={},
        raw_usage=raw if usage is None else usage, usage_status=normalized(raw if usage is None else usage).status.value, **changes)


def normalized(raw, status='complete'):
    from learnai.adapters.tutor.anthropic.usage import normalize_anthropic_usage
    from learnai.adapters.tutor.observations import UsageStatus
    return normalize_anthropic_usage(raw, status=UsageStatus(status),
        response_metadata={'service_tier':'standard','inference_geo':'not_available'})


def changed_record(record, **changes):
    raw = changes.get('raw_usage', record.raw_usage)
    usage = normalized(raw, changes.get('usage_status',record.usage_status))
    return replace(record, **changes, normalized_usage=usage, **({} if 'usage_status' in changes else {'usage_status':usage.status.value}))


def test_disjoint_nested_usage_cost_and_idempotent_updates():
    ledger = RequestLedger()
    ledger.record(record())
    ledger.record(record())
    assert len(ledger.records) == 1
    result = estimate_cost(ledger, prices())
    assert result.known_subtotal == Decimal('0.0029')
    assert result.total == Decimal('0.0029') and result.complete
    ledger.record(record('b', phase='judge', retry=True))
    result = estimate_cost(ledger, prices())
    assert result.total == Decimal('0.0058')
    assert result.by_phase == {'tutor': Decimal('0.0029'), 'judge': Decimal('0.0029'), 'smoke': Decimal('0')}
    assert result.retry_subtotal == Decimal('0.0029')
    with pytest.raises(ValueError, match='identity'):
        ledger.record(replace(record(), phase='judge'))


def test_duration_categories_do_not_double_charge_the_creation_aggregate():
    ledger = RequestLedger()
    ledger.record(record(usage={'input_tokens': 0, 'output_tokens': 0, 'cache_read_input_tokens': 0,
        'cache_creation_input_tokens': 300,
        'cache_creation': {'ephemeral_5m_input_tokens': 100, 'ephemeral_1h_input_tokens': 200}}))
    assert estimate_cost(ledger, prices()).total == Decimal('0.0015')


@pytest.mark.parametrize('changes,reason', [
    ({'raw_usage': None, 'usage_status': 'missing'}, 'missing usage'),
    ({'usage_status': 'partial'}, 'partial usage'),
    ({'returned_model': 'unknown-model'}, 'unknown model'),
    ({'raw_usage': {'input_tokens': 0}}, 'output'),
    ({'raw_usage': {'input_tokens': 0, 'output_tokens': 0, 'cache_creation_input_tokens': 5}}, 'duration'),
    ({'raw_usage': {'input_tokens': 0, 'output_tokens': 0, 'mystery_tokens': 5}}, 'unknown usage'),
    ({'raw_usage': {'input_tokens': 0, 'output_tokens': 0, 'service_tier': 'batch'}}, 'condition'),
])
def test_unknowns_keep_known_subtotal_without_claiming_a_total(changes, reason):
    ledger = RequestLedger()
    ledger.record(record())
    ledger.record(changed_record(record('unknown'), **changes))
    result = estimate_cost(ledger, prices())
    assert not result.complete and result.total is None
    assert result.known_subtotal >= Decimal('0.0029')
    assert any(reason in item for item in result.unknown_entries)


def test_explicit_zero_is_known_and_missing_rate_is_incomplete():
    ledger = RequestLedger()
    ledger.record(record(usage={'input_tokens': 0, 'output_tokens': 0}))
    assert estimate_cost(ledger, prices()).total == 0
    ledger.record(record('paid'))
    book = PriceBook((replace(snapshot(), rates={'fiction-model': {'input': Decimal('2')}}),))
    result = estimate_cost(ledger, book)
    assert not result.complete and result.total is None
    assert result.known_subtotal == Decimal('0.0002')


def test_invalid_pricing_snapshot_is_a_local_validation_error(tmp_path):
    import yaml
    from learnai.eval.accounting import load_prices
    path = tmp_path / 'routes.yaml'
    path.write_text(yaml.safe_dump({'pricing': {'version': 'test', 'date': '2026-10-26', 'currency': 'USD',
        'unit': 1000000, 'rates': {'fiction-model': {'input': 'not-a-price'}},
        'source_url': 'https://example.test', 'retrieved_at': '2026-10-26', 'conditions': {}}}))
    with pytest.raises(ValueError, match='pricing'):
        load_prices(path)


@pytest.mark.parametrize('nested', ['invalid', [], 0, False, None])
@pytest.mark.parametrize('aggregate', [None, 0])
def test_present_malformed_cache_creation_is_unknown_even_without_positive_aggregate(nested, aggregate):
    raw = {'input_tokens': 1, 'output_tokens': 2, 'cache_creation': nested}
    if aggregate is not None:
        raw['cache_creation_input_tokens'] = aggregate
    ledger = RequestLedger()
    ledger.record(record(usage=raw))
    result = estimate_cost(ledger, prices())
    assert result.total is None and not result.complete
    assert result.known_subtotal == Decimal('0.000010')
    assert any('cache creation' in reason for reason in result.unknown_entries)
