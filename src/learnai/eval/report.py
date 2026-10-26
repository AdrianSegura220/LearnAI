"""Readable partial run artifacts, explicit denominators and comparison caveats."""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal
from hashlib import sha256
import math
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from learnai.eval.accounting import PriceBook, RequestLedger, estimate_cost
from learnai.eval.artifacts import SavedRun, encode
from learnai.eval.judge import JudgePacket, JudgeScores
from learnai.eval.manifest import RunManifest, canonical_json
from learnai.eval.runner import ScenarioOutcome


@dataclass(frozen=True)
class TutorTreatment:
    route_names: tuple[str, ...]
    allow_tutor_dependency_changes: bool = False

    def __post_init__(self) -> None:
        if (not isinstance(self.route_names, tuple) or not self.route_names
                or any(not isinstance(name, str) or not name.strip() for name in self.route_names)
                or len(set(self.route_names)) != len(self.route_names)
                or type(self.allow_tutor_dependency_changes) is not bool):
            raise ValueError('tutor treatment requires unique nonempty route names')


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
                 ledger: RequestLedger, prices: PriceBook, persona_smoke: Any) -> Path:
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
    report = dict(schema_version=2, run_id=manifest.run_id, status=manifest.status, phase=manifest.phase,
        counts=counts, eligible_ids=eligible_ids,
        unexecuted_ids=[key for key in manifest.selected_ids if key not in (outcomes or judge_packets)],
        coverage={'judged_of_eligible': _coverage(judged, len(eligible_ids)),
                  'scored_of_eligible': _coverage(len(numeric), len(eligible_ids))},
        score_averages={name: sum(getattr(score, name) for score in numeric) / len(numeric) if numeric else None
                        for name in ('mathematics', 'help_level', 'diagnosis', 'tone')},
        scores={key: _json(score) for key, score in scores.items()},
        latency_by_response_job=_latencies(outcomes), cost=cost, prices=prices.to_dict(),
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


def compare_runs(left: SavedRun, right: SavedRun, *, treatment: TutorTreatment | None = None) -> dict[str, Any]:
    """Artifact inspection only: disclose configuration/evaluator changes first."""
    # Path support preserves existing callers; composition owns version dispatch.
    if isinstance(left, Path) or isinstance(right, Path):
        from learnai.application.artifacts import load_saved_run
        left = load_saved_run(left) if isinstance(left, Path) else left
        right = load_saved_run(right) if isinstance(right, Path) else right
    manifests = [run.manifest for run in (left, right)]
    reports = [run.report for run in (left, right)]
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
                                             'missing_inputs', 'saved_packet_inputs', 'identities', 'role_dependencies', 'pricing_snapshots')},
    } for manifest, material in zip(manifests, materials)]
    execution_differences = {key: {'left': execution_inputs[0][key], 'right': execution_inputs[1][key]}
                             for key in execution_inputs[0]
                             if execution_inputs[0][key] != execution_inputs[1][key]}
    def returned(run: SavedRun) -> list[tuple[Any, ...]]:
        return [(entry.scenario_id, entry.phase, entry.requested_model, entry.returned_model,
                 entry.provider, entry.api_family) for entry in run.records]
    provider_models = [returned(run) for run in (left, right)]
    by_phase = [{phase: [list(entry) for entry in sorted(
        {(entry[0], *entry[2:]) for entry in models if entry[1] == phase},
        key=canonical_json)] for phase in ('tutor', 'judge', 'smoke')} for models in provider_models]
    if by_phase[0]['judge'] != by_phase[1]['judge']:
        evaluator_differences['returned_judge_models'] = {'left': by_phase[0]['judge'], 'right': by_phase[1]['judge']}
    evaluator_changed = bool(evaluator_differences)
    # Conservative verdict: matching fingerprints alone never establish quality.
    comparable = not (changed_inputs or settings_changed or evaluator_changed or execution_differences)
    controlled = _controlled_tutor_comparison(left, right, treatment)
    return dict(tutor_treatment=asdict(treatment) if treatment is not None else None,
        controlled_tutor_comparison=controlled, compatibility_notes={'left': left.compatibility_notes, 'right': right.compatibility_notes},
        changed_input_hashes=changed_inputs, settings_changed=settings_changed,
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
            if all(type(report.get('score_averages', {}).get(name)) in (int, float)
                   for report in reports) else None)
            for name in ('mathematics', 'help_level', 'diagnosis', 'tone')})


