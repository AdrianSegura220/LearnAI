"""Provider identity, normalized accounting and immutable saved-run compatibility."""
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pytest

from learnai.adapters.tutor.observations import BillingCondition, UsageObservation, UsageStatus
from learnai.eval import accounting


def observation(counts=None, **conditions):
    return UsageObservation(counts or {'input':100}, UsageStatus.COMPLETE,
        billing_conditions={key:BillingCondition(value,'returned','synthetic response') for key,value in conditions.items()})


def request(provider='anthropic', request_id='a', normalized=None):
    return accounting.RequestRecord(request_id=request_id,exchange_id='exchange',phase='tutor',scenario_id='case',
        requested_model='same-name',returned_model='same-name',settings={'service_tier':'requested'},
        raw_usage={'vendor_secret_counter':999999},usage_status='complete',provider=provider,api_family='test',
        normalized_usage=normalized or observation())


def price(provider='anthropic', rate='2', currency='USD', conditions=None):
    return accounting.PriceSnapshot(provider=provider,version='test',date='2026-10-26',currency=currency,unit=1000000,
        rates={'same-name':{'input':Decimal(rate)}},source_url='https://example.test',retrieved_at='2026-10-26',conditions=conditions or {})


def test_provider_is_part_of_model_identity():
    ledger=accounting.RequestLedger()
    ledger.record(request())
    ledger.record(request('openai','b'))
    result=accounting.estimate_cost(ledger,accounting.PriceBook((price(),price('openai','4'))))
    assert result.complete and result.known_subtotal==Decimal('0.0006')


def test_price_uses_returned_condition_not_requested():
    ledger=accounting.RequestLedger()
    ledger.record(request(normalized=observation(service_tier='returned')))
    prices=accounting.PriceBook((price(rate='2',conditions={'service_tier':'requested'}),price(rate='4',conditions={'service_tier':'returned'})))
    assert accounting.estimate_cost(ledger,prices).total==Decimal('0.0004')


def test_unknown_condition_retains_other_known_subtotals():
    ledger=accounting.RequestLedger()
    ledger.record(request())
    ledger.record(request('openai','b'))
    result=accounting.estimate_cost(ledger,accounting.PriceBook((price(),price('openai',conditions={'tier':'standard'}))))
    assert result.total is None and result.known_subtotal==Decimal('0.0002')


def test_mixed_currencies_and_unused_prices():
    ledger=accounting.RequestLedger()
    ledger.record(request())
    book=accounting.PriceBook((price(),price('openai','4','EUR')))
    assert accounting.estimate_cost(ledger,book).currency=='USD'
    ledger.record(request('openai','b'))
    result=accounting.estimate_cost(ledger,book)
    assert result.known_by_currency=={'USD':Decimal('.0002'),'EUR':Decimal('.0004')}
    assert result.currency is result.known_subtotal is result.by_phase is result.retry_subtotal is result.total is None
    assert not result.complete
    assert accounting.estimate_cost(accounting.RequestLedger(),book).currency is None


def test_ledger_snapshots_nested_usage_and_provider_identity():
    ledger=accounting.RequestLedger()
    r=request()
    ledger.record(r)
    r.normalized_usage.counts['input']=1
    first=ledger.records[0]
    first.normalized_usage.counts['input']=2
    assert ledger.records[0].normalized_usage.counts['input']==100
    with pytest.raises(ValueError,match='identity'):
        ledger.record(request('openai'))
    with pytest.raises(ValueError,match='ambiguous'):
        accounting.PriceBook((price(),price()))


def test_frozen_v1_fixture_and_checksums():
    from learnai.application.artifacts import load_saved_run
    root=Path(__file__).parents[1]/'fixtures/eval_v1'
    checks=json.loads((root/'checksums.json').read_text())
    assert {str(p.relative_to(root/'run')):sha256(p.read_bytes()).hexdigest() for p in (root/'run').rglob('*') if p.is_file()}==checks
    saved=load_saved_run(root/'run')
    assert saved.manifest['run_id']=='baseline-v1-synthetic'
    assert saved.records[0].provider=='anthropic'
    assert saved.records[0].normalized_usage.counts['input']==100
    assert saved.records[0].normalized_usage.billing_conditions['service_tier'].source=='unknown'
    assert saved.report['score_averages']['mathematics']==2
    assert saved.packets['synthetic-case'].turn.message
    assert saved.compatibility_notes


