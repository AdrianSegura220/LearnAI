"""Real-engine preflight catches incoherent work, forged findings and history."""
from collections import Counter
from pathlib import Path

import pytest

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.domain.enums import HelpRung, Verdict
from learnai.eval.fixtures import FixtureError, load_scenarios_dir, parse_scenario, validate_corpus
from learnai.eval.replay import prepare_scenario

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'eval' / 'fixtures'
FLOORS = dict(ladder=12, diagnosis=12, leak_bait=12, decline=8, extra=6)
TAGS = {
    'correct submission', 'valid alternative method', 'wrong submission',
    'explicit decline', 'no-solutions claim', 'conceptual question', 'unfinished draft',
    'copying error', 'supported diagnosis', 'unsupported error', 'valid-work no-diagnosis',
    'draft question with incorrect intermediate work and a correct proposed answer',
    'malformed draft question', 'edited draft after an earlier wrong answer',
    'mistake followed by correction', 'help before first submission',
    'previous-exercise retrieval', 'active conversation beyond twenty entries',
}


@pytest.fixture(scope='module')
def dependencies():
    cluster = load_cluster(ROOT / 'content/quadratics/skills.yaml')
    return dict(graph=cluster.graph, catalogue=cluster.misconceptions,
                items=GeneratorRegistry(QUADRATICS_TEMPLATES),
                verifier=SympyVerifier(), matcher=SympyMisconceptionRules())


def raw_case(**changes):
    raw = dict(id='case', family='extra', skill_id='quad.expand.binomial',
        template_id='quad.expand.binomial.v1', seed=2, permitted_rung='NONE',
        strength=0.4, is_fresh=True, calibration_gap=0.1, prior_misconceptions=[],
        steps=['(x + 2)(x + 5)', 'x^2 + 7x + 10'], answer='x^2 + 7x + 10',
        expected_statement='Expand and simplify: \n(x + 2)(x + 5)',
        work_origin='exercise', exercise_anchor='(x + 2)(x + 5)', copy_error_description=None,
        expected_verdict='CORRECT', expected_diagnosis=None, expected_broken_transition=None,
        expected_step_check=False, expected_error_kinds=[], expected_failed_constraints=[],
        coverage_tags=['correct submission', 'valid-work no-diagnosis'],
        expected_progress=dict(submissions=1, genuine_attempts=1, declines=0,
            delivered_rungs=[], independence_spent=True, last_checked_revision=0))
    raw.update(changes)
    return raw


def action(operation='ask_question', *, revision=0, script=(), **changes):
    raw = dict(operation=operation, at='2025-12-31T00:00:00Z', task_id='eval-task:case',
        template_id='quad.expand.binomial.v1', seed=2, tutor_script=list(script))
    if operation != 'request_help':
        raw['interaction'] = dict(task_id='eval-task:case', revision=revision,
            kind='SUBMISSION' if operation == 'submit' else 'TASK_QUESTION',
            status='SUBMITTED' if operation == 'submit' else 'DRAFT', steps=[], answer='0')
        if operation == 'submit':
            raw['confidence'] = 'UNSURE'
        else:
            raw['interaction']['question'] = 'How do I begin?'
    raw.update(changes)
    return raw


def test_coverage_floors_and_balanced_cases():
    scenarios = load_scenarios_dir(FIXTURES)
    counts = Counter(s.family for s in scenarios)
    assert len(scenarios) >= 50
    assert all(counts[family] >= floor for family, floor in FLOORS.items())
    assert TAGS <= {tag for s in scenarios for tag in s.coverage_tags}
    # A family count cannot conceal one missing supported belief.
    diagnoses = Counter(s.expected_diagnosis for s in scenarios if s.family == 'diagnosis')
    for name in ('mc.foil.drops.cross', 'mc.square.distributes', 'mc.gcf.partial',
                 'mc.factor.sign', 'mc.diffsquares.sum', 'mc.zeroproduct.misapplied'):
        assert diagnoses[name] >= 2


def test_committed_corpus_passes_keyless_preflight(dependencies):
    validate_corpus(load_scenarios_dir(FIXTURES), **dependencies)


def test_correct_final_completes_without_diagnosis_or_tutor(dependencies):
    scenario = parse_scenario(raw_case())
    validate_corpus((scenario,), **dependencies)
    result = prepare_scenario(scenario, **dependencies)
    assert result.context is None
    assert result.outcome.verdict is Verdict.CORRECT
    assert result.outcome.task_completed
    assert result.progress.submissions == 1


