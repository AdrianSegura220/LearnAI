# tests/content/test_generator_contracts.py
import json
import pathlib
from collections import Counter

import pytest
import sympy as sp

from learnai.adapters.cas.parse import parse_math
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.domain.enums import AnswerKind, Verdict
from learnai.domain.ids import SkillId, TemplateId
from learnai.domain.items import Formula, Item, Submission

REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)
VERIFIER = SympyVerifier()
X, Y = sp.symbols("x y")

LIGHT_SEEDS = 300
DEEP_SEEDS = 50

GOLDEN = pathlib.Path(__file__).parent / "golden_items.json"
GOLDEN_SEEDS = 5


def ids(spec):
    return str(spec.id)


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_generation_is_deterministic_and_well_formed(spec):
    for seed in range(LIGHT_SEEDS):
        item = REGISTRY.instantiate(spec.id, seed)
        assert item == REGISTRY.instantiate(spec.id, seed), "generator is not deterministic"
        assert item.statement
        assert item.answer_spec.expression.strip()
        assert item.id == f"{spec.id}#{seed}"
        assert item.skill_id == spec.skill_id


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_the_answer_key_is_correct_by_its_own_verifier(spec):
    for seed in range(DEEP_SEEDS):
        item = REGISTRY.instantiate(spec.id, seed)
        result = VERIFIER.check_answer(VERIFIER.key_submission(item.answer_spec), item.answer_spec)
        assert result.verdict is Verdict.CORRECT, (spec.id, seed, item, result)


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_worked_steps_never_contain_a_broken_transition(spec):
    for seed in range(DEEP_SEEDS):
        item = REGISTRY.instantiate(spec.id, seed)
        assert VERIFIER.diff_steps(item.worked_steps) is None, (spec.id, seed)


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_typing_the_question_back_is_never_accepted(spec):
    """Equivalence alone accepts a restatement — (x+1)(x+2) is equal to its own
    expansion — so an item whose prompt is an expression must carry a form
    constraint that rejects the prompt itself. This subsumes checking that the
    prompt is not already in its answer's form."""
    for seed in range(DEEP_SEEDS):
        problem = REGISTRY.instantiate_raw(spec.id, seed)
        if problem.prompt_expression is None:
            continue
        item = REGISTRY.instantiate(spec.id, seed)
        result = VERIFIER.check_answer(Submission.of(problem.prompt_expression), item.answer_spec)
        assert result.verdict is not Verdict.CORRECT, (spec.id, seed, problem.prompt_expression)


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_an_item_that_asks_for_a_value_labels_its_field(spec):
    """With no expression to transform, the student computes a value, and the
    field must say which ("x =", "Width (cm):"). A transformation item's field
    holds the expression itself and needs no label."""
    for seed in range(DEEP_SEEDS):
        problem = REGISTRY.instantiate_raw(spec.id, seed)
        item = REGISTRY.instantiate(spec.id, seed)
        assert (item.answer_spec.label is not None) == (problem.prompt_expression is None), (spec.id, seed)


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_statements_show_maths_only_as_formulas_a_student_could_type(spec):
    """Prose never carries notation; every Formula reads back through the
    student's own parser and names only the item's variables, so a stray "zoo"
    or "nan" from SymPy fails here; and a rewriting item shows its prompt."""
    for seed in range(DEEP_SEEDS):
        problem = REGISTRY.instantiate_raw(spec.id, seed)
        for block in problem.statement:
            if isinstance(block, Formula):
                parsed = parse_math(block.source, allow_equation=True)
                assert parsed.free_symbols <= {X, Y}, (spec.id, seed, block.source)
            else:
                assert not set(block.text) & set("^*="), (spec.id, seed, block.text)
        if problem.prompt_expression is not None:
            assert Formula(problem.prompt_expression) in problem.statement, (spec.id, seed)


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_no_single_answer_is_right_for_most_items(spec):
    """A student who types the same thing every time must not be right by default."""
    keys = Counter(REGISTRY.instantiate_raw(spec.id, seed).answer for seed in range(LIGHT_SEEDS))
    answer, count = keys.most_common(1)[0]
    assert count <= LIGHT_SEEDS / 2, f"{spec.id}: {answer!r} is right for {count} of {LIGHT_SEEDS} items"