def test_v2_roundtrip_conditions_and_local_rejection(tmp_path):
    from learnai.application.artifacts import load_saved_run
    from learnai.eval.manifest import build_manifest
    from learnai.eval.report import write_report
    from tests.eval.test_judge import packet
    ledger=accounting.RequestLedger()
    ledger.record(request(normalized=observation(tier='returned')))
    manifest=build_manifest(root=tmp_path,selected_ids=('case',),seeds=(7,),settings={},prompts={},references={})
    run=write_report(tmp_path,manifest=manifest,outcomes={},scores={},judge_packets={'case':packet()},ledger=ledger,
        prices=accounting.PriceBook((price(),)),persona_smoke={})
    saved=load_saved_run(run)
    assert saved.records==ledger.records
    assert saved.records[0].normalized_usage.billing_conditions['tier'].source=='returned'
    report=json.loads((run/'report.json').read_text())
    report['judge_packets']['case']['sha256']='bad'
    (run/'report.json').write_text(json.dumps(report))
    with pytest.raises(ValueError,match='hash'):
        load_saved_run(run)
    manifest=json.loads((run/'manifest.json').read_text())
    manifest['schema_version']=999
    (run/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='unsupported'):
        load_saved_run(run)


def compared(*,model='same-name',provider='anthropic',tutor_version='1',judge_version='1',transport_version='1',prompt='fixed',budget=10):
    from learnai.eval.artifacts import SavedRun
    route={'adapter':provider,'model':model,'prompt':'tutor@1'}
    judge={'adapter':'anthropic','model':'same-name','prompt':'judge@1'}
    settings={'routes':{'tutor':route,'judge':judge},'judge_route':'judge','budgets':{'tokens':budget}}
    material={'settings':settings,'prompts':{'tutor@1':prompt,'judge@1':'fixed'},'references':{'case':'ref'},
        'pricing_snapshots':{'schema_version':2,'snapshots':[]},'python':'3.12','dependencies':{provider:tutor_version,'anthropic':judge_version,'httpx':transport_version},
        'role_dependencies':{'tutor':{provider:tutor_version,'httpx':transport_version},'judge':{'anthropic':judge_version,'httpx':transport_version}},
        'identities':{'tutor':{'tutor':{'provider':provider,'api_family':provider,'schema_hashes':{'final_output':provider,'canonical_read_tools':'canonical-fixed','wire_read_tools':provider},'usage_mapper_id':provider,'token_counter_id':'fixed'}},'judge':{'judge':{'provider':'anthropic','api_family':'messages','schema_hashes':{'final_output':'fixed'},'usage_mapper_id':'fixed','token_counter_id':'fixed'}}},
        'inputs':[],'missing_inputs':[],'deleted_inputs':[],'saved_packet_inputs':[]}
    manifest={'schema_version':2,'run_id':'test','selected_ids':['case'],'seeds':[1],'code_revision':'abc','material':material}
    return SavedRun(Path('unused'),manifest,(request(provider), replace(request('anthropic','j'),phase='judge',api_family='messages')),{}, {'score_averages':{'mathematics':2}})


def test_controlled_comparison_requires_declaration():
    from learnai.eval.report import compare_runs,TutorTreatment
    left,right=compared(),compared(provider='openai')
    assert not compare_runs(left,right)['controlled_tutor_comparison']['eligible']
    result=compare_runs(left,right,treatment=TutorTreatment(('tutor',)))
    assert result['controlled_tutor_comparison']['eligible'],result
    assert not result['direct_comparison_inputs_held_fixed']
    for changed in (compared(provider='openai',prompt='edited'),compared(provider='openai',budget=20)):
        assert not compare_runs(left,changed,treatment=TutorTreatment(('tutor',)))['controlled_tutor_comparison']['eligible']
    with pytest.raises(ValueError): TutorTreatment(('tutor','tutor'))
    assert not compare_runs(left,left,treatment=TutorTreatment(('judge',)))['controlled_tutor_comparison']['eligible']


def test_tutor_only_sdk_change_requires_opt_in():
    from learnai.eval.report import compare_runs,TutorTreatment
    left,right=compared(provider='openai'),compared(provider='openai',tutor_version='2')
    assert not compare_runs(left,right,treatment=TutorTreatment(('tutor',)))['controlled_tutor_comparison']['eligible']
    assert compare_runs(left,right,treatment=TutorTreatment(('tutor',),True))['controlled_tutor_comparison']['eligible']


