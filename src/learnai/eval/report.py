"""Readable partial run artifacts, explicit denominators and comparison caveats."""
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from hashlib import sha256
import math
from pathlib import Path
from statistics import median
from typing import Any

from learnai.eval.accounting import PriceSnapshot, RequestLedger, estimate_cost
from learnai.eval.artifacts import encode, read_json
from learnai.eval.judge import JudgePacket, JudgeScores
from learnai.eval.manifest import RunManifest, canonical_json
from learnai.eval.runner import ScenarioOutcome


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return _json(asdict(value))
    if isinstance(value, dict):
        return {key: _json(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(entry) for entry in value]
    return value


def _write(path: Path, value: Any) -> str:
    text = canonical_json(_json(value))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + '\n', encoding='utf-8')
    return sha256(text.encode('utf-8')).hexdigest()


def _coverage(numerator: int, denominator: int) -> dict[str, Any]:
    return dict(numerator=numerator, denominator=denominator,
                ratio=numerator / denominator if denominator else None)


def _latencies(outcomes: Mapping[str, ScenarioOutcome]) -> dict[str, Any]:
    jobs: dict[str, list[ScenarioOutcome]] = {}
    for outcome in outcomes.values():
        if outcome.context is not None:
            jobs.setdefault(outcome.context.response_job.value, []).append(outcome)
    result = {}
    for job, cases in jobs.items():
        samples = sorted(case.trace.elapsed_seconds for case in cases
                         if case.turn is not None and case.trace is not None)
        failed = sum(case.turn is None for case in cases)
        exhausted = sum(case.error is not None and (case.error.endswith('exhausted') or case.error.endswith('limit'))
                        for case in cases)
        result[job] = dict(accepted_buffered_seconds={'median': median(samples) if samples else None,
            'p95': samples[max(0, math.ceil(.95 * len(samples)) - 1)] if samples else None,
            'samples': len(samples)}, failure_rate=_coverage(failed, len(cases)),
            exhaustion_rate=_coverage(exhausted, len(cases)))
    return result


