"""Historical raw usage interpretation belongs to the Anthropic adapter."""
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from learnai.adapters.tutor.anthropic.legacy import read_run_v1

FIXTURE=Path(__file__).parents[2]/'fixtures/eval_v1/run'


def test_legacy_inference_and_missing_evidence_are_explicit():
    saved=read_run_v1(FIXTURE)
    record=saved.records[0]
    assert record.provider=='anthropic' and record.api_family=='messages'
    assert record.normalized_usage.counts=={'input':100,'output':400,'cache_read':200,'cache_write_5m':300,'cache_write_1h':0}
    assert record.normalized_usage.billing_conditions['service_tier'].source=='unknown'
    assert 'inferred' in saved.compatibility_notes[0]
    assert saved.packets['synthetic-case'].context.interaction.answer.fields==('  (x+1)*(x+2)  ','')


def test_legacy_saved_request_and_response_evidence_and_partial_duration(tmp_path):
    run=tmp_path/'run'
    shutil.copytree(FIXTURE,run)
    p=run/'requests.jsonl'
    raw=json.loads(p.read_text())
    raw['raw_usage']={'input_tokens':100,'output_tokens':400,'cache_creation_input_tokens':20}
    raw['request']={'service_tier':'standard_only'}
    raw['response']={'inference_geo':'us'}
    p.write_text(json.dumps(raw)+'\n')
    record=read_run_v1(run).records[0]
    assert record.usage_status=='partial'
    assert 'cache_write_5m' not in record.normalized_usage.counts
    assert record.normalized_usage.billing_conditions['service_tier'].source=='requested'
    assert record.normalized_usage.billing_conditions['inference_geo'].value=='us'


def test_legacy_rejects_packet_tampering(tmp_path):
    run=tmp_path/'run'
    shutil.copytree(FIXTURE,run)
    p=run/'packets/0000.json'
    p.write_text('{}')
    with pytest.raises(ValueError,match='hash'):
        read_run_v1(run)


def test_legacy_malformed_raw_usage_is_a_local_validation_error(tmp_path):
    run=tmp_path/'run'
    shutil.copytree(FIXTURE,run)
    path=run/'requests.jsonl'
    raw=json.loads(path.read_text())
    raw['raw_usage']=['invalid vendor usage']
    path.write_text(json.dumps(raw)+'\n')
    with pytest.raises(ValueError):
        read_run_v1(run)