def test_shared_judge_sdk_change_blocks_controlled_comparison():
    from learnai.eval.report import compare_runs,TutorTreatment
    assert not compare_runs(compared(),compared(provider='openai',judge_version='2'),treatment=TutorTreatment(('tutor',),True))['controlled_tutor_comparison']['eligible']


def test_shared_transport_change_blocks_controlled_comparison():
    from learnai.eval.report import compare_runs,TutorTreatment
    assert not compare_runs(compared(provider='openai'),compared(provider='openai',transport_version='2'),treatment=TutorTreatment(('tutor',),True))['controlled_tutor_comparison']['eligible']


def test_empty_and_missing_price_coverage_are_valid(tmp_path):
    from learnai.eval.accounting import load_prices
    path=tmp_path/'prices.yaml'
    path.write_text('routes: {}\n')
    assert load_prices(path).snapshots==()
    ledger=accounting.RequestLedger()
    ledger.record(request())
    result=accounting.estimate_cost(ledger,load_prices(path))
    assert not result.complete and result.total is None and result.known_by_currency=={}
    path.write_text('pricing:\n  schema_version: 2\n  snapshots: []\n')
    assert load_prices(path).snapshots==()


def test_config_hash_changes_are_classified_by_full_semantics():
    from copy import deepcopy
    import yaml
    from learnai.eval.report import compare_runs,TutorTreatment
    left,right=compared(),compared(provider='openai')
    for run in (left,right):
        content=yaml.safe_dump(run.manifest['material']['settings'])
        run.manifest['material']['inputs']=[{'path':'config/selected/routes.yaml','content':content,'sha256':sha256(content.encode()).hexdigest()}]
    assert compare_runs(left,right,treatment=TutorTreatment(('tutor',)))['controlled_tutor_comparison']['eligible']
    right.manifest['material']['inputs'][0]['content']+='\nprompts: edited\n'
    right.manifest['material']['inputs'][0]['sha256']='changed'
    assert not compare_runs(left,right,treatment=TutorTreatment(('tutor',)))['controlled_tutor_comparison']['eligible']


def test_changed_judge_provider_with_same_model_blocks_treatment():
    from learnai.eval.report import compare_runs,TutorTreatment
    left,right=compared(),compared(provider='openai')
    right.manifest['material']['settings']['routes']['judge']['adapter']='openai'
    assert not compare_runs(left,right,treatment=TutorTreatment(('tutor',)))['controlled_tutor_comparison']['eligible']


def test_cli_dependency_flag_requires_treatment(capsys):
    from learnai.eval.__main__ import main
    assert main(['compare','missing','missing','--allow-tutor-dependency-changes'])==2
    assert 'requires --tutor-treatment' in capsys.readouterr().err


@pytest.mark.parametrize('mutation', ['outside','bad-outcomes','bad-eligible','bad-reasons','nan','bool-counter','mismatched-counts','extra-condition-field'])
def test_v2_rejects_malformed_structure(tmp_path,mutation):
    from learnai.application.artifacts import load_saved_run
    from learnai.eval.manifest import build_manifest
    from learnai.eval.report import write_report
    from tests.eval.test_judge import packet
    ledger=accounting.RequestLedger()
    ledger.record(request(normalized=observation(tier='returned')))
    manifest=build_manifest(root=tmp_path,selected_ids=('case',),seeds=(7,),settings={},prompts={},references={})
    run=write_report(tmp_path,manifest=manifest,outcomes={},scores={},judge_packets={'case':packet()},ledger=ledger,
        prices=accounting.PriceBook((price(),)),persona_smoke={})
    report=json.loads((run/'report.json').read_text())
    raw=json.loads((run/'requests.jsonl').read_text())
    if mutation=='outside': report['judge_packets']['case']['path']='../outside.json'
    elif mutation=='bad-outcomes': report['outcomes']=[]
    elif mutation=='bad-eligible': report['eligible_ids']=None; report['judge_packets']={}
    elif mutation=='bad-reasons': raw['normalized_usage']['reasons']='bad'
    elif mutation=='nan': raw['elapsed_seconds']=float('nan')
    elif mutation=='bool-counter': raw['normalized_usage']['counts']['input']=True
    elif mutation=='mismatched-counts': raw['normalized_tokens']['input']=2
    elif mutation=='extra-condition-field': raw['normalized_usage']['billing_conditions']['tier']['extra']='bad'
    (run/'report.json').write_text(json.dumps(report))
    (run/'requests.jsonl').write_text(json.dumps(raw)+'\n')
    with pytest.raises(ValueError): load_saved_run(run)