def write_report(directory: Path, *, manifest: RunManifest, outcomes: Mapping[str, ScenarioOutcome],
                 scores: Mapping[str, JudgeScores | str], judge_packets: Mapping[str, JudgePacket],
                 ledger: RequestLedger, prices: PriceSnapshot, persona_smoke: Any) -> Path:
    """One unique directory per execution. Existing runs are never overwritten."""
    run = directory / manifest.run_id
    run.mkdir(parents=True, exist_ok=False)
    _write(run / 'manifest.json', manifest.to_dict())
    for entry in manifest.material.get('inputs', ()):
        relative = Path(entry['artifact_path'])
        path = run / relative
        if relative.is_absolute() or not path.resolve().is_relative_to(run.resolve()):
            raise ValueError('input artifact path escapes run directory')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry['content'], encoding='utf-8')
    with (run / 'requests.jsonl').open('w', encoding='utf-8') as stream:
        for record in ledger.records:
            stream.write(canonical_json(_json(asdict(record))) + '\n')
    trace_entries = []
    for index, trace in enumerate(ledger.traces.values()):
        path = f'traces/{index:04d}.json'
        digest = _write(run / path, trace)
        trace_entries.append({'path': path, 'sha256': digest, 'phase': trace['phase']})
    packet_entries, outcome_entries = {}, {}
    for index, (case_id, packet) in enumerate(judge_packets.items()):
        path = f'packets/{index:04d}.json'
        digest = _write(run / path, encode(packet))
        packet_entries[case_id] = {'path': path, 'sha256': digest}
    for index, (case_id, outcome) in enumerate(outcomes.items()):
        value = dict(scenario=encode(outcome.scenario), item=encode(outcome.item),
                     turn=encode(outcome.turn), context=encode(outcome.context), attempts=outcome.attempts,
                     error=outcome.error, non_tutored_reason=outcome.non_tutored_reason,
                     observed_usage=outcome.usage,
                     trace=outcome.trace.to_dict() if outcome.trace is not None else None)
        path = f'outcomes/{index:04d}.json'
        digest = _write(run / path, value)
        outcome_entries[case_id] = {'path': path, 'sha256': digest}
    accepted = sum(case.turn is not None for case in outcomes.values())
    eligible_ids = [key for key, case in outcomes.items() if case.turn is not None and case.context is not None]
    numeric = [score for score in scores.values() if isinstance(score, JudgeScores) and score.status == 'scored']
    abstained = sum(isinstance(score, JudgeScores) and score.status == 'insufficient_evidence'
                    for score in scores.values())
    errors = sum(isinstance(score, str) for score in scores.values())
    # Rejudging has saved packets and no generation outcomes.
    if not outcomes and judge_packets:
        accepted, eligible_ids = len(judge_packets), list(judge_packets)
    judged = len(numeric) + abstained
    counts = dict(selected=len(manifest.selected_ids), accepted=accepted,
        eligible=len(eligible_ids), judged=judged, scored=len(numeric), abstained=abstained,
        judge_error=errors, tutor_failed=sum(case.context is not None and case.turn is None for case in outcomes.values()),
        expected_non_tutored=sum(case.non_tutored_reason is not None for case in outcomes.values()))
    costs = estimate_cost(ledger, prices)
    cost = _json(costs)
    tutor_ledger = RequestLedger()
    for record in ledger.records:
        if record.phase == 'tutor':
            tutor_ledger.record(record)
    tutor_cost = estimate_cost(tutor_ledger, prices)
    cost['scenario_tutor_per_accepted'] = (str(tutor_cost.total / accepted)
        if accepted and tutor_cost.total is not None else None)
    cost['full_evaluation_per_accepted_including_judge_smoke'] = (str(costs.total / accepted)
        if accepted and costs.total is not None else None)
    cost['estimate_notice'] = 'Estimated API cost, not an invoice; retry subtotal overlaps phase totals.'
    report = dict(schema_version=1, run_id=manifest.run_id, status=manifest.status, phase=manifest.phase,
        counts=counts, eligible_ids=eligible_ids,
        unexecuted_ids=[key for key in manifest.selected_ids if key not in (outcomes or judge_packets)],
        coverage={'judged_of_eligible': _coverage(judged, len(eligible_ids)),
                  'scored_of_eligible': _coverage(len(numeric), len(eligible_ids))},
        score_averages={name: sum(getattr(score, name) for score in numeric) / len(numeric) if numeric else None
                        for name in ('mathematics', 'help_level', 'diagnosis', 'tone')},
        scores={key: _json(score) for key, score in scores.items()},
        latency_by_response_job=_latencies(outcomes), cost=cost, prices=_json(prices),
        judge_packets=packet_entries, outcomes=outcome_entries, traces=trace_entries, persona_smoke=persona_smoke)
    _write(run / 'report.json', report)
    lines = [f'Run {manifest.run_id}: {manifest.status} ({manifest.phase})', '',
        f'Configuration fingerprint: {manifest.to_dict()["configuration_fingerprint"]}', '',
        f'Selected {counts["selected"]}; accepted {accepted}; eligible {len(eligible_ids)}; '
        f'judged {judged}; scored {len(numeric)}; abstained {abstained}; judge errors {errors}.',
        f'Tutor failures {counts["tutor_failed"]}; expected non-tutored {counts["expected_non_tutored"]}.', '',
        f'Estimated API cost: {costs.total if costs.complete else "incomplete"} {costs.currency}; '
        f'known subtotal {costs.known_subtotal}. This estimate is not an invoice.',
        f'Phase subtotals: {cost["by_phase"]}; retry subtotal {costs.retry_subtotal} overlaps these totals.',
        f'Scenario tutor cost per accepted response: {cost["scenario_tutor_per_accepted"]}.',
        'Full evaluation cost per accepted response (includes judge/smoke): '
        f'{cost["full_evaluation_per_accepted_including_judge_smoke"]}.', '',
        f'Coverage (explicit denominators): {report["coverage"]}',
        f'Numeric scored averages only: {report["score_averages"]}',
        f'Buffered accepted response latency, failures and exhaustion: {report["latency_by_response_job"]}',
        f'Smoke: {persona_smoke}', *costs.unknown_entries]
    (run / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return run


def compare_runs(left: Path, right: Path) -> dict[str, Any]:
    """Artifact inspection only: disclose configuration/evaluator changes first."""
    manifests = [read_json(path / 'manifest.json') for path in (left, right)]
    reports = [read_json(path / 'report.json') for path in (left, right)]
    materials = [manifest['material'] for manifest in manifests]
    hashes = [{entry['path']: entry['sha256'] for entry in material.get('inputs', ())} for material in materials]
    changed_inputs = {path: {'left': hashes[0].get(path), 'right': hashes[1].get(path)}
                      for path in sorted(hashes[0].keys() | hashes[1].keys())
                      if hashes[0].get(path) != hashes[1].get(path)}
    settings = [material.get('settings', {}) for material in materials]
    changed_settings = {key: {'left': settings[0].get(key), 'right': settings[1].get(key)}
                        for key in sorted(settings[0].keys() | settings[1].keys())
                        if settings[0].get(key) != settings[1].get(key)}
    settings_changed = bool(changed_settings)
    judges = [setting.get('routes', {}).get(setting.get('judge_route')) for setting in settings]
    evaluator_differences = {key: {'left': materials[0].get(key), 'right': materials[1].get(key)}
                            for key in ('prompts', 'references')
                            if materials[0].get(key) != materials[1].get(key)}
    if judges[0] != judges[1]:
        evaluator_differences['judge_settings'] = {'left': judges[0], 'right': judges[1]}
    selected = [set(manifest['selected_ids']) for manifest in manifests]
    execution_inputs = [{
        'selected_ids': manifest['selected_ids'], 'seeds': manifest['seeds'],
        'schema_version': manifest['schema_version'], 'code_revision': manifest['code_revision'],
        **{key: material.get(key) for key in ('python', 'dependencies', 'deleted_inputs',
                                             'missing_inputs', 'saved_packet_inputs')},
    } for manifest, material in zip(manifests, materials)]
    execution_differences = {key: {'left': execution_inputs[0][key], 'right': execution_inputs[1][key]}
                             for key in execution_inputs[0]
                             if execution_inputs[0][key] != execution_inputs[1][key]}
    def returned(path: Path) -> list[tuple[Any, ...]]:
        from json import loads
        return [(entry.get('scenario_id'), entry['phase'], entry['requested_model'], entry['returned_model'])
                for line in (path / 'requests.jsonl').read_text(encoding='utf-8').splitlines() if (entry := loads(line))]
    provider_models = [returned(path) for path in (left, right)]
    by_phase = [{phase: [list(entry) for entry in sorted(
        {(case, requested, actual) for case, recorded_phase, requested, actual in models if recorded_phase == phase},
        key=canonical_json)] for phase in ('tutor', 'judge', 'smoke')} for models in provider_models]
    if by_phase[0]['judge'] != by_phase[1]['judge']:
        evaluator_differences['returned_judge_models'] = {'left': by_phase[0]['judge'], 'right': by_phase[1]['judge']}
    evaluator_changed = bool(evaluator_differences)
    # Conservative verdict: matching fingerprints alone never establish quality.
    comparable = not (changed_inputs or settings_changed or evaluator_changed or execution_differences)
    return dict(changed_input_hashes=changed_inputs, settings_changed=settings_changed,
        changed_settings=changed_settings, execution_input_differences=execution_differences,
        evaluator_differences=evaluator_differences,
        evaluator_or_reference_changed=evaluator_changed, selected_case_overlap=sorted(selected[0] & selected[1]),
        provider_returned_models={'left': provider_models[0], 'right': provider_models[1],
                                 'changed': provider_models[0] != provider_models[1],
                                 **{phase: {'left': by_phase[0][phase], 'right': by_phase[1][phase],
                                           'changed': by_phase[0][phase] != by_phase[1][phase]}
                                    for phase in ('tutor', 'judge', 'smoke')}},
        direct_comparison_inputs_held_fixed=comparable,
        comparison_notice='Inspect scenarios, references and judge before interpreting numerical differences.',
        numerical_differences={name: (reports[1]['score_averages'][name] - reports[0]['score_averages'][name]
            if reports[1]['score_averages'][name] is not None and reports[0]['score_averages'][name] is not None else None)
            for name in ('mathematics', 'help_level', 'diagnosis', 'tone')})
