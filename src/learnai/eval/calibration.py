"""Prepare authored drafts and assess them in an isolated judge-only operation."""
import argparse
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

import yaml

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.configuration import ResolvedRoleConfig
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.routing import load_budget_profiles, load_routes
from learnai.adapters.tutor.turn_schema import TurnSchemaError, parse_turn
from learnai.application.ports import ProviderFactory
from learnai.application.providers import ProviderServices, default_registry, resolve_operation_routes
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId
from learnai.domain.misconceptions import MisconceptionMatcher
from learnai.domain.ports import Verifier
from learnai.domain.skills import Misconception
from learnai.domain.turn import RejectionReason, ValidationResult, validate_turn
from learnai.eval.accounting import RequestLedger, load_prices
from learnai.eval.artifacts import encode
from learnai.eval.fixtures import FixtureError, Scenario, load_scenarios_dir
from learnai.eval.judge import JudgeError, JudgePacket, run_judge
from learnai.eval.manifest import build_manifest, canonical_json
from learnai.eval.reference import build_reference
from learnai.eval.replay import prepare_scenario

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class PreparedCalibrationCase:
    id: str
    packet: JudgePacket
    validation: ValidationResult
    expected_scores: Mapping[str, int]
    review_status: str
    assessment_source: str


def _mapping(value: object, keys: set[str], path: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise FixtureError(f"{path} must be a mapping")
    if set(value) != keys:
        raise FixtureError(f"{path}: missing or unknown fields; required {sorted(keys)}")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureError(f"{path} must be a nonblank string")
    return value


def prepare_calibration(path: Path, *, scenarios: Mapping[str, Scenario], graph: SkillGraph,
                        items: GeneratorRegistry,
                        catalogue: Mapping[MisconceptionId, Misconception], verifier: Verifier,
                        matcher: MisconceptionMatcher) -> tuple[PreparedCalibrationCase, ...]:
    """Validate the complete collection without clients, delivery or judge calls.

    Candidates may be deliberately rejected drafts. Their exact engine outcomes
    must match the declarations; labels and gate results never enter packets.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise FixtureError(f"cannot read calibration {path}: {exc}") from exc
    raw = _mapping(raw, {"version", "cases"}, "calibration")
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise FixtureError("calibration.version must be 1")
    if not isinstance(raw["cases"], list) or not raw["cases"]:
        raise FixtureError("calibration.cases must be a nonempty list")
    prepared = []
    ids = set()
    for index, entry in enumerate(raw["cases"]):
        entry = _mapping(entry, {"id", "scenario_id", "candidate", "expected_scores", "rationale",
                                 "review_status", "assessment_source", "expected_engine"},
                         f"cases[{index}]")
        case_id = _text(entry["id"], f"cases[{index}].id")
        if case_id in ids:
            raise FixtureError(f"duplicate calibration id: {case_id}")
        ids.add(case_id)
        scenario_id = _text(entry["scenario_id"], f"{case_id}.scenario_id")
        if scenario_id not in scenarios:
            raise FixtureError(f"{case_id}: unknown scenario {scenario_id}")
        _text(entry["rationale"], f"{case_id}.rationale")
        status, source = entry["review_status"], entry["assessment_source"]
        if status not in ("proposed", "user_confirmed"):
            raise FixtureError(f"{case_id}: invalid review_status")
        if source not in ("judge_packet", "trace_review"):
            raise FixtureError(f"{case_id}: invalid assessment_source")
        scores = entry["expected_scores"]
        if (not isinstance(scores, Mapping)
                or any(name not in ("mathematics", "help_level", "diagnosis", "tone")
                       or type(score) is not int or not 0 <= score <= 2
                       for name, score in scores.items())):
            raise FixtureError(f"{case_id}: expected_scores must contain score names and integers 0–2")
        if source == "trace_review" and scores:
            raise FixtureError(f"{case_id}: trace_review requires empty expected_scores")
        expected = _mapping(entry["expected_engine"], {"accepted", "reason"},
                            f"{case_id}.expected_engine")
        accepted, reason = expected["accepted"], expected["reason"]
        if (type(accepted) is not bool
                or (accepted and reason is not None)
                or (not accepted and (not isinstance(reason, str) or reason not in RejectionReason.__members__))):
            raise FixtureError(f"{case_id}: invalid expected_engine acceptance/rejection reason")
        try:
            candidate = parse_turn(entry["candidate"])
        except (TurnSchemaError, TypeError) as exc:
            raise FixtureError(f"{case_id}: invalid candidate: {exc}") from exc
        scenario = scenarios[scenario_id]
        replayed = prepare_scenario(scenario, graph=graph, items=items, catalogue=catalogue,
                                   verifier=verifier, matcher=matcher)
        if replayed.context is None:
            raise FixtureError(f"{case_id}: scenario {scenario_id} has no tutor opportunity")
        validation = validate_turn(candidate, replayed.context, graph, verifier)
        actual_reason = validation.reason.name if validation.reason is not None else None
        if validation.accepted != accepted or actual_reason != reason:
            raise FixtureError(f"{case_id}: engine gate mismatch: expected {dict(expected)}, "
                               f"got accepted={validation.accepted}, reason={actual_reason}")
        reference = build_reference(scenario, item=replayed.task.item, graph=graph,
                                    catalogue=catalogue, verifier=verifier)
        prepared.append(PreparedCalibrationCase(case_id, JudgePacket(replayed.context, candidate, reference),
                                               validation, dict(scores), status, source))
    return tuple(prepared)


def _case_snapshot(case: PreparedCalibrationCase) -> dict:
    return dict(id=case.id, packet=encode(case.packet), validation=encode(case.validation),
                expected_scores=dict(case.expected_scores), review_status=case.review_status,
                assessment_source=case.assessment_source)


def _summary(cases: tuple[PreparedCalibrationCase, ...], results: Mapping[str, dict]) -> dict:
    counts = dict(total=len(cases), judge_packet=0, trace_review=0,
                  **{status: 0 for status in ('scored', 'insufficient_evidence', 'judge_error',
                      'manual_review_required', 'pending', 'running', 'error', 'interrupted')})
    expected, compared, matches, excluded = 0, 0, 0, {}
    for case in cases:
        result = results[case.id]
        counts[case.assessment_source] += 1
        counts[result['status']] += 1
        if case.review_status == 'user_confirmed':
            dimensions = len(case.expected_scores)
            expected += dimensions
            if result['status'] == 'scored':
                compared += dimensions
                matches += sum(entry['matches'] for entry in result['comparison'].values())
            elif dimensions:
                status = result['status']
                excluded[status] = excluded.get(status, 0) + dimensions
    return dict(counts=counts, confirmed_agreement=dict(expected_dimensions=expected,
        compared_dimensions=compared, matches=matches, ratio=matches / compared if compared else None,
        excluded_dimensions=excluded))


def _persist(directory: Path, envelope: dict, *, cases: tuple[PreparedCalibrationCase, ...],
             ledger: RequestLedger) -> None:
    """Replace one private snapshot atomically; earlier complete snapshots survive interruption."""
    envelope['summary'] = _summary(cases, envelope['results'])
    envelope['requests'] = [asdict(record) for record in ledger.records]
    envelope['traces'] = list(ledger.traces.values())
    content = canonical_json(envelope) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                         prefix='.calibration-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(directory / 'calibration.json')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _execute(*, cases: tuple[PreparedCalibrationCase, ...], services: ProviderServices,
             factory: ProviderFactory, config: ResolvedRoleConfig, directory: Path,
             envelope: dict, ledger: RequestLedger) -> int:
    original_error = None
    current = None
    failed = False
    try:
        with services:
            for case in cases:
                if case.assessment_source == 'trace_review':
                    continue
                current = case.id
                result = envelope['results'][current]
                result['status'] = 'running'
                _persist(directory, envelope, cases=cases, ledger=ledger)
                try:
                    factory.prepare_judge(config, packet=case.packet)
                    scores = run_judge(services.judge(scenario_id=case.id), packet=case.packet)
                except JudgeError as exc:
                    result.update(status='judge_error', error=str(exc))
                    failed = True
                else:
                    result.update(status=scores.status, scores=asdict(scores))
                    observations = {name: dict(expected=expected, actual=getattr(scores, name))
                                    for name, expected in case.expected_scores.items()}
                    if case.review_status == 'user_confirmed' and scores.status == 'scored':
                        result['comparison'] = {name: dict(value, matches=value['expected'] == value['actual'])
                                                for name, value in observations.items()}
                    elif case.review_status == 'proposed':
                        result['proposed_observation'] = observations
                _persist(directory, envelope, cases=cases, ledger=ledger)
                current = None
            envelope['status'] = 'incomplete' if failed else 'complete'
    except BaseException as exc:
        original_error = exc
        status = 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'error'
        envelope.update(status=status, error=f'{type(exc).__name__}: {exc}')
        if current is not None:
            envelope['results'][current].update(status=status, error=f'{type(exc).__name__}: {exc}')
        failed = True
    finally:
        envelope['ended_at'] = datetime.now(UTC).isoformat()
        _persist(directory, envelope, cases=cases, ledger=ledger)
        print(str(directory))
    if isinstance(original_error, (KeyboardInterrupt, SystemExit)):
        raise original_error
    if original_error is not None:
        print(envelope['error'], file=sys.stderr)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m learnai.eval.calibration')
    parser.add_argument('--calibration', type=Path, required=True)
    parser.add_argument('--routes', type=Path, default=ROOT / 'config/llm_routes.yaml')
    parser.add_argument('--judge-route', default='rubric_judge_openai')
    parser.add_argument('--out', type=Path, default=ROOT / 'eval/reports')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    ledger = RequestLedger()
    try:
        content = args.calibration.read_text(encoding='utf-8')
        cluster = load_cluster(ROOT / 'content/quadratics/skills.yaml')
        cases = prepare_calibration(args.calibration,
            scenarios={scenario.id: scenario for scenario in load_scenarios_dir(ROOT / 'eval/fixtures')},
            graph=cluster.graph, items=GeneratorRegistry(QUADRATICS_TEMPLATES),
            catalogue=cluster.misconceptions, verifier=SympyVerifier(), matcher=SympyMisconceptionRules())
        if args.calibration.read_text(encoding='utf-8') != content:
            raise ValueError('calibration content changed during preparation')
        routes, profiles, prices = load_routes(args.routes), load_budget_profiles(args.routes), load_prices(args.routes)
        selected = resolve_operation_routes(routes=routes, contexts=(), judge_route_name=args.judge_route,
                                            smoke=False, rejudge=True)
        registry = default_registry()
        route = selected.judge
        factory = registry.get(route.adapter)
        # Static resolution and request encoding are keyless and never import provider SDKs.
        factory.validate_route(route, role='judge')
        config = factory.resolve_config(route, role='judge', profiles=profiles, prompts_root=PROMPTS_ROOT)
        for case in cases:
            if case.assessment_source == 'judge_packet':
                request = factory.prepare_judge(config, packet=case.packet)
                if not request.admitted:
                    raise ValueError(f'{case.id}: judge request exceeds context budget')
        if args.dry_run:
            print(json.dumps(dict(status='dry_run', judge_route=route.name,
                judge_cases=sum(case.assessment_source == 'judge_packet' for case in cases),
                manual_review_cases=sum(case.assessment_source == 'trace_review' for case in cases))))
            return 0
        services = ProviderServices(selected=selected, registry=registry, environment=os.environ,
            dependencies=None, profiles=profiles, prompts_root=PROMPTS_ROOT, ledger=ledger)
        services.validate()
        config = services.resolved_configs['judge', route.name]
        settings = dict(operation='calibration', judge_route=route.name, sdk_max_retries=0,
            routes={route.name: dict(asdict(route), effective_settings=dict(config.effective_settings))},
            budgets={route.budget_profile: asdict(config.profile)})
        identity = dict(provider=config.provider, api_family=config.api_family,
            usage_mapper_id=config.usage_mapper_id, token_counter_id=config.token_counter_id,
            schema_hashes=dict(config.schema_hashes))
        base = build_manifest(root=ROOT, selected_ids=[case.id for case in cases], seeds=(),
            settings=settings, prompts={config.prompt.id: config.prompt.text}, references={},
            identities={'judge': {route.name: identity}},
            role_dependencies={'judge': dict(config.dependency_versions)},
            supplemental_inputs={'config/selected/routes.yaml': args.routes.read_text(encoding='utf-8')},
            pricing_snapshots=prices.to_dict())
        if base.missing_inputs:
            raise ValueError(f'missing captured inputs: {base.missing_inputs}')
        material = dict(base=base.material, calibration=dict(content=content,
            sha256=sha256(content.encode('utf-8')).hexdigest()), cases=[_case_snapshot(case) for case in cases])
        envelope = dict(kind='tutor_calibration', schema_version=1, calibration_id=str(uuid4()),
            started_at=datetime.now(UTC).isoformat(), ended_at=None, status='running',
            material=material, configuration_fingerprint=sha256(canonical_json(material).encode('utf-8')).hexdigest(),
            base_manifest=base.to_dict(), results={case.id: dict(status='manual_review_required'
                if case.assessment_source == 'trace_review' else 'pending') for case in cases})
        args.out.mkdir(parents=True, exist_ok=True)
        directory = args.out / ('calibration-' + envelope['calibration_id'])
        directory.mkdir(mode=0o700)
        _persist(directory, envelope, cases=cases, ledger=ledger)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return _execute(cases=cases, services=services, factory=factory, config=config,
                    directory=directory, envelope=envelope, ledger=ledger)


if __name__ == '__main__':
    raise SystemExit(main())
