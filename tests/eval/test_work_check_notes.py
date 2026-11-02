"""Scoped work findings survive engine replay, rendering and old saved packets."""
from pathlib import Path

import pytest

from learnai.adapters.tutor.rendering import render_interaction
from learnai.domain.interaction import VerificationSnapshot
from learnai.eval.artifacts import encode, decode
from learnai.eval.authored import load_authored_items
from learnai.eval.fixtures import load_scenarios_dir
from learnai.eval.replay import prepare_scenario
from tests.eval.test_fixture_corpus import dependencies

ROOT = Path(__file__).resolve().parents[2]


def test_branch_scope_reaches_tutor_without_a_false_error(dependencies):
    scenario = load_scenarios_dir(ROOT / 'eval/independent/scenarios')[11]
    prepared = prepare_scenario(scenario, **(dependencies | {
        'items': load_authored_items(ROOT / 'eval/independent/items.yaml')}))
    checked = prepared.context.verification
    assert checked.step_diff is None
    assert checked.work_notes
    rendered = render_interaction(prepared.context.interaction, checked)
    assert 'work_notes' in rendered and 'remaining' in rendered
    assert decode(encode(checked)) == checked


def test_legacy_snapshot_shape_decodes_with_no_invented_work_notes():
    snapshot = VerificationSnapshot(0, False, True, None, None, None, work_notes=())
    old = encode(snapshot)
    del old['fields']['work_notes']
    assert decode(old) == snapshot
    assert 'work_notes' not in old['fields']


def test_legacy_snapshot_exception_does_not_accept_other_missing_fields():
    old = encode(VerificationSnapshot(0, False, True, None, None, None))
    del old['fields']['work_notes']
    del old['fields']['diagnosis']
    with pytest.raises(ValueError, match='fields do not match'):
        decode(old)