_TUTOR_FIELDS = {'adapter', 'model', 'effort', 'thinking', 'temperature', 'max_tokens', 'stream', 'provider_options'}


def _without_treatment_routes(settings: Mapping[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    result = deepcopy(dict(settings))
    for name in names:
        route = result.get('routes', {}).get(name)
        if isinstance(route, dict):
            for field in _TUTOR_FIELDS:
                route.pop(field, None)
    return result


def _known_role_identity(value: Any, *, tutor: bool) -> bool:
    if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or not value[key].strip()
            for key in ('provider', 'api_family', 'usage_mapper_id', 'token_counter_id')):
        return False
    hashes = value.get('schema_hashes')
    required = ('final_output', 'canonical_read_tools', 'wire_read_tools') if tutor else ('final_output',)
    return isinstance(hashes, dict) and all(isinstance(hashes.get(key), str) and hashes[key].strip()
                                           for key in required)


def _controlled_tutor_comparison(left: SavedRun, right: SavedRun,
                                 treatment: TutorTreatment | None) -> dict[str, Any]:
    if treatment is None:
        return {'eligible': False, 'reasons': ['no tutor treatment declared']}
    reasons = []
    runs = (left, right)
    materials = [run.manifest['material'] for run in runs]
    settings = [material.get('settings', {}) for material in materials]
    names = treatment.route_names
    identities = [material.get('identities', {}) for material in materials]
    roles = [material.get('role_dependencies', {}) for material in materials]
    for run, setting, identity in zip(runs, settings, identities):
        for name in names:
            route = setting.get('routes', {}).get(name)
            role_identity = identity.get('tutor', {}).get(name)
            if not _known_role_identity(role_identity, tutor=True):
                reasons.append(f'unknown tutor encoding identity: {name}')
            if (not isinstance(route, dict) or name == setting.get('judge_route')
                    or not isinstance(role_identity, dict) or not role_identity
                    or not any(record.phase == 'tutor' and record.requested_model == route.get('model')
                               and record.provider == role_identity.get('provider') for record in run.records)):
                reasons.append(f'declared route is not established as used for tutor generation: {name}')
        judge_name = setting.get('judge_route')
        judge_identity = identity.get('judge', {}).get(judge_name)
        judge_route = setting.get('routes', {}).get(judge_name)
        observed_judges = [record for record in run.records if record.phase == 'judge']
        if (not _known_role_identity(judge_identity, tutor=False) or not isinstance(judge_route, dict)
                or not observed_judges or any(not record.returned_model
                    or record.requested_model != judge_route.get('model')
                    or record.provider != judge_identity.get('provider')
                    or record.api_family != judge_identity.get('api_family') for record in observed_judges)):
            reasons.append('unknown or conflicting evaluator identity')
        if not run.manifest['material'].get('pricing_snapshots'):
            reasons.append('unknown pricing snapshot identity')
    if _without_treatment_routes(settings[0], names) != _without_treatment_routes(settings[1], names):
        reasons.append('settings changed outside declared tutor fields')
    for key in ('prompts', 'references', 'python', 'deleted_inputs', 'missing_inputs', 'saved_packet_inputs', 'pricing_snapshots'):
        if materials[0].get(key) != materials[1].get(key):
            reasons.append(f'held-fixed material changed: {key}')
    for key in ('selected_ids', 'seeds', 'schema_version', 'code_revision'):
        if left.manifest.get(key) != right.manifest.get(key):
            reasons.append(f'execution identity changed: {key}')
    if not left.manifest.get('code_revision') or not right.manifest.get('code_revision'):
        reasons.append('unknown source revision')
    if left.compatibility_notes or right.compatibility_notes:
        reasons.append('legacy normalization is not identical')
    # Only attributable provider/API/schema/mapper changes can follow a tutor switch.
    identity_copies = []
    for identity in identities:
        value = deepcopy(identity)
        for name in names:
            route = value.get('tutor', {}).get(name)
            if isinstance(route, dict):
                for key in ('provider', 'api_family', 'usage_mapper_id'):
                    route.pop(key, None)
                hashes = route.get('schema_hashes')
                if isinstance(hashes, dict):
                    for key in ('final_output', 'wire_read_tools'):
                        hashes.pop(key, None)
                if isinstance(route.get('effective_settings'), dict):
                    for key in _TUTOR_FIELDS:
                        route['effective_settings'].pop(key, None)
        identity_copies.append(value)
    if identity_copies[0] != identity_copies[1]:
        reasons.append('role identities changed outside attributable tutor provider/API/schema identities')
    for role in ('tutor', 'judge'):
        for role_map in roles:
            deps = role_map.get(role)
            if not isinstance(deps, dict) or not deps or any(not isinstance(v, str) or not v for v in deps.values()):
                reasons.append(f'unknown {role} dependency versions')
    tutor_deps = [role.get('tutor', {}) for role in roles]
    judge_deps = [role.get('judge', {}) for role in roles]
    if judge_deps[0] != judge_deps[1]:
        reasons.append('judge dependency versions changed (including shared SDK/transport)')
    for dependency in tutor_deps[0].keys() & tutor_deps[1].keys():
        if tutor_deps[0][dependency] != tutor_deps[1][dependency]:
            if not treatment.allow_tutor_dependency_changes:
                reasons.append(f'tutor dependency version change needs opt-in: {dependency}')
            if dependency in judge_deps[0] or dependency in judge_deps[1]:
                reasons.append(f'changed tutor dependency is also used by judge: {dependency}')
    provider_switch = any(settings[0].get('routes', {}).get(name, {}).get('adapter') !=
                          settings[1].get('routes', {}).get(name, {}).get('adapter') for name in names)
    if tutor_deps[0].keys() != tutor_deps[1].keys() and not provider_switch and not treatment.allow_tutor_dependency_changes:
        reasons.append('tutor dependency membership change needs opt-in')
    dependencies = [material.get('dependencies', {}) for material in materials]
    for name in dependencies[0].keys() | dependencies[1].keys():
        if dependencies[0].get(name) != dependencies[1].get(name):
            if name not in tutor_deps[0] and name not in tutor_deps[1]:
                reasons.append(f'unclassified dependency changed: {name}')
            elif name in judge_deps[0] or name in judge_deps[1]:
                reasons.append(f'shared judge dependency changed: {name}')
    # Compare complete captured YAML semantics after removing only declared fields.
    inputs = [{entry['path']: entry for entry in material.get('inputs', ())} for material in materials]
    for path in inputs[0].keys() | inputs[1].keys():
        a, b = inputs[0].get(path), inputs[1].get(path)
        if a is not None and b is not None and a.get('sha256') == b.get('sha256'):
            continue
        if a is not None and b is not None and path.startswith('config/') and Path(path).suffix in {'.yaml', '.yml'}:
            try:
                parsed = [yaml.safe_load(entry['content']) for entry in (a, b)]
                if all(isinstance(value, dict) for value in parsed) and (
                    _without_treatment_routes(parsed[0], names) == _without_treatment_routes(parsed[1], names)):
                    continue
            except (KeyError, TypeError, ValueError, yaml.YAMLError):
                pass
        reasons.append(f'unclassified captured input changed: {path}')
    # New unknown material cannot silently become an exemption.
    known_keys = {'schema_version','selected_ids','seeds','settings','prompts','references','inputs','code_revision',
                  'python','dependencies','missing_inputs','deleted_inputs','saved_packet_inputs','identities','role_dependencies','pricing_snapshots'}
    for key in (materials[0].keys() | materials[1].keys()) - known_keys:
        if materials[0].get(key) != materials[1].get(key):
            reasons.append(f'unclassified material changed: {key}')
    returned_judges = [[(record.scenario_id, record.provider, record.api_family, record.requested_model, record.returned_model)
                       for record in run.records if record.phase == 'judge'] for run in runs]
    if returned_judges[0] != returned_judges[1]:
        reasons.append('judge provider/API/returned model changed')
    return {'eligible': not reasons, 'reasons': list(dict.fromkeys(reasons))}