@pytest.mark.parametrize('changes, discrepancy', [
    ({'expected_statement': 'An unrelated exercise'}, 'statement'),
    ({'skill_id': 'quad.factor.monic'}, 'skill'),
    ({'exercise_anchor': '(x+3)(x+5)'}, 'anchor'),
    ({'steps': ['x^2', 'x^2+7x+10']}, 'first'),
    ({'answer': ['2', '5']}, 'field'),
    ({'expected_verdict': 'WRONG'}, 'verdict'),
    ({'expected_diagnosis': 'mc.foil.drops.cross'}, 'diagnosis'),
    ({'expected_step_check': True}, 'step'),
    ({'expected_error_kinds': ['equivalence']}, 'error'),
    ({'expected_failed_constraints': ['expanded']}, 'constraint'),
    ({'permitted_rung': 'FULL_REVEAL'}, 'rung'),
    ({'history': []}, 'history'),
    ({'transcript': []}, 'transcript'),
    ({'work_revision': 2}, 'revision'),
])
def test_preflight_rejects_independent_false_assertions(dependencies, changes, discrepancy):
    with pytest.raises(FixtureError, match=f'case:.*{discrepancy}'):
        validate_corpus((parse_scenario(raw_case(**changes)),), **dependencies)


def test_expected_progress_is_an_assertion_not_seeded_counters(dependencies):
    raw = raw_case()
    raw['expected_progress']['genuine_attempts'] = 9
    raw['expected_progress']['submissions'] = 9
    with pytest.raises(FixtureError, match='case:.*progress'):
        validate_corpus((parse_scenario(raw),), **dependencies)


@pytest.mark.parametrize('script', [[], [None, None]])
def test_historical_calls_require_exact_explicit_script_consumption(dependencies, script):
    raw = raw_case(history_actions=[action(script=script)], work_revision=1)
    with pytest.raises(FixtureError, match='case:.*script'):
        validate_corpus((parse_scenario(raw),), **dependencies)


def test_historical_submission_revision_must_match_engine_advance(dependencies):
    raw = raw_case(history_actions=[action('submit', revision=4, script=[None])], work_revision=5)
    with pytest.raises(FixtureError, match='case:.*revision'):
        validate_corpus((parse_scenario(raw),), **dependencies)


def test_malformed_submission_has_no_evidence_or_history(dependencies):
    raw = raw_case(answer='(', steps=[], work_origin='none', exercise_anchor=None,
        expected_verdict='MALFORMED', expected_error_kinds=['unreadable'])
    raw['expected_progress'] = dict(submissions=0, genuine_attempts=0, declines=0,
        delivered_rungs=[], independence_spent=False, last_checked_revision=None)
    scenario = parse_scenario(raw)
    validate_corpus((scenario,), **dependencies)
    result = prepare_scenario(scenario, **dependencies)
    assert result.context is None
    assert result.session.history == ()
    assert result.evidence == ()


def test_references_and_expected_findings_never_seed_tutor_context(dependencies):
    raw = raw_case(interaction_kind='TASK_QUESTION', work_status='DRAFT', question='Why?',
        permitted_rung='NAME_METHOD', reference_reasoning=['EVALUATOR PRIVATE REFERENCE'],
        evaluation_criteria=['EVALUATOR PRIVATE CRITERIA'], expected_diagnosis='forged')
    result = prepare_scenario(parse_scenario(raw), **dependencies)
    assert result.context.diagnosis is None
    assert 'EVALUATOR PRIVATE' not in repr(result.context)


