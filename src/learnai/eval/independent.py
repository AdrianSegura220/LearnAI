"""Keyless preflight for the reviewed independent-evaluation scenario set."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys

from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.application.ports import TutorDependencies
from learnai.application.providers import default_registry
from learnai.eval.__main__ import _parser, _preflight

ROOT = Path(__file__).resolve().parents[3]
JUDGE_SHA256 = 'a3f4451236fa1b9e434425162d2b8a6996e28e46e800d01cff81297b2d240a4d'
_LIMITATIONS = {
    'independent-05-repeated-root-why': 'Chained equality is unreadable to the verifier although the displayed calculation is valid.',
    'independent-07-ambiguous-negative': 'Coefficient declarations and discriminant substitution are not equivalent equations; this is valid mixed working, not an erroneous transformation.',
    'independent-08-local-sign-confusion': 'Coefficient declarations followed by formula substitution receive a misleading equivalence error.',
    'independent-10-changed-approach': 'Valid formula setup receives a misleading equivalence error after coefficient declarations.',
    'independent-12-local-check-answer-boundary': 'Following one branch of a zero-product equation is not full solution-set equivalence; the checker cannot represent the intended branch.',
}


def preflight_independent() -> dict:
    if sha256((PROMPTS_ROOT / 'rubric_judge/v2.md').read_bytes()).hexdigest() != JUDGE_SHA256:
        raise ValueError('fixed judge prompt changed; explicitly review and version the evaluation baseline')
    args = _parser().parse_args(['run', '--fixtures', str(ROOT / 'eval/independent/scenarios'),
        '--items', str(ROOT / 'eval/independent/items.yaml'), '--no-smoke'])
    registry = default_registry()
    prepared = _preflight(args, registry)
    deps = TutorDependencies(prepared['items'], prepared['cluster'].misconceptions)
    blockers, cases, admission = [], [], []
    for scenario, context in zip(prepared['scenarios'], prepared['contexts'], strict=True):
        checked = context.verification
        diff = checked.step_diff
        if scenario.id in _LIMITATIONS and diff is not None:
            blockers.append(dict(id=scenario.id, reason=_LIMITATIONS[scenario.id]))
        if scenario.id in _LIMITATIONS and not checked.work_notes:
            blockers.append(dict(id=scenario.id, reason='Required contextual verification scope is missing.'))
        cases.append(dict(id=scenario.id, permitted_rung=context.permitted_rung.name,
            answer_checked=checked.answer_checked, steps_checked=checked.steps_checked,
            verdict=checked.verdict.name if checked.verdict else None,
            step_finding='unreadable' if diff and diff.unreadable else 'equivalence' if diff else None,
            diagnosis=checked.diagnosis, work_notes=list(checked.work_notes),
            submissions=context.task_progress.submissions))
        for route_name in ('tutor_dialogue', 'tutor_openai'):
            route = replace(prepared['routes'][route_name], prompt='tutor_math@2')
            factory = registry.get(route.adapter)
            config = factory.resolve_config(route, role='tutor', profiles=prepared['profiles'],
                                            prompts_root=PROMPTS_ROOT)
            request = factory.prepare_tutor(config, context=context, dependencies=deps)
            margin = config.profile.context_input_tokens - request.input_units - request.output_reservation
            admission.append(dict(id=scenario.id, provider=route.adapter,
                                  admitted=request.admitted, remaining_units=margin))
            if not request.admitted or margin < 8192:
                blockers.append(dict(id=scenario.id, reason=f'{route.adapter} tutor payload lacks required headroom'))
    blocked_ids = {entry['id'] for entry in blockers}
    return dict(status='blocked' if blockers else 'ready', scenario_count=len(cases),
        tutor_opportunities=len(prepared['contexts']), ready_count=len(cases) - len(blocked_ids),
        judge_sha256=JUDGE_SHA256, blockers=blockers, cases=cases, admission=admission)


def main() -> int:
    try:
        report = preflight_independent()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 1 if report['blockers'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
