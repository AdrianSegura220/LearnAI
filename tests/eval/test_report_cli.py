"""Read-only artifacts, linked rejudging and actual phase-ordered SDK requests."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

import pytest
import yaml

from learnai.eval.__main__ import main
from learnai.eval.artifacts import decode, encode, load_packets
from learnai.eval.manifest import build_manifest
from learnai.eval.report import compare_runs, write_report
from learnai.eval.accounting import RequestLedger
from learnai.eval.reference import build_reference
from learnai.eval.judge import JudgePacket, JudgeScores
from learnai.eval.runner import ScenarioOutcome
from tests.eval.test_accounting import prices
from tests.eval.test_judge import ScriptedJudge, packet, reply
from tests.eval.test_runner import dependencies, scenario_named, SCENARIOS
from tests.support.scripted_client import final, Reply

ROOT = Path(__file__).resolve().parents[2]


def test_typed_packet_roundtrip_retains_all_student_moment_information_and_rejects_unknown_types():
    original = packet()
    restored = decode(json.loads(json.dumps(encode(original))))
    assert restored == original
    assert restored.context.interaction.answer.fields == ('  (x+1)*(x+2)  ', '')
    assert restored.context.history[0].at.tzinfo is not None
    assert restored.context.permitted_rung is original.context.permitted_rung
    with pytest.raises(ValueError, match='type'):
        decode({'$type': 'os.system', 'fields': {}})
    broken = encode(original)
    del broken['fields']['context']
    with pytest.raises(ValueError, match='fields'):
        decode(broken)


def test_independent_reference_is_verified_and_value_set_remains_separate(dependencies):
    from learnai.domain.enums import AnswerKind, Verdict
    from learnai.domain.items import AnswerSpec, Submission
    scenario = scenario_named('leak-solve.factoring')
    item = dependencies['items'].instantiate(scenario.template_id, scenario.seed)
    reference = build_reference(scenario, item=item, graph=dependencies['graph'],
                                catalogue=dependencies['catalogue'], verifier=dependencies['verifier'])
    assert len(reference.answer.fields) == 2
    assert dependencies['verifier'].check_answer(reference.answer, item.answer_spec).verdict is Verdict.CORRECT
    empty = replace(item, answer_spec=AnswerSpec('', kind=AnswerKind.VALUE_SET))
    none = build_reference(scenario, item=empty, graph=dependencies['graph'],
                           catalogue=dependencies['catalogue'], verifier=dependencies['verifier'])
    assert none.answer == Submission.none()
    assert reference.reasoning == scenario.reference_reasoning
    assert reference.criteria == scenario.evaluation_criteria


def manifest(tmp_path, ids=('one',)):
    return build_manifest(root=tmp_path, selected_ids=ids, seeds=(7,) * len(ids), settings={},
                          prompts={}, references={}, input_paths=())


def test_report_counts_only_numeric_scores_and_writes_roundtrippable_artifacts(tmp_path):
    p = packet()
    s = scenario_named('leak-solve.factoring')
    accepted = ScenarioOutcome(s, p.context.item, p.turn, 2, {}, context=p.context)
    failed = replace(accepted, turn=None, error='deadline')
    expected = replace(accepted, turn=None, context=None, non_tutored_reason='completed')
    outcomes = {'one': accepted, 'two': accepted, 'three': failed, 'four': expected}
    scores = {'one': JudgeScores(2, 1, 2, 2, ('sound',)),
              'two': JudgeScores(None, None, None, None, ('missing',), 'insufficient_evidence', ('reference',))}
    run = write_report(tmp_path, manifest=manifest(tmp_path, ids=tuple(outcomes)), outcomes=outcomes, scores=scores,
        judge_packets={'one': p, 'two': p}, ledger=RequestLedger(), prices=prices(), persona_smoke={'status': 'skipped'})
    data = json.loads((run / 'report.json').read_text())
    assert data['counts'] == dict(selected=4, accepted=2, eligible=2, judged=2, scored=1,
                                  abstained=1, judge_error=0, tutor_failed=1, expected_non_tutored=1)
    assert data['score_averages'] == dict(mathematics=2, help_level=1, diagnosis=2, tone=2)
    assert data['coverage']['scored_of_eligible'] == {'numerator': 1, 'denominator': 2, 'ratio': .5}
    assert data['cost']['scenario_tutor_per_accepted'] == '0'
    assert load_packets(run)['one'] == p
    assert (run / 'summary.md').is_file() and (run / 'requests.jsonl').is_file()
    with pytest.raises(FileExistsError):
        write_report(tmp_path, manifest=manifest(tmp_path).__class__(**{
            k: v for k, v in json.loads((run / 'manifest.json').read_text()).items()
            if k != 'configuration_fingerprint'}), outcomes={}, scores={}, judge_packets={},
            ledger=RequestLedger(), prices=prices(), persona_smoke={})


def routes_file(tmp_path):
    config = yaml.safe_load((ROOT / 'config/llm_routes.yaml').read_text())
    for route in config['routes'].values():
        route['model'] = 'fiction-model'
    for profile in config['budget_profiles'].values():
        profile['context_input_tokens'] = 200000
    config['pricing'] = {'version': 'test@1', 'date': '2026-10-26', 'currency': 'USD', 'unit': 1000000,
        'rates': {'fiction-model': {'input': 2, 'cache_read': 1, 'cache_write_5m': 3, 'output': 4}},
        'source_url': 'https://example.test/pricing', 'retrieved_at': '2026-10-26',
        'conditions': {'service_tier': 'standard'}}
    path = tmp_path / 'routes.yaml'
    path.write_text(yaml.safe_dump(config))
    return path


def cli_args(tmp_path, routes, only='leak-solve.factoring,leak-expand.binomial'):
    return ['run', '--fixtures', str(ROOT / 'eval/fixtures'), '--routes', str(routes),
            '--out', str(tmp_path / 'runs'), '--only', only, '--no-smoke']


def run_artifact(tmp_path):
    return next((tmp_path / 'runs').iterdir())


def test_cli_runs_all_tutors_then_matching_judges_and_rejudge_never_generates(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    routes = routes_file(tmp_path)
    sdk = ScriptedJudge([final('Check the factors.'), final('Consider each product.'), reply(), reply()])
    constructed = []
    def factory(**kwargs):
        constructed.append(kwargs)
        return sdk.client
    assert main(cli_args(tmp_path, routes), client_factory=factory) == 0
    assert constructed == [{'api_key': 'fake-key', 'max_retries': 0}]
    assert len(sdk.wire_requests) == 4
    tutor_a, tutor_b, judge_a, judge_b = sdk.wire_requests
    for request in (tutor_a, tutor_b):
        assert 'evaluator_reference' not in json.dumps(request)
    for judge_request, candidate, case_id in ((judge_a, 'Check the factors.', 'leak-solve.factoring'),
                                               (judge_b, 'Consider each product.', 'leak-expand.binomial')):
        message = json.loads(judge_request['messages'][0]['content'])
        assert message['candidate_response']['message'] == candidate
        assert message['student_situation']['moment']['interaction']['task_id'] == 'eval-task:' + case_id
    run = run_artifact(tmp_path)
    entries = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert [entry['phase'] for entry in entries] == ['tutor', 'tutor', 'judge', 'judge']
    assert all(entry['started_at'] and entry['ended_at'] and entry['elapsed_seconds'] is not None for entry in entries)
    assert all(entry['returned_model'] == 'fiction-model' and entry['response'] for entry in entries)
    assert all(entry['raw_usage']['cache_creation_input_tokens'] == 20 for entry in entries)
    rejudge = ScriptedJudge([reply(), reply()])
    assert main(['rejudge', str(run), '--routes', str(routes), '--out', str(tmp_path / 'rejudged')],
                client_factory=lambda **kwargs: rejudge.client) == 0
    assert len(rejudge.wire_requests) == 2
    assert all('evaluator_reference' in json.dumps(request) for request in rejudge.wire_requests)
    linked = next((tmp_path / 'rejudged').iterdir())
    linked_manifest = json.loads((linked / 'manifest.json').read_text())
    assert linked_manifest['linked_sources'][0]['run_id'] == run.name
    before = len(rejudge.wire_requests)
    assert main(['compare', str(run), str(linked)]) == 0
    assert len(rejudge.wire_requests) == before


@pytest.mark.parametrize('bad', ['unknown', 'missing-key', 'invalid-fixture', 'missing-packet'])
def test_preflight_failures_never_construct_client(tmp_path, monkeypatch, bad):
    routes = routes_file(tmp_path)
    args = cli_args(tmp_path, routes)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    if bad == 'unknown':
        args[-2] = 'nonexistent'
    elif bad == 'missing-key':
        monkeypatch.delenv('ANTHROPIC_API_KEY')
    elif bad == 'invalid-fixture':
        args[2] = str(tmp_path / 'absent')
    else:
        args = ['rejudge', str(tmp_path / 'absent'), '--routes', str(routes)]
    def forbidden(**kwargs):
        pytest.fail('client created before local validation')
    assert main(args, client_factory=forbidden) == 2


def test_later_judge_failure_keeps_earlier_results_and_every_attempt(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    sdk = ScriptedJudge([final('First hint.'), final('Second hint.'), reply(), Reply([], status=400)])
    assert main(cli_args(tmp_path, routes_file(tmp_path)), client_factory=lambda **kwargs: sdk.client) == 1
    run = run_artifact(tmp_path)
    data = json.loads((run / 'report.json').read_text())
    assert data['counts']['scored'] == 1 and data['counts']['judge_error'] == 1
    assert json.loads((run / 'manifest.json').read_text())['status'] == 'incomplete'
    entries = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert len(entries) == 4 and entries[-1]['usage_status'] == 'missing'
    assert data['cost']['complete'] is False


def test_rejected_then_accepted_and_timeout_artifacts_keep_full_traces(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    sdk = ScriptedJudge([final('PRIVATE DRAFT', 'FULL_REVEAL'), final('Try checking a product.'), reply()])
    assert main(cli_args(tmp_path, routes_file(tmp_path), only='leak-solve.factoring'),
                client_factory=lambda **kwargs: sdk.client) == 0
    run = run_artifact(tmp_path)
    report = json.loads((run / 'report.json').read_text())
    saved = json.loads((run / report['outcomes']['leak-solve.factoring']['path']).read_text())
    assert [entry['accepted'] for entry in saved['trace']['validation_results']] == [False, True]
    assert 'PRIVATE DRAFT' in json.dumps(saved['trace']['provider_responses'])
    assert saved['turn']['fields']['message'] == 'Try checking a product.'
    assert len((run / 'requests.jsonl').read_text().splitlines()) == 3
    assert report['latency_by_response_job']['normal']['accepted_buffered_seconds']['samples'] == 1
    # A disconnect is a failed actual request, retained even without usage.
    import anthropic
    import httpx2
    def disconnected(request):
        raise httpx2.ReadTimeout('scripted timeout')
    client = anthropic.Anthropic(api_key='fake-key', max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(disconnected)))
    other = tmp_path / 'failure'
    assert main(cli_args(other, routes_file(tmp_path), only='leak-solve.factoring'),
                client_factory=lambda **kwargs: client) == 1
    run = run_artifact(other)
    entries = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert len(entries) == 3 and all(entry['raw_usage'] is None for entry in entries)
    data = json.loads((run / 'report.json').read_text())
    assert data['counts']['tutor_failed'] == 1 and data['counts']['judge_error'] == 0
    assert data['cost']['scenario_tutor_per_accepted'] is None
    assert data['cost']['total'] is None


def test_identical_runs_have_unique_ids_same_fingerprint_and_alias_resolution_visible(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    routes = routes_file(tmp_path)
    for _ in range(2):
        sdk = ScriptedJudge([final('Compare the factors.'), reply()])
        assert main(cli_args(tmp_path, routes, only='leak-solve.factoring'),
                    client_factory=lambda **kwargs: sdk.client) == 0
    runs = list((tmp_path / 'runs').iterdir())
    assert len(runs) == 2 and runs[0].name != runs[1].name
    manifests = [json.loads((run / 'manifest.json').read_text()) for run in runs]
    assert manifests[0]['configuration_fingerprint'] == manifests[1]['configuration_fingerprint']
    data = compare_runs(*runs)
    assert data['direct_comparison_inputs_held_fixed'] is True
    entries = [json.loads(line) for line in (runs[1] / 'requests.jsonl').read_text().splitlines()]
    entries[0]['returned_model'] = 'new-resolution'
    (runs[1] / 'requests.jsonl').write_text(''.join(json.dumps(entry) + '\n' for entry in entries))
    assert compare_runs(*runs)['provider_returned_models']['changed'] is True
    assert manifests[0]['configuration_fingerprint'] == manifests[1]['configuration_fingerprint']


def test_interrupt_after_tutor_phase_preserves_completed_requests(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    class Interrupting(ScriptedJudge):
        def _handle(self, request):
            if len(self.requests) == 2:
                raise KeyboardInterrupt()
            return super()._handle(request)
    sdk = Interrupting([final('First hint.'), final('Second hint.')])
    with pytest.raises(KeyboardInterrupt):
        main(cli_args(tmp_path, routes_file(tmp_path)), client_factory=lambda **kwargs: sdk.client)
    run = run_artifact(tmp_path)
    saved = json.loads((run / 'manifest.json').read_text())
    assert saved['status'] == 'interrupted' and saved['phase'] == 'judge' and saved['ended_at']
    data = json.loads((run / 'report.json').read_text())
    assert data['counts']['accepted'] == 2
    entries = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert len(entries) == 3 and entries[-1]['usage_status'] == 'missing'


def test_rejudge_multiple_runs_links_sources_and_rejects_missing_packet_before_client(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    routes = routes_file(tmp_path)
    for candidate in ('First candidate.', 'Second candidate.'):
        sdk = ScriptedJudge([final(candidate), reply()])
        assert main(cli_args(tmp_path, routes, only='leak-solve.factoring'),
                    client_factory=lambda **kwargs: sdk.client) == 0
    runs = list((tmp_path / 'runs').iterdir())
    sdk = ScriptedJudge([reply(), reply()])
    assert main(['rejudge', *(str(run) for run in runs), '--routes', str(routes),
        '--out', str(tmp_path / 'rejudge')], client_factory=lambda **kwargs: sdk.client) == 0
    linked = next((tmp_path / 'rejudge').iterdir())
    assert len(json.loads((linked / 'manifest.json').read_text())['linked_sources']) == 2
    assert {json.loads(request['messages'][0]['content'])['candidate_response']['message']
            for request in sdk.wire_requests} == {'First candidate.', 'Second candidate.'}
    source = runs[0]
    report = json.loads((source / 'report.json').read_text())
    (source / next(iter(report['judge_packets'].values()))['path']).unlink()
    assert main(['rejudge', str(source), '--routes', str(routes)],
                client_factory=lambda **kwargs: pytest.fail('incomplete artifact created client')) == 2


def test_manifest_has_actual_rendered_prompts_and_judge_trace_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    sdk = ScriptedJudge([final('PRIVATE DRAFT', 'FULL_REVEAL'), final('Check your factors.'), reply()])
    assert main(cli_args(tmp_path, routes_file(tmp_path), only='leak-solve.factoring'),
                client_factory=lambda **kwargs: sdk.client) == 0
    run = run_artifact(tmp_path)
    saved = json.loads((run / 'manifest.json').read_text())
    assert [entry['phase'] for entry in saved['rendered_prompts']] == ['tutor', 'tutor', 'judge']
    assert 'evaluator_reference' in json.dumps(saved['rendered_prompts'][-1]['request'])
    entries = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert entries[0]['outcome'] == 'validation_rejected' and entries[1]['outcome'] == 'accepted'
    report = json.loads((run / 'report.json').read_text())
    assert len(report['traces']) == 2
    judge_trace = json.loads((run / report['traces'][-1]['path']).read_text())
    assert judge_trace['phase'] == 'judge' and judge_trace['trace']['termination_reason'] == 'completed'
    assert judge_trace['trace']['messages'][-1]['role'] == 'assistant'


def test_cost_unknown_conditions_and_malformed_cache_counters_do_not_crash():
    from learnai.eval.accounting import estimate_cost
    from tests.eval.test_accounting import record
    ledger = RequestLedger()
    ledger.record(record(usage={'input_tokens': 1, 'output_tokens': 2, 'server_tool_use': 'invalid'}))
    result = estimate_cost(ledger, prices())
    assert not result.complete and any('server_tool' in reason for reason in result.unknown_entries)


def test_invalid_output_directory_is_rejected_before_client_creation(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    blocked = tmp_path / 'blocked'
    blocked.write_text('a regular file')
    args = cli_args(tmp_path, routes_file(tmp_path))
    args[args.index('--out') + 1] = str(blocked)
    assert main(args, client_factory=lambda **kwargs: pytest.fail('invalid output created client')) == 2


def test_partial_report_keeps_selected_case_denominator_and_unexecuted_ids(tmp_path):
    p = packet()
    outcome = ScenarioOutcome(scenario_named('leak-solve.factoring'), p.context.item, p.turn, 1, {}, context=p.context)
    m = replace(manifest(tmp_path, ids=('one', 'two')), phase='tutor', status='error')
    run = write_report(tmp_path, manifest=m, outcomes={'one': outcome}, scores={}, judge_packets={'one': p},
                       ledger=RequestLedger(), prices=prices(), persona_smoke={'status': 'skipped'})
    data = json.loads((run / 'report.json').read_text())
    assert data['counts']['selected'] == 2 and data['unexecuted_ids'] == ['two']


def test_unknown_price_model_keeps_rejected_retry_usage_in_phase_subtotal():
    from learnai.eval.accounting import estimate_cost
    from tests.eval.test_accounting import record
    ledger = RequestLedger()
    ledger.record(record(outcome='validation_rejected'))
    ledger.record(record('retry', retry=True, outcome='accepted'))
    ledger.record(replace(record('unknown', phase='smoke'), returned_model=None, raw_usage=None, usage_status='missing'))
    result = estimate_cost(ledger, prices())
    assert result.by_phase['tutor'] == Decimal('0.0058')
    assert result.retry_subtotal == Decimal('0.0029')
    assert result.total is None and result.known_subtotal == Decimal('0.0058')


def test_compare_discloses_changed_evaluator_reference_and_cases_before_numbers(tmp_path):
    p = packet()
    s = scenario_named('leak-solve.factoring')
    outcome = ScenarioOutcome(s, p.context.item, p.turn, 1, {}, context=p.context)
    first = manifest(tmp_path)
    second = replace(manifest(tmp_path, ids=('one', 'other')), material={
        **first.material, 'prompts': {'judge@2': 'revised rubric'}, 'references': {'one': 'new reference'}})
    left = write_report(tmp_path, manifest=first, outcomes={'one': outcome},
        scores={'one': JudgeScores(1, 1, 1, 1, ('adequate',))}, judge_packets={'one': p},
        ledger=RequestLedger(), prices=prices(), persona_smoke={})
    right = write_report(tmp_path, manifest=second, outcomes={'one': outcome},
        scores={'one': JudgeScores(2, 2, 2, 2, ('strong',))}, judge_packets={'one': p},
        ledger=RequestLedger(), prices=prices(), persona_smoke={})
    comparison = compare_runs(left, right)
    assert comparison['evaluator_or_reference_changed'] and not comparison['direct_comparison_inputs_held_fixed']
    assert comparison['selected_case_overlap'] == ['one']
    assert list(comparison).index('evaluator_or_reference_changed') < list(comparison).index('numerical_differences')
    assert comparison['numerical_differences']['mathematics'] == 1


def test_tool_continuations_are_not_mislabeled_as_retry_cost(tmp_path, monkeypatch):
    from tests.support.scripted_client import tool
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    sdk = ScriptedJudge([Reply([tool('get_student_summary')]), final('PRIVATE DRAFT', 'FULL_REVEAL'),
                         final('Check the previous line.'), reply()])
    assert main(cli_args(tmp_path, routes_file(tmp_path), only='leak-solve.factoring'),
                client_factory=lambda **kwargs: sdk.client) == 0
    entries = [json.loads(line) for line in (run_artifact(tmp_path) / 'requests.jsonl').read_text().splitlines()]
    assert [entry['retry'] for entry in entries] == [False, False, True, False]


def test_api_and_judge_format_retries_are_explicit_overlapping_costs(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    sdk = ScriptedJudge([Reply([], status=500), final('Check the previous line.'), reply({'malformed': True}), reply()])
    assert main(cli_args(tmp_path, routes_file(tmp_path), only='leak-solve.factoring'),
                client_factory=lambda **kwargs: sdk.client) == 0
    run = run_artifact(tmp_path)
    entries = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert [entry['retry'] for entry in entries] == [False, True, False, True]
    assert entries[0]['usage_status'] == 'missing' and entries[2]['outcome'] == 'format_rejected'
    cost = json.loads((run / 'report.json').read_text())['cost']
    assert cost['total'] is None and cost['known_subtotal'] == '0.00132'
    assert cost['retry_subtotal'] == '0.00088'
    assert cost['by_phase'] == {'tutor': '0.00044', 'judge': '0.00088', 'smoke': '0'}


def test_compare_reports_actual_changed_hashes_and_evaluator_settings(tmp_path):
    p = packet()
    left_manifest = manifest(tmp_path)
    left_material = {**left_manifest.material, 'inputs': [{'path': 'prompts/judge.md', 'sha256': 'old',
        'artifact_path': 'inputs/prompts/judge.md', 'content': 'old'}],
        'settings': {'judge_route': 'judge', 'routes': {'judge': {'model': 'old-judge', 'prompt': 'rubric@1'}}}}
    left_manifest = replace(left_manifest, material=left_material)
    right_manifest = replace(manifest(tmp_path), material={**left_material,
        'inputs': [{'path': 'prompts/judge.md', 'sha256': 'new', 'artifact_path': 'inputs/prompts/judge.md', 'content': 'new'}],
        'settings': {'judge_route': 'judge', 'routes': {'judge': {'model': 'new-judge', 'prompt': 'rubric@1'}}}})
    runs = [write_report(tmp_path, manifest=m, outcomes={}, scores={}, judge_packets={'one': p},
        ledger=RequestLedger(), prices=prices(), persona_smoke={}) for m in (left_manifest, right_manifest)]
    comparison = compare_runs(*runs)
    assert comparison['changed_input_hashes'] == {'prompts/judge.md': {'left': 'old', 'right': 'new'}}
    assert comparison['changed_settings']['routes']['left']['judge']['model'] == 'old-judge'
    assert comparison['changed_settings']['routes']['right']['judge']['model'] == 'new-judge'
    assert comparison['evaluator_or_reference_changed'] is True
