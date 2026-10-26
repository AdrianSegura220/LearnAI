"""Explicit paid run/rejudge operations and read-only saved-artifact comparison."""
import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable

import anthropic

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor, _request_kwargs
from learnai.adapters.tutor.anthropic.routing import load_budget_profiles, load_routes, resolve_tutor_route
from learnai.adapters.tutor.prompts import load_prompt
from learnai.eval.accounting import RequestLedger, load_prices
from learnai.eval.artifacts import encode
from learnai.eval.fixtures import load_scenarios_dir, validate_corpus
from learnai.eval.judge import JudgeError, JudgePacket, run_judge
from learnai.eval.manifest import build_manifest, canonical_json
from learnai.eval.reference import build_reference
from learnai.eval.replay import prepare_scenario
from learnai.eval.report import TutorTreatment, compare_runs, write_report
from learnai.application.artifacts import load_saved_run
from learnai.eval.runner import run_scenario

ROOT = Path(__file__).resolve().parents[3]


def run_optional_smoke(*, tutor: Any, graph: Any, misconceptions: Any, items: Any,
                       verifiers: Any, matcher: Any) -> dict[str, Any]:
    """Task14 integration seam. Absence is explicit and never fabricated success."""
    try:
        module = importlib.import_module('learnai.eval.smoke')
    except ModuleNotFoundError as exc:
        if exc.name != 'learnai.eval.smoke':
            raise
        return {'status': 'unavailable', 'reason': 'Persona smoke integration is not implemented yet.'}
    result = module.run_persona_smoke(tutor=tutor, graph=graph, misconceptions=misconceptions,
        items=items, verifiers=verifiers, matcher=matcher)
    return {'status': 'complete', 'results': result}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m learnai.eval')
    operations = parser.add_subparsers(dest='operation', required=True)
    run = operations.add_parser('run')
    run.add_argument('--fixtures', type=Path, default=ROOT / 'eval/fixtures')
    run.add_argument('--only', help='Comma-separated ids, evaluated in the supplied order')
    run.add_argument('--no-smoke', action='store_true')
    rejudge = operations.add_parser('rejudge')
    rejudge.add_argument('sources', type=Path, nargs='+')
    for command in (run, rejudge):
        command.add_argument('--routes', type=Path, default=ROOT / 'config/llm_routes.yaml')
        command.add_argument('--out', type=Path, default=ROOT / 'eval/reports')
        command.add_argument('--judge-route', default='rubric_judge')
    compare = operations.add_parser('compare')
    compare.add_argument('left', type=Path)
    compare.add_argument('right', type=Path)
    compare.add_argument('--tutor-treatment', help='Comma-separated tutor route names')
    compare.add_argument('--allow-tutor-dependency-changes', action='store_true')
    return parser


