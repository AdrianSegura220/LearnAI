"""Fresh scenarios are real engine opportunities, never forged context snapshots."""
from hashlib import sha256
from pathlib import Path
import json
import os
import subprocess
import sys

from learnai.domain.enums import HelpRung, ProvenanceKind
from learnai.eval.authored import load_authored_items
from learnai.eval.fixtures import load_scenarios_dir, validate_corpus
from learnai.eval.replay import prepare_scenario
from tests.eval.test_fixture_corpus import dependencies

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / 'eval/independent'
FROZEN_JUDGE = 'a3f4451236fa1b9e434425162d2b8a6996e28e46e800d01cff81297b2d240a4d'


def test_all_fourteen_cases_replay_without_forged_findings(dependencies):
    scenarios = load_scenarios_dir(BUNDLE / 'scenarios')
    assert len(scenarios) == 14
    deps = dependencies | {'items': load_authored_items(BUNDLE / 'items.yaml')}
    validate_corpus(scenarios, **deps)
    prepared = [prepare_scenario(case, **deps) for case in scenarios]
    assert all(p.context is not None for p in prepared)
    assert all(p.context.permitted_rung is HelpRung.NAME_METHOD for p in prepared)
    assert all(p.task.item.provenance.kind is ProvenanceKind.AUTHORED for p in prepared)
    assert all(p.context.task_progress == p.progress for p in prepared)
    assert prepared[8].progress.delivered_rungs == (HelpRung.NAME_METHOD,)
    for index in (12, 13):
        assert prepared[index].progress.submissions == 1
        assert len(prepared[index].evidence) == 1
        assert prepared[index].context.diagnosis is None
    assert prepared[13].context.interaction.steps == ()


def test_original_corpus_and_fixed_judge_stay_separate():
    assert len(load_scenarios_dir(ROOT / 'eval/fixtures')) == 71
    assert sha256((ROOT / 'prompts/rubric_judge/v2.md').read_bytes()).hexdigest() == FROZEN_JUDGE


def test_cli_preflight_captures_authored_content_and_keeps_references_private():
    from learnai.eval.__main__ import _parser, _preflight
    from learnai.application.providers import default_registry
    from learnai.adapters.tutor.rendering import render_moment
    args = _parser().parse_args(['run', '--fixtures', str(BUNDLE / 'scenarios'),
                                '--items', str(BUNDLE / 'items.yaml'), '--no-smoke'])
    prepared = _preflight(args, default_registry())
    assert prepared['supplemental_inputs']['eval/fixtures/selected-authored/items.yaml'] == (BUNDLE / 'items.yaml').read_text()
    from learnai.eval.manifest import build_manifest
    manifest = build_manifest(root=ROOT, selected_ids=[s.id for s in prepared['scenarios']],
        seeds=[s.seed for s in prepared['scenarios']], settings=prepared['settings'],
        prompts={}, references=prepared['captured'],
        supplemental_inputs=prepared['supplemental_inputs'])
    captured = next(entry for entry in manifest.material['inputs']
                    if entry['path'] == 'eval/fixtures/selected-authored/items.yaml')
    assert captured['content'] == (BUNDLE / 'items.yaml').read_text()
    assert captured['sha256'] == sha256((BUNDLE / 'items.yaml').read_bytes()).hexdigest()
    assert len(prepared['references']) == len(prepared['contexts']) == 14
    for context in prepared['contexts']:
        message = json.loads(render_moment(context))
        assert 'reference_reasoning' not in message
        assert 'evaluation_criteria' not in message
        assert 'expected_scores' not in message


def test_keyless_command_checks_contextual_scope_without_sdks_or_network():
    script = '''
import socket, sys
class NoSDK:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'httpx2'}:
            raise AssertionError('SDK import during keyless preflight')
sys.meta_path.insert(0, NoSDK())
def forbidden(*args, **kwargs):
    raise AssertionError('network during keyless preflight')
socket.create_connection = forbidden
socket.socket = forbidden
from learnai.eval.independent import main
raise SystemExit(main())
'''
    env = {k: v for k, v in os.environ.items() if k not in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY')}
    result = subprocess.run([sys.executable, '-c', script], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'ready'
    assert report['scenario_count'] == report['tutor_opportunities'] == 14
    assert report['ready_count'] == 14
    assert report['blockers'] == []
    for index in (4, 6, 7, 9, 11):
        assert report['cases'][index]['work_notes']
        assert report['cases'][index]['step_finding'] is None
    assert len(report['admission']) == 28
    assert all(entry['admitted'] for entry in report['admission'])


def test_authored_keys_solve_the_exercises_independently():
    import sympy as sp
    from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application, convert_xor
    from learnai.domain.items import Formula
    from learnai.domain.enums import AnswerKind
    transformations = standard_transformations + (implicit_multiplication_application, convert_xor)
    def parse(text):
        return parse_expr(text, transformations=transformations)
    for item in load_authored_items(BUNDLE / 'items.yaml').authored.values():
        formulas = [block.source for block in item.statement if isinstance(block, Formula)]
        if not formulas:
            # The word problem's model and positive-length restriction are independent of its key.
            width = parse(item.answer_spec.expression)
            assert width > 0 and width * (width + 3) == 40
        elif item.answer_spec.kind is AnswerKind.VALUE_SET:
            left, right = formulas[0].split('=')
            roots = sp.solve(parse(left) - parse(right), sp.Symbol('x'))
            assert set(roots) == {parse(value) for value in item.answer_spec.expression.split(',')}
        else:
            assert sp.simplify(parse(formulas[0]) - parse(item.answer_spec.expression)) == 0