@pytest.mark.parametrize(
    "template_id", ["quad.factor.monic.v1", "quad.factor.diffsquares.v1", "quad.factor.nonmonic.v1"]
)
def test_a_factoring_item_exercises_no_other_factoring_skill(template_id):
    """A common factor to take out first belongs to quad.factor.common, and a
    monic prompt with no x term is a difference of squares: either way a miss
    would be recorded against the wrong skill."""
    for seed in range(DEEP_SEEDS):
        prompt = parse_math(REGISTRY.instantiate_raw(TemplateId(template_id), seed).prompt_expression)
        assert sp.factor_list(prompt)[0] == 1, (template_id, seed, prompt)
        if template_id == "quad.factor.monic.v1":
            assert sp.Poly(prompt, X).coeff_monomial(X) != 0, (seed, prompt)


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_no_degenerate_coefficients(spec):
    for seed in range(DEEP_SEEDS):
        problem = REGISTRY.instantiate_raw(spec.id, seed)
        if problem.kind is not AnswerKind.SINGLE_VALUE:
            continue
        for number in parse_math(problem.answer).atoms(sp.Integer):
            assert abs(int(number)) <= 400, f"{spec.id} seed {seed} produced a wild coefficient"


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_every_emitted_constraint_is_supported_by_the_verifier(spec):
    """The load-time gate that replaces the old enum's compile-time safety."""
    for seed in range(DEEP_SEEDS):
        problem = REGISTRY.instantiate_raw(spec.id, seed)
        unknown = set(problem.form_constraints) - VERIFIER.supported_constraints
        assert not unknown, f"{spec.id} emits constraints the verifier cannot judge: {unknown}"


def _snapshot(item: Item) -> dict[str, object]:
    return {
        "statement": [repr(block) for block in item.statement],
        "answer": item.answer_spec.expression,
        "form_constraints": list(item.answer_spec.form_constraints),
        "label": item.answer_spec.label,
        "worked_steps": list(item.worked_steps),
    }


def test_an_item_id_names_the_same_problem_forever():
    """The determinism contract across upgrades, not just within one run. An
    evidence event names its item as template#seed, so a Python or SymPy
    upgrade that changed what a seed generates would silently rewrite a
    student's history. Change a generator by registering a new version
    (".v2"), never by editing a recorded item. New templates are recorded on
    their first run: review the file, commit it, and rerun."""
    current = {
        str(item.id): _snapshot(item)
        for spec in QUADRATICS_TEMPLATES
        for item in (REGISTRY.instantiate(spec.id, seed) for seed in range(GOLDEN_SEEDS))
    }
    recorded = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
    changed = sorted(i for i in recorded if current.get(i) != recorded[i])
    assert not changed, f"these ids no longer generate their recorded problem: {changed}"
    new = {i: s for i, s in current.items() if i not in recorded}
    if new:
        GOLDEN.write_text(json.dumps(recorded | new, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        pytest.fail(f"recorded {len(new)} new items in {GOLDEN.name}: review it, commit it, and rerun")


def test_next_item_picks_the_closest_difficulty_band():
    item = REGISTRY.next_item(SkillId("quad.factor.monic"), target_difficulty=0.0, seed=7)
    assert item.skill_id == SkillId("quad.factor.monic")
    assert item.difficulty == 0.0


def test_unknown_skill_raises():
    with pytest.raises(KeyError):
        REGISTRY.next_item(SkillId("nope"), target_difficulty=0.0, seed=1)


def test_every_skill_in_the_cluster_has_a_template():
    from learnai.adapters.content.loader import load_cluster

    cluster = load_cluster(
        pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
    )
    covered = {spec.skill_id for spec in QUADRATICS_TEMPLATES}
    assert set(cluster.graph.skills) == covered