def _preflight(args: argparse.Namespace) -> dict[str, Any]:
    routes, profiles, prices = load_routes(args.routes), load_budget_profiles(args.routes), load_prices(args.routes)
    if args.judge_route not in routes:
        raise ValueError(f'unknown judge route: {args.judge_route}')
    judge_route = routes[args.judge_route]
    if judge_route.prompt is None or judge_route.temperature is not None:
        raise ValueError('judge requires a versioned prompt and omitted temperature')
    prompts = {route.prompt: load_prompt(route.prompt).text for route in routes.values() if route.prompt}
    settings = {'routes': {name: asdict(route) for name, route in routes.items()},
        'budgets': {name: asdict(profile) for name, profile in profiles.items()},
        'judge_route': args.judge_route, 'operation': args.operation,
        'sdk_max_retries': 0, 'token_counter': 'utf8-bytes-plus-256@1'}
    values = dict(routes=routes, profiles=profiles, prices=prices, settings=settings, prompts=prompts)
    if args.operation == 'rejudge':
        packets, links = {}, []
        for source in args.sources:
            source_run = load_saved_run(source)
            saved_manifest, saved = source_run.manifest, source_run.packets
            source_id = saved_manifest['run_id']
            links.append({'run_id': source_id,
                'manifest_sha256': sha256(canonical_json(saved_manifest).encode('utf-8')).hexdigest(),
                'packets': {key: sha256(canonical_json(encode(packet)).encode('utf-8')).hexdigest()
                            for key, packet in saved.items()}})
            for key, packet in saved.items():
                selected_id = f'{source_id}:{key}'
                if selected_id in packets:
                    raise ValueError('duplicate rejudge source packet')
                packets[selected_id] = packet
        values.update(packets=packets, links=links, supplemental_inputs={
            'config/selected/routes.yaml': args.routes.read_text(encoding='utf-8')})
        return values
    cluster = load_cluster(ROOT / 'content/quadratics/skills.yaml')
    items, verifier, matcher = GeneratorRegistry(QUADRATICS_TEMPLATES), SympyVerifier(), SympyMisconceptionRules()
    scenarios = load_scenarios_dir(args.fixtures)
    by_id = {scenario.id: scenario for scenario in scenarios}
    if args.only:
        requested = args.only.split(',')
        if len(set(requested)) != len(requested):
            raise ValueError('duplicate selected scenario id')
        if unknown := set(requested) - by_id.keys():
            raise ValueError(f'unknown scenario ids: {sorted(unknown)}')
        scenarios = tuple(by_id[key] for key in requested)
    if not scenarios:
        raise ValueError('no selected scenarios')
    references, captured = {}, {}
    for scenario in scenarios:
        validate_corpus((scenario,), graph=cluster.graph, items=items, catalogue=cluster.misconceptions,
                        verifier=verifier, matcher=matcher)
        prepared = prepare_scenario(scenario, graph=cluster.graph, items=items,
            catalogue=cluster.misconceptions, verifier=verifier, matcher=matcher)
        reference = build_reference(scenario, item=prepared.task.item, graph=cluster.graph,
                                   catalogue=cluster.misconceptions, verifier=verifier)
        references[scenario.id] = reference
        captured[scenario.id] = {'scenario': encode(scenario), 'generated_item': encode(prepared.task.item)}
        if prepared.context is not None:
            route = resolve_tutor_route(routes, prepared.context.response_job)
            if route.prompt is None:
                raise ValueError('tutor requires a versioned prompt')
            _request_kwargs(route)
    values.update(cluster=cluster, items=items, verifier=verifier, matcher=matcher,
                  scenarios=scenarios, references=references, captured=captured)
    values['settings']['smoke_enabled'] = not args.no_smoke
    # Captured selected inputs include external fixture/config files explicitly requested by the user.
    values['supplemental_inputs'] = {
        'eval/fixtures/selected/' + path.name: path.read_text(encoding='utf-8') for path in sorted(args.fixtures.iterdir())
        if path.is_file() and path.suffix in {'.yaml', '.yml', '.json'}}
    values['supplemental_inputs']['config/selected/routes.yaml'] = args.routes.read_text(encoding='utf-8')
    return values