def test_unknown_role_identity_blocks_treatment():
    from learnai.eval.report import compare_runs,TutorTreatment
    for unknown in ({}, {'tutor':{'tutor':{'provider':'anthropic'}},'judge':{'judge':{}}}):
        left,right=compared(),compared()
        left.manifest['material']['identities']=right.manifest['material']['identities']=unknown
        assert not compare_runs(left,right,treatment=TutorTreatment(('tutor',)))['controlled_tutor_comparison']['eligible']


def test_snapshot_validates_and_owns_rate_metadata():
    rates={'same-name':{'input':Decimal('2')}}
    conditions={'tier':'standard'}
    snapshot=replace(price(),rates=rates,conditions=conditions)
    rates['same-name']['input']=Decimal('999')
    conditions['tier']='changed'
    assert snapshot.rates['same-name']['input']==Decimal('2')
    assert snapshot.conditions=={'tier':'standard'}
    for changes in ({'provider':''},{'currency':''},{'unit':True},{'unit':1.5},{'conditions':{'tier':None}}):
        with pytest.raises(ValueError): replace(price(),**changes)


def test_shared_accounting_does_not_decode_vendor_keys():
    import inspect
    source=inspect.getsource(accounting)
    for field in ('cache_creation_input_tokens','cache_read_input_tokens','input_tokens','service_tier','inference_geo'):
        assert field not in source


def test_tutor_schema_treatment_only_exempts_encoding_hashes():
    from learnai.eval.report import compare_runs,TutorTreatment
    left,right=compared(),compared(provider='openai')
    treatment=TutorTreatment(('tutor',))
    assert compare_runs(left,right,treatment=treatment)['controlled_tutor_comparison']['eligible']
    right.manifest['material']['identities']['tutor']['tutor']['schema_hashes']['canonical_read_tools']='changed'
    assert not compare_runs(left,right,treatment=treatment)['controlled_tutor_comparison']['eligible']
    right=compared(provider='openai')
    right.manifest['material']['identities']['tutor']['tutor']['schema_hashes']['unclassified']='changed'
    assert not compare_runs(left,right,treatment=treatment)['controlled_tutor_comparison']['eligible']


def test_ledger_revalidates_mutable_observation_maps():
    ledger=accounting.RequestLedger()
    entry=request()
    entry.normalized_usage.counts['input']=-1
    with pytest.raises(ValueError): ledger.record(entry)


def test_v2_price_books_load_provider_identity(tmp_path):
    from dataclasses import asdict
    import yaml
    p=tmp_path/'prices.yaml'
    entries=[]
    for snapshot in (price(),price('openai','4')):
        raw=asdict(snapshot)
        raw['rates']={model:{category:str(rate) for category,rate in rates.items()} for model,rates in snapshot.rates.items()}
        entries.append(raw)
    p.write_text(yaml.safe_dump({'pricing':{'schema_version':2,'snapshots':entries}}))
    assert accounting.load_prices(p)==accounting.PriceBook((price(),price('openai','4')))


def test_missing_returned_judge_identity_prevents_controlled_claim():
    from learnai.eval.report import compare_runs,TutorTreatment
    left,right=compared(),compared(provider='openai')
    left=replace(left,records=tuple(replace(record,returned_model=None) if record.phase=='judge' else record for record in left.records))
    right=replace(right,records=tuple(replace(record,returned_model=None) if record.phase=='judge' else record for record in right.records))
    assert not compare_runs(left,right,treatment=TutorTreatment(('tutor',)))['controlled_tutor_comparison']['eligible']


def test_conflicting_conditional_currency_is_not_applicable_to_actual_attempt():
    ledger=accounting.RequestLedger()
    ledger.record(request())
    ledger.record(request('openai','b',observation(tier='standard')))
    book=accounting.PriceBook((price(),price('openai','4','EUR',{'tier':'batch'})))
    result=accounting.estimate_cost(ledger,book)
    assert result.known_subtotal==Decimal('.0002') and result.currency=='USD'
    assert not result.complete and result.total is None
