"""Authored evaluation items preserve exact content and honest provenance."""
from pathlib import Path

import pytest
import yaml

from learnai.domain.enums import ProvenanceKind, VettingLevel
from learnai.eval.fixtures import FixtureError


def item_data():
    return dict(id='eval.authored.example', skill_id='quad.solve.factoring',
        statement=[{'text': 'Find all real solutions.'}, {'formula': 'x^2 = 9'}],
        answer=dict(expression='-3, 3', kind='VALUE_SET', form_constraints=[], label='x ='),
        worked_steps=[], difficulty=0.0)


def write_items(tmp_path, entries):
    path = tmp_path / 'items.yaml'
    path.write_text(yaml.safe_dump(dict(version=1, items=entries)))
    return path


def test_authored_item_keeps_statement_and_provenance(tmp_path):
    from learnai.eval.authored import load_authored_items
    source = load_authored_items(write_items(tmp_path, [item_data()]))
    item = source.instantiate('eval.authored.example', 0)
    assert item.statement[1].source == 'x^2 = 9'
    assert item.answer_spec.expression == '-3, 3'
    assert item.provenance.kind is ProvenanceKind.AUTHORED
    assert item.provenance.seed is item.provenance.template_id is None
    assert item.vetting_level is VettingLevel.HUMAN_REVIEWED
    assert source.instantiate('quad.expand.binomial.v1', 2).provenance.kind is ProvenanceKind.GENERATED
    with pytest.raises(FixtureError, match='seed'):
        source.instantiate('eval.authored.example', 1)


@pytest.mark.parametrize('change', [
    {'id': 'quad.expand.binomial.v1'}, {'id': ''}, {'skill_id': ''},
    {'difficulty': True}, {'difficulty': float('nan')}, {'statement': []},
    {'statement': [{'text': 'x', 'formula': 'y'}]}, {'statement': [{'formula': 4}]},
    {'worked_steps': 'x'}, {'unexpected': 'value'},
    {'answer': dict(expression='3', kind='VALUE_SET', form_constraints=[], label=None, unknown=1)},
])
def test_malformed_authored_item_rejected(tmp_path, change):
    from learnai.eval.authored import load_authored_items
    entry = item_data() | change
    with pytest.raises(FixtureError):
        load_authored_items(write_items(tmp_path, [entry]))


def test_duplicate_authored_ids_rejected(tmp_path):
    from learnai.eval.authored import load_authored_items
    with pytest.raises(FixtureError, match='duplicate'):
        load_authored_items(write_items(tmp_path, [item_data(), item_data()]))


def test_cli_has_explicit_items_option():
    from learnai.eval.__main__ import _parser
    args = _parser().parse_args(['run', '--items', 'authored.yaml', '--no-smoke'])
    assert args.items == Path('authored.yaml')