def main(argv: list[str] | None = None, *, client_factory: Callable[..., Any] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.operation == 'compare':
        try:
            if args.allow_tutor_dependency_changes and not args.tutor_treatment:
                raise ValueError('--allow-tutor-dependency-changes requires --tutor-treatment')
            treatment = (TutorTreatment(tuple(args.tutor_treatment.split(',')), args.allow_tutor_dependency_changes)
                         if args.tutor_treatment else None)
            result = compare_runs(load_saved_run(args.left), load_saved_run(args.right), treatment=treatment)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except (ValueError, OSError, KeyError, TypeError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    try:
        prepared = _preflight(args)
        key = os.environ.get('ANTHROPIC_API_KEY')
        if not key or not key.strip():
            raise ValueError('ANTHROPIC_API_KEY is required for an explicit run/rejudge operation')
        if args.operation == 'run':
            selected = tuple(scenario.id for scenario in prepared['scenarios'])
            seeds = tuple(scenario.seed for scenario in prepared['scenarios'])
            refs = {key: encode(value) for key, value in prepared['references'].items()}
            refs['captured_generated_inputs'] = prepared['captured']
        else:
            selected, seeds = tuple(prepared['packets']), ()
            refs = {key: encode(packet.reference) for key, packet in prepared['packets'].items()}
        manifest = build_manifest(root=ROOT, selected_ids=selected, seeds=seeds,
            settings=prepared['settings'], prompts=prepared['prompts'], references=refs,
            linked_sources=prepared.get('links', ()), supplemental_inputs=prepared['supplemental_inputs'],
            pricing_snapshots=prepared['prices'].to_dict())
        if manifest.missing_inputs:
            raise ValueError(f'missing captured inputs: {manifest.missing_inputs}')
        args.out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=args.out):
            pass
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    ledger, outcomes, scores, packets = RequestLedger(), {}, {}, {}
    smoke: dict[str, Any] = {'status': 'skipped'}
    failed = False
    original_error: BaseException | None = None
    try:
        factory = anthropic.Anthropic if client_factory is None else client_factory
        client = factory(api_key=key, max_retries=0)
        if args.operation == 'run':
            manifest = replace(manifest, phase='tutor')
            cluster, items = prepared['cluster'], prepared['items']
            verifiers = {skill.verification_kind: prepared['verifier'] for skill in cluster.graph.skills.values()}
            for scenario in prepared['scenarios']:
                tutor = AnthropicTutor(prepared['routes'], client, items, cluster.misconceptions,
                    budget_profiles=prepared['profiles'], trace_sink=ledger.sink(phase='tutor', scenario_id=scenario.id))
                outcome = run_scenario(scenario, tutor=tutor, graph=cluster.graph, items=items,
                    catalogue=cluster.misconceptions, verifiers=verifiers, matcher=prepared['matcher'])
                outcomes[scenario.id] = outcome
                if outcome.error:
                    failed = True
                if outcome.turn is not None and outcome.context is not None:
                    packets[scenario.id] = JudgePacket(outcome.context, outcome.turn, prepared['references'][scenario.id])
        else:
            packets.update(prepared['packets'])
        manifest = replace(manifest, phase='judge')
        for case_id, packet in packets.items():
            try:
                scores[case_id] = run_judge(client, prepared['routes'], packet=packet,
                    route_name=args.judge_route, budget_profiles=prepared['profiles'],
                    trace_sink=ledger.sink(phase='judge', scenario_id=case_id))
            except JudgeError as exc:
                scores[case_id] = str(exc)
                failed = True
        if args.operation == 'run' and not args.no_smoke:
            manifest = replace(manifest, phase='smoke')
            tutor = AnthropicTutor(prepared['routes'], client, prepared['items'], prepared['cluster'].misconceptions,
                budget_profiles=prepared['profiles'], trace_sink=ledger.sink(phase='smoke'))
            smoke = run_optional_smoke(tutor=tutor, graph=cluster.graph, misconceptions=cluster.misconceptions,
                items=items, verifiers=verifiers, matcher=prepared['matcher'])
            failed = failed or smoke['status'] != 'complete'
        manifest = replace(manifest, phase='finished', status='incomplete' if failed else 'complete')
    except BaseException as exc:
        original_error = exc
        manifest = replace(manifest, status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'error')
        failed = True
    finally:
        manifest = replace(manifest, ended_at=datetime.now(UTC).isoformat(),
            rendered_prompts=tuple({'request_id': record.request_id, 'phase': record.phase,
                                    'request': record.request} for record in ledger.records))
        try:
            run = write_report(args.out, manifest=manifest, outcomes=outcomes, scores=scores,
                judge_packets=packets, ledger=ledger, prices=prepared['prices'], persona_smoke=smoke)
            print(str(run))
        except BaseException as report_error:
            if original_error is None:
                raise
            print(f'Partial artifact writing failed: {report_error}', file=sys.stderr)
    if original_error is not None:
        if isinstance(original_error, (KeyboardInterrupt, SystemExit)):
            raise original_error
        print(f'{type(original_error).__name__}: {original_error}', file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