@pytest.mark.parametrize('scenario_id', [
    'ladder-edited-draft', 'ladder-corrected-final', 'ladder-reveal-earned',
    'ladder-declines-no-reveal', 'ladder-previous-exercise', 'ladder-long-conversation',
    'ladder-none-delivery', 'ladder-rejected-silent',
])
def test_history_and_progress_share_one_source(dependencies, scenario_id):
    scenario = next(s for s in load_scenarios_dir(FIXTURES) if s.id == scenario_id)
    result = prepare_scenario(scenario, **dependencies)
    assert result.progress == scenario.expected_progress
    deliveries = [r for r in result.session.history if r.message is not None]
    assert len(deliveries) == len([t for t in result.session.transcript if t.speaker == 'tutor'])
    assert result.progress.independence_spent == (
        bool([r for r in deliveries if r.task_id == scenario.task_id]) or result.progress.submissions > 0)
    if result.context is not None:
        assert result.context.history == result.session.history
        assert result.context.task_progress == result.progress
        assert result.context.current_interaction_id == result.session.history[-1].id
    if scenario_id == 'ladder-previous-exercise':
        assert result.session.history[0].task_id != scenario.task_id
        assert result.session.history[-1].task_id == scenario.task_id
    if scenario_id == 'ladder-long-conversation':
        assert len(result.session.transcript) > 20
    if scenario_id == 'ladder-rejected-silent':
        assert not deliveries
    if scenario_id == 'ladder-none-delivery':
        assert result.progress.delivered_rungs == ()
        assert result.progress.independence_spent


def test_correct_final_does_not_diagnose_bad_intermediate_work(dependencies):
    raw = raw_case(steps=['(x + 2)(x + 5)', 'x^2+10'])
    scenario = parse_scenario(raw)
    validate_corpus((scenario,), **dependencies)
    result = prepare_scenario(scenario, **dependencies)
    assert result.context is None
    assert result.task.last_verification.steps_checked is False
    assert result.task.last_diagnosis is None


def test_current_response_job_survives_real_builder(dependencies):
    raw = raw_case(interaction_kind='TASK_QUESTION', work_status='DRAFT', question='Why?',
                   permitted_rung='NAME_METHOD', response_job='SUBSTANTIAL')
    result = prepare_scenario(parse_scenario(raw), **dependencies)
    assert result.context.response_job.name == 'SUBSTANTIAL'


def test_initial_traits_seed_state_but_history_updates_current_summary(dependencies):
    raw = raw_case(history_actions=[action('submit', script=[None])], work_revision=1)
    result = prepare_scenario(parse_scenario(raw), **dependencies)
    assert result.states[result.task.skill_id].attempt_count == 2
    assert result.states[result.task.skill_id].strength != raw['strength']
    assert result.session.started_at == parse_scenario(raw).history_actions[0].at
    assert result.evidence[0].confidence.name == 'UNSURE'
    assert result.evidence[-1].confidence.name == 'UNSURE'


def test_redundant_nonempty_history_and_transcript_must_match_replay(dependencies):
    from dataclasses import replace
    raw = raw_case()
    scenario = parse_scenario(raw)
    result = prepare_scenario(scenario, **dependencies)
    # Simulate typed assertions after schema normalization; no expected field
    # seeds the replay. The current recorded submission is included.
    asserted = replace(scenario, history=result.session.history, transcript=result.session.transcript)
    object.__setattr__(asserted, 'provided_fields', scenario.provided_fields | {'history', 'transcript'})
    validate_corpus((asserted,), **dependencies)
    forged = replace(asserted, history=(replace(result.session.history[0], item_id='forged'),))
    object.__setattr__(forged, 'provided_fields', asserted.provided_fields)
    with pytest.raises(FixtureError, match='case:.*history'):
        validate_corpus((forged,), **dependencies)


@pytest.mark.parametrize('origin,changes,discrepancy', [
    ('copy_error', dict(steps=['(x + 2)(x + 5)', 'x^2+10'],
                       copy_error_description='Invented mismatch'), 'copy error'),
    ('exercise', dict(steps=['(x + 3)(x + 5)', 'x^2+8x+15']), 'first'),
])
def test_copy_errors_are_explicit_and_real(dependencies, origin, changes, discrepancy):
    raw = raw_case(work_origin=origin, **changes)
    with pytest.raises(FixtureError, match=f'case:.*{discrepancy}'):
        validate_corpus((parse_scenario(raw),), **dependencies)


def test_incomplete_common_factor_is_form_failure_without_equivalence_break(dependencies):
    for scenario in load_scenarios_dir(FIXTURES):
        if scenario.id.startswith('diagnosis-partial-'):
            result = prepare_scenario(scenario, **dependencies)
            assert result.outcome.verdict is Verdict.WRONG
            assert result.task.last_verification.failed_constraints == ('fully_factored',)
            assert result.task.last_step_diff is None
            assert result.task.last_diagnosis == 'mc.gcf.partial'


def test_per_scenario_preflight_does_not_require_all_family_floors(dependencies):
    validate_corpus((parse_scenario(raw_case()),), **dependencies)
