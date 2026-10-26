"""Read-only artifacts, linked rejudging and actual phase-ordered SDK requests."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

import pytest
import yaml

from tests.support.provider_fakes import anthropic_override
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
        'conditions': {}}
    path = tmp_path / 'routes.yaml'
    path.write_text(yaml.safe_dump(config))
    return path


def cli_args(tmp_path, routes, only='leak-solve.factoring,leak-expand.binomial'):
    return ['run', '--fixtures', str(ROOT / 'eval/fixtures'), '--routes', str(routes),
            '--out', str(tmp_path / 'runs'), '--only', only, '--no-smoke']


def run_artifact(tmp_path):
    return next((tmp_path / 'runs').iterdir())


def test_cli_real_persona_smoke_records_each_call_only_in_smoke_phase(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    sdk = ScriptedJudge([final('Check the factors.'), reply(),
                         *[final('Consider the next step.') for _ in range(6)]])
    args = cli_args(tmp_path, routes_file(tmp_path), only='leak-solve.factoring')
    args.remove('--no-smoke')
    assert main(args, provider_factories=anthropic_override(lambda **kwargs: sdk.client)) == 0
    run = run_artifact(tmp_path)
    entries = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert len(sdk.wire_requests) == len(entries) == 8
    assert [entry['phase'] for entry in entries] == ['tutor', 'judge', *['smoke'] * 6]
    assert len({entry['request_id'] for entry in entries}) == 8
    assert [entry['session_id'] for entry in entries[2:]] == [
        *['smoke:help_seeker:0'] * 3, *['smoke:help_seeker:1'] * 3]
    data = json.loads((run / 'report.json').read_text())
    smoke = data['persona_smoke']
    assert smoke['status'] == 'complete'
    assert smoke['results']['diligent']['cold_wrong'] == 6
    assert smoke['results']['help_seeker']['items_completed'] == 6
    assert smoke['results']['help_seeker']['tutor_turns'] == 6
    assert smoke['results']['help_seeker']['strength_total'] == 0
    assert smoke['results']['help_seeker']['traced_turns'] == 6
    assert data['cost']['by_phase'] == {'tutor': '0.00044', 'judge': '0.00044', 'smoke': '0.00264'}
    assert data['cost']['known_subtotal'] == '0.00352'
    assert data['cost']['total'] is None  # Transport omits the cache write duration.


def test_cli_runs_all_tutors_then_matching_judges_and_rejudge_never_generates(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    routes = routes_file(tmp_path)
    sdk = ScriptedJudge([final('Check the factors.'), final('Consider each product.'), reply(), reply()])
    constructed = []
    def factory(**kwargs):
        constructed.append(kwargs)
        return sdk.client
    assert main(cli_args(tmp_path, routes), provider_factories=anthropic_override(factory)) == 0
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
                provider_factories=anthropic_override(lambda **kwargs: rejudge.client)) == 0
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
        args = ['rejudge', str(tmp_path / 'absent'), '--routes', str(routes),
                '--out', str(tmp_path / 'rejudged')]
    def forbidden(**kwargs):
        pytest.fail('client created before local validation')
    assert main(args, provider_factories=anthropic_override(forbidden)) == 2


def test_later_judge_failure_keeps_earlier_results_and_every_attempt(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    sdk = ScriptedJudge([final('First hint.'), final('Second hint.'), reply(), Reply([], status=400)])
    assert main(cli_args(tmp_path, routes_file(tmp_path)), provider_factories=anthropic_override(lambda **kwargs: sdk.client)) == 1
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
                provider_factories=anthropic_override(lambda **kwargs: sdk.client)) == 0
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
                provider_factories=anthropic_override(lambda **kwargs: client)) == 1
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
                    provider_factories=anthropic_override(lambda **kwargs: sdk.client)) == 0
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
        main(cli_args(tmp_path, routes_file(tmp_path)), provider_factories=anthropic_override(lambda **kwargs: sdk.client))
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
                    provider_factories=anthropic_override(lambda **kwargs: sdk.client)) == 0
    runs = list((tmp_path / 'runs').iterdir())
    sdk = ScriptedJudge([reply(), reply()])
    assert main(['rejudge', *(str(run) for run in runs), '--routes', str(routes),
        '--out', str(tmp_path / 'rejudge')], provider_factories=anthropic_override(lambda **kwargs: sdk.client)) == 0
    linked = next((tmp_path / 'rejudge').iterdir())
    assert len(json.loads((linked / 'manifest.json').read_text())['linked_sources']) == 2
    assert {json.loads(request['messages'][0]['content'])['candidate_response']['message']
            for request in sdk.wire_requests} == {'First candidate.', 'Second candidate.'}
    source = runs[0]
    report = json.loads((source / 'report.json').read_text())
    (source / next(iter(report['judge_packets'].values()))['path']).unlink()
    assert main(['rejudge', str(source), '--routes', str(routes), '--out', str(tmp_path / 'rejudged')],
                provider_factories=anthropic_override(lambda **kwargs: pytest.fail('incomplete artifact created client'))) == 2


def test_manifest_has_actual_rendered_prompts_and_judge_trace_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    sdk = ScriptedJudge([final('PRIVATE DRAFT', 'FULL_REVEAL'), final('Check your factors.'), reply()])
    assert main(cli_args(tmp_path, routes_file(tmp_path), only='leak-solve.factoring'),
                provider_factories=anthropic_override(lambda **kwargs: sdk.client)) == 0
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
    from tests.eval.test_accounting import record, changed_record
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
    assert main(args, provider_factories=anthropic_override(lambda **kwargs: pytest.fail('invalid output created client'))) == 2


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
    from tests.eval.test_accounting import record, changed_record
    ledger = RequestLedger()
    ledger.record(record(outcome='validation_rejected'))
    ledger.record(record('retry', retry=True, outcome='accepted'))
    ledger.record(changed_record(record('unknown', phase='smoke'), returned_model=None, raw_usage=None, usage_status='missing'))
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
                provider_factories=anthropic_override(lambda **kwargs: sdk.client)) == 0
    entries = [json.loads(line) for line in (run_artifact(tmp_path) / 'requests.jsonl').read_text().splitlines()]
    assert [entry['retry'] for entry in entries] == [False, False, True, False]


def test_api_and_judge_format_retries_are_explicit_overlapping_costs(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    sdk = ScriptedJudge([Reply([], status=500), final('Check the previous line.'), reply({'malformed': True}), reply()])
    assert main(cli_args(tmp_path, routes_file(tmp_path), only='leak-solve.factoring'),
                provider_factories=anthropic_override(lambda **kwargs: sdk.client)) == 0
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


def saved_packet_run(tmp_path):
    return write_report(tmp_path / 'source', manifest=manifest(tmp_path), outcomes={}, scores={},
        judge_packets={'one': packet()}, ledger=RequestLedger(), prices=prices(), persona_smoke={})


def test_default_output_writes_reports_under_project_root_without_touching_legacy_runs(tmp_path, monkeypatch):
    from learnai.eval import __main__ as cli
    project = tmp_path / 'project'
    project.mkdir()
    monkeypatch.setattr(cli, 'ROOT', project)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    legacy = project / 'eval/runs'
    legacy.mkdir(parents=True)
    private = legacy / 'private-existing.json'
    private.write_text('preserve existing artifact')
    for operation in ('run', 'rejudge'):
        args = [operation] if operation == 'run' else [operation, str(tmp_path / 'source')]
        assert cli._parser().parse_args(args).out == project / 'eval/reports'
    sdk = ScriptedJudge([reply()])
    source = saved_packet_run(tmp_path)
    assert main(['rejudge', str(source), '--routes', str(routes_file(tmp_path))],
                provider_factories=anthropic_override(lambda **kwargs: sdk.client)) == 0
    run = next((project / 'eval/reports').iterdir())
    assert (run / 'report.json').is_file()
    assert list(legacy.iterdir()) == [private]
    assert private.read_text() == 'preserve existing artifact'


def replace_saved_packet(run, mutate):
    from hashlib import sha256
    from learnai.eval.manifest import canonical_json
    report_path = run / 'report.json'
    report = json.loads(report_path.read_text())
    entry = report['judge_packets']['one']
    target = run / entry['path']
    raw = json.loads(target.read_text())
    mutate(raw)
    encoded = canonical_json(raw)
    target.write_text(encoded)
    entry['sha256'] = sha256(encoded.encode('utf-8')).hexdigest()
    report_path.write_text(json.dumps(report))


@pytest.mark.parametrize('change', ['candidate', 'student_moment'])
def test_rejudge_fingerprint_identifies_saved_candidate_and_context_inputs(tmp_path, monkeypatch, change):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    source = saved_packet_run(tmp_path)
    routes = routes_file(tmp_path)
    args = ['rejudge', str(source), '--routes', str(routes), '--out', str(tmp_path / 'rejudged')]
    first_sdk = ScriptedJudge([reply()])
    assert main(args, provider_factories=anthropic_override(lambda **kwargs: first_sdk.client)) == 0
    first = next((tmp_path / 'rejudged').iterdir())
    if change == 'candidate':
        mutate = lambda raw: raw['fields']['turn']['fields'].__setitem__('message', 'Consider the product and sum.')
    else:
        mutate = lambda raw: raw['fields']['context']['fields']['interaction']['fields'].__setitem__('question', 'Why does expansion verify it?')
    replace_saved_packet(source, mutate)
    second_sdk = ScriptedJudge([reply()])
    assert main(args, provider_factories=anthropic_override(lambda **kwargs: second_sdk.client)) == 0
    second = next(path for path in (tmp_path / 'rejudged').iterdir() if path != first)
    manifests = [json.loads((path / 'manifest.json').read_text()) for path in (first, second)]
    assert manifests[0]['material']['references'] == manifests[1]['material']['references']
    assert manifests[0]['selected_ids'] == manifests[1]['selected_ids']
    assert manifests[0]['configuration_fingerprint'] != manifests[1]['configuration_fingerprint']
    assert len(first_sdk.wire_requests) == len(second_sdk.wire_requests) == 1


@pytest.mark.parametrize('field,value', [('message', None), ('rung_used', 'NUDGE'), ('proposals', ['invalid'])])
def test_malformed_saved_turn_fields_fail_before_client_creation(tmp_path, monkeypatch, field, value):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    source = saved_packet_run(tmp_path)
    replace_saved_packet(source, lambda raw: raw['fields']['turn']['fields'].__setitem__(field, value))
    with pytest.raises(ValueError):
        load_packets(source)
    assert main(['rejudge', str(source), '--routes', str(routes_file(tmp_path)),
                 '--out', str(tmp_path / 'rejudged')],
                provider_factories=anthropic_override(lambda **kwargs: pytest.fail('invalid packet created client'))) == 2


@pytest.mark.parametrize('case', ['string-turn', 'statement-block', 'negative-progress', 'history-revision',
                                  'reference-shape', 'reference-none-and-fields', 'interaction-kind',
                                  'blank-candidate', 'exceeded-rung', 'oversized-number'])
def test_malformed_nested_saved_packet_is_a_local_validation_failure(tmp_path, monkeypatch, case):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-key')
    source = saved_packet_run(tmp_path)
    def mutate(raw):
        fields = raw['fields']
        context = fields['context']['fields']
        if case == 'string-turn':
            fields['turn'] = 'invalid candidate'
        elif case == 'statement-block':
            context['item']['fields']['statement'] = {'$tuple': ['invalid block']}
        elif case == 'negative-progress':
            context['task_progress']['fields']['submissions'] = -1
        elif case == 'history-revision':
            context['history']['$tuple'][0]['fields']['revision'] = True
        elif case == 'reference-shape':
            fields['reference']['fields']['answer']['fields']['fields'] = {'$tuple': ['x', 'y']}
        elif case == 'reference-none-and-fields':
            fields['reference']['fields']['answer']['fields']['claims_none'] = True
        elif case == 'blank-candidate':
            fields['turn']['fields']['message'] = '   '
        elif case == 'exceeded-rung':
            fields['turn']['fields']['rung_used']['name'] = 'FULL_REVEAL'
        elif case == 'oversized-number':
            context['student_summary']['fields']['strength'] = 10 ** 400
        else:
            context['interaction']['fields']['kind'] = 'TASK_QUESTION'
    replace_saved_packet(source, mutate)
    assert main(['rejudge', str(source), '--routes', str(routes_file(tmp_path)),
                 '--out', str(tmp_path / 'rejudged')],
                provider_factories=anthropic_override(lambda **kwargs: pytest.fail('invalid nested packet created client'))) == 2


def write_returned_models(run, *, tutor='tutor-version-a', judge_model='judge-version-a'):
    from dataclasses import asdict
    from tests.eval.test_accounting import record
    entries = [asdict(replace(record('tutor'),scenario_id='one',requested_model='tutor-alias',returned_model=tutor)),
               asdict(replace(record('judge',phase='judge'),scenario_id='one',requested_model='judge-alias',returned_model=judge_model))]
    for entry in entries:
        entry['normalized_tokens'] = entry['normalized_usage']['counts']
    (run / 'requests.jsonl').write_text(''.join(json.dumps(entry) + '\n' for entry in entries))


def test_actual_returned_judge_change_invalidates_fixed_evaluator_comparison(tmp_path):
    left, right = saved_packet_run(tmp_path), saved_packet_run(tmp_path)
    write_returned_models(left)
    write_returned_models(right, judge_model='judge-version-b')
    compared = compare_runs(left, right)
    assert compared['evaluator_or_reference_changed'] is True
    assert compared['evaluator_differences']['returned_judge_models'] == {
        'left': [['one', 'judge-alias', 'judge-version-a', 'anthropic', 'messages']],
        'right': [['one', 'judge-alias', 'judge-version-b', 'anthropic', 'messages']]}
    assert compared['direct_comparison_inputs_held_fixed'] is False
    write_returned_models(right, tutor='tutor-version-b')
    compared = compare_runs(left, right)
    assert compared['provider_returned_models']['tutor']['changed'] is True
    assert compared['provider_returned_models']['judge']['changed'] is False
    assert compared['evaluator_or_reference_changed'] is False
    assert compared['direct_comparison_inputs_held_fixed'] is True


@pytest.mark.parametrize('difference,expected', [
    ('order', {'left': ['one', 'two'], 'right': ['two', 'one']}),
    ('seeds', {'left': [7, 8], 'right': [7, 9]}),
    ('python', {'left': '3.12.1', 'right': '3.12.2'}),
    ('dependencies', {'left': {'verifier': '1.0'}, 'right': {'verifier': '1.1'}}),
])
def test_compare_surfaces_selected_order_seeds_and_runtime_provenance(tmp_path, difference, expected):
    left, right = saved_packet_run(tmp_path), saved_packet_run(tmp_path)
    for index, run in enumerate((left, right)):
        path = run / 'manifest.json'
        raw = json.loads(path.read_text())
        raw['selected_ids'] = ['one', 'two']
        raw['seeds'] = [7, 8]
        raw['material']['python'] = '3.12.1'
        raw['material']['dependencies'] = {'verifier': '1.0'}
        if index == 1:
            if difference == 'order':
                raw['selected_ids'] = ['two', 'one']
            elif difference == 'seeds':
                raw['seeds'] = [7, 9]
            elif difference == 'python':
                raw['material']['python'] = '3.12.2'
            else:
                raw['material']['dependencies'] = {'verifier': '1.1'}
        path.write_text(json.dumps(raw))
    compared = compare_runs(left, right)
    key = {'order': 'selected_ids', 'seeds': 'seeds', 'python': 'python', 'dependencies': 'dependencies'}[difference]
    assert compared['execution_input_differences'][key] == expected
    assert compared['selected_case_overlap'] == ['one', 'two']
    assert compared['direct_comparison_inputs_held_fixed'] is False


def test_rejudge_rejects_unknown_source_version_before_client(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY','fake-key')
    run=saved_packet_run(tmp_path)
    path=run/'manifest.json'
    manifest=json.loads(path.read_text())
    manifest['schema_version']=999
    path.write_text(json.dumps(manifest))
    assert main(['rejudge',str(run),'--routes',str(routes_file(tmp_path)),'--out',str(tmp_path/'rejudged')],
        provider_factories=anthropic_override(lambda **kwargs:pytest.fail('unsupported version constructed a client')))==2
