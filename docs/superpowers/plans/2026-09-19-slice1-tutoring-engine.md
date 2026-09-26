# Slice 1 — Tutoring Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the headless tutoring engine for the quadratics cluster — skill graph, CAS-verified generators, mastery model, Practice mode contract, LeakGuard, and session orchestration — driven end to end by a fake tutor and a fake clock.

**Architecture:** Hexagonal. A pure-Python domain core with no I/O, no framework imports, and no LLM calls holds every consequential decision (sequencing, verification routing, mastery, help policy). Adapters behind ports supply SymPy verification, generator content, a scripted tutor, and an in-memory evidence log. The engine is exercised entirely through tests: property tests over the domain, contract tests over generators, and simulated students against a fake clock.

**Tech Stack:** Python 3.12+, SymPy, pytest, Hypothesis, PyYAML. No web framework, no database, no Anthropic SDK in this plan.

**Spec:** `docs/superpowers/specs/2026-09-14-ai-tutoring-platform-design.md`

## Scope

**In this plan (Plan 1 — the engine):** spec deliverables 1–8 and 11 of §13, minus persistence. Domain core, quadratics content, SymPy verifier, mastery and calibration, Practice contract, LeakGuard, turn validation, `FakeTutor`, session planner, in-memory append-only evidence log with projection rebuild, and the simulated-student suite.

**Deferred to Plan 2 (the application):** PostgreSQL persistence and migrations, FastAPI endpoints, the `AnthropicTutor` adapter with model routing and prompt caching, the graded tutor eval set, and the React session UI. Those are spec deliverables 9 and 10 plus the durable half of 8.

**Why here:** the cut is the hexagonal boundary. Plan 1 finishes with a tutoring engine whose every pedagogical guarantee is proven by test, and Plan 2 attaches I/O to it. Nothing in Plan 2 can change a Plan 1 decision.

## Global Constraints

Copied verbatim from the spec; every task's requirements implicitly include these.

- **P1 — The engine decides; the model speaks.** Every consequential decision lives in deterministic code.
- **P2 — The model has no write path to mastery.** No tool, port, or adapter reachable by a tutor may mutate `SkillState`. Enforced by absence, and by a property test.
- **P3 — Verification before language.** A deterministic checker runs first; the model receives its output.
- **P4 — Assistance is free; credit is not.** Help costs nothing except mastery credit.
- **P5 — Performance is not learning.** Evidence gathered on a skill taught in the same session is weighted near zero.
- **P6 — Evidence is append-only.** Attempts and help events are immutable; `SkillState` is a projection rebuildable from the log.
- Domain core (`src/learnai/domain/`) imports only the standard library and `typing`. **No SymPy, no YAML, no I/O.** Enforced by a test.
- All time is UTC, `datetime` aware, and reaches the domain only through the `Clock` port. Elapsed time is float days.
- Python 3.12+. Strict typing: every public function annotated.

---

## File Structure

```
pyproject.toml
src/learnai/
  domain/                      # pure: stdlib only
    parameters.py              # MasteryParameters value object + defaults
    enums.py                   # closed, subject-neutral vocabularies
    ids.py                     # NewType aliases: ids, plus opaque tokens
    skills.py                  # Skill, Concept, Misconception, PrereqEdge
    graph.py                   # SkillGraph: traversal, frontier, cycle detection
    items.py                   # Item, AnswerSpec, Provenance, StepDiff
    ports.py                   # Protocols: Verifier, ItemSource, Tutor, Clock, EvidenceLog
    mastery.py                 # SkillState, strength, stability, derived states
    evidence.py                # evidence classification and weights
    calibration.py             # confidence mapping, calibration gap
    propagation.py             # prerequisite propagation
    contracts.py               # ModeContract, PRACTICE
    help.py                    # hint ladder state machine
    misconceptions.py          # rule registry, step-diff matching
    leakguard.py               # answer-leak detection over tutor drafts
    turn.py                    # TurnContext, TutorTurn, validation pipeline
    session.py                 # Session, Task, state machine
    planner.py                 # frontier selection, difficulty targeting
    engine.py                  # PracticeEngine — orchestrates one task's lifecycle
  adapters/
    clock.py                   # SystemClock, FakeClock
    cas/vocabulary.py          # this adapter's kind, answer kinds, form tokens
    cas/parse.py               # safe parsing of student/author input
    cas/sympy_verifier.py      # Verifier implementation
    content/loader.py          # YAML -> SkillGraph
    content/registry.py        # GeneratorRegistry -> ItemSource
    content/generators/quadratics.py
    tutor/fake_tutor.py        # scripted Tutor
    persistence/in_memory.py   # append-only log + projection
content/quadratics/skills.yaml
tests/
  domain/                      # one module per domain module
  adapters/
  content/test_generator_contracts.py
  simulation/test_simulated_students.py
  test_domain_purity.py
```

Split by responsibility, not by layer. `mastery.py` holds the two update rules and the derived predicates and nothing else; `evidence.py` decides what class an attempt is and never computes an update.

---

### Task 1: Project scaffold and skill graph

**Files:**
- Create: `pyproject.toml`, `src/learnai/__init__.py`, `src/learnai/domain/__init__.py`
- Create: `src/learnai/domain/ids.py`, `src/learnai/domain/enums.py`, `src/learnai/domain/skills.py`, `src/learnai/domain/graph.py`
- Test: `tests/domain/test_graph.py`, `tests/test_domain_purity.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SkillId`, `MisconceptionId`, `ConceptId`, `ItemId`, `StudentId`, `SessionId`, `TaskId` (all `NewType[str]`) plus the opaque token `VerificationKind`; `PrereqStrength`; `Skill`, `Concept`, `Misconception`, `PrereqEdge` (frozen dataclasses; concepts and misconceptions are subject-scoped and shared, linked many-to-many from the skill side); `SkillGraph` with `hard_prereqs(SkillId) -> frozenset[SkillId]`, `soft_prereqs(SkillId) -> frozenset[SkillId]`, `dependents(SkillId) -> frozenset[SkillId]`, `frontier(learned: set[SkillId]) -> frozenset[SkillId]`, `topological_order() -> tuple[SkillId, ...]`, and classmethod `build(skills, edges) -> SkillGraph` which raises `CycleError` on a cycle in hard edges. `CycleError.cycle` holds one offending path, closed and in prerequisite-first order — `(a, b, c, a)` — so an author can see which edges to fix.

- [ ] **Step 1: Create the project scaffold**

```toml
# pyproject.toml
[project]
name = "learnai"
version = "0.1.0"
requires-python = ">=3.12"
# SymPy is pinned: grading depends on its evaluation rules, which change between
# releases. Upgrade deliberately, and let the generator contract tests catch drift.
dependencies = ["sympy~=1.14.0", "pyyaml>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "hypothesis>=6.100", "pytest-cov>=5.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/learnai"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

```bash
mkdir -p src/learnai/domain src/learnai/adapters tests/domain
touch src/learnai/__init__.py src/learnai/domain/__init__.py src/learnai/adapters/__init__.py
touch tests/__init__.py tests/domain/__init__.py
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 2: Write the failing graph test**

```python
# tests/domain/test_graph.py
import pytest

from learnai.domain.enums import PrereqStrength
from learnai.domain.graph import CycleError, SkillGraph
from learnai.domain.ids import SkillId, VerificationKind
from learnai.domain.skills import PrereqEdge, Skill


def skill(sid: str) -> Skill:
    return Skill(
        id=SkillId(sid),
        subject_id="math",
        name=sid,
        can_do_statement=f"can do {sid}",
        verification_kind=VerificationKind("cas_symbolic"),
        concept_ids=(),
        misconception_ids=(),
    )


def hard(a: str, b: str) -> PrereqEdge:
    return PrereqEdge(SkillId(a), SkillId(b), PrereqStrength.HARD)


def test_hard_prereqs_are_direct_only():
    g = SkillGraph.build([skill("a"), skill("b"), skill("c")], [hard("a", "b"), hard("b", "c")])
    assert g.hard_prereqs(SkillId("c")) == frozenset({SkillId("b")})
    assert g.hard_prereqs(SkillId("a")) == frozenset()


def test_dependents_are_direct_only():
    g = SkillGraph.build([skill("a"), skill("b"), skill("c")], [hard("a", "b"), hard("a", "c")])
    assert g.dependents(SkillId("a")) == frozenset({SkillId("b"), SkillId("c")})


def test_frontier_is_unlearned_skills_whose_hard_prereqs_are_learned():
    g = SkillGraph.build([skill("a"), skill("b"), skill("c")], [hard("a", "b"), hard("b", "c")])
    assert g.frontier(learned=set()) == frozenset({SkillId("a")})
    assert g.frontier(learned={SkillId("a")}) == frozenset({SkillId("b")})
    assert g.frontier(learned={SkillId("a"), SkillId("b")}) == frozenset({SkillId("c")})
    assert g.frontier(learned={SkillId("a"), SkillId("b"), SkillId("c")}) == frozenset()


def test_soft_edges_do_not_gate_the_frontier():
    edges = [PrereqEdge(SkillId("a"), SkillId("b"), PrereqStrength.SOFT)]
    g = SkillGraph.build([skill("a"), skill("b")], edges)
    assert SkillId("b") in g.frontier(learned=set())
    assert g.soft_prereqs(SkillId("b")) == frozenset({SkillId("a")})


def test_cycle_in_hard_edges_is_rejected():
    with pytest.raises(CycleError):
        SkillGraph.build([skill("a"), skill("b")], [hard("a", "b"), hard("b", "a")])


def test_a_cycle_error_names_the_path_and_nothing_downstream():
    """d depends on the cycle but is not part of it, so it must not be blamed."""
    edges = [hard("a", "b"), hard("b", "c"), hard("c", "a"), hard("c", "d")]
    with pytest.raises(CycleError) as err:
        SkillGraph.build([skill(s) for s in "abcd"], edges)
    assert err.value.cycle == (SkillId("a"), SkillId("b"), SkillId("c"), SkillId("a"))
    assert "a -> b -> c -> a" in str(err.value)


def test_edge_referencing_unknown_skill_is_rejected():
    with pytest.raises(KeyError):
        SkillGraph.build([skill("a")], [hard("a", "ghost")])
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.domain.graph'`

- [ ] **Step 4: Write the ids and enums**

```python
# src/learnai/domain/ids.py
from typing import NewType

VerificationKind = NewType("VerificationKind", str)
"""Selects which Verifier adapter judges a skill, e.g. "cas_symbolic".

Opaque, like FormConstraint: enumerating adapter kinds here would mean every
new subject edits the core, which is exactly what this seam exists to prevent.
Each adapter declares its own kind; the engine resolves skill -> verifier
through a registry. See spec §6.1.
"""

SkillId = NewType("SkillId", str)
ConceptId = NewType("ConceptId", str)
MisconceptionId = NewType("MisconceptionId", str)
ItemId = NewType("ItemId", str)
TemplateId = NewType("TemplateId", str)
StudentId = NewType("StudentId", str)
SessionId = NewType("SessionId", str)
TaskId = NewType("TaskId", str)
CourseId = NewType("CourseId", str)
```

```python
# src/learnai/domain/enums.py
from enum import Enum, IntEnum


class PrereqStrength(Enum):
    HARD = "hard"
    SOFT = "soft"


class ConceptKind(Enum):
    """Subject-neutral taxonomy of declarative knowledge.

    A history CLAIM is a cause, a maths CLAIM is a theorem; a chemistry RULE is
    a law, a maths RULE is a formula. Naming the general shape keeps the core
    usable for subjects that have no theorems.
    """

    DEFINITION = "definition"
    CLAIM = "claim"
    RULE = "rule"
    PROCEDURE = "procedure"
    FACT = "fact"


class AnswerKind(Enum):
    """How an answer is compared. Subject-neutral by construction.

    RELATION covers a maths equation and a balanced chemical equation alike:
    both are judged by what they assert, not by their surface form.
    """

    SINGLE_VALUE = "single_value"
    RELATION = "relation"
    VALUE_SET = "value_set"
    """An unordered collection, compared as a set."""


class HelpRung(IntEnum):
    """Ordered: comparison operators express the ladder."""

    NONE = 0
    NUDGE = 1
    NEXT_STEP = 2
    NAME_METHOD = 3
    FULL_REVEAL = 4


class EvidenceClass(Enum):
    UNASSISTED_COLD = "unassisted_cold"
    TIMED_EXAM = "timed_exam"
    POST_INSTRUCTION = "post_instruction"
    ASSISTED = "assisted"


class Confidence(IntEnum):
    NO_IDEA = 0
    """Declined to answer. Distinct from guessing, which submits something."""

    GUESSING = 1
    UNSURE = 2
    FAIRLY_SURE = 3
    CERTAIN = 4


class VettingLevel(IntEnum):
    LLM_ONLY = 0
    HUMAN_REVIEWED = 1
    MACHINE_VERIFIED = 2
    """The answer key is derived by code, not written by a human or a model."""


class ProvenanceKind(Enum):
    """Where an item came from.

    Closed on purpose: each new source changes how far an answer key can be
    trusted, so adding one should be a decision rather than a new string. The
    spec anticipates an LLM_BATCH member; it arrives with batch generation.
    """

    GENERATED = "generated"
    """From a template and a seed; the pair reproduces the item exactly."""

    AUTHORED = "authored"


class InterventionTiming(Enum):
    LET_RUN = "let_run"
    IMMEDIATE = "immediate"
    BY_ERROR_TYPE = "by_error_type"
    NEVER = "never"


class RevealPrice(Enum):
    NONE = "none"
    SELF_EXPLAIN = "self_explain"
    FRESH_VARIANT_COLD = "fresh_variant_cold"


class Verdict(Enum):
    CORRECT = "correct"
    WRONG = "wrong"
    MALFORMED = "malformed"
    NO_ANSWER = "no_answer"
    """The student declined. Same competence signal as wrong, different pedagogy."""
```

- [ ] **Step 5: Write the skill types**

```python
# src/learnai/domain/skills.py
from dataclasses import dataclass

from learnai.domain.enums import ConceptKind, PrereqStrength
from learnai.domain.ids import ConceptId, MisconceptionId, SkillId, VerificationKind


@dataclass(frozen=True, slots=True)
class Concept:
    """Declarative knowledge, shared by every skill that needs it.

    Deliberately not owned by one skill. The Nyquist-Shannon theorem serves
    sampling-rate calculation, aliasing identification, reconstruction and
    filter choice; giving it a single owner would mean duplicating it per skill,
    and duplicating a concept duplicates its *memory state* — the student would
    rehearse one theorem on four independent schedules and be told they had
    forgotten something they demonstrably know. `Skill.concept_ids` carries the
    relationship, many-to-many.
    """

    id: ConceptId
    subject_id: str
    kind: ConceptKind
    prompt: str
    answer: str
    introduced_by: SkillId | None = None
    """Where a Learn session should first teach it. An ordering hint, not
    ownership. Unused until Slice 3."""


@dataclass(frozen=True, slots=True)
class Misconception:
    """A wrong belief, shared by every skill it afflicts.

    Same reasoning as Concept: `(a+b)^2 -> a^2+b^2` shows up in expanding a
    square and in completing the square. One belief, one catalogue entry, one
    rule registration, and one entry in the student's active-misconception set.
    """

    id: MisconceptionId
    subject_id: str
    name: str
    description: str
    signature: str
    """Key into the rewrite-rule registry in domain.misconceptions."""


@dataclass(frozen=True, slots=True)
class Skill:
    id: SkillId
    subject_id: str
    name: str
    can_do_statement: str
    verification_kind: VerificationKind
    concept_ids: tuple[ConceptId, ...]
    misconception_ids: tuple[MisconceptionId, ...]


@dataclass(frozen=True, slots=True)
class PrereqEdge:
    from_skill: SkillId
    to_skill: SkillId
    strength: PrereqStrength
```

- [ ] **Step 6: Write the graph**

```python
# src/learnai/domain/graph.py
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from learnai.domain.enums import PrereqStrength
from learnai.domain.ids import SkillId
from learnai.domain.skills import PrereqEdge, Skill


class CycleError(ValueError):
    """Raised when hard prerequisite edges contain a cycle.

    Carries one offending path. The graph never breaks a cycle itself: which
    dependency is false — or whether a shared prerequisite is missing — is a
    pedagogical judgement it has no information to make. See spec §6.1, D11.
    """

    def __init__(self, cycle: tuple[SkillId, ...]) -> None:
        self.cycle = cycle
        super().__init__("hard prerequisites form a cycle: " + " -> ".join(cycle))


@dataclass(frozen=True, slots=True)
class SkillGraph:
    skills: dict[SkillId, Skill]
    _hard_in: dict[SkillId, frozenset[SkillId]]
    _soft_in: dict[SkillId, frozenset[SkillId]]
    _out: dict[SkillId, frozenset[SkillId]]

    @classmethod
    def build(cls, skills: Iterable[Skill], edges: Iterable[PrereqEdge]) -> "SkillGraph":
        by_id = {s.id: s for s in skills}
        hard_in: dict[SkillId, set[SkillId]] = defaultdict(set)
        soft_in: dict[SkillId, set[SkillId]] = defaultdict(set)
        out: dict[SkillId, set[SkillId]] = defaultdict(set)

        for e in edges:
            for sid in (e.from_skill, e.to_skill):
                if sid not in by_id:
                    raise KeyError(f"edge references unknown skill: {sid}")
            if e.strength is PrereqStrength.HARD:
                hard_in[e.to_skill].add(e.from_skill)
            else:
                soft_in[e.to_skill].add(e.from_skill)
            out[e.from_skill].add(e.to_skill)

        graph = cls(
            skills=by_id,
            _hard_in={k: frozenset(v) for k, v in hard_in.items()},
            _soft_in={k: frozenset(v) for k, v in soft_in.items()},
            _out={k: frozenset(v) for k, v in out.items()},
        )
        graph.topological_order()  # raises CycleError
        return graph

    def hard_prereqs(self, skill_id: SkillId) -> frozenset[SkillId]:
        return self._hard_in.get(skill_id, frozenset())

    def soft_prereqs(self, skill_id: SkillId) -> frozenset[SkillId]:
        return self._soft_in.get(skill_id, frozenset())

    def dependents(self, skill_id: SkillId) -> frozenset[SkillId]:
        return self._out.get(skill_id, frozenset())

    def frontier(self, learned: set[SkillId]) -> frozenset[SkillId]:
        return frozenset(
            sid
            for sid in self.skills
            if sid not in learned and self.hard_prereqs(sid) <= learned
        )

    def topological_order(self) -> tuple[SkillId, ...]:
        indegree = {sid: len(self.hard_prereqs(sid)) for sid in self.skills}
        ready = sorted(sid for sid, d in indegree.items() if d == 0)
        order: list[SkillId] = []
        while ready:
            sid = ready.pop(0)
            order.append(sid)
            for dep in sorted(self.dependents(sid)):
                if sid in self.hard_prereqs(dep):
                    indegree[dep] -= 1
                    if indegree[dep] == 0:
                        ready.append(dep)
            ready.sort()
        if len(order) != len(self.skills):
            raise CycleError(self._find_cycle(set(self.skills) - set(order)))
        return tuple(order)

    def _find_cycle(self, stuck: set[SkillId]) -> tuple[SkillId, ...]:
        """Walk backwards through hard prereqs, within the unordered skills, until one repeats.

        Every stuck skill has at least one stuck hard prereq — otherwise it would
        have been ordered — so the walk cannot dead-end and must close a loop.
        Skills merely downstream of the cycle are stuck too, but the walk leaves
        them behind. Smallest id at each choice, so the reported path is stable.
        """
        path: list[SkillId] = []
        position: dict[SkillId, int] = {}
        current = min(stuck)
        while current not in position:
            position[current] = len(path)
            path.append(current)
            current = min(self.hard_prereqs(current) & stuck)
        loop = path[position[current]:] + [current]
        return tuple(reversed(loop))  # prerequisite first, the way edges read
```

- [ ] **Step 7: Run the graph tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_graph.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 8: Write the domain purity test**

This test is the mechanical enforcement of the global constraint that the domain core has no I/O and no third-party dependencies.

```python
# tests/test_domain_purity.py
import ast
import pathlib

ALLOWED_TOP_LEVEL = {
    "learnai",
    "collections", "dataclasses", "datetime", "enum", "math", "typing",
    "abc", "functools", "itertools", "uuid", "random", "re",
}
FORBIDDEN = {"sympy", "yaml", "anthropic", "sqlalchemy", "fastapi", "requests", "httpx", "os", "pathlib"}

DOMAIN = pathlib.Path(__file__).parent.parent / "src" / "learnai" / "domain"


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_domain_imports_only_stdlib_and_itself():
    offenders: dict[str, set[str]] = {}
    for path in DOMAIN.rglob("*.py"):
        bad = _imported_roots(path) - ALLOWED_TOP_LEVEL
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"domain core must stay pure, found: {offenders}"


def test_domain_never_imports_forbidden_packages():
    for path in DOMAIN.rglob("*.py"):
        assert not (_imported_roots(path) & FORBIDDEN), f"{path.name} imports a forbidden package"
```

- [ ] **Step 9: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS — 9 tests.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml src/learnai tests
git commit -m "feat: project scaffold and skill graph with purity enforcement"
```

---

### Task 2: Quadratics skill graph content and loader

**Files:**
- Create: `content/quadratics/skills.yaml`
- Create: `src/learnai/adapters/content/__init__.py`, `src/learnai/adapters/content/loader.py`
- Test: `tests/adapters/__init__.py`, `tests/adapters/test_content_loader.py`

**Interfaces:**
- Consumes: `Skill`, `Concept`, `Misconception`, `PrereqEdge`, `SkillGraph.build` from Task 1.
- Produces: `parse_cluster(raw: Mapping[str, Any]) -> LoadedCluster`, which holds every content rule and touches no I/O, plus the thin file wrapper `load_cluster(path: Path) -> LoadedCluster`. `LoadedCluster` is a frozen dataclass with fields `graph: SkillGraph`, `concepts: dict[ConceptId, Concept]`, `misconceptions: dict[MisconceptionId, Misconception]`. Raises `ContentError` on a missing `subject` or `verification`, a dangling reference, a duplicate id, a catalogue entry no skill references, a concept whose `introduced_by` is not one of the skills that use it, or a hard-prerequisite cycle (message names the path).

**What the loader deliberately does not do.** It has no default verification kind and imports nothing from any verifier adapter: the cluster declares the kind, and only the engine's registry can say whether a verifier exists for it (Task 17). It does not require a skill to list misconceptions: an unmatched error is diagnosed as novel (Task 8), and a mandatory entry would invite invented ones.

- [ ] **Step 1: Create the test package and write the content file**

```bash
mkdir -p tests/adapters content/quadratics src/learnai/adapters/content
touch tests/adapters/__init__.py src/learnai/adapters/content/__init__.py
```


Twelve skills with genuine dependency structure. Each happens to carry at least one misconception, which gives Task 8's diagnosis something to match in every skill; that is a property of this content, not a loader rule.

```yaml
# content/quadratics/skills.yaml
subject: math
# Which Verifier grades these skills. Required, with no fallback in code; a
# skill may override it with its own `verification:` key.
verification: cas_symbolic

# One catalogue, referenced by id. A belief that afflicts several skills is
# authored once — see mc.square.distributes below, which two skills share.
misconceptions:
  - id: mc.foil.drops.cross
    name: Drops the cross terms
    description: Multiplies first and last terms only, ignoring the inner and outer products.
    signature: product_of_sums_drops_cross
  - id: mc.square.distributes
    name: Square distributes over a sum
    description: Believes (a + b)^2 equals a^2 + b^2.
    signature: square_distributes_over_sum
  - id: mc.gcf.partial
    name: Factors out only part of the common factor
    description: Extracts a common factor but leaves a further common factor behind.
    signature: incomplete_common_factor
  - id: mc.factor.sign
    name: Sign error in the factors
    description: Chooses roots of the right magnitude but the wrong sign.
    signature: factor_sign_flip
  - id: mc.diffsquares.sum
    name: Factors a sum of squares
    description: Applies the difference-of-squares pattern to a^2 + b^2.
    signature: sum_of_squares_factored
  - id: mc.nonmonic.ignores.lead
    name: Ignores the leading coefficient
    description: Factors as though the leading coefficient were 1.
    signature: ignores_leading_coefficient
  - id: mc.zeroproduct.misapplied
    name: Applies zero-product to a non-zero right side
    description: Sets each factor equal to the right-hand side instead of first moving it to zero.
    signature: zero_product_without_zero
  - id: mc.complete.forgets.subtract
    name: Adds the square without compensating
    description: Adds (b/2)^2 without subtracting it again.
    signature: completes_without_compensating
  - id: mc.formula.sign.b
    name: Drops the negation of b
    description: Uses b instead of -b in the numerator.
    signature: formula_b_not_negated
  - id: mc.discriminant.sign
    name: Reverses the discriminant cases
    description: Reads a negative discriminant as two real roots.
    signature: discriminant_cases_reversed
  - id: mc.vertex.sign
    name: Sign error reading the vertex
    description: Reads (x - h)^2 + k as having vertex (-h, k).
    signature: vertex_sign_flip
  - id: mc.word.keeps.negative
    name: Keeps a negative length
    description: Reports a negative root as a valid physical dimension.
    signature: negative_root_kept

skills:
  - id: quad.expand.binomial
    name: Expand a product of two binomials
    can_do: Expand (x + a)(x + b) into standard form.
    misconceptions: [mc.foil.drops.cross]
  - id: quad.expand.square
    name: Expand a squared binomial
    can_do: Expand (x + a)^2 into standard form.
    prereqs: [{skill: quad.expand.binomial, strength: hard}]
    misconceptions: [mc.square.distributes]
  - id: quad.factor.common
    name: Factor out a common monomial
    can_do: Factor the greatest common monomial from a polynomial.
    misconceptions: [mc.gcf.partial]
  - id: quad.factor.monic
    name: Factor a monic quadratic
    can_do: Factor x^2 + bx + c into two binomials.
    prereqs:
      - {skill: quad.expand.binomial, strength: hard}
      - {skill: quad.factor.common, strength: soft}
    misconceptions: [mc.factor.sign]
  - id: quad.factor.diffsquares
    name: Factor a difference of squares
    can_do: Factor a^2 - b^2 as (a - b)(a + b).
    prereqs: [{skill: quad.expand.binomial, strength: hard}]
    misconceptions: [mc.diffsquares.sum]
  - id: quad.factor.nonmonic
    name: Factor a non-monic quadratic
    can_do: Factor ax^2 + bx + c where a is not 1.
    prereqs: [{skill: quad.factor.monic, strength: hard}]
    misconceptions: [mc.nonmonic.ignores.lead]
  - id: quad.solve.factoring
    name: Solve a quadratic by factoring
    can_do: Solve a quadratic equation using the zero-product property.
    prereqs: [{skill: quad.factor.monic, strength: hard}]
    misconceptions: [mc.zeroproduct.misapplied]
  - id: quad.completesquare
    name: Complete the square
    can_do: Rewrite x^2 + bx + c in the form (x + p)^2 + q.
    prereqs: [{skill: quad.expand.square, strength: hard}]
    misconceptions: [mc.complete.forgets.subtract, mc.square.distributes]
  - id: quad.formula.apply
    name: Apply the quadratic formula
    can_do: Solve any quadratic using the quadratic formula.
    prereqs: [{skill: quad.completesquare, strength: soft}, {skill: quad.solve.factoring, strength: hard}]
    misconceptions: [mc.formula.sign.b]
  - id: quad.discriminant
    name: Interpret the discriminant
    can_do: Determine the number and nature of roots from b^2 - 4ac.
    prereqs: [{skill: quad.formula.apply, strength: hard}]
    misconceptions: [mc.discriminant.sign]
  - id: quad.vertex
    name: Find the vertex of a parabola
    can_do: Find the vertex of a quadratic from its equation.
    prereqs: [{skill: quad.completesquare, strength: hard}]
    misconceptions: [mc.vertex.sign]
  - id: quad.word.area
    name: Solve an area word problem with a quadratic
    can_do: Model and solve an area problem that reduces to a quadratic.
    prereqs: [{skill: quad.solve.factoring, strength: hard}]
    misconceptions: [mc.word.keeps.negative]
```

- [ ] **Step 2: Write the failing loader test**

```python
# tests/adapters/test_content_loader.py
import pathlib

import pytest
import yaml

from learnai.adapters.content.loader import ContentError, load_cluster, parse_cluster
from learnai.domain.ids import ConceptId, MisconceptionId, SkillId

CLUSTER = pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"


def test_loads_every_skill():
    cluster = load_cluster(CLUSTER)
    assert len(cluster.graph.skills) == 12


def test_hard_and_soft_edges_are_distinguished():
    cluster = load_cluster(CLUSTER)
    assert cluster.graph.hard_prereqs(SkillId("quad.factor.monic")) == frozenset(
        {SkillId("quad.expand.binomial")}
    )
    assert cluster.graph.soft_prereqs(SkillId("quad.factor.monic")) == frozenset(
        {SkillId("quad.factor.common")}
    )


def test_roots_are_the_initial_frontier():
    cluster = load_cluster(CLUSTER)
    assert cluster.graph.frontier(learned=set()) == frozenset(
        {SkillId("quad.expand.binomial"), SkillId("quad.factor.common")}
    )


def test_every_misconception_id_resolves():
    cluster = load_cluster(CLUSTER)
    for skill in cluster.graph.skills.values():
        for mid in skill.misconception_ids:
            assert mid in cluster.misconceptions


def test_a_misconception_can_be_shared_by_several_skills():
    """One belief, one catalogue entry, one memory — not one copy per skill."""
    cluster = load_cluster(CLUSTER)
    shared = MisconceptionId("mc.square.distributes")
    owners = [s.id for s in cluster.graph.skills.values() if shared in s.misconception_ids]
    assert set(owners) == {SkillId("quad.expand.square"), SkillId("quad.completesquare")}


def test_misconceptions_are_subject_scoped_not_skill_owned():
    cluster = load_cluster(CLUSTER)
    assert all(m.subject_id == "math" for m in cluster.misconceptions.values())
    assert not hasattr(next(iter(cluster.misconceptions.values())), "skill_id")


# Content rules are exercised through parse_cluster: no temp files, no YAML
# round-trip, and the failure cases read as data rather than as string escaping.

MC = {"id": "m1", "name": "M", "description": "d", "signature": "s"}
CONCEPT = {"id": "c1", "kind": "definition", "prompt": "p", "answer": "a"}
SKILL_A = {"id": "a", "name": "A", "can_do": "does a", "misconceptions": ["m1"]}
SKILL_B = {"id": "b", "name": "B", "can_do": "does b", "misconceptions": ["m1"]}


def cluster(**overrides) -> dict:
    # "any_checker", not "cas_symbolic": the loader treats the kind as opaque.
    base = {"subject": "math", "verification": "any_checker", "misconceptions": [MC], "skills": [SKILL_A]}
    return base | overrides


def test_the_baseline_cluster_is_valid():
    assert parse_cluster(cluster()).graph.skills.keys() == {SkillId("a")}


def test_a_cluster_without_a_subject_is_rejected():
    with pytest.raises(ContentError):
        parse_cluster({"skills": []})


def test_a_cluster_without_a_verification_kind_is_rejected():
    """No fallback: a history cluster that forgot the key must not be graded by SymPy."""
    without = {k: v for k, v in cluster().items() if k != "verification"}
    with pytest.raises(ContentError):
        parse_cluster(without)


def test_skills_inherit_the_cluster_verification_kind():
    skill = parse_cluster(cluster()).graph.skills[SkillId("a")]
    assert skill.verification_kind == "any_checker"


def test_a_skill_can_override_the_verification_kind():
    loaded = parse_cluster(cluster(skills=[SKILL_A | {"verification": "other_checker"}]))
    assert loaded.graph.skills[SkillId("a")].verification_kind == "other_checker"


def test_a_dangling_prereq_is_rejected():
    with pytest.raises(ContentError):
        parse_cluster(cluster(skills=[SKILL_A | {"prereqs": [{"skill": "ghost", "strength": "hard"}]}]))


def test_a_prereq_cycle_is_rejected_with_its_path():
    a = SKILL_A | {"prereqs": [{"skill": "b", "strength": "hard"}]}
    b = SKILL_B | {"prereqs": [{"skill": "a", "strength": "hard"}]}
    with pytest.raises(ContentError, match="a -> b -> a"):
        parse_cluster(cluster(skills=[a, b]))


def test_a_skill_without_misconceptions_is_accepted():
    """Diagnosis treats an unmatched error as novel; requiring an entry would invite invented ones."""
    bare = {"id": "a", "name": "A", "can_do": "does a"}
    loaded = parse_cluster(cluster(misconceptions=[], skills=[bare]))
    assert loaded.graph.skills[SkillId("a")].misconception_ids == ()


def test_a_dangling_misconception_reference_is_rejected():
    with pytest.raises(ContentError):
        parse_cluster(cluster(skills=[SKILL_A | {"misconceptions": ["ghost"]}]))


def test_a_misconception_no_skill_references_is_rejected():
    orphan = {"id": "orphan", "name": "O", "description": "d", "signature": "s"}
    with pytest.raises(ContentError):
        parse_cluster(cluster(misconceptions=[MC, orphan]))


def test_a_duplicate_misconception_id_is_rejected():
    with pytest.raises(ContentError):
        parse_cluster(cluster(misconceptions=[MC, dict(MC)]))


def test_introduced_by_may_name_any_skill_that_uses_the_concept():
    """An override, not "the first user": b may introduce it even though a also uses it."""
    loaded = parse_cluster(
        cluster(
            concepts=[CONCEPT | {"introduced_by": "b"}],
            skills=[SKILL_A | {"concepts": ["c1"]}, SKILL_B | {"concepts": ["c1"]}],
        )
    )
    assert loaded.concepts[ConceptId("c1")].introduced_by == SkillId("b")


def test_introduced_by_must_be_a_skill_that_uses_the_concept():
    with pytest.raises(ContentError):
        parse_cluster(
            cluster(
                concepts=[CONCEPT | {"introduced_by": "b"}],
                skills=[SKILL_A | {"concepts": ["c1"]}, SKILL_B],
            )
        )


def test_introduced_by_naming_an_unknown_skill_is_rejected():
    with pytest.raises(ContentError):
        parse_cluster(
            cluster(
                concepts=[CONCEPT | {"introduced_by": "ghost"}],
                skills=[SKILL_A | {"concepts": ["c1"]}],
            )
        )


def test_the_file_loader_adds_nothing_but_reading():
    assert load_cluster(CLUSTER) == parse_cluster(yaml.safe_load(CLUSTER.read_text()))
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_content_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.adapters.content'`

- [ ] **Step 4: Write the parser and the file loader**

```python
# src/learnai/adapters/content/loader.py
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from learnai.domain.enums import ConceptKind, PrereqStrength
from learnai.domain.graph import CycleError, SkillGraph
from learnai.domain.ids import ConceptId, MisconceptionId, SkillId, VerificationKind
from learnai.domain.skills import Concept, Misconception, PrereqEdge, Skill


class ContentError(ValueError):
    """Raised when a content file is structurally invalid."""


@dataclass(frozen=True, slots=True)
class LoadedCluster:
    graph: SkillGraph
    concepts: dict[ConceptId, Concept]
    misconceptions: dict[MisconceptionId, Misconception]


def parse_cluster(raw: Mapping[str, Any]) -> LoadedCluster:
    """Validate and build a cluster from already-decoded content.

    Every content rule lives here, deliberately apart from any I/O, so that
    each source runs the same checks. A source that admitted content this
    rejects would be a quiet route to a broken graph — and a Postgres reader
    that re-implemented the rules would drift from this one within a release.
    """
    subject = raw.get("subject")
    if not subject:
        raise ContentError("cluster file has no subject")

    # Which checker grades a skill is a fact about the content, so the content
    # states it. A fallback here would send any cluster that forgot the key to
    # SymPy — a history cluster graded as algebra, silently. The token stays
    # opaque: whether a verifier exists for it is the engine's check (Task 17).
    default_verification = raw.get("verification")
    if not default_verification:
        raise ContentError("cluster file has no verification kind")

    skills: list[Skill] = []
    edges: list[PrereqEdge] = []

    # Catalogues first: concepts and misconceptions are shared, so they are
    # authored once at the top level and referenced by id from any number of
    # skills. A single owner would force duplication, and duplicating a concept
    # duplicates its memory state.
    misconceptions: dict[MisconceptionId, Misconception] = {}
    for mc in raw.get("misconceptions", []):
        mid = MisconceptionId(mc["id"])
        if mid in misconceptions:
            raise ContentError(f"duplicate misconception id: {mid}")
        misconceptions[mid] = Misconception(
            id=mid,
            subject_id=subject,
            name=mc["name"],
            description=mc["description"],
            signature=mc["signature"],
        )

    concepts: dict[ConceptId, Concept] = {}
    for c in raw.get("concepts", []):
        cid = ConceptId(c["id"])
        if cid in concepts:
            raise ContentError(f"duplicate concept id: {cid}")
        concepts[cid] = Concept(
            id=cid,
            subject_id=subject,
            kind=ConceptKind(c["kind"]),
            prompt=c["prompt"],
            answer=c["answer"],
            introduced_by=SkillId(c["introduced_by"]) if c.get("introduced_by") else None,
        )

    referenced_mcs: set[MisconceptionId] = set()
    # The skills_for_concept index Slice 2 will expose; here it only validates.
    concept_users: dict[ConceptId, set[SkillId]] = defaultdict(set)

    for entry in raw.get("skills", []):
        sid = SkillId(entry["id"])
        # May be empty: a new skill has no catalogued errors yet, and a recall
        # skill's wrong answer is not knowing rather than a false belief.
        # Diagnosis reports an unmatched error as novel (Task 8).
        mc_ids = tuple(MisconceptionId(m) for m in entry.get("misconceptions", []))
        for mid in mc_ids:
            if mid not in misconceptions:
                raise ContentError(f"{sid} references unknown misconception {mid}")
        referenced_mcs.update(mc_ids)

        concept_ids = tuple(ConceptId(c) for c in entry.get("concepts", []))
        for cid in concept_ids:
            if cid not in concepts:
                raise ContentError(f"{sid} references unknown concept {cid}")
            concept_users[cid].add(sid)

        skills.append(
            Skill(
                id=sid,
                subject_id=subject,
                name=entry["name"],
                can_do_statement=entry["can_do"],
                verification_kind=VerificationKind(
                    entry.get("verification", default_verification)
                ),
                concept_ids=concept_ids,
                misconception_ids=mc_ids,
            )
        )
        for pre in entry.get("prereqs", []):
            edges.append(
                PrereqEdge(
                    from_skill=SkillId(pre["skill"]),
                    to_skill=sid,
                    strength=PrereqStrength(pre["strength"]),
                )
            )

    # Sharing must not become orphaning: content nothing points at is dead weight
    # that would still be scheduled for review.
    if orphans := set(misconceptions) - referenced_mcs:
        raise ContentError(f"misconceptions referenced by no skill: {sorted(orphans)}")
    if orphans := set(concepts) - concept_users.keys():
        raise ContentError(f"concepts referenced by no skill: {sorted(orphans)}")

    # introduced_by overrides where a Learn session first teaches a concept, so
    # it must name a skill that actually uses it. This also catches a typo'd id,
    # which would otherwise sit unnoticed until Slice 3 reads the field.
    for concept in concepts.values():
        users = concept_users[concept.id]
        if concept.introduced_by is not None and concept.introduced_by not in users:
            raise ContentError(
                f"{concept.id} is introduced_by {concept.introduced_by}, which does not "
                f"use it; choose one of {sorted(users)}"
            )

    try:
        graph = SkillGraph.build(skills, edges)
    except (KeyError, CycleError) as exc:
        raise ContentError(str(exc)) from exc

    return LoadedCluster(graph=graph, concepts=concepts, misconceptions=misconceptions)


def load_cluster(path: Path) -> LoadedCluster:
    """Read a YAML cluster file. A thin wrapper; the rules are in `parse_cluster`.

    Other sources skip this entirely: an HTTP or S3 reader decodes bytes and
    calls `parse_cluster`, and a database reader builds the domain objects from
    rows without going near YAML.
    """
    return parse_cluster(yaml.safe_load(path.read_text()))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_content_loader.py -v`
Expected: PASS — 21 tests.

- [ ] **Step 6: Commit**

```bash
git add content src/learnai/adapters/content tests/adapters
git commit -m "feat: quadratics skill cluster and validating content loader"
```

---

### Task 3: Item and answer types

**Files:**
- Create: `src/learnai/domain/items.py`
- Test: `tests/domain/test_items.py`

**Interfaces:**
- Consumes: ids and enums from Task 1, including `AnswerKind` (`SINGLE_VALUE` / `RELATION` / `VALUE_SET`) and `ProvenanceKind`.
- Produces: `FormConstraint = NewType("FormConstraint", str)` — **opaque to the domain**, which never interprets one; each `Verifier` adapter owns its own vocabulary (see Task 5). `AnswerSpec(expression: str, form_constraints: tuple[FormConstraint, ...], kind: AnswerKind)`; `Provenance(kind: ProvenanceKind, template_id: TemplateId | None, seed: int | None)` with constructors `Provenance.generated(template_id, seed)` and `Provenance.authored()`; `Item(id, skill_id, provenance, statement, answer_spec, worked_steps, difficulty, vetting_level)`; `StepDiff(index: int, previous: str, current: str)`; `Submission(fields: tuple[str, ...], claims_none: bool = False)` with `Submission.of(*fields)`, `Submission.none()`, `is_blank`, `entries` and `check_shape(kind)`, which raises `SubmissionShapeError`; `MULTI_FIELD_KINDS`.

**Why answers arrive as fields:** the input widget follows the answer kind — one field, or one field per value with "add another" and a "none" option — so the student's answer reaches the engine already shaped, and nothing ever splits a string on commas or guesses at separators. The domain owns the shape and never what a field contains: the CAS adapter parses a field as maths, and a rubric adapter would judge it as prose, exactly as with form constraints.

- [ ] **Step 1: Write the failing test**

```python
# tests/domain/test_items.py
import pytest

from learnai.domain.enums import AnswerKind, ProvenanceKind, VettingLevel
from learnai.domain.ids import ItemId, SkillId, TemplateId
from learnai.domain.items import (
    AnswerSpec,
    FormConstraint,
    Item,
    Provenance,
    StepDiff,
    Submission,
    SubmissionShapeError,
)


def test_generated_provenance_is_reproducible_from_template_and_seed():
    p = Provenance.generated(TemplateId("quad.factor.monic.v1"), seed=4242)
    assert p.kind is ProvenanceKind.GENERATED
    assert (p.template_id, p.seed) == (TemplateId("quad.factor.monic.v1"), 4242)


def test_authored_provenance_has_no_seed():
    p = Provenance.authored()
    assert p.kind is ProvenanceKind.AUTHORED
    assert p.template_id is None and p.seed is None


def test_item_is_immutable():
    item = Item(
        id=ItemId("i1"),
        skill_id=SkillId("quad.factor.monic"),
        provenance=Provenance.generated(TemplateId("t"), 1),
        statement="Factor x^2 + 3x + 2",
        answer_spec=AnswerSpec(
            "(x + 1)*(x + 2)", (FormConstraint("fully_factored"),), AnswerKind.SINGLE_VALUE
        ),
        worked_steps=("x^2 + 3x + 2", "(x + 1)*(x + 2)"),
        difficulty=0.0,
        vetting_level=VettingLevel.MACHINE_VERIFIED,
    )
    try:
        item.difficulty = 1.0  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("Item must be frozen")


def test_a_form_constraint_is_just_an_opaque_token():
    """The domain must not know what 'fully_factored' means — only the verifier does."""
    token = FormConstraint("anything_the_adapter_understands")
    assert AnswerSpec("x", (token,)).form_constraints == (token,)


def test_answer_kind_defaults_to_single_value():
    spec = AnswerSpec("x + 1")
    assert spec.kind is AnswerKind.SINGLE_VALUE
    assert spec.form_constraints == ()


def test_step_diff_records_the_first_broken_transition():
    d = StepDiff(index=2, previous="2*x = 10", current="x = 8")
    assert d.index == 2


def test_a_single_value_answer_takes_exactly_one_field():
    Submission.of("x + 1").check_shape(AnswerKind.SINGLE_VALUE)
    with pytest.raises(SubmissionShapeError):
        Submission.of("1", "2").check_shape(AnswerKind.SINGLE_VALUE)
    with pytest.raises(SubmissionShapeError):
        Submission.none().check_shape(AnswerKind.RELATION)


def test_a_value_list_may_hold_any_number_of_values_or_claim_there_are_none():
    Submission.of("2", "-3").check_shape(AnswerKind.VALUE_SET)
    Submission.none().check_shape(AnswerKind.VALUE_SET)
    with pytest.raises(SubmissionShapeError):
        Submission(("2",), claims_none=True).check_shape(AnswerKind.VALUE_SET)


def test_blank_fields_are_a_decline_but_claiming_none_is_an_answer():
    assert Submission.of("  ").is_blank
    assert Submission.of("", "").is_blank
    assert not Submission.none().is_blank
    assert Submission.of("2", " ").entries == ("2",)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_items.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.domain.items'`

- [ ] **Step 3: Write the item types**

```python
# src/learnai/domain/items.py
from dataclasses import dataclass
from typing import NewType

from learnai.domain.enums import AnswerKind, ProvenanceKind, VettingLevel
from learnai.domain.ids import ItemId, SkillId, TemplateId

FormConstraint = NewType("FormConstraint", str)
"""A required form for an answer, e.g. "fully_factored".

Deliberately opaque: the domain knows an answer may carry form requirements and
that the Verifier judges them, but never what any particular one means. Each
subject adapter owns its own vocabulary and declares it via
`Verifier.supported_constraints`, so adding physics or chemistry never edits
the core. See spec §6.2.
"""


@dataclass(frozen=True, slots=True)
class AnswerSpec:
    expression: str
    """The answer key, in the Verifier adapter's own format."""

    form_constraints: tuple[FormConstraint, ...] = ()
    kind: AnswerKind = AnswerKind.SINGLE_VALUE
    """How the verifier compares a submission with `expression`; see AnswerKind."""


MULTI_FIELD_KINDS = frozenset({AnswerKind.VALUE_SET})
"""Kinds answered with any number of fields. Every other kind takes exactly one."""


class SubmissionShapeError(ValueError):
    """A submission cannot be an answer of the item's kind.

    Always a client bug — the input widget follows the kind — never a student
    error, so it is raised rather than graded.
    """


@dataclass(frozen=True, slots=True)
class Submission:
    """What the student entered: one string per answer field.

    The domain owns the shape, which the item's AnswerKind decides — one field,
    or a list of values that may be empty. It never interprets a field: whether
    one holds "(x+1)(x+2)" or "the Treaty of Versailles" is the Verifier
    adapter's to judge, exactly as with form constraints.
    """

    fields: tuple[str, ...]
    claims_none: bool = False
    """The student asserts there are no values — "no real solutions", "none of
    these". That is an answer; leaving every field blank is a decline."""

    @classmethod
    def of(cls, *fields: str) -> "Submission":
        return cls(fields)

    @classmethod
    def none(cls) -> "Submission":
        return cls((), claims_none=True)

    @property
    def is_blank(self) -> bool:
        """A decline: nothing entered and nothing claimed."""
        return not self.claims_none and all(not f.strip() for f in self.fields)

    @property
    def entries(self) -> tuple[str, ...]:
        """The fields that hold something. A value list's spare blank field is not an answer."""
        return tuple(f for f in self.fields if f.strip())

    def check_shape(self, kind: AnswerKind) -> None:
        if kind in MULTI_FIELD_KINDS:
            if self.claims_none and self.entries:
                raise SubmissionShapeError("claims there are no values, but lists some")
            return
        if self.claims_none or len(self.fields) != 1:
            raise SubmissionShapeError(f"a {kind.value} answer takes exactly one field")


@dataclass(frozen=True, slots=True)
class Provenance:
    kind: ProvenanceKind
    template_id: TemplateId | None = None
    seed: int | None = None

    @classmethod
    def generated(cls, template_id: TemplateId, seed: int) -> "Provenance":
        return cls(kind=ProvenanceKind.GENERATED, template_id=template_id, seed=seed)

    @classmethod
    def authored(cls) -> "Provenance":
        return cls(kind=ProvenanceKind.AUTHORED)


@dataclass(frozen=True, slots=True)
class Item:
    id: ItemId
    skill_id: SkillId
    provenance: Provenance
    statement: str
    answer_spec: AnswerSpec
    worked_steps: tuple[str, ...]
    difficulty: float
    vetting_level: VettingLevel


@dataclass(frozen=True, slots=True)
class StepDiff:
    """The first transition at which the student's work stopped being equivalent."""

    index: int
    previous: str
    current: str
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_items.py -v`
Expected: PASS — 9 tests.

- [ ] **Step 5: Commit**

```bash
git add src/learnai/domain/items.py tests/domain/test_items.py
git commit -m "feat: item, answer spec, and provenance value objects"
```

---

### Task 4: Safe parsing and mathematical equivalence

**Files:**
- Create: `src/learnai/adapters/cas/__init__.py`, `src/learnai/adapters/cas/parse.py`, `src/learnai/adapters/cas/equivalence.py`
- Test: `tests/adapters/test_parse.py`, `tests/adapters/test_equivalence.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ParseError`; `parse_math(text: str, *, allow_equation: bool = False, as_written: bool = False) -> sympy.Basic`; `evaluated(expr: sympy.Basic) -> sympy.Basic`; `expressions_equivalent(a: sympy.Expr, b: sympy.Expr) -> bool`; `equations_equivalent(a: sympy.Eq, b: sympy.Eq) -> bool`, which expects written forms; `real_solutions(eq: sympy.Eq, var: sympy.Symbol) -> frozenset[sympy.Expr] | None`; `solution_sets_equivalent(a: Sequence[sympy.Expr], b: Sequence[sympy.Expr]) -> bool`.

**Why the parser is its own module, and why it has no blocklist:** `sympy.parse_expr` ends in Python's `eval`, so student text reaching it unguarded is a remote-code-execution path. Safety is by construction: a small alphabet (no quotes, underscores, brackets or semicolons, and a dot only inside a decimal), every name resolved before SymPy sees it, and an explicit empty `__builtins__`. A list of forbidden words cannot do this job — `eval` silently inserts every builtin into the namespace it is given, which leaves the list as the only barrier.

**Why powers are bounded before evaluation:** `9^9^9` is five characters and evaluates for minutes. The length limit cannot catch it; a bound on the combined power along any chain of nested powers can, checked on the unevaluated tree.

**Written versus evaluated forms.** Evaluation normalises and forgets: `4(x+2)` becomes `4x + 8`, and `(x-1)^2/(x-1)` becomes `x - 1`, erasing the hole at 1. Expression equivalence wants the evaluated form. Two things need the written one: form constraints (Task 5 must see `4(x+2)` as factored) and equations, whose solutions must exclude points where the student's own expression is undefined.

**Holes and domains — the equivalence policy (spec §9).** Expressions are equivalent when they agree wherever both are defined, so an isolated hole is ignored — simplifying `(x^2-1)/(x-1)` to `x+1` is the exercise — while a region of disagreement is not: `log(x^2)` and `2log(x)` differ for every negative x. Equations are equivalent when they have the same real solutions, holes respected, which is what catches the classic solving errors: dividing by something that can be zero loses a root, multiplying through by it or squaring both sides admits one. Where solutions cannot be listed, proportionality is the fallback (spec D12).

**Decimals are exact; ambiguous spacing is refused.** A typed `0.1` is one tenth, not the nearest binary fraction — otherwise `0.1 + 0.2` would not equal `0.3` and correct decimal work would be marked wrong. Parsing still keeps it as a decimal, so form constraints can see that one was typed; only equivalence reads it exactly. A space between two numbers (`2 3`, `1 1/2`) raises `ParseError` rather than multiplying: a structured maths editor will remove the ambiguity (spec D1), and until then refusing is kinder than a verdict on an answer the student did not mean.

- [ ] **Step 1: Write the failing parser test**

```python
# tests/adapters/test_parse.py
import time

import pytest
import sympy as sp

from learnai.adapters.cas.parse import ParseError, evaluated, parse_math

x, y = sp.symbols("x y")


def test_implicit_multiplication_is_accepted():
    assert parse_math("2x") == 2 * x


def test_adjacent_letters_are_separate_variables():
    assert parse_math("2xy") == 2 * x * y


def test_a_known_name_is_found_inside_a_letter_run():
    assert parse_math("xsin(x)") == x * sp.sin(x)


def test_caret_means_exponentiation():
    assert parse_math("x^2") == x**2


def test_allowed_function_resolves():
    assert parse_math("sqrt(8)") == sp.sqrt(8)


def test_equation_is_parsed_when_permitted():
    parsed = parse_math("2x = 10", allow_equation=True)
    assert isinstance(parsed, sp.Eq)
    assert parsed.lhs == 2 * x and parsed.rhs == 10


def test_a_trivially_true_equation_stays_an_equation():
    """Eq(x, x) would otherwise collapse to True and break every caller expecting an Eq."""
    assert isinstance(parse_math("x = x", allow_equation=True), sp.Eq)


def test_equation_is_rejected_when_not_permitted():
    with pytest.raises(ParseError):
        parse_math("2x = 10")


def test_the_written_form_is_kept_on_request():
    """Form constraints judge what the student wrote, not what SymPy normalises it to."""
    written = parse_math("4(x+2)", as_written=True)
    assert written != 4 * x + 8
    assert evaluated(written) == 4 * x + 8
    assert parse_math("4(x+2)") == 4 * x + 8


@pytest.mark.parametrize(
    "hostile",
    [
        "__import__('os').system('echo pwned')",
        "().__class__.__bases__",
        "lambda: 1",
        "eval('1+1')",
        "open('/etc/passwd')",
        "pi.func",
        "x[0]",
        "x; y",
        "x()",
        "2(())",
    ],
)
def test_hostile_input_is_rejected(hostile):
    with pytest.raises(ParseError):
        parse_math(hostile)


@pytest.mark.parametrize("name", ["print(x)", "vars(x)", "exit(x)", "Symbol(x)", "lambda(x)"])
def test_names_never_reach_python(name):
    """Letters outside the known names become variables, so no builtin is ever called."""
    parsed = parse_math(name)
    assert isinstance(parsed, sp.Expr)
    assert parsed.free_symbols <= set(sp.symbols("a b c d e i l m n o p r s t v x y S"))


@pytest.mark.parametrize("tower", ["9^9^9", "2^(10^10)", "((x+1)^100)^100", "x^(99*99*99)"])
def test_power_towers_are_refused_before_evaluation(tower):
    started = time.monotonic()
    with pytest.raises(ParseError):
        parse_math(tower)
    assert time.monotonic() - started < 1.0


def test_ordinary_powers_of_powers_are_accepted():
    assert parse_math("(x^2)^3") == x**6


@pytest.mark.parametrize("ambiguous", ["2 3", "1 1/2", "0.5 2"])
def test_a_space_between_numbers_is_refused_not_guessed(ambiguous):
    """23 or 2*3? A mixed number, or 1 times 1/2? Guessing marks someone wrong."""
    with pytest.raises(ParseError):
        parse_math(ambiguous)


def test_a_space_before_a_letter_is_still_multiplication():
    assert parse_math("2 x") == 2 * x


def test_typed_decimals_stay_visible_to_form_checks():
    """Equivalence reads 0.5 exactly; a form constraint must still see a decimal was typed."""
    assert parse_math("0.5").atoms(sp.Float)


def test_overlong_input_is_rejected():
    with pytest.raises(ParseError):
        parse_math("x+" * 2000 + "1")


def test_unparseable_input_raises_parse_error():
    with pytest.raises(ParseError):
        parse_math("x +* 2")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.adapters.cas'`

- [ ] **Step 3: Write the parser**

```python
# src/learnai/adapters/cas/parse.py
"""The one entry point for untrusted mathematical text.

SymPy's parser ends in Python's `eval`, so safety here is by construction, not
by blocklist: only a small alphabet is admitted, every name is resolved before
SymPy sees it, and powers are bounded before anything is evaluated.
"""
import re
import warnings

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

MAX_INPUT_LENGTH = 512

MAX_EXPONENT_LOAD = 1000
"""Largest combined power along any chain of nested powers: (x^2)^3 carries 6.

Bounds the size of anything later evaluated or expanded. Without it "9^9^9",
five characters, evaluates for longer than any request may take.
"""

_ALLOWED = re.compile(r"[0-9A-Za-z\s.+\-*/^()=]*")
_DOT_NOT_BEFORE_DIGIT = re.compile(r"\.(?!\d)")
_NUMBER_SPACE_NUMBER = re.compile(r"[\d.]\s+[\d.]")
_LETTER_RUN = re.compile(r"[A-Za-z]+")

_FUNCTIONS = {
    "sqrt": sp.sqrt, "abs": sp.Abs, "exp": sp.exp, "log": sp.log, "ln": sp.log,
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
}
_CONSTANTS = {"pi": sp.pi}
_KNOWN = sorted(_FUNCTIONS.keys() | _CONSTANTS.keys(), key=len, reverse=True)

KNOWN_NAMES: frozenset[str] = frozenset(_KNOWN)
"""Every multi-letter name the parser reads as maths rather than as single-letter variables."""

_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,
    convert_xor,
)

# What SymPy's generated code may reference besides the per-call names. The
# explicit empty __builtins__ stops eval from inserting the real ones.
_GLOBALS = {
    "__builtins__": {},
    "Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational,
    "Add": sp.Add, "Mul": sp.Mul, "Pow": sp.Pow,
}


class ParseError(ValueError):
    """Raised when input is unsafe, malformed, or not permitted in this position."""


def parse_math(text: str, *, allow_equation: bool = False, as_written: bool = False) -> sp.Basic:
    """Parse untrusted mathematical text. Never call SymPy's parser directly elsewhere.

    Returns the evaluated form by default, which is what equivalence needs.
    `as_written=True` returns the tree exactly as typed, which is what form
    constraints and hole-respecting equation checks need.
    """
    stripped = text.strip()
    if not stripped:
        raise ParseError("empty input")
    if len(stripped) > MAX_INPUT_LENGTH:
        raise ParseError("input too long")
    if not _ALLOWED.fullmatch(stripped):
        raise ParseError("input contains a character outside the maths alphabet")
    if _DOT_NOT_BEFORE_DIGIT.search(stripped):
        raise ParseError("a dot may only appear inside a decimal number")
    # Refuse rather than guess: "2 3" may be 23 or 2*3, and "1 1/2" is a mixed
    # number that implicit multiplication would read as 1/2. A structured maths
    # editor removes the ambiguity at the source (spec D1).
    if _NUMBER_SPACE_NUMBER.search(stripped):
        raise ParseError("a space between two numbers is ambiguous")

    if "=" in stripped:
        if not allow_equation:
            raise ParseError("an equation is not permitted in this position")
        lhs, _, rhs = stripped.partition("=")
        if "=" in rhs:
            raise ParseError("more than one equals sign")
        written: sp.Basic = sp.Eq(_parse_side(lhs), _parse_side(rhs), evaluate=False)
    else:
        written = _parse_side(stripped)
    if as_written:
        return written
    try:
        return evaluated(written)
    except Exception as exc:  # anything SymPy raises here is still bad input
        raise ParseError(f"could not evaluate {text!r}") from exc


def evaluated(expr: sp.Basic, *, exact_decimals: bool = False) -> sp.Basic:
    """The evaluated form of a written expression, rebuilt bottom-up.

    Evaluation normalises, and in doing so forgets: it distributes 4(x+2) into
    4x + 8, and cancels (x-1)^2/(x-1) to x - 1, erasing the hole at 1.

    `exact_decimals` reads each typed decimal as the exact number it denotes —
    0.1 is one tenth, not the nearest binary fraction — before any arithmetic,
    so 0.1 + 0.2 is exactly 0.3. Parsing keeps decimals as SymPy Floats so that
    form checks can still see that a decimal was typed; equivalence asks for
    exact values.
    """
    if isinstance(expr, sp.Float):
        return sp.Rational(str(expr)) if exact_decimals else expr
    if isinstance(expr, sp.Eq):
        return sp.Eq(
            evaluated(expr.lhs, exact_decimals=exact_decimals),
            evaluated(expr.rhs, exact_decimals=exact_decimals),
            evaluate=False,
        )
    if not expr.args:
        return expr
    return expr.func(*(evaluated(arg, exact_decimals=exact_decimals) for arg in expr.args))


def _parse_side(text: str) -> sp.Expr:
    rewritten, names = _resolve_names(text)
    try:
        with warnings.catch_warnings():
            # A deprecation raised while parsing means the input built something
            # odd — "x()" is x times an empty Tuple — so treat it as unparseable
            # rather than rely on a path SymPy has scheduled for removal.
            warnings.simplefilter("error", DeprecationWarning)
            expr = parse_expr(
                rewritten,
                local_dict=names,
                global_dict=dict(_GLOBALS),
                transformations=_TRANSFORMATIONS,
                evaluate=False,
            )
    except Exception as exc:  # SymPy raises a wide variety here
        raise ParseError(f"could not parse {text!r}") from exc
    # Every node, not just the root: "x()" parses to x times an empty Tuple.
    if not all(isinstance(node, sp.Expr) for node in sp.preorder_traversal(expr)):
        raise ParseError(f"{text!r} is not a mathematical expression")
    _exponent_load(expr)
    return expr


def _resolve_names(text: str) -> tuple[str, dict[str, object]]:
    """Rewrite each run of letters into names, and say what every name means.

    Known names match longest-first; any other letter is its own variable, so
    "xy" is x*y and "xsin(x)" is x*sin(x). Every name in the rewritten text is
    in the returned table, so SymPy never resolves one itself: a student's
    "print" is the product p*r*i*n*t, never Python's print.
    """
    table: dict[str, object] = {}

    def rewrite(match: re.Match[str]) -> str:
        run, names, i = match.group(), [], 0
        while i < len(run):
            name = next((k for k in _KNOWN if run.startswith(k, i)), run[i])
            names.append(name)
            i += len(name)
        for name in names:
            if name in _FUNCTIONS:
                table[name] = _FUNCTIONS[name]
            elif name in _CONSTANTS:
                table[name] = _CONSTANTS[name]
            else:
                table[name] = sp.Symbol(name)
        return " ".join(names)

    return _LETTER_RUN.sub(rewrite, text), table


def _exponent_load(expr: sp.Basic) -> float:
    """The combined power carried by `expr`, refusing anything over the limit.

    Children are checked before their parent, so a symbol-free exponent is
    only evaluated once every power inside it is known to be small.
    """
    loads = [_exponent_load(arg) for arg in expr.args]
    load = max(loads, default=1.0)
    if isinstance(expr, sp.Pow) and not expr.exp.free_symbols:
        magnitude = abs(evaluated(expr.exp))
        if not magnitude.is_finite or magnitude > MAX_EXPONENT_LOAD:
            raise ParseError("exponent too large")
        load = max(1.0, float(magnitude)) * loads[0]
    if load > MAX_EXPONENT_LOAD:
        raise ParseError("powers nested too deeply")
    return load
```

- [ ] **Step 4: Run the parser tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_parse.py -v`
Expected: PASS — 36 tests (the parametrised cases count individually).

- [ ] **Step 5: Write the failing equivalence test**

```python
# tests/adapters/test_equivalence.py
import pytest

from learnai.adapters.cas.equivalence import (
    equations_equivalent,
    expressions_equivalent,
    solution_sets_equivalent,
)
from learnai.adapters.cas.parse import parse_math


def expr(text: str):
    return parse_math(text)


def eq(text: str):
    return parse_math(text, allow_equation=True, as_written=True)


@pytest.mark.parametrize(
    "a,b",
    [
        ("1/2", "0.5"),
        ("2/4", "1/2"),
        ("(x+1)(x+2)", "x^2 + 3x + 2"),
        ("2sin(x)cos(x)", "sin(2x)"),
        ("sqrt(8)", "2sqrt(2)"),
        ("x + x", "2x"),
        ("(x^2 - 1)/(x - 1)", "x + 1"),  # an isolated hole is not a difference
        ("0.1 + 0.2", "0.3"),  # decimals are exact, not binary approximations
        ("0.3", "3/10"),
    ],
)
def test_equivalent_expressions_are_accepted(a, b):
    assert expressions_equivalent(expr(a), expr(b))


@pytest.mark.parametrize(
    "a,b",
    [
        ("x + 1", "x + 2"),
        ("(x+1)(x+2)", "x^2 + 3x + 3"),
        ("x^2", "x^3"),
        ("log(x^2)", "2log(x)"),  # differ for every negative x
        ("sqrt(x^2)", "x"),
    ],
)
def test_inequivalent_expressions_are_rejected(a, b):
    assert not expressions_equivalent(expr(a), expr(b))


@pytest.mark.parametrize(
    "a,b",
    [
        ("2x = 10", "x = 5"),
        ("x + 3 = 7", "2x + 6 = 14"),
        ("(x-1)^2 = 0", "x - 1 = 0"),  # a repeated root is still one solution
        ("(x^2 - 1)/(x - 1) = 0", "x + 1 = 0"),  # the hole at 1 is not a solution anyway
        ("x^2 + 9 = 0", "x^2 = -9"),  # no real solutions: falls back to proportionality
        ("y = 2x + 1", "2y = 4x + 2"),  # two variables: falls back to proportionality
        ("0.5x = 1", "x = 2"),
    ],
)
def test_equations_with_the_same_solutions_are_equivalent(a, b):
    assert equations_equivalent(eq(a), eq(b))


@pytest.mark.parametrize(
    "a,b",
    [
        ("2x = 10", "x = 8"),
        ("x^2 = 4", "x = 2"),  # a square root taken without the negative branch
        ("x^2 = 2x", "x = 2"),  # dividing by x loses the root 0
        ("x/(x-2) = 2/(x-2)", "x = 2"),  # multiplying through admits a root the original excludes
        ("(x-1)^2/(x-1) = 0", "x - 1 = 0"),  # the only candidate root is the hole
        ("sqrt(x) = -2", "x = 4"),  # squaring admits a root
        ("x^2 + 1 = 0", "x^2 + 4 = 0"),  # both empty, still not the same equation
        ("x = 2", "y = 2"),
    ],
)
def test_equations_with_different_solutions_are_not_equivalent(a, b):
    assert not equations_equivalent(eq(a), eq(b))


def test_decimals_are_exact_before_any_arithmetic():
    """In binary, 0.1*3 - 0.3 is 5.6e-17. Read as typed, it is exactly zero."""
    assert expressions_equivalent(parse_math("0.1*3 - 0.3", as_written=True), expr("0"))


def test_solution_sets_ignore_order_and_representation():
    assert solution_sets_equivalent([expr("-1"), expr("2")], [expr("2"), expr("-2/2")])


def test_solution_sets_of_different_size_differ():
    assert not solution_sets_equivalent([expr("1")], [expr("1"), expr("2")])
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_equivalence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.adapters.cas.equivalence'`

- [ ] **Step 7: Write the equivalence module**

```python
# src/learnai/adapters/cas/equivalence.py
"""When do two pieces of mathematics mean the same thing?

Expressions are equivalent when they agree wherever both are defined. Isolated
holes are ignored — that (x^2-1)/(x-1) simplifies to x+1 is the exercise, not
an error — but disagreement over a region is not: log(x^2) and 2log(x) differ
for every negative x. Typed decimals are exact: 0.1 means one tenth.

Equations are equivalent when they have the same real solutions, with holes
respected. Evaluation cancels holes, so equation checks need the *written*
form: `parse_math(text, allow_equation=True, as_written=True)`.
"""
import math
import random
from collections.abc import Sequence

import sympy as sp

from learnai.adapters.cas.parse import evaluated

_NUMERIC_TRIALS = 12
_TOLERANCE = 1e-9


def _exact(expr: sp.Basic) -> sp.Basic:
    """Evaluated, with typed decimals read as exact: 0.1 + 0.2 is exactly 0.3."""
    return evaluated(expr, exact_decimals=True)


def _numeric_disagrees(a: sp.Expr, b: sp.Expr) -> bool:
    """Fast rejection: if the two disagree at any sampled point, they are not equal.

    Sampling only ever produces a confident NO. A clean sweep is not proof of
    equality, so a negative result here falls through to the symbolic check.
    A point where either side is undefined is skipped, which is why isolated
    holes never cause a rejection.
    """
    symbols = sorted(a.free_symbols | b.free_symbols, key=str)
    rng = random.Random(20260919)
    for _ in range(_NUMERIC_TRIALS):
        point = {s: sp.Rational(rng.randint(-20, 20), rng.randint(1, 7)) for s in symbols}
        try:
            va = complex(sp.N(a.subs(point)))
            vb = complex(sp.N(b.subs(point)))
        except (TypeError, ValueError, ArithmeticError):
            continue
        if not all(math.isfinite(part) for v in (va, vb) for part in (v.real, v.imag)):
            continue
        if abs(va - vb) > _TOLERANCE * max(1.0, abs(va), abs(vb)):
            return True
    return False


def expressions_equivalent(a: sp.Expr, b: sp.Expr) -> bool:
    a, b = _exact(a), _exact(b)
    if a == b:
        return True
    if _numeric_disagrees(a, b):
        return False
    decided = (a - b).equals(0)
    if decided is None:
        # Symbolic equality is undecidable in general. Many sampled points agreed,
        # so accept: a false accept here costs a student nothing, a false reject
        # marks correct work wrong, which is the failure that loses their trust.
        return True
    return bool(decided)


def real_solutions(eq: sp.Eq, var: sp.Symbol) -> frozenset[sp.Expr] | None:
    """The real solutions of a written equation, or None when they cannot be listed.

    Solved on the evaluated form, then filtered against the written one: a root
    survives only where both written sides are defined and real. The filter is
    what stops (x-1)^2/(x-1) = 0 claiming the solution 1 — SymPy's solver only
    ever sees x - 1 = 0, because evaluation has already cancelled the hole.
    """
    found = sp.solveset(_exact(eq.lhs) - _exact(eq.rhs), var, domain=sp.S.Reals)
    if found is sp.S.EmptySet:
        return frozenset()
    if not isinstance(found, sp.FiniteSet):
        return None  # infinitely many (sin x = 0), or not in closed form
    return frozenset(root for root in found if _defined_at(eq, var, root))


def _defined_at(eq: sp.Eq, var: sp.Symbol, point: sp.Expr) -> bool:
    for side in (eq.lhs, eq.rhs):
        value = _value_at(side, var, point)
        if not (value.is_finite and value.is_real):
            return False
    return True


def _value_at(expr: sp.Basic, var: sp.Symbol, point: sp.Expr) -> sp.Basic:
    """Substitute and evaluate bottom-up, so every child is a number before its parent is built.

    Plain `subs` rebuilds the parent first, and SymPy then merges
    (x-1)^-1 * (x-1)^2 into x-1 before x-1 has become 0 — cancelling the very
    hole this is meant to find.
    """
    if expr == var:
        return point
    if isinstance(expr, sp.Float):
        return _exact(expr)
    if not expr.args:
        return expr
    return expr.func(*(_value_at(arg, var, point) for arg in expr.args))


def equations_equivalent(a: sp.Eq, b: sp.Eq) -> bool:
    """Same real solutions, holes respected. Pass written forms (see module docstring).

    Falls back to proportionality — one side a nonzero constant multiple of the
    other — when the solutions cannot be compared: several variables, solutions
    that cannot be listed, or no real solutions on either side (where comparing
    two empty sets would accept any slip between x^2 + 1 = 0 and x^2 + 4 = 0).
    Proportional equations do share their solutions, but the fallback rejects
    genuine rewrites such as (x-1)^2 = 0 to x - 1 = 0 and is blind to holes.
    See spec D12.
    """
    variables = a.free_symbols | b.free_symbols
    if len(variables) == 1:
        (var,) = variables
        sa, sb = real_solutions(a, var), real_solutions(b, var)
        if sa is not None and sb is not None and (sa or sb):
            return solution_sets_equivalent(list(sa), list(sb))
    return _proportional(a, b)


def _proportional(a: sp.Eq, b: sp.Eq) -> bool:
    da = sp.simplify(_exact(a.lhs) - _exact(a.rhs))
    db = sp.simplify(_exact(b.lhs) - _exact(b.rhs))
    if db == 0:
        return bool(da == 0)
    ratio = sp.simplify(da / db)
    return not ratio.free_symbols and ratio != 0


def solution_sets_equivalent(a: Sequence[sp.Expr], b: Sequence[sp.Expr]) -> bool:
    if len(a) != len(b):
        return False
    remaining = list(b)
    for root in a:
        match = next((r for r in remaining if expressions_equivalent(root, r)), None)
        if match is None:
            return False
        remaining.remove(match)
    return True
```

- [ ] **Step 8: Run the equivalence tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_equivalence.py -v`
Expected: PASS — 32 tests.

- [ ] **Step 9: Commit**

```bash
git add src/learnai/adapters/cas tests/adapters/test_parse.py tests/adapters/test_equivalence.py
git commit -m "feat: allowlisted math parser and CAS equivalence checking"
```

---

### Task 5: Answer checking with form constraints

**Files:**
- Create: `src/learnai/domain/verification.py`, `src/learnai/domain/ports.py`
- Create: `src/learnai/adapters/cas/vocabulary.py`, `src/learnai/adapters/cas/sympy_verifier.py`
- Test: `tests/adapters/test_sympy_verifier.py`

**Interfaces:**
- Consumes: `AnswerKind`, `Verdict` (Task 1); `AnswerSpec`, `FormConstraint`, `StepDiff` (Task 3); `parse_math`, the three equivalence functions (Task 4).
- Produces: `CheckResult(verdict: Verdict, failed_constraints: tuple[FormConstraint, ...], step_diff: StepDiff | None)`; the `Verifier` protocol with `check_answer(submission: Submission, spec: AnswerSpec) -> CheckResult`, `key_submission(spec: AnswerSpec) -> Submission`, `diff_steps(steps: Sequence[str]) -> StepDiff | None`, `extract_candidate_expressions(text: str) -> tuple[str, ...]`, `matches_answer(expression: str, spec: AnswerSpec) -> bool`; `supported_constraints -> frozenset[FormConstraint]`; `SympyVerifier` implementing it. In `adapters/cas/vocabulary.py`: the tokens `FULLY_FACTORED`, `EXPANDED`, `EXACT_NOT_DECIMAL`, `COMPLETED_SQUARE`, the set `MATH_CONSTRAINTS`, the errors `UnknownConstraintError`, `UnsupportedAnswerKindError` and `InvalidAnswerKeyError`, and the kind token `CAS_SYMBOLIC`. `parse.py` also exports `KNOWN_NAMES`. (`diff_steps` is stubbed to `None` in this task and implemented in Task 6.)

**Why the vocabulary lives here:** `_satisfies` is the only code in the system that ever interprets a form constraint, so the tokens belong beside it. A physics adapter will declare `correct_units` and `significant_figures` without touching the domain, which is the whole point of the `verification_kind` seam.

**Form constraints judge what the student wrote.** Evaluation distributes `4(x+2)` into `4x + 8`, so a check on the evaluated form marks a correct factorisation as unfactored and accepts `2(x+1)` typed back as an expansion. Every check therefore reads the written form (Task 4's `as_written=True`), and each has a stated definition in its docstring. There is no `simplified`: it names several different school rules, each of which becomes its own constraint when an item needs it.

**Content errors raise; only the student's own input is graded.** An unknown constraint or an answer key that does not parse raises before the submission is looked at. Reporting either as `MALFORMED` would tell the student their input was the problem.

**What counts as a leak** (for Task 13): text a student could copy into the answer field and be marked correct — or, for a list of values, any one of them. Plain equivalence would be too broad: the question `x^2 + 3x + 2` equals its answer `(x+1)(x+2)`, and quoting the problem is not a leak.

- [ ] **Step 1: Write the failing verifier test**

```python
# tests/adapters/test_sympy_verifier.py
import pytest

from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.cas.vocabulary import (
    COMPLETED_SQUARE,
    EXACT_NOT_DECIMAL,
    EXPANDED,
    FULLY_FACTORED,
    MATH_CONSTRAINTS,
    InvalidAnswerKeyError,
    UnknownConstraintError,
    UnsupportedAnswerKindError,
)
from learnai.domain.enums import AnswerKind, Verdict
from learnai.domain.items import AnswerSpec, FormConstraint, Submission, SubmissionShapeError

V = SympyVerifier()


def verdict(answer: str | Submission, spec: AnswerSpec) -> Verdict:
    submission = answer if isinstance(answer, Submission) else Submission.of(answer)
    return V.check_answer(submission, spec).verdict


def test_equivalent_answer_in_any_representation_is_correct():
    spec = AnswerSpec("1/2")
    for submitted in ("1/2", "0.5", "2/4"):
        assert verdict(submitted, spec) is Verdict.CORRECT


def test_wrong_answer_is_wrong():
    assert verdict("x + 3", AnswerSpec("x + 1")) is Verdict.WRONG


def test_unparseable_answer_is_malformed_not_wrong():
    assert verdict("x +* 2", AnswerSpec("x + 1")) is Verdict.MALFORMED


def test_a_blank_submission_is_no_answer():
    assert verdict("  ", AnswerSpec("x + 1")) is Verdict.NO_ANSWER


def test_naming_the_value_found_is_accepted():
    """A student asked for the vertex's x-coordinate writes "x = -3"."""
    assert verdict("x = -3", AnswerSpec("-3")) is Verdict.CORRECT


def test_an_equation_in_a_value_field_is_not_mistaken_for_a_named_value():
    assert verdict("x = x + 1", AnswerSpec("1")) is Verdict.MALFORMED


# -- form constraints judge what was written, not what SymPy normalises it to --


@pytest.mark.parametrize("written", ["(x+1)(x+2)", "4(x+2)", "2(x+1)(x+2)", "x^2 + 1", "-(x-1)(x+3)"])
def test_fully_factored_accepts_complete_factorisations(written):
    from learnai.adapters.cas.parse import parse_math

    key = AnswerSpec(str(parse_math(written)), (FULLY_FACTORED,))
    assert verdict(written, key) is Verdict.CORRECT


@pytest.mark.parametrize("written", ["x^2 + 3x + 2", "(2x+2)(x+2)", "(x^2 - 1)(x + 3)", "4x + 8"])
def test_fully_factored_rejects_what_can_still_be_factored(written):
    from learnai.adapters.cas.parse import parse_math

    key = AnswerSpec(str(parse_math(written)), (FULLY_FACTORED,))
    result = V.check_answer(Submission.of(written), key)
    assert result.verdict is Verdict.WRONG
    assert result.failed_constraints == (FULLY_FACTORED,)


def test_expanded_form_is_required_when_the_constraint_says_so():
    spec = AnswerSpec("x^2 + 3*x + 2", (EXPANDED,))
    assert verdict("x^2 + 3x + 2", spec) is Verdict.CORRECT
    assert verdict("(x+1)(x+2)", spec) is Verdict.WRONG
    assert verdict("x^2 + 2x + x + 2", spec) is Verdict.WRONG, "like terms must be combined"


def test_the_question_typed_back_is_not_expanded():
    """Evaluation would distribute 2(x+1) into 2x + 2; the student wrote no expansion."""
    assert verdict("2(x+1)", AnswerSpec("2*x + 2", (EXPANDED,))) is Verdict.WRONG


def test_completed_square_form_is_required_when_the_constraint_says_so():
    spec = AnswerSpec("(x + 3)**2 - 4", (COMPLETED_SQUARE,))
    assert verdict("(x+3)^2 - 4", spec) is Verdict.CORRECT

    result = V.check_answer(Submission.of("x^2 + 6x + 5"), spec)
    assert result.verdict is Verdict.WRONG
    assert result.failed_constraints == (COMPLETED_SQUARE,)


def test_a_product_of_two_brackets_is_not_a_completed_square():
    spec = AnswerSpec("(x + 3)**2 - 4", (COMPLETED_SQUARE,))
    assert verdict("(x+3)(x+3) - 4", spec) is Verdict.WRONG


def test_exact_form_rejects_a_decimal_for_an_exact_value():
    result = V.check_answer(Submission.of("0.5"), AnswerSpec("1/2", (EXACT_NOT_DECIMAL,)))
    assert result.verdict is Verdict.WRONG
    assert result.failed_constraints == (EXACT_NOT_DECIMAL,)


# -- answer kinds ---------------------------------------------------------------


def test_value_list_answers_ignore_order():
    spec = AnswerSpec("-1, 2", kind=AnswerKind.VALUE_SET)
    assert verdict(Submission.of("2", "-1"), spec) is Verdict.CORRECT
    assert verdict(Submission.of("-1"), spec) is Verdict.WRONG


def test_value_list_fields_may_name_their_values_and_leave_a_spare_blank():
    spec = AnswerSpec("2, -3", kind=AnswerKind.VALUE_SET)
    assert verdict(Submission.of("x = 2", "x = -3", ""), spec) is Verdict.CORRECT


def test_a_repeated_root_counts_once():
    spec = AnswerSpec("3", kind=AnswerKind.VALUE_SET)
    assert verdict(Submission.of("3", "3"), spec) is Verdict.CORRECT


def test_claiming_there_are_no_values_is_an_answer():
    assert verdict(Submission.none(), AnswerSpec("", kind=AnswerKind.VALUE_SET)) is Verdict.CORRECT
    assert verdict(Submission.none(), AnswerSpec("2", kind=AnswerKind.VALUE_SET)) is Verdict.WRONG


def test_value_list_constraints_apply_to_every_value():
    spec = AnswerSpec("1 + sqrt(2), 1 - sqrt(2)", (EXACT_NOT_DECIMAL,), kind=AnswerKind.VALUE_SET)
    assert verdict(Submission.of("1 - sqrt(2)", "1 + sqrt(2)"), spec) is Verdict.CORRECT
    assert verdict(Submission.of("2.414213", "-0.414213"), spec) is Verdict.WRONG


def test_equation_answers_compare_solution_sets():
    spec = AnswerSpec("x = 5", kind=AnswerKind.RELATION)
    assert verdict("2x = 10", spec) is Verdict.CORRECT
    assert verdict("x = 8", spec) is Verdict.WRONG
    assert verdict("5", spec) is Verdict.MALFORMED


def test_a_submission_of_the_wrong_shape_is_a_client_bug():
    with pytest.raises(SubmissionShapeError):
        V.check_answer(Submission.of("1", "2"), AnswerSpec("x + 1"))


def test_an_unsupported_answer_kind_raises_rather_than_guessing():
    """A kind this verifier cannot compare must never fall through to expressions.

    Every member is handled today, so the guard is exercised by passing a value
    the type system forbids — which is exactly the state a newly added member
    is in before someone writes its branch.
    """
    spec = AnswerSpec("x + 1", kind="ordered_sequence")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAnswerKindError):
        V.check_answer(Submission.of("x + 1"), spec)


# -- content errors are raised, never graded as the student's mistake -----------


def test_the_verifier_declares_the_vocabulary_it_can_judge():
    assert V.supported_constraints == MATH_CONSTRAINTS


def test_an_unknown_constraint_fails_loudly_even_when_the_answer_is_wrong():
    spec = AnswerSpec("x + 1", (FormConstraint("balanced_equation"),))
    with pytest.raises(UnknownConstraintError):
        V.check_answer(Submission.of("x + 9"), spec)


def test_an_answer_key_that_does_not_parse_is_a_content_error():
    with pytest.raises(InvalidAnswerKeyError):
        V.check_answer(Submission.of("x + 1"), AnswerSpec("x +* 1"))


def test_the_key_submission_is_what_a_student_would_enter():
    assert V.key_submission(AnswerSpec("-1, 2", kind=AnswerKind.VALUE_SET)) == Submission.of("-1", "2")
    assert V.key_submission(AnswerSpec("", kind=AnswerKind.VALUE_SET)) == Submission.none()
    assert V.key_submission(AnswerSpec("x + 1")) == Submission.of("x + 1")


# -- what the leak guard sees ----------------------------------------------------


@pytest.mark.parametrize(
    "prose,expected",
    [
        ("Try rewriting it as (x+1)(x+2) and see.", "(x+1)(x+2)"),
        ("So the roots are x = 2 and x = 3.", "3"),
        ("It factors as x² + 3x + 2 = (x + 1)(x + 2).", "(x + 1)(x + 2)"),
        ("It factors as x² + 3x + 2 = (x + 1)(x + 2).", "x^2 + 3x + 2"),
        ("The roots are 2, 3.", "2"),
        ("Inline maths like $(x+1)(x+2)$ is read too.", "(x+1)(x+2)"),
        ("Take √2 as given.", "sqrt(2)"),
    ],
)
def test_extracts_candidate_expressions_from_prose(prose, expected):
    assert expected in V.extract_candidate_expressions(prose)


def test_prose_words_are_never_candidates():
    assert V.extract_candidate_expressions("Take your time and read the question.") == ()


def test_a_leak_is_what_would_be_marked_correct():
    spec = AnswerSpec("(x + 1)*(x + 2)", (FULLY_FACTORED,))
    assert V.matches_answer("(x+2)(x+1)", spec)
    assert not V.matches_answer("x^2 + 3x + 2", spec), "quoting the question is not a leak"
    assert not V.matches_answer("x + 7", spec)


def test_revealing_any_one_root_is_a_leak():
    spec = AnswerSpec("2, 3", kind=AnswerKind.VALUE_SET)
    assert V.matches_answer("2", spec)
    assert V.matches_answer("x = 3", spec)
    assert not V.matches_answer("6", spec)


def test_an_equivalent_equation_leaks_a_relation():
    spec = AnswerSpec("x = 5", kind=AnswerKind.RELATION)
    assert V.matches_answer("2x = 10", spec)
    assert not V.matches_answer("x = 6", spec)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_sympy_verifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.adapters.cas.sympy_verifier'`

- [ ] **Step 3: Write the domain verification result and port**

```python
# src/learnai/domain/verification.py
from dataclasses import dataclass

from learnai.domain.enums import Verdict
from learnai.domain.items import FormConstraint, StepDiff


@dataclass(frozen=True, slots=True)
class CheckResult:
    verdict: Verdict
    failed_constraints: tuple[FormConstraint, ...] = ()
    step_diff: StepDiff | None = None
```

```python
# src/learnai/domain/ports.py
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from learnai.domain.items import AnswerSpec, FormConstraint, StepDiff, Submission
from learnai.domain.verification import CheckResult


class Verifier(Protocol):
    """Deterministic judgement of student work. Implementations are subject-specific."""

    @property
    def supported_constraints(self) -> frozenset[FormConstraint]:
        """The form vocabulary this adapter can judge. Content is validated against it."""
        ...

    def check_answer(self, submission: Submission, spec: AnswerSpec) -> CheckResult:
        """Grade a submission. A blank one is NO_ANSWER; an answer key or form
        constraint the adapter cannot use raises, because a content error must
        never be reported to the student as their mistake."""
        ...

    def key_submission(self, spec: AnswerSpec) -> Submission:
        """The submission that enters this item's answer key.

        Only the adapter can build it, because the key's format is the
        adapter's. It is what a reveal shows and what a test submits as right.
        """
        ...

    def diff_steps(self, steps: Sequence[str]) -> StepDiff | None: ...

    def extract_candidate_expressions(self, text: str) -> tuple[str, ...]: ...

    def matches_answer(self, expression: str, spec: AnswerSpec) -> bool:
        """Would this text, entered as the answer, give it away?

        The leak guard's definition of a leak: text a student could copy into the
        answer field and be marked correct — or, for a list of values, one of them.
        """
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...
```

- [ ] **Step 4: Write the adapter's form vocabulary**

```python
# src/learnai/adapters/cas/vocabulary.py
"""Everything this adapter names that the domain treats as opaque.

The core knows a skill has a verification kind and that an answer may carry
form requirements; it never knows what "cas_symbolic" or "fully_factored"
mean. This module is the only place the mathematical vocabulary is named, and
`sympy_verifier._satisfies` is the only place it is interpreted.

Answer keys use this adapter's format: a value in the parser's syntax, an
equation for a RELATION, and for a VALUE_SET the values separated by commas,
with an empty key meaning there are none.
"""
from learnai.domain.ids import VerificationKind
from learnai.domain.items import FormConstraint

CAS_SYMBOLIC = VerificationKind("cas_symbolic")

FULLY_FACTORED = FormConstraint("fully_factored")
EXPANDED = FormConstraint("expanded")
EXACT_NOT_DECIMAL = FormConstraint("exact_not_decimal")
COMPLETED_SQUARE = FormConstraint("completed_square")

# No "simplified": it has no single meaning — lowest terms, rationalised
# denominators and collected terms are separate school rules, each of which
# becomes its own constraint when an item needs it.
MATH_CONSTRAINTS: frozenset[FormConstraint] = frozenset(
    {FULLY_FACTORED, EXPANDED, EXACT_NOT_DECIMAL, COMPLETED_SQUARE}
)


class UnsupportedAnswerKindError(ValueError):
    """This verifier has no comparison for that answer kind.

    Raised rather than falling back to single-value comparison: a future
    ORDERED_SEQUENCE reaching the expression branch would be compared as one
    expression and quietly return wrong verdicts.
    """


class UnknownConstraintError(KeyError):
    """An item demands a form this verifier cannot judge.

    Raised rather than ignored: silently skipping an unknown constraint would
    mark a wrongly-formed answer correct, which is worse than a loud failure.
    """


class InvalidAnswerKeyError(ValueError):
    """An item's answer key does not parse, or asks for something it cannot.

    A content error, raised so it is fixed, never graded as the student's
    MALFORMED. The generator contract tests catch it before an item ships.
    """
```

- [ ] **Step 5: Write the SymPy verifier**

```python
# src/learnai/adapters/cas/sympy_verifier.py
import re
from collections.abc import Callable, Iterator, Sequence

import sympy as sp

from learnai.adapters.cas.equivalence import (
    equations_equivalent,
    expressions_equivalent,
    solution_sets_equivalent,
)
from learnai.adapters.cas.parse import KNOWN_NAMES, ParseError, evaluated, parse_math
from learnai.adapters.cas.vocabulary import (
    COMPLETED_SQUARE,
    EXACT_NOT_DECIMAL,
    EXPANDED,
    FULLY_FACTORED,
    MATH_CONSTRAINTS,
    InvalidAnswerKeyError,
    UnknownConstraintError,
    UnsupportedAnswerKindError,
)
from learnai.domain.enums import AnswerKind, Verdict
from learnai.domain.items import AnswerSpec, FormConstraint, StepDiff, Submission
from learnai.domain.verification import CheckResult

_SUPPORTED_KINDS = frozenset({AnswerKind.SINGLE_VALUE, AnswerKind.RELATION, AnswerKind.VALUE_SET})

# "x = -3" names the value found. Only a single letter, and only when it does
# not appear on the right: "x = x + 1" is an equation and stays one.
_NAMED_VALUE = re.compile(r"\s*([A-Za-z])\s*=(?!=)(.*)", re.S)

# Tutor prose arrives with typographic maths; the parser only reads ASCII.
_UNICODE_MATHS = str.maketrans(
    {"−": "-", "–": "-", "×": "*", "·": "*", "⋅": "*", "÷": "/", "²": "^2", "³": "^3"}
)
_ROOT_SIGN = re.compile(r"√\s*(\(|[0-9]+|[A-Za-z])")
_EDGE = ".,;:!?\"'`$"  # sentence punctuation, and the dollars of inline maths


class SympyVerifier:
    """Verifier for `cas_symbolic` skills."""

    @property
    def supported_constraints(self) -> frozenset[FormConstraint]:
        return MATH_CONSTRAINTS

    def check_answer(self, submission: Submission, spec: AnswerSpec) -> CheckResult:
        key = _parse_key(spec)  # content errors raise before the student is judged
        submission.check_shape(spec.kind)
        if submission.is_blank:
            return CheckResult(Verdict.NO_ANSWER)
        try:
            if spec.kind is AnswerKind.VALUE_SET:
                return _check_values(submission, key, spec.form_constraints)
            if spec.kind is AnswerKind.RELATION:
                return _check_relation(submission.fields[0], key)
            return _check_single(submission.fields[0], key, spec.form_constraints)
        except ParseError:
            return CheckResult(Verdict.MALFORMED)

    def key_submission(self, spec: AnswerSpec) -> Submission:
        if spec.kind is AnswerKind.VALUE_SET:
            values = _key_values(spec.expression)
            return Submission(tuple(values)) if values else Submission.none()
        return Submission.of(spec.expression)

    def diff_steps(self, steps: Sequence[str]) -> StepDiff | None:
        return None  # implemented in Task 6

    def extract_candidate_expressions(self, text: str) -> tuple[str, ...]:
        """Every stretch of maths in a piece of prose, and its parts.

        A word of two or more letters that is not a known function name ends a
        stretch, so "Try rewriting it as (x+1)(x+2) and see." yields
        "(x+1)(x+2)". Each side of an "=" and each item of a comma list is a
        candidate too, since any of them may be the answer on its own.
        """
        text = _ROOT_SIGN.sub(
            lambda m: "sqrt(" if m.group(1) == "(" else f"sqrt({m.group(1)})",
            text.translate(_UNICODE_MATHS),
        )
        found: list[str] = []
        for stretch in _maths_stretches(text):
            pieces = [stretch]
            if "=" in stretch:
                pieces += stretch.split("=")
            pieces += [item for piece in list(pieces) for item in piece.split(",")]
            for piece in pieces:
                piece = piece.strip(_EDGE + " ")
                if piece and piece not in found:
                    found.append(piece)
        return tuple(found)

    def matches_answer(self, expression: str, spec: AnswerSpec) -> bool:
        # Plain equivalence would be too broad: the question x^2 + 3x + 2 equals
        # its answer (x+1)(x+2), and quoting the problem is not a leak.
        if spec.kind is AnswerKind.VALUE_SET:
            key = _parse_key(spec)
            try:
                value = parse_math(_value_text(expression), as_written=True)
            except ParseError:
                return False
            return any(
                expressions_equivalent(value, k) for k in key
            ) and all(_satisfies(value, c) for c in spec.form_constraints)
        verdict = self.check_answer(Submission.of(expression), spec).verdict
        return verdict is Verdict.CORRECT


def _maths_stretches(text: str) -> Iterator[str]:
    current: list[str] = []
    for token in text.split():
        core = token.strip(_EDGE + "()")
        if core.isalpha() and len(core) > 1 and core.lower() not in KNOWN_NAMES:
            if current:
                yield " ".join(current).strip(_EDGE + " ")
            current = []
        else:
            current.append(token)
    if current:
        yield " ".join(current).strip(_EDGE + " ")


def _parse_key(spec: AnswerSpec) -> object:
    if spec.kind not in _SUPPORTED_KINDS:
        raise UnsupportedAnswerKindError(spec.kind)
    if unknown := set(spec.form_constraints) - MATH_CONSTRAINTS:
        raise UnknownConstraintError(sorted(unknown))
    try:
        if spec.kind is AnswerKind.VALUE_SET:
            return [parse_math(v) for v in _key_values(spec.expression)]
        if spec.kind is AnswerKind.RELATION:
            if spec.form_constraints:
                raise InvalidAnswerKeyError("form constraints apply to values, not relations")
            key = parse_math(spec.expression, allow_equation=True, as_written=True)
            if not isinstance(key, sp.Eq):
                raise InvalidAnswerKeyError(f"relation key {spec.expression!r} is not an equation")
            return key
        return parse_math(spec.expression)
    except ParseError as exc:
        raise InvalidAnswerKeyError(f"answer key {spec.expression!r} does not parse") from exc


def _key_values(expression: str) -> list[str]:
    return [v for v in (part.strip() for part in expression.split(",")) if v]


def _value_text(field: str) -> str:
    """'x = -3' reads as '-3': naming the value found is not part of the value."""
    named = _NAMED_VALUE.fullmatch(field)
    if named is None:
        return field
    try:
        value = parse_math(named.group(2))
    except ParseError:
        return field
    return named.group(2) if sp.Symbol(named.group(1)) not in value.free_symbols else field


def _check_single(
    field: str, key: sp.Expr, constraints: tuple[FormConstraint, ...]
) -> CheckResult:
    written = parse_math(_value_text(field), as_written=True)
    if not expressions_equivalent(written, key):
        return CheckResult(Verdict.WRONG)
    failed = tuple(c for c in constraints if not _satisfies(written, c))
    return CheckResult(Verdict.WRONG, failed) if failed else CheckResult(Verdict.CORRECT)


def _check_relation(field: str, key: sp.Eq) -> CheckResult:
    written = parse_math(field, allow_equation=True, as_written=True)
    if not isinstance(written, sp.Eq):
        return CheckResult(Verdict.MALFORMED)
    return CheckResult(Verdict.CORRECT if equations_equivalent(written, key) else Verdict.WRONG)


def _check_values(
    submission: Submission, key: list[sp.Expr], constraints: tuple[FormConstraint, ...]
) -> CheckResult:
    if submission.claims_none:
        return CheckResult(Verdict.CORRECT if not key else Verdict.WRONG)
    written = [parse_math(_value_text(field), as_written=True) for field in submission.entries]
    # A set: a repeated root is one solution, however many times it is entered.
    if not solution_sets_equivalent(_distinct(written), _distinct(key)):
        return CheckResult(Verdict.WRONG)
    failed = tuple(c for c in constraints if not all(_satisfies(v, c) for v in written))
    return CheckResult(Verdict.WRONG, failed) if failed else CheckResult(Verdict.CORRECT)


def _distinct(values: Sequence[sp.Expr]) -> list[sp.Expr]:
    kept: list[sp.Expr] = []
    for value in values:
        if not any(expressions_equivalent(value, seen) for seen in kept):
            kept.append(value)
    return kept


# -- form constraints, judged on what the student wrote ------------------------


def _factors(expr: sp.Basic) -> Iterator[sp.Basic]:
    """The multiplicands of a written product, however the parser nested them."""
    if isinstance(expr, sp.Mul):
        for arg in expr.args:
            yield from _factors(arg)
    else:
        yield expr


def _terms(expr: sp.Basic) -> Iterator[sp.Basic]:
    """The summands of a written sum, however the parser nested them."""
    if isinstance(expr, sp.Add):
        for arg in expr.args:
            yield from _terms(arg)
    else:
        yield expr


def _is_fully_factored(written: sp.Expr) -> bool:
    """Every factor is irreducible over the rationals, with no whole number left inside it.

    4(x+2) passes; (2x+2)(x+2) does not, since the 2 inside the first factor is
    still common; x^2 + 1 passes, since it cannot be factored over the rationals.
    """
    for factor in _factors(written):
        base = factor.base if isinstance(factor, sp.Pow) else factor
        if base.is_number:
            continue
        try:
            content, irreducibles = sp.factor_list(evaluated(base))
        except sp.PolynomialError:
            continue  # not a polynomial: nothing left to factor at school level
        if abs(content) != 1 or len(irreducibles) != 1 or irreducibles[0][1] != 1:
            return False
    return True


def _is_expanded(written: sp.Expr) -> bool:
    """No product or power of a sum remains, and like terms are combined."""
    for node in sp.preorder_traversal(written):
        if isinstance(node, sp.Mul) and any(isinstance(f, sp.Add) for f in _factors(node)):
            return False
        if isinstance(node, sp.Pow) and isinstance(node.base, sp.Add):
            if node.exp.is_Integer and node.exp > 1:
                return False
    combined = sp.Add.make_args(sp.expand(evaluated(written)))
    return len(list(_terms(written))) == len(combined)


def _is_square_of_sum(term: sp.Basic) -> bool:
    factors = list(_factors(term))
    squares = [
        f for f in factors if isinstance(f, sp.Pow) and isinstance(f.base, sp.Add) and f.exp == 2
    ]
    return len(squares) == 1 and all(f.is_number for f in factors if f is not squares[0])


def _is_completed_square(written: sp.Expr) -> bool:
    """a(x + p)^2 + q: one squared sum, optionally times a number, and at most one number beside it."""
    squares = numbers = others = 0
    for term in _terms(written):
        if term.is_number:
            numbers += 1
        elif _is_square_of_sum(term):
            squares += 1
        else:
            others += 1
    return squares == 1 and numbers <= 1 and others == 0


_FORM_CHECKS: dict[FormConstraint, Callable[[sp.Expr], bool]] = {
    FULLY_FACTORED: _is_fully_factored,
    EXPANDED: _is_expanded,
    EXACT_NOT_DECIMAL: lambda written: not written.atoms(sp.Float),
    COMPLETED_SQUARE: _is_completed_square,
}
assert set(_FORM_CHECKS) == MATH_CONSTRAINTS, "declared vocabulary and checks disagree"


def _satisfies(written: sp.Expr, constraint: FormConstraint) -> bool:
    """Judge a form constraint on the written form: 4(x+2) must still look factored."""
    check = _FORM_CHECKS.get(constraint)
    if check is None:
        raise UnknownConstraintError(constraint)
    return check(written)
```

- [ ] **Step 6: Run the verifier tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_sympy_verifier.py -v`
Expected: PASS — 43 tests.

- [ ] **Step 7: Run the whole suite, including the purity test**

Run: `.venv/bin/pytest -v`
Expected: PASS. `tests/test_domain_purity.py` must still pass — `verification.py` and `ports.py` import no SymPy.

- [ ] **Step 8: Commit**

```bash
git add src/learnai/domain/verification.py src/learnai/domain/ports.py \
        src/learnai/adapters/cas/vocabulary.py src/learnai/adapters/cas/sympy_verifier.py tests/adapters/test_sympy_verifier.py
git commit -m "feat: answer checking with form constraints and answer kinds"
```

---

### Task 6: Step diffing — localise the broken step

**Files:**
- Modify: `src/learnai/adapters/cas/sympy_verifier.py` (replace the `diff_steps` stub)
- Test: `tests/adapters/test_step_diff.py`

**Interfaces:**
- Consumes: `StepDiff` (Task 3), equivalence functions (Task 4), `SympyVerifier` (Task 5).
- Produces: `SympyVerifier.diff_steps(steps) -> StepDiff | None` returning the **first** transition at which equivalence breaks, with `index` being the index of the offending step (so `steps[index - 1] -> steps[index]` is the broken transition).

**Note on mixed step types:** algebra steps alternate between expressions (`x^2 + 3x + 2`) and equations (`2x = 10`). Equations compare by solution set, expressions by value. A transition from one kind to the other is treated as broken, because it is a change of claim rather than a manipulation.

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_step_diff.py
from learnai.adapters.cas.sympy_verifier import SympyVerifier

V = SympyVerifier()


def test_correct_expression_work_has_no_diff():
    assert V.diff_steps(["(x+1)(x+2)", "x^2 + 3x + 2", "x^2 + 3x + 2"]) is None


def test_correct_equation_work_has_no_diff():
    assert V.diff_steps(["2x + 4 = 10", "2x = 6", "x = 3"]) is None


def test_arithmetic_slip_is_localised():
    diff = V.diff_steps(["2x + 4 = 10", "2x = 6", "x = 8"])
    assert diff is not None
    assert diff.index == 2
    assert diff.previous == "2x = 6"
    assert diff.current == "x = 8"


def test_the_first_break_is_reported_not_the_last():
    diff = V.diff_steps(["x + 1 = 5", "x = 9", "x = 100"])
    assert diff is not None and diff.index == 1


def test_expansion_error_is_localised():
    diff = V.diff_steps(["(x+3)^2", "x^2 + 9"])
    assert diff is not None and diff.index == 1


def test_switching_between_expression_and_equation_breaks():
    diff = V.diff_steps(["2x = 6", "2x"])
    assert diff is not None and diff.index == 1


def test_a_single_step_can_never_break():
    assert V.diff_steps(["x = 3"]) is None


def test_unparseable_step_is_reported_at_its_index():
    diff = V.diff_steps(["2x = 6", "x =* 3"])
    assert diff is not None and diff.index == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_step_diff.py -v`
Expected: FAIL — six tests fail with `assert None is not None`, because the stub always returns `None`.

- [ ] **Step 3: Replace the stub**

```python
    def diff_steps(self, steps: Sequence[str]) -> StepDiff | None:
        if len(steps) < 2:
            return None

        parsed: list[sp.Basic | None] = []
        for raw in steps:
            try:
                # Written form: an equation step must keep its holes (Task 4).
                parsed.append(parse_math(raw, allow_equation=True, as_written=True))
            except ParseError:
                parsed.append(None)

        for i in range(1, len(parsed)):
            previous, current = parsed[i - 1], parsed[i]
            if current is None or previous is None:
                return StepDiff(index=i, previous=steps[i - 1], current=steps[i])
            if not _steps_equivalent(previous, current):
                return StepDiff(index=i, previous=steps[i - 1], current=steps[i])
        return None
```

Add the module-level helper below `_satisfies`:

```python
def _steps_equivalent(a: sp.Basic, b: sp.Basic) -> bool:
    a_is_eq, b_is_eq = isinstance(a, sp.Eq), isinstance(b, sp.Eq)
    if a_is_eq != b_is_eq:
        return False
    if a_is_eq:
        return equations_equivalent(a, b)
    return expressions_equivalent(a, b)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_step_diff.py -v`
Expected: PASS — 8 tests.

- [ ] **Step 5: Commit**

```bash
git add src/learnai/adapters/cas/sympy_verifier.py tests/adapters/test_step_diff.py
git commit -m "feat: localise the first broken step in student work"
```

---

### Task 7: Quadratics generators, registry, and contract tests

**Files:**
- Create: `src/learnai/adapters/content/types.py`, `src/learnai/adapters/content/generators/__init__.py`, `src/learnai/adapters/content/generators/quadratics.py`, `src/learnai/adapters/content/registry.py`
- Modify: `src/learnai/domain/ports.py` (add the `ItemSource` protocol)
- Test: `tests/content/__init__.py`, `tests/content/test_generator_contracts.py`

**Interfaces:**
- Consumes: `AnswerKind` (Task 1); `Item`, `AnswerSpec`, `FormConstraint`, `Provenance` (Task 3); `SympyVerifier` (Tasks 5–6).
- Produces: `GeneratedProblem(statement, prompt_expression, answer, form_constraints, kind, worked_steps)`; `TemplateSpec(id, skill_id, difficulty, generate)`; `QUADRATICS_TEMPLATES: tuple[TemplateSpec, ...]` (twelve, one per skill); `GeneratorRegistry` with `all_templates()`, `templates_for(skill_id)`, `instantiate(template_id, seed) -> Item`, `instantiate_raw(template_id, seed) -> GeneratedProblem`, and `next_item(skill_id, target_difficulty, seed) -> Item`; `ItemSource` protocol in `domain/ports.py`.

**Determinism contract:** `instantiate(template_id, seed)` must return an identical `Item` for identical arguments, forever. Item ids are `f"{template_id}#{seed}"`, so an item a student saw is reproducible from two values rather than stored.

- [ ] **Step 1: Write the content types and the ItemSource port**

```python
# src/learnai/adapters/content/types.py
import random
from collections.abc import Callable
from dataclasses import dataclass

from learnai.domain.enums import AnswerKind
from learnai.domain.ids import SkillId, TemplateId
from learnai.domain.items import FormConstraint


@dataclass(frozen=True, slots=True)
class GeneratedProblem:
    statement: str
    prompt_expression: str | None
    """The bare mathematics the student is asked to transform, if any.

    Used by the contract tests to assert a template never hands back a problem
    that is already in its own answer form.
    """
    answer: str
    form_constraints: tuple[FormConstraint, ...]
    kind: AnswerKind
    worked_steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    id: TemplateId
    skill_id: SkillId
    difficulty: float
    """Author-declared, in logits, replaced by empirical values once data exists."""
    generate: Callable[[random.Random], GeneratedProblem]
```

Append to `src/learnai/domain/ports.py`:

```python
class ItemSource(Protocol):
    def next_item(self, skill_id: SkillId, target_difficulty: float, seed: int) -> Item: ...
```

and extend its imports to `from learnai.domain.ids import SkillId` and `from learnai.domain.items import AnswerSpec, Item, StepDiff`.

- [ ] **Step 2: Write the twelve generators**

```python
# src/learnai/adapters/content/generators/quadratics.py
import random

import sympy as sp

from learnai.adapters.cas.vocabulary import (
    COMPLETED_SQUARE,
    EXACT_NOT_DECIMAL,
    EXPANDED,
    FULLY_FACTORED,
)
from learnai.adapters.content.types import GeneratedProblem, TemplateSpec
from learnai.domain.enums import AnswerKind
from learnai.domain.ids import SkillId, TemplateId

X = sp.Symbol("x")


def _nonzero(rng: random.Random, lo: int = -9, hi: int = 9) -> int:
    value = 0
    while value == 0:
        value = rng.randint(lo, hi)
    return value


def expand_binomial(rng: random.Random) -> GeneratedProblem:
    a = _nonzero(rng)
    b = _nonzero(rng)
    while b == a:
        b = _nonzero(rng)
    prompt = (X + a) * (X + b)
    answer = sp.expand(prompt)
    return GeneratedProblem(
        statement=f"Expand and simplify: {sp.sstr(prompt)}",
        prompt_expression=sp.sstr(prompt),
        answer=sp.sstr(answer),
        form_constraints=(EXPANDED,),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(sp.sstr(prompt), sp.sstr(answer)),
    )


def expand_square(rng: random.Random) -> GeneratedProblem:
    a = _nonzero(rng)
    prompt = (X + a) ** 2
    answer = sp.expand(prompt)
    return GeneratedProblem(
        statement=f"Expand and simplify: {sp.sstr(prompt)}",
        prompt_expression=sp.sstr(prompt),
        answer=sp.sstr(answer),
        form_constraints=(EXPANDED,),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(sp.sstr(prompt), sp.sstr(answer)),
    )


def factor_common(rng: random.Random) -> GeneratedProblem:
    coefficient = rng.randint(2, 6)
    power = rng.randint(0, 1)
    p = rng.randint(2, 7)
    q = _nonzero(rng)
    while sp.gcd(p, q) != 1:
        q = _nonzero(rng)
    prompt = sp.expand(coefficient * X**power * (p * X + q))
    answer = sp.factor(prompt)
    return GeneratedProblem(
        statement=f"Factor completely: {sp.sstr(prompt)}",
        prompt_expression=sp.sstr(prompt),
        answer=sp.sstr(answer),
        form_constraints=(FULLY_FACTORED,),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(sp.sstr(prompt), sp.sstr(answer)),
    )


def factor_monic(rng: random.Random) -> GeneratedProblem:
    r1, r2 = _nonzero(rng), _nonzero(rng)
    prompt = sp.expand((X - r1) * (X - r2))
    answer = sp.factor(prompt)
    return GeneratedProblem(
        statement=f"Factor: {sp.sstr(prompt)}",
        prompt_expression=sp.sstr(prompt),
        answer=sp.sstr(answer),
        form_constraints=(FULLY_FACTORED,),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(sp.sstr(prompt), sp.sstr(answer)),
    )


def factor_difference_of_squares(rng: random.Random) -> GeneratedProblem:
    a, b = rng.randint(1, 6), rng.randint(1, 9)
    prompt = sp.expand(a**2 * X**2 - b**2)
    answer = sp.factor(prompt)
    return GeneratedProblem(
        statement=f"Factor: {sp.sstr(prompt)}",
        prompt_expression=sp.sstr(prompt),
        answer=sp.sstr(answer),
        form_constraints=(FULLY_FACTORED,),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(sp.sstr(prompt), sp.sstr(answer)),
    )


def factor_nonmonic(rng: random.Random) -> GeneratedProblem:
    p, r = rng.randint(2, 5), rng.randint(2, 5)
    q, s = _nonzero(rng, -7, 7), _nonzero(rng, -7, 7)
    prompt = sp.expand((p * X + q) * (r * X + s))
    answer = sp.factor(prompt)
    return GeneratedProblem(
        statement=f"Factor: {sp.sstr(prompt)}",
        prompt_expression=sp.sstr(prompt),
        answer=sp.sstr(answer),
        form_constraints=(FULLY_FACTORED,),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(sp.sstr(prompt), sp.sstr(answer)),
    )


def solve_by_factoring(rng: random.Random) -> GeneratedProblem:
    r1, r2 = _nonzero(rng), _nonzero(rng)
    lhs = sp.expand((X - r1) * (X - r2))
    roots = sorted({r1, r2})
    return GeneratedProblem(
        statement=f"Solve for x: {sp.sstr(lhs)} = 0",
        prompt_expression=None,
        answer=", ".join(str(r) for r in roots),
        form_constraints=(),
        kind=AnswerKind.VALUE_SET,
        worked_steps=(f"{sp.sstr(lhs)} = 0", f"{sp.sstr(sp.factor(lhs))} = 0"),
    )


def complete_the_square(rng: random.Random) -> GeneratedProblem:
    p = _nonzero(rng, -7, 7)
    q = rng.randint(-20, 20)
    answer = (X + p) ** 2 + q
    prompt = sp.expand(answer)
    return GeneratedProblem(
        statement=f"Rewrite by completing the square: {sp.sstr(prompt)}",
        prompt_expression=sp.sstr(prompt),
        answer=sp.sstr(answer),
        form_constraints=(COMPLETED_SQUARE,),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(sp.sstr(prompt), sp.sstr(answer)),
    )


def apply_quadratic_formula(rng: random.Random) -> GeneratedProblem:
    for _ in range(200):
        a = rng.randint(1, 3)
        b = _nonzero(rng)
        c = _nonzero(rng)
        discriminant = b * b - 4 * a * c
        if discriminant > 0 and not sp.sqrt(discriminant).is_Integer:
            break
    else:  # pragma: no cover - the search succeeds within a few draws in practice
        a, b, c = 1, 1, -1
    roots = sp.solve(sp.Eq(a * X**2 + b * X + c, 0), X)
    return GeneratedProblem(
        statement=f"Solve exactly using the quadratic formula: {sp.sstr(a * X**2 + b * X + c)} = 0",
        prompt_expression=None,
        answer=", ".join(sp.sstr(r) for r in roots),
        form_constraints=(EXACT_NOT_DECIMAL,),
        kind=AnswerKind.VALUE_SET,
        worked_steps=(),
    )


def count_real_roots(rng: random.Random) -> GeneratedProblem:
    a = rng.randint(1, 3)
    b = _nonzero(rng)
    c = rng.randint(-9, 9)
    discriminant = b * b - 4 * a * c
    count = 2 if discriminant > 0 else (1 if discriminant == 0 else 0)
    return GeneratedProblem(
        statement=(
            f"How many distinct real roots does {sp.sstr(a * X**2 + b * X + c)} = 0 have? "
            "Answer 0, 1, or 2."
        ),
        prompt_expression=None,
        answer=str(count),
        form_constraints=(),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(),
    )


def vertex_x_coordinate(rng: random.Random) -> GeneratedProblem:
    a = _nonzero(rng, -4, 4)
    b = _nonzero(rng)
    c = rng.randint(-9, 9)
    return GeneratedProblem(
        statement=(
            "Find the x-coordinate of the vertex of "
            f"y = {sp.sstr(a * X**2 + b * X + c)}. Give an exact value."
        ),
        prompt_expression=None,
        answer=sp.sstr(sp.Rational(-b, 2 * a)),
        form_constraints=(EXACT_NOT_DECIMAL,),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(),
    )


def rectangle_area_word_problem(rng: random.Random) -> GeneratedProblem:
    width = rng.randint(2, 12)
    extra = rng.randint(1, 9)
    area = width * (width + extra)
    return GeneratedProblem(
        statement=(
            f"A rectangle is {extra} cm longer than it is wide. "
            f"Its area is {area} cm^2. Find its width in cm."
        ),
        prompt_expression=None,
        answer=str(width),
        form_constraints=(),
        kind=AnswerKind.SINGLE_VALUE,
        worked_steps=(),
    )


QUADRATICS_TEMPLATES: tuple[TemplateSpec, ...] = (
    TemplateSpec(TemplateId("quad.expand.binomial.v1"), SkillId("quad.expand.binomial"), -1.0, expand_binomial),
    TemplateSpec(TemplateId("quad.expand.square.v1"), SkillId("quad.expand.square"), -0.5, expand_square),
    TemplateSpec(TemplateId("quad.factor.common.v1"), SkillId("quad.factor.common"), -0.5, factor_common),
    TemplateSpec(TemplateId("quad.factor.monic.v1"), SkillId("quad.factor.monic"), 0.0, factor_monic),
    TemplateSpec(TemplateId("quad.factor.diffsquares.v1"), SkillId("quad.factor.diffsquares"), 0.0, factor_difference_of_squares),
    TemplateSpec(TemplateId("quad.factor.nonmonic.v1"), SkillId("quad.factor.nonmonic"), 1.0, factor_nonmonic),
    TemplateSpec(TemplateId("quad.solve.factoring.v1"), SkillId("quad.solve.factoring"), 0.5, solve_by_factoring),
    TemplateSpec(TemplateId("quad.completesquare.v1"), SkillId("quad.completesquare"), 1.0, complete_the_square),
    TemplateSpec(TemplateId("quad.formula.apply.v1"), SkillId("quad.formula.apply"), 1.0, apply_quadratic_formula),
    TemplateSpec(TemplateId("quad.discriminant.v1"), SkillId("quad.discriminant"), 0.5, count_real_roots),
    TemplateSpec(TemplateId("quad.vertex.v1"), SkillId("quad.vertex"), 0.5, vertex_x_coordinate),
    TemplateSpec(TemplateId("quad.word.area.v1"), SkillId("quad.word.area"), 1.5, rectangle_area_word_problem),
)
```

- [ ] **Step 3: Write the registry**

```python
# src/learnai/adapters/content/registry.py
import random
from collections.abc import Iterable

from learnai.adapters.content.types import GeneratedProblem, TemplateSpec
from learnai.domain.enums import VettingLevel
from learnai.domain.ids import ItemId, SkillId, TemplateId
from learnai.domain.items import AnswerSpec, Item, Provenance


class GeneratorRegistry:
    """An ItemSource backed by deterministic parameterised generators."""

    def __init__(self, specs: Iterable[TemplateSpec]) -> None:
        self._by_id: dict[TemplateId, TemplateSpec] = {s.id: s for s in specs}
        self._by_skill: dict[SkillId, list[TemplateSpec]] = {}
        for spec in self._by_id.values():
            self._by_skill.setdefault(spec.skill_id, []).append(spec)

    def all_templates(self) -> tuple[TemplateSpec, ...]:
        return tuple(self._by_id.values())

    def templates_for(self, skill_id: SkillId) -> tuple[TemplateSpec, ...]:
        return tuple(self._by_skill.get(skill_id, ()))

    def instantiate_raw(self, template_id: TemplateId, seed: int) -> GeneratedProblem:
        spec = self._by_id[template_id]
        return spec.generate(random.Random(f"{template_id}:{seed}"))

    def instantiate(self, template_id: TemplateId, seed: int) -> Item:
        spec = self._by_id[template_id]
        problem = self.instantiate_raw(template_id, seed)
        return Item(
            id=ItemId(f"{template_id}#{seed}"),
            skill_id=spec.skill_id,
            provenance=Provenance.generated(template_id, seed),
            statement=problem.statement,
            answer_spec=AnswerSpec(
                expression=problem.answer,
                form_constraints=problem.form_constraints,
                kind=problem.kind,
            ),
            worked_steps=problem.worked_steps,
            difficulty=spec.difficulty,
            vetting_level=VettingLevel.MACHINE_VERIFIED,
        )

    def next_item(self, skill_id: SkillId, target_difficulty: float, seed: int) -> Item:
        candidates = self.templates_for(skill_id)
        if not candidates:
            raise KeyError(f"no template registered for skill {skill_id}")
        chosen = min(candidates, key=lambda s: abs(s.difficulty - target_difficulty))
        return self.instantiate(chosen.id, seed)
```

- [ ] **Step 4: Write the contract tests**

These are the tests that keep a wrong answer key from ever reaching an unassisted check.

```python
# tests/content/test_generator_contracts.py
import pytest
import sympy as sp

from learnai.adapters.cas.parse import parse_math
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.domain.enums import AnswerKind, Verdict
from learnai.domain.items import Submission

REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)
VERIFIER = SympyVerifier()

LIGHT_SEEDS = 300
DEEP_SEEDS = 50


def ids(spec):
    return str(spec.id)


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_generation_is_deterministic_and_well_formed(spec):
    for seed in range(LIGHT_SEEDS):
        item = REGISTRY.instantiate(spec.id, seed)
        assert item == REGISTRY.instantiate(spec.id, seed), "generator is not deterministic"
        assert item.statement.strip()
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
def test_no_degenerate_coefficients(spec):
    for seed in range(DEEP_SEEDS):
        problem = REGISTRY.instantiate_raw(spec.id, seed)
        expr_text = problem.prompt_expression or problem.statement
        for number in parse_math(problem.answer).atoms(sp.Integer) if problem.kind is AnswerKind.SINGLE_VALUE else ():
            assert abs(int(number)) <= 400, f"{spec.id} seed {seed} produced a wild coefficient"
        assert "zoo" not in expr_text and "nan" not in expr_text


@pytest.mark.parametrize("spec", QUADRATICS_TEMPLATES, ids=ids)
def test_every_emitted_constraint_is_supported_by_the_verifier(spec):
    """The load-time gate that replaces the old enum's compile-time safety."""
    for seed in range(DEEP_SEEDS):
        problem = REGISTRY.instantiate_raw(spec.id, seed)
        unknown = set(problem.form_constraints) - VERIFIER.supported_constraints
        assert not unknown, f"{spec.id} emits constraints the verifier cannot judge: {unknown}"


def test_next_item_picks_the_closest_difficulty_band():
    from learnai.domain.ids import SkillId

    item = REGISTRY.next_item(SkillId("quad.factor.monic"), target_difficulty=0.0, seed=7)
    assert item.skill_id == SkillId("quad.factor.monic")
    assert item.difficulty == 0.0


def test_unknown_skill_raises():
    from learnai.domain.ids import SkillId

    with pytest.raises(KeyError):
        REGISTRY.next_item(SkillId("nope"), target_difficulty=0.0, seed=1)


def test_every_skill_in_the_cluster_has_a_template():
    import pathlib

    from learnai.adapters.content.loader import load_cluster

    cluster = load_cluster(
        pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
    )
    covered = {spec.skill_id for spec in QUADRATICS_TEMPLATES}
    assert set(cluster.graph.skills) == covered
```

- [ ] **Step 5: Run the contract tests**

Run: `.venv/bin/pytest tests/content/test_generator_contracts.py -v`
Expected: PASS — 75 tests (six parametrised suites over twelve templates, plus three standalone). This is the slowest suite in the project; if it exceeds about 90 seconds, lower `DEEP_SEEDS` to 30 rather than weakening an assertion.

- [ ] **Step 6: Commit**

```bash
git add src/learnai/adapters/content src/learnai/domain/ports.py tests/content
git commit -m "feat: twelve CAS-verified quadratics generators with contract tests"
```

---

### Task 8: Misconception diagnosis

**Files:**
- Create: `src/learnai/domain/misconceptions.py`
- Create: `src/learnai/adapters/cas/misconception_rules.py`
- Test: `tests/domain/test_diagnosis.py`, `tests/adapters/test_misconception_rules.py`

**Interfaces:**
- Consumes: `StepDiff` (Task 3), `Misconception` (Task 1), equivalence functions (Task 4).
- Produces: `MisconceptionMatcher` protocol with `exhibits(signature: str, previous: str, current: str) -> bool`; `diagnose(step_diff, candidates, matcher) -> MisconceptionId | None` in the domain; `SympyMisconceptionRules` implementing the protocol, with `IMPLEMENTED_SIGNATURES: frozenset[str]` and `DEFERRED_SIGNATURES: frozenset[str]`.

**Scope decision — six rules, six deferred.** Rules are written for the six skills a Slice 1 Practice session actually reaches from an empty frontier: `product_of_sums_drops_cross`, `square_distributes_over_sum`, `incomplete_common_factor`, `factor_sign_flip`, `sum_of_squares_factored`, `zero_product_without_zero`. The remaining six signatures are declared in `DEFERRED_SIGNATURES` and return `False` cleanly, so diagnosis degrades to "novel error" rather than crashing. A test asserts every signature in the content file is in exactly one of the two sets, so a new misconception cannot be added without a decision being made about it.

- [ ] **Step 1: Write the failing domain test**

```python
# tests/domain/test_diagnosis.py
from learnai.domain.ids import MisconceptionId
from learnai.domain.items import StepDiff
from learnai.domain.misconceptions import diagnose
from learnai.domain.skills import Misconception


class StubMatcher:
    def __init__(self, matching: set[str]) -> None:
        self.matching = matching
        self.calls: list[str] = []

    def exhibits(self, signature: str, previous: str, current: str) -> bool:
        self.calls.append(signature)
        return signature in self.matching


def mc(mid: str, signature: str) -> Misconception:
    return Misconception(
        id=MisconceptionId(mid),
        subject_id="math",
        name=mid,
        description="",
        signature=signature,
    )


DIFF = StepDiff(index=1, previous="(x+3)^2", current="x^2 + 9")


def test_returns_the_matching_misconception():
    matcher = StubMatcher({"sig_b"})
    found = diagnose(DIFF, [mc("m_a", "sig_a"), mc("m_b", "sig_b")], matcher)
    assert found == MisconceptionId("m_b")


def test_returns_none_when_nothing_matches():
    assert diagnose(DIFF, [mc("m_a", "sig_a")], StubMatcher(set())) is None


def test_returns_none_for_no_diff():
    assert diagnose(None, [mc("m_a", "sig_a")], StubMatcher({"sig_a"})) is None


def test_first_declared_match_wins_and_stops_evaluating():
    matcher = StubMatcher({"sig_a", "sig_b"})
    found = diagnose(DIFF, [mc("m_a", "sig_a"), mc("m_b", "sig_b")], matcher)
    assert found == MisconceptionId("m_a")
    assert matcher.calls == ["sig_a"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_diagnosis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.domain.misconceptions'`

- [ ] **Step 3: Write the domain diagnosis policy**

```python
# src/learnai/domain/misconceptions.py
from collections.abc import Sequence
from typing import Protocol

from learnai.domain.ids import MisconceptionId
from learnai.domain.items import StepDiff
from learnai.domain.skills import Misconception


class MisconceptionMatcher(Protocol):
    def exhibits(self, signature: str, previous: str, current: str) -> bool: ...


def diagnose(
    step_diff: StepDiff | None,
    candidates: Sequence[Misconception],
    matcher: MisconceptionMatcher,
) -> MisconceptionId | None:
    """Name the belief behind a broken step, if a catalogued one explains it.

    Candidates are tried in declaration order and the first match wins: the
    content author's ordering is the priority, not the matcher's.
    """
    if step_diff is None:
        return None
    for candidate in candidates:
        if matcher.exhibits(candidate.signature, step_diff.previous, step_diff.current):
            return candidate.id
    return None
```

- [ ] **Step 4: Run the domain test to verify it passes**

Run: `.venv/bin/pytest tests/domain/test_diagnosis.py -v`
Expected: PASS — 4 tests.

- [ ] **Step 5: Write the failing rules test**

```python
# tests/adapters/test_misconception_rules.py
import pathlib

import pytest

from learnai.adapters.cas.misconception_rules import (
    DEFERRED_SIGNATURES,
    IMPLEMENTED_SIGNATURES,
    SympyMisconceptionRules,
)
from learnai.adapters.content.loader import load_cluster

RULES = SympyMisconceptionRules()
CLUSTER = pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"


@pytest.mark.parametrize(
    "signature,previous,current",
    [
        ("square_distributes_over_sum", "(x+3)^2", "x^2 + 9"),
        ("product_of_sums_drops_cross", "(x+2)(x+5)", "x^2 + 10"),
        ("incomplete_common_factor", "12x^2 + 18x", "2*(6x^2 + 9x)"),
        ("factor_sign_flip", "x^2 + 3x + 2", "(x-1)(x-2)"),
        ("sum_of_squares_factored", "x^2 + 9", "(x+3)(x+3)"),
        ("zero_product_without_zero", "(x-1)(x-2) = 6", "x = 7, x = 8"),
    ],
)
def test_each_implemented_rule_fires_on_its_own_error(signature, previous, current):
    assert RULES.exhibits(signature, previous, current)


@pytest.mark.parametrize("signature", sorted(IMPLEMENTED_SIGNATURES))
def test_no_rule_fires_on_correct_work(signature):
    assert not RULES.exhibits(signature, "(x+3)^2", "x^2 + 6x + 9")


def test_deferred_signatures_return_false_rather_than_raising():
    for signature in DEFERRED_SIGNATURES:
        assert RULES.exhibits(signature, "(x+3)^2", "x^2 + 9") is False


def test_unknown_signature_returns_false():
    assert RULES.exhibits("not_a_real_signature", "x", "y") is False


def test_unparseable_input_returns_false_rather_than_raising():
    assert RULES.exhibits("square_distributes_over_sum", "x +* 2", "y") is False


def test_every_content_signature_is_classified():
    cluster = load_cluster(CLUSTER)
    declared = {m.signature for m in cluster.misconceptions.values()}
    classified = IMPLEMENTED_SIGNATURES | DEFERRED_SIGNATURES
    assert declared <= classified, f"unclassified signatures: {declared - classified}"
    assert not (IMPLEMENTED_SIGNATURES & DEFERRED_SIGNATURES)
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/adapters/test_misconception_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.adapters.cas.misconception_rules'`

- [ ] **Step 7: Write the rules**

```python
# src/learnai/adapters/cas/misconception_rules.py
from collections.abc import Callable

import sympy as sp

from learnai.adapters.cas.equivalence import expressions_equivalent
from learnai.adapters.cas.parse import ParseError, parse_math

X = sp.Symbol("x")
_A, _B, _C, _D = (sp.Wild(n, exclude=[0]) for n in ("wa", "wb", "wc", "wd"))

Rule = Callable[[sp.Basic, sp.Basic], bool]


def _square_distributes(previous: sp.Basic, current: sp.Basic) -> bool:
    match = previous.match((_A + _B) ** 2)
    if not match:
        return False
    wrong = match[_A] ** 2 + match[_B] ** 2
    return expressions_equivalent(sp.expand(current), sp.expand(wrong))


def _drops_cross_terms(previous: sp.Basic, current: sp.Basic) -> bool:
    match = previous.match((_A + _B) * (_C + _D))
    if not match:
        return False
    wrong = match[_A] * match[_C] + match[_B] * match[_D]
    return expressions_equivalent(sp.expand(current), sp.expand(wrong))


def _incomplete_common_factor(previous: sp.Basic, current: sp.Basic) -> bool:
    """Still algebraically correct, but a further common factor remains."""
    if not expressions_equivalent(sp.expand(previous), sp.expand(current)):
        return False
    return sp.factor(current) != current


def _factor_sign_flip(previous: sp.Basic, current: sp.Basic) -> bool:
    """Right magnitudes, wrong signs: the answer factors previous(-x) instead."""
    if expressions_equivalent(sp.expand(previous), sp.expand(current)):
        return False
    reflected = sp.expand(previous.subs(X, -X))
    return expressions_equivalent(sp.expand(current), reflected)


def _sum_of_squares_factored(previous: sp.Basic, current: sp.Basic) -> bool:
    if not previous.is_Add or len(previous.args) != 2:
        return False
    if not all(term.is_number or term.is_Pow for term in previous.args):
        return False
    if any(term.is_number and term < 0 for term in previous.args):
        return False
    return bool(current.is_Mul or (current.is_Pow and current.exp == 2))


def _zero_product_without_zero(previous: sp.Basic, current: sp.Basic) -> bool:
    """Sets each factor equal to a non-zero right-hand side."""
    if not isinstance(previous, sp.Eq) or previous.rhs == 0:
        return False
    factors = sp.factor(previous.lhs)
    if not factors.is_Mul:
        return False
    naive_roots: set[sp.Expr] = set()
    for factor in factors.args:
        if factor.free_symbols:
            naive_roots.update(sp.solve(sp.Eq(factor, previous.rhs), X))
    if not naive_roots:
        return False
    claimed = _claimed_values(current)
    return bool(claimed) and claimed <= {sp.nsimplify(r) for r in naive_roots}


def _claimed_values(current: sp.Basic) -> set[sp.Expr]:
    if isinstance(current, sp.Eq):
        return {current.rhs}
    return set()


_RULES: dict[str, Rule] = {
    "square_distributes_over_sum": _square_distributes,
    "product_of_sums_drops_cross": _drops_cross_terms,
    "incomplete_common_factor": _incomplete_common_factor,
    "factor_sign_flip": _factor_sign_flip,
    "sum_of_squares_factored": _sum_of_squares_factored,
    "zero_product_without_zero": _zero_product_without_zero,
}

IMPLEMENTED_SIGNATURES = frozenset(_RULES)

DEFERRED_SIGNATURES = frozenset(
    {
        "ignores_leading_coefficient",
        "completes_without_compensating",
        "formula_b_not_negated",
        "discriminant_cases_reversed",
        "vertex_sign_flip",
        "negative_root_kept",
    }
)


class SympyMisconceptionRules:
    """Matcher for `cas_symbolic` skills.

    A deferred or unknown signature returns False, so diagnosis degrades to
    "novel error" and the tutor still receives the localised step.
    """

    def exhibits(self, signature: str, previous: str, current: str) -> bool:
        rule = _RULES.get(signature)
        if rule is None:
            return False
        try:
            prev_expr = parse_math(previous, allow_equation=True)
        except ParseError:
            return False
        try:
            cur_expr = _parse_current(current)
        except ParseError:
            return False
        try:
            return bool(rule(prev_expr, cur_expr))
        except (TypeError, ValueError, NotImplementedError, sp.SympifyError):
            return False


def _parse_current(current: str) -> sp.Basic:
    """Student work may claim several roots at once, e.g. "x = 7, x = 8"."""
    parts = [p for p in current.split(",") if p.strip()]
    if len(parts) > 1:
        return sp.Tuple(*[parse_math(p, allow_equation=True) for p in parts])
    return parse_math(current, allow_equation=True)
```

Note: `_claimed_values` must also read a `sp.Tuple` of equations, so extend it:

```python
def _claimed_values(current: sp.Basic) -> set[sp.Expr]:
    if isinstance(current, sp.Eq):
        return {sp.nsimplify(current.rhs)}
    if isinstance(current, sp.Tuple):
        values: set[sp.Expr] = set()
        for entry in current:
            values |= _claimed_values(entry)
        return values
    return set()
```

- [ ] **Step 8: Run the rules tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_misconception_rules.py -v`
Expected: PASS — 16 tests.

- [ ] **Step 9: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS. Confirm `tests/test_domain_purity.py` still passes — `misconceptions.py` holds policy only and imports no SymPy.

- [ ] **Step 10: Commit**

```bash
git add src/learnai/domain/misconceptions.py src/learnai/adapters/cas/misconception_rules.py \
        tests/domain/test_diagnosis.py tests/adapters/test_misconception_rules.py
git commit -m "feat: misconception diagnosis with six CAS rules and explicit deferrals"
```

---

### Task 9: Mastery — strength and evidence weighting

**Files:**
- Create: `src/learnai/domain/parameters.py`, `src/learnai/domain/mastery.py`, `src/learnai/domain/evidence.py`
- Test: `tests/domain/test_strength.py`, `tests/domain/test_evidence.py`

**Interfaces:**
- Consumes: ids and enums (Task 1).
- Produces: `MasteryParameters` (frozen, all fields defaulted, including `guess_baseline` and `confidence_probability`) and `DEFAULT_PARAMETERS` in `parameters.py`; `SkillState` frozen dataclass; `p_expected(strength, difficulty) -> float`, `k_factor(attempt_count) -> float`, `update_strength(state, item_difficulty, outcome: float, weight, params) -> SkillState`; every mastery function takes `params: MasteryParameters = DEFAULT_PARAMETERS` as its final argument; `EVIDENCE_WEIGHT: dict[EvidenceClass, float]` and `classify_evidence(*, attempt_index, help_taken, taught_this_session, timed) -> EvidenceClass`.

**Interpretation recorded here:** the spec says "first attempt cold counts". A second attempt on the same item, even with no hint taken, follows a wrong-answer verdict — information the student did not have before — so it is **not** cold. `classify_evidence` returns `ASSISTED` for any attempt after the first. Flag this to the spec owner if they intended otherwise; it is a one-line change.

- [ ] **Step 1: Write the parameters value object**

These are **injected, not imported.** Spec §7.2 requires `r_target` to be a per-skill
policy value, and §7.8 requires fitting globally and then per-skill; module-level
constants make both impossible and make a canary comparison of two configurations
impossible too. Defaults live on the dataclass so no call site is noisier for it.

```python
# src/learnai/domain/parameters.py
"""Tuned parameters of the mastery model. See spec §7.8 for how each is calibrated."""
from collections.abc import Mapping
from dataclasses import dataclass, field

from learnai.domain.enums import AnswerKind, Confidence


@dataclass(frozen=True, slots=True)
class MasteryParameters:
    # --- Strength (Elo, logit scale; spec §7.1) ------------------------------
    strength_scale: float = 1.0
    """1.0 means strength and difficulty are in logits: a gap of 1 is p≈0.73."""
    k0: float = 0.4
    k_decay: float = 0.05
    """K = k0 / (1 + k_decay * attempts): fast early, stable once well determined."""
    strength_threshold: float = 1.5
    """Logits above an item's difficulty required for mastery: p≈0.82 on a core item."""
    min_unassisted_correct: int = 2

    # --- Memory (half-life days; spec §7.2) ----------------------------------
    r_target: float = 0.9
    """Per-skill policy value: raise inside an exam horizon, lower for maintenance."""
    stability_growth_a: float = 5.0
    """Derived, not guessed: A = (m-1)/(1-r_target) with m=1.5 reaches ~30-day
    intervals after fourteen on-time successes."""
    failure_multiplier_f: float = 0.3
    """F = m**-3: a lapse forfeits about three reviews' progress."""
    initial_stability_days: float = 1.0
    min_stability_days: float = 0.2

    # --- Prerequisite propagation (spec §7.4) --------------------------------
    prereq_propagation_weight: float = 0.3

    # --- Calibration (spec §7.5) ---------------------------------------------
    calibration_ema_alpha: float = 0.2
    overconfidence_threshold: float = 0.15
    guess_baseline: Mapping[AnswerKind, float] = field(
        default_factory=lambda: {
            AnswerKind.SINGLE_VALUE: 0.03,
            AnswerKind.RELATION: 0.03,
            AnswerKind.VALUE_SET: 0.02,
        }
    )
    """P(correct | pure guess), per answer format.

    A decline is scored at this value rather than at zero, which makes declining
    and guessing cost exactly the same in expectation — at any guess rate. That
    matters little on free response (the edge is ~0.012 logits) and a great deal
    once four-option multiple choice exists, where guessing would otherwise pay
    about 0.1 logits an item. Fitted from data like every value here.
    """
    confidence_probability: Mapping[Confidence, float] = field(
        default_factory=lambda: {
            Confidence.NO_IDEA: 0.02,
            Confidence.GUESSING: 0.15,
            Confidence.UNSURE: 0.40,
            Confidence.FAIRLY_SURE: 0.75,
            Confidence.CERTAIN: 0.93,
        }
    )
    """P(correct | stated confidence). Free-response priors, not MCQ ones: a guess
    at "factor x^2 + 3x + 2" is nothing like a guess among four options, and the
    MCQ value of 0.25 would libel every honest low-confidence student.

    Fit from data, but **at population level only** — fitting each student against
    their own history makes everyone calibrated by construction and the metric
    measures nothing. Key it by answer kind once multiple-choice items exist.
    Treat the dict as immutable.
    """

    # --- Planning (spec §7.6) ------------------------------------------------
    target_logit_margin: float = 1.1
    """Serve items the student should clear about 75% of the time."""


DEFAULT_PARAMETERS = MasteryParameters()
```

- [ ] **Step 2: Write the failing strength test**

```python
# tests/domain/test_strength.py
import math

from hypothesis import given
from hypothesis import strategies as st

from learnai.domain.enums import AnswerKind
from learnai.domain.ids import SkillId, StudentId
from learnai.domain.mastery import SkillState, k_factor, p_expected, update_strength
from learnai.domain.parameters import DEFAULT_PARAMETERS

FINITE = st.floats(min_value=-4.0, max_value=4.0, allow_nan=False, allow_infinity=False)


def state(strength: float = 0.0, attempts: int = 0) -> SkillState:
    return SkillState(
        student_id=StudentId("s1"),
        skill_id=SkillId("quad.factor.monic"),
        strength=strength,
        attempt_count=attempts,
    )


def test_equal_strength_and_difficulty_is_a_coin_flip():
    assert p_expected(0.5, 0.5) == 0.5


def test_one_logit_of_advantage_is_about_073():
    assert math.isclose(p_expected(1.0, 0.0), 0.7311, abs_tol=1e-4)


def test_p_expected_rises_with_strength():
    assert p_expected(-1.0, 0.0) < p_expected(0.0, 0.0) < p_expected(1.0, 0.0)


def test_success_on_a_hard_item_moves_more_than_on_an_easy_one():
    base = state(strength=0.5)
    hard = update_strength(base, item_difficulty=2.5, outcome=1.0, weight=1.0)
    easy = update_strength(base, item_difficulty=-1.5, outcome=1.0, weight=1.0)
    assert hard.strength - base.strength > easy.strength - base.strength


def test_failure_on_an_easy_item_costs_more_than_on_a_hard_one():
    base = state(strength=0.5)
    easy = update_strength(base, item_difficulty=-1.5, outcome=0.0, weight=1.0)
    hard = update_strength(base, item_difficulty=2.5, outcome=0.0, weight=1.0)
    assert base.strength - easy.strength > base.strength - hard.strength


def test_k_decays_with_observations():
    assert k_factor(0) == DEFAULT_PARAMETERS.k0
    assert k_factor(50) < k_factor(10) < k_factor(0)


def test_attempt_count_increments():
    assert update_strength(state(), 0.0, 1.0, 1.0).attempt_count == 1


def test_unassisted_correct_count_tracks_only_weighted_successes():
    assert update_strength(state(), 0.0, 1.0, 1.0).unassisted_correct_count == 1
    assert update_strength(state(), 0.0, 1.0, 0.0).unassisted_correct_count == 0
    assert update_strength(state(), 0.0, 0.0, 1.0).unassisted_correct_count == 0
    assert update_strength(state(), 0.0, 0.03, 1.0).unassisted_correct_count == 0


def test_declining_and_guessing_cost_the_same_in_expectation():
    """Scoring a decline at the guess baseline removes the incentive to guess."""
    base = state(strength=0.5)
    g = DEFAULT_PARAMETERS.guess_baseline[AnswerKind.SINGLE_VALUE]

    declined = update_strength(base, 0.0, g, 1.0).strength - base.strength
    guessed = g * (update_strength(base, 0.0, 1.0, 1.0).strength - base.strength) + (
        1 - g
    ) * (update_strength(base, 0.0, 0.0, 1.0).strength - base.strength)
    assert math.isclose(declined, guessed, abs_tol=1e-12)


def test_parameters_are_injected_not_baked_in():
    """Spec §7.8 fits these per skill; a module constant could never be overridden."""
    from dataclasses import replace as dc_replace

    from learnai.domain.parameters import MasteryParameters

    eager = dc_replace(MasteryParameters(), k0=2.0)
    base = state()
    assert (
        update_strength(base, 0.0, 1.0, 1.0, eager).strength
        > update_strength(base, 0.0, 1.0, 1.0).strength
    )


@given(strength=FINITE, difficulty=FINITE, correct=st.booleans())
def test_zero_weight_evidence_never_moves_strength(strength, difficulty, correct):
    """P2 and P4 in arithmetic: assistance cannot move mastery, at all."""
    before = state(strength=strength)
    after = update_strength(before, difficulty, float(correct), weight=0.0)
    assert after.strength == before.strength
    assert after.unassisted_correct_count == before.unassisted_correct_count


@given(strength=FINITE, difficulty=FINITE)
def test_a_correct_unassisted_attempt_never_lowers_strength(strength, difficulty):
    before = state(strength=strength)
    after = update_strength(before, difficulty, outcome=1.0, weight=1.0)
    assert after.strength >= before.strength


@given(strength=FINITE, difficulty=FINITE)
def test_a_wrong_unassisted_attempt_never_raises_strength(strength, difficulty):
    before = state(strength=strength)
    after = update_strength(before, difficulty, outcome=0.0, weight=1.0)
    assert after.strength <= before.strength
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_strength.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.domain.mastery'`

- [ ] **Step 4: Write the mastery state and strength update**

```python
# src/learnai/domain/mastery.py
import math
from dataclasses import dataclass, replace
from datetime import datetime

from learnai.domain.ids import MisconceptionId, SkillId, StudentId
from learnai.domain.parameters import DEFAULT_PARAMETERS, MasteryParameters


@dataclass(frozen=True, slots=True)
class SkillState:
    student_id: StudentId
    skill_id: SkillId
    strength: float = 0.0
    stability: float = 0.0
    """Memory half-life in days. Zero means never successfully retrieved."""
    last_success_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    attempt_count: int = 0
    unassisted_correct_count: int = 0
    calibration_gap: float = 0.0
    active_misconceptions: tuple[MisconceptionId, ...] = ()


def p_expected(
    strength: float, difficulty: float, params: MasteryParameters = DEFAULT_PARAMETERS
) -> float:
    return 1.0 / (1.0 + math.exp(-(strength - difficulty) / params.strength_scale))


def k_factor(attempt_count: int, params: MasteryParameters = DEFAULT_PARAMETERS) -> float:
    return params.k0 / (1.0 + params.k_decay * attempt_count)


def update_strength(
    state: SkillState,
    item_difficulty: float,
    outcome: float,
    weight: float,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> SkillState:
    """Elo update, scaled by how much this observation is permitted to count.

    `outcome` is 1.0 for a correct answer and 0.0 for a wrong one. A decline is
    scored at the format's guess baseline instead, so declining and guessing
    cost the same in expectation and the system never teaches a stuck student
    to guess rather than say so.

    `weight` is the product of the mode contract's weight and the evidence
    class weight. A weight of zero leaves strength untouched — that is the
    whole of P2, expressed arithmetically.
    """
    surprise = outcome - p_expected(state.strength, item_difficulty, params)
    delta = k_factor(state.attempt_count, params) * weight * surprise
    return replace(
        state,
        strength=state.strength + delta,
        attempt_count=state.attempt_count + 1,
        # Only an actual correct answer counts toward the mastery gate: a decline
        # scored near the guess baseline must never mint evidence of competence.
        unassisted_correct_count=state.unassisted_correct_count
        + (1 if outcome >= 1.0 and weight > 0.0 else 0),
    )
```

- [ ] **Step 5: Run the strength tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_strength.py -v`
Expected: PASS — 14 tests.

- [ ] **Step 6: Write the failing evidence test**

```python
# tests/domain/test_evidence.py
from learnai.domain.enums import EvidenceClass
from learnai.domain.evidence import EVIDENCE_WEIGHT, classify_evidence


def test_a_clean_first_attempt_is_cold():
    assert (
        classify_evidence(attempt_index=0, help_taken=False, taught_this_session=False, timed=False)
        is EvidenceClass.UNASSISTED_COLD
    )


def test_any_help_makes_it_assisted():
    assert (
        classify_evidence(attempt_index=0, help_taken=True, taught_this_session=False, timed=False)
        is EvidenceClass.ASSISTED
    )


def test_a_retry_is_not_cold_because_the_verdict_was_information():
    assert (
        classify_evidence(attempt_index=1, help_taken=False, taught_this_session=False, timed=False)
        is EvidenceClass.ASSISTED
    )


def test_same_session_teaching_makes_it_post_instruction():
    assert (
        classify_evidence(attempt_index=0, help_taken=False, taught_this_session=True, timed=False)
        is EvidenceClass.POST_INSTRUCTION
    )


def test_timed_beats_everything():
    assert (
        classify_evidence(attempt_index=3, help_taken=True, taught_this_session=True, timed=True)
        is EvidenceClass.TIMED_EXAM
    )


def test_help_beats_post_instruction_because_it_is_stricter():
    assert (
        classify_evidence(attempt_index=0, help_taken=True, taught_this_session=True, timed=False)
        is EvidenceClass.ASSISTED
    )


def test_only_cold_and_timed_evidence_carries_full_weight():
    assert EVIDENCE_WEIGHT[EvidenceClass.UNASSISTED_COLD] == 1.0
    assert EVIDENCE_WEIGHT[EvidenceClass.TIMED_EXAM] == 1.0
    assert EVIDENCE_WEIGHT[EvidenceClass.ASSISTED] == 0.0
    assert 0.0 < EVIDENCE_WEIGHT[EvidenceClass.POST_INSTRUCTION] < 0.25


def test_every_evidence_class_has_a_weight():
    assert set(EVIDENCE_WEIGHT) == set(EvidenceClass)
```

- [ ] **Step 7: Write the evidence module**

```python
# src/learnai/domain/evidence.py
from learnai.domain.enums import EvidenceClass

EVIDENCE_WEIGHT: dict[EvidenceClass, float] = {
    EvidenceClass.UNASSISTED_COLD: 1.0,
    EvidenceClass.TIMED_EXAM: 1.0,
    EvidenceClass.POST_INSTRUCTION: 0.1,
    EvidenceClass.ASSISTED: 0.0,
}


def classify_evidence(
    *, attempt_index: int, help_taken: bool, taught_this_session: bool, timed: bool
) -> EvidenceClass:
    """Decide what an attempt is worth. Strictest applicable class wins.

    `attempt_index` is zero-based: only the very first submission on a task can
    be cold, because every later one follows a verdict the student learned from.
    """
    if timed:
        return EvidenceClass.TIMED_EXAM
    if help_taken or attempt_index > 0:
        return EvidenceClass.ASSISTED
    if taught_this_session:
        return EvidenceClass.POST_INSTRUCTION
    return EvidenceClass.UNASSISTED_COLD
```

- [ ] **Step 8: Run the evidence tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_evidence.py -v`
Expected: PASS — 8 tests.

- [ ] **Step 9: Commit**

```bash
git add src/learnai/domain/parameters.py src/learnai/domain/mastery.py \
        src/learnai/domain/evidence.py tests/domain/test_strength.py tests/domain/test_evidence.py
git commit -m "feat: Elo strength update and evidence classification"
```

---

### Task 10: Mastery — stability, retrievability, and derived states

**Files:**
- Modify: `src/learnai/domain/mastery.py`
- Create: `src/learnai/adapters/clock.py`
- Test: `tests/domain/test_stability.py`

**Interfaces:**
- Consumes: `SkillState`, constants (Task 9); `Clock` protocol (Task 5).
- Produces: `elapsed_days(earlier, later) -> float`, `retrievability(state, now) -> float`, `update_stability(state, correct, now) -> SkillState`, `due_at(state) -> datetime | None`, `is_fresh(state, now) -> bool`, `is_learned(state) -> bool`; `SystemClock` and `FakeClock` (with `advance(days: float)` and `set(moment)`) in `adapters/clock.py`.

- [ ] **Step 1: Write the fake clock**

```python
# src/learnai/adapters/clock.py
from datetime import UTC, datetime, timedelta


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Lets a term of study run in milliseconds. Essential for decay testing."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, days: float) -> datetime:
        self._now = self._now + timedelta(days=days)
        return self._now

    def set(self, moment: datetime) -> None:
        self._now = moment
```

- [ ] **Step 2: Write the failing stability test**

```python
# tests/domain/test_stability.py
import math

from hypothesis import given
from hypothesis import strategies as st

from learnai.adapters.clock import FakeClock
from learnai.domain.ids import SkillId, StudentId
from learnai.domain.parameters import DEFAULT_PARAMETERS as P
from learnai.domain.mastery import (
    SkillState,
    due_at,
    is_fresh,
    is_learned,
    retrievability,
    update_stability,
)


def state(**kwargs) -> SkillState:
    base = {"student_id": StudentId("s1"), "skill_id": SkillId("quad.factor.monic")}
    return SkillState(**(base | kwargs))


def test_never_retrieved_has_zero_retrievability():
    clock = FakeClock()
    assert retrievability(state(), clock.now()) == 0.0


def test_retrievability_is_one_at_the_moment_of_success():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    assert retrievability(s, clock.now()) == 1.0


def test_retrievability_is_one_half_after_exactly_one_half_life():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    assert math.isclose(retrievability(s, clock.advance(10.0)), 0.5, abs_tol=1e-9)


def test_retrievability_is_one_quarter_after_two_half_lives():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    assert math.isclose(retrievability(s, clock.advance(20.0)), 0.25, abs_tol=1e-9)


def test_first_success_sets_the_initial_stability():
    clock = FakeClock()
    after = update_stability(state(), correct=True, now=clock.now())
    assert after.stability == P.initial_stability_days
    assert after.last_success_at == clock.now()


def test_a_late_success_grows_stability_more_than_a_prompt_one():
    clock = FakeClock()
    start = state(stability=10.0, last_success_at=clock.now())

    prompt_clock = FakeClock(clock.now())
    prompt = update_stability(start, correct=True, now=prompt_clock.advance(1.0))

    late_clock = FakeClock(clock.now())
    late = update_stability(start, correct=True, now=late_clock.advance(9.0))

    assert late.stability > prompt.stability


def test_failure_collapses_stability_by_the_failure_multiplier():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    after = update_stability(s, correct=False, now=clock.advance(5.0))
    assert math.isclose(after.stability, 10.0 * P.failure_multiplier_f, abs_tol=1e-9)
    assert after.last_success_at == s.last_success_at, "a failure is not a success"


def test_stability_never_falls_below_the_floor():
    clock = FakeClock()
    s = state(stability=P.min_stability_days, last_success_at=clock.now())
    assert update_stability(s, correct=False, now=clock.now()).stability == P.min_stability_days


def test_due_at_is_about_fifteen_percent_of_the_half_life():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    gap = (due_at(s) - clock.now()).total_seconds() / 86400.0
    assert math.isclose(gap, 10.0 * math.log2(1 / P.r_target), rel_tol=1e-6)
    assert 1.4 < gap < 1.6


def test_due_at_is_none_when_never_retrieved():
    assert due_at(state()) is None


def test_freshness_flips_exactly_at_the_target():
    clock = FakeClock()
    s = state(stability=10.0, last_success_at=clock.now())
    assert is_fresh(s, clock.now())
    assert is_fresh(s, due_at(s))
    clock.set(due_at(s))
    assert not is_fresh(s, clock.advance(0.1))


def test_learned_requires_both_strength_and_repeated_cold_success():
    assert not is_learned(state(strength=3.0, unassisted_correct_count=1))
    assert not is_learned(state(strength=0.1, unassisted_correct_count=5))
    assert is_learned(state(strength=P.strength_threshold, unassisted_correct_count=2))


@given(days=st.floats(min_value=0.0, max_value=3650.0, allow_nan=False))
def test_retrievability_never_increases_with_time(days):
    clock = FakeClock()
    s = state(stability=30.0, last_success_at=clock.now())
    earlier = retrievability(s, clock.now())
    later = retrievability(s, clock.advance(days))
    assert later <= earlier + 1e-12
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_stability.py -v`
Expected: FAIL — `ImportError: cannot import name 'retrievability' from 'learnai.domain.mastery'`

- [ ] **Step 4: Extend mastery.py**

Add `from datetime import timedelta` at the top. `MasteryParameters` is already imported. Then append:

```python
def elapsed_days(earlier: datetime, later: datetime) -> float:
    """Wall-clock days as a float. Never quantise to calendar days."""
    return (later - earlier).total_seconds() / 86400.0


def retrievability(state: SkillState, now: datetime) -> float:
    """Probability the student could do this right now: 2 ** (-elapsed / half-life)."""
    if state.last_success_at is None or state.stability <= 0.0:
        return 0.0
    return 2.0 ** (-elapsed_days(state.last_success_at, now) / state.stability)


def update_stability(
    state: SkillState,
    correct: bool,
    now: datetime,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> SkillState:
    """Grow the half-life on a successful retrieval; collapse it on a lapse.

    Growth scales with 1 - retrievability, so a retrieval made when the memory
    had decayed further is worth more. That is the spacing effect, and it is why
    an immediate re-test earns almost nothing.
    """
    if not correct:
        collapsed = max(params.min_stability_days, state.stability * params.failure_multiplier_f)
        return replace(state, stability=collapsed, last_reviewed_at=now)

    if state.last_success_at is None or state.stability <= 0.0:
        return replace(
            state,
            stability=params.initial_stability_days,
            last_success_at=now,
            last_reviewed_at=now,
        )

    r = retrievability(state, now)
    grown = state.stability * (1.0 + params.stability_growth_a * (1.0 - r))
    return replace(state, stability=grown, last_success_at=now, last_reviewed_at=now)


def due_at(
    state: SkillState, params: MasteryParameters = DEFAULT_PARAMETERS
) -> datetime | None:
    """When retrievability will fall to r_target — roughly 0.152 half-lives."""
    if state.last_success_at is None or state.stability <= 0.0:
        return None
    gap = state.stability * math.log2(1.0 / params.r_target)
    return state.last_success_at + timedelta(days=gap)


def is_fresh(
    state: SkillState, now: datetime, params: MasteryParameters = DEFAULT_PARAMETERS
) -> bool:
    return retrievability(state, now) >= params.r_target


def is_learned(state: SkillState, params: MasteryParameters = DEFAULT_PARAMETERS) -> bool:
    """An achievement, not a freshness reading: once earned it never un-earns."""
    return (
        state.strength >= params.strength_threshold
        and state.unassisted_correct_count >= params.min_unassisted_correct
    )
```

- [ ] **Step 5: Run the stability tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_stability.py -v`
Expected: PASS — 13 tests.

- [ ] **Step 6: Commit**

```bash
git add src/learnai/domain/mastery.py src/learnai/adapters/clock.py tests/domain/test_stability.py
git commit -m "feat: memory stability, retrievability, and derived mastery states"
```

---

### Task 11: Prerequisite propagation and calibration

**Files:**
- Create: `src/learnai/domain/propagation.py`, `src/learnai/domain/calibration.py`
- Test: `tests/domain/test_propagation.py`, `tests/domain/test_calibration.py`

**Interfaces:**
- Consumes: `SkillGraph` (Task 1), `SkillState`, `update_stability`, `is_learned` (Tasks 9–10), `Confidence` (Task 1), constants (Task 9).
- Produces: `propagate_success(states, graph, skill_id, now, params) -> dict[SkillId, SkillState]`; `update_calibration(gap, confidence, correct, params) -> float`, `is_overconfident(gap, params) -> bool`. The confidence-to-probability mapping is `params.confidence_probability`, not a module constant.

- [ ] **Step 1: Write the failing propagation test**

```python
# tests/domain/test_propagation.py
from learnai.adapters.clock import FakeClock
from learnai.domain.enums import PrereqStrength
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import SkillId, StudentId, VerificationKind
from learnai.domain.mastery import SkillState
from learnai.domain.propagation import propagate_success
from learnai.domain.skills import PrereqEdge, Skill


def skill(sid: str) -> Skill:
    return Skill(SkillId(sid), "math", sid, f"can {sid}", VerificationKind("cas_symbolic"), (), ())


GRAPH = SkillGraph.build(
    [skill("base"), skill("mid"), skill("top"), skill("soft")],
    [
        PrereqEdge(SkillId("base"), SkillId("mid"), PrereqStrength.HARD),
        PrereqEdge(SkillId("mid"), SkillId("top"), PrereqStrength.HARD),
        PrereqEdge(SkillId("soft"), SkillId("top"), PrereqStrength.SOFT),
    ],
)


def st(sid: str, **kwargs) -> SkillState:
    return SkillState(student_id=StudentId("s1"), skill_id=SkillId(sid), **kwargs)


def learned_state(sid: str, clock: FakeClock) -> SkillState:
    return st(sid, strength=2.0, unassisted_correct_count=2, stability=10.0,
              last_success_at=clock.now())


def test_a_downstream_success_refreshes_a_learned_hard_prerequisite():
    clock = FakeClock()
    states = {SkillId("mid"): learned_state("mid", clock)}
    before = states[SkillId("mid")].stability
    clock.advance(8.0)

    updated = propagate_success(states, GRAPH, SkillId("top"), clock.now())
    assert updated[SkillId("mid")].stability > before


def test_propagation_is_weaker_than_a_direct_retrieval():
    from learnai.domain.mastery import update_stability

    clock = FakeClock()
    original = learned_state("mid", clock)
    clock.advance(8.0)

    direct = update_stability(original, correct=True, now=clock.now())
    propagated = propagate_success(
        {SkillId("mid"): original}, GRAPH, SkillId("top"), clock.now()
    )[SkillId("mid")]
    assert propagated.stability < direct.stability


def test_soft_prerequisites_are_not_propagated_to():
    clock = FakeClock()
    states = {SkillId("soft"): learned_state("soft", clock)}
    clock.advance(8.0)
    updated = propagate_success(states, GRAPH, SkillId("top"), clock.now())
    assert updated[SkillId("soft")] == states[SkillId("soft")]


def test_propagation_stops_at_direct_prerequisites():
    clock = FakeClock()
    states = {
        SkillId("mid"): learned_state("mid", clock),
        SkillId("base"): learned_state("base", clock),
    }
    clock.advance(8.0)
    updated = propagate_success(states, GRAPH, SkillId("top"), clock.now())
    assert updated[SkillId("base")] == states[SkillId("base")]


def test_an_unlearned_prerequisite_is_not_credited():
    clock = FakeClock()
    states = {SkillId("mid"): st("mid", strength=0.1, stability=2.0,
                                 last_success_at=clock.now())}
    clock.advance(8.0)
    updated = propagate_success(states, GRAPH, SkillId("top"), clock.now())
    assert updated[SkillId("mid")] == states[SkillId("mid")]


def test_propagation_never_touches_strength():
    """Only direct evidence moves competence; propagation is a memory refresh."""
    clock = FakeClock()
    states = {SkillId("mid"): learned_state("mid", clock)}
    clock.advance(8.0)
    updated = propagate_success(states, GRAPH, SkillId("top"), clock.now())
    assert updated[SkillId("mid")].strength == states[SkillId("mid")].strength
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_propagation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.domain.propagation'`

- [ ] **Step 3: Write propagation**

```python
# src/learnai/domain/propagation.py
from dataclasses import replace
from datetime import datetime

from learnai.domain.graph import SkillGraph
from learnai.domain.ids import SkillId
from learnai.domain.mastery import SkillState, is_learned, retrievability
from learnai.domain.parameters import DEFAULT_PARAMETERS, MasteryParameters


def propagate_success(
    states: dict[SkillId, SkillState],
    graph: SkillGraph,
    skill_id: SkillId,
    now: datetime,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> dict[SkillId, SkillState]:
    """Credit an implicit retrieval to the direct hard prerequisites of a success.

    Solving something downstream demonstrates the prerequisite is still available,
    so refresh its memory rather than making the student sit a review of it. The
    credit is partial, reaches direct hard prerequisites only, and never touches
    strength — competence is only ever moved by direct evidence.
    """
    updated = dict(states)
    for prereq_id in graph.hard_prereqs(skill_id):
        prereq = updated.get(prereq_id)
        if prereq is None or not is_learned(prereq, params) or prereq.stability <= 0.0:
            continue
        r = retrievability(prereq, now)
        growth = 1.0 + params.prereq_propagation_weight * params.stability_growth_a * (1.0 - r)
        updated[prereq_id] = replace(
            prereq,
            stability=prereq.stability * growth,
            last_success_at=now,
            last_reviewed_at=now,
        )
    return updated
```

- [ ] **Step 4: Run the propagation tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_propagation.py -v`
Expected: PASS — 6 tests.

- [ ] **Step 5: Write the failing calibration test**

```python
# tests/domain/test_calibration.py
from learnai.domain.calibration import is_overconfident, update_calibration
from learnai.domain.enums import Confidence
from learnai.domain.parameters import DEFAULT_PARAMETERS

MAPPING = DEFAULT_PARAMETERS.confidence_probability


def test_every_confidence_level_maps_to_a_probability():
    assert set(MAPPING) == set(Confidence)
    values = [MAPPING[c] for c in sorted(Confidence)]
    assert values == sorted(values), "probabilities must rise with confidence"
    assert all(0.0 < v < 1.0 for v in values)


def test_the_priors_are_free_response_shaped_not_multiple_choice():
    """A guess at a free-response item is nothing like a guess among four options."""
    assert MAPPING[Confidence.NO_IDEA] < 0.05
    assert MAPPING[Confidence.GUESSING] < 0.20


def test_declining_and_being_wrong_is_near_perfect_calibration():
    gap = 0.0
    for _ in range(20):
        gap = update_calibration(gap, Confidence.NO_IDEA, correct=False)
    assert abs(gap) < 0.05
    assert not is_overconfident(gap)


def test_certain_and_wrong_pushes_the_gap_positive():
    assert update_calibration(0.0, Confidence.CERTAIN, correct=False) > 0.0


def test_guessing_and_right_pushes_the_gap_negative():
    assert update_calibration(0.0, Confidence.GUESSING, correct=True) < 0.0


def test_a_well_calibrated_student_converges_toward_zero():
    gap = 0.5
    for _ in range(60):
        gap = update_calibration(gap, Confidence.FAIRLY_SURE, correct=True)
        gap = update_calibration(gap, Confidence.FAIRLY_SURE, correct=True)
        gap = update_calibration(gap, Confidence.FAIRLY_SURE, correct=True)
        gap = update_calibration(gap, Confidence.FAIRLY_SURE, correct=False)
    assert abs(gap) < 0.1


def test_persistent_overconfidence_is_detected():
    gap = 0.0
    for _ in range(20):
        gap = update_calibration(gap, Confidence.CERTAIN, correct=False)
    assert is_overconfident(gap)


def test_a_calibrated_student_is_not_flagged():
    assert not is_overconfident(0.0)
```

- [ ] **Step 6: Write calibration**

```python
# src/learnai/domain/calibration.py
from learnai.domain.enums import Confidence
from learnai.domain.parameters import DEFAULT_PARAMETERS, MasteryParameters


def update_calibration(
    gap: float,
    confidence: Confidence,
    correct: bool,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> float:
    """Exponential moving average of (stated probability - outcome).

    Positive means overconfident. This is the platform's core diagnostic: the
    failure it exists to fix is students not knowing what they do not know, and
    this number is that failure, measured.
    """
    observation = params.confidence_probability[confidence] - (1.0 if correct else 0.0)
    alpha = params.calibration_ema_alpha
    return (1.0 - alpha) * gap + alpha * observation


def is_overconfident(gap: float, params: MasteryParameters = DEFAULT_PARAMETERS) -> bool:
    return gap > params.overconfidence_threshold
```

- [ ] **Step 7: Run the calibration tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_calibration.py -v`
Expected: PASS — 8 tests.

- [ ] **Step 8: Commit**

```bash
git add src/learnai/domain/propagation.py src/learnai/domain/calibration.py \
        tests/domain/test_propagation.py tests/domain/test_calibration.py
git commit -m "feat: prerequisite propagation and calibration tracking"
```

---

### Task 12: Mode contracts and the hint ladder

**Files:**
- Create: `src/learnai/domain/contracts.py`, `src/learnai/domain/help.py`
- Test: `tests/domain/test_contracts.py`, `tests/domain/test_help_ladder.py`

**Interfaces:**
- Consumes: `HelpRung`, `RevealPrice`, `InterventionTiming`, `VettingLevel` (Task 1).
- Produces: `EffortCondition(min_attempts, ladder_exhausted)`; `ModeContract(name, base_max_rung, unlock_full_reveal_after, reveal_price, evidence_weight, min_vetting_level, intervention_timing, timed, mixes_skills)`; the `PRACTICE` contract instance; `HelpState(rungs_used, attempts)` with properties `highest_rung` and `help_taken`; `ladder_exhausted(contract, help_state) -> bool`, `reveal_unlocked(contract, help_state) -> bool`, `permitted_rung(contract, help_state) -> HelpRung`, `next_rung(contract, help_state) -> HelpRung | None`, `record_help(help_state, rung) -> HelpState`, `record_attempt(help_state) -> HelpState`.

**Deferred:** `initial_strategy` / `TeachingStrategy` from spec §8.3 belongs to Learn mode and arrives with it in Slice 3. In Practice the generosity that applies is difficulty targeting, which Task 15's planner implements.

- [ ] **Step 1: Write the failing contract test**

```python
# tests/domain/test_contracts.py
from learnai.domain.contracts import PRACTICE, EffortCondition, ModeContract
from learnai.domain.enums import HelpRung, InterventionTiming, RevealPrice, VettingLevel


def test_practice_never_starts_above_naming_the_method():
    assert PRACTICE.base_max_rung is HelpRung.NAME_METHOD


def test_practice_unlocks_a_reveal_only_after_documented_effort():
    assert PRACTICE.unlock_full_reveal_after == EffortCondition(
        min_attempts=2, ladder_exhausted=True
    )


def test_practice_charges_the_fresh_variant_price():
    assert PRACTICE.reveal_price is RevealPrice.FRESH_VARIANT_COLD


def test_practice_only_serves_cas_verified_items():
    assert PRACTICE.min_vetting_level is VettingLevel.MACHINE_VERIFIED


def test_practice_lets_an_error_run_before_intervening():
    assert PRACTICE.intervention_timing is InterventionTiming.LET_RUN


def test_practice_is_untimed_and_mixes_skills():
    assert PRACTICE.timed is False and PRACTICE.mixes_skills is True


def test_a_contract_is_immutable():
    try:
        PRACTICE.timed = True  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ModeContract must be frozen")
```

- [ ] **Step 2: Write the contracts**

```python
# src/learnai/domain/contracts.py
from dataclasses import dataclass

from learnai.domain.enums import HelpRung, InterventionTiming, RevealPrice, VettingLevel


@dataclass(frozen=True, slots=True)
class EffortCondition:
    """What a student must have done before a reveal can be unlocked."""

    min_attempts: int
    ladder_exhausted: bool


@dataclass(frozen=True, slots=True)
class ModeContract:
    name: str
    base_max_rung: HelpRung
    unlock_full_reveal_after: EffortCondition | None
    reveal_price: RevealPrice
    evidence_weight: float
    min_vetting_level: VettingLevel
    intervention_timing: InterventionTiming
    timed: bool
    mixes_skills: bool


PRACTICE = ModeContract(
    name="practice",
    base_max_rung=HelpRung.NAME_METHOD,
    unlock_full_reveal_after=EffortCondition(min_attempts=2, ladder_exhausted=True),
    reveal_price=RevealPrice.FRESH_VARIANT_COLD,
    evidence_weight=1.0,
    min_vetting_level=VettingLevel.MACHINE_VERIFIED,
    intervention_timing=InterventionTiming.LET_RUN,
    timed=False,
    mixes_skills=True,
)
```

- [ ] **Step 3: Run the contract tests**

Run: `.venv/bin/pytest tests/domain/test_contracts.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 4: Write the failing hint-ladder test**

```python
# tests/domain/test_help_ladder.py
from learnai.domain.contracts import PRACTICE
from learnai.domain.enums import HelpRung
from learnai.domain.help import (
    HelpState,
    ladder_exhausted,
    next_rung,
    permitted_rung,
    record_attempt,
    record_help,
    reveal_unlocked,
)


def test_a_fresh_task_has_taken_no_help():
    state = HelpState()
    assert state.highest_rung is HelpRung.NONE
    assert state.help_taken is False


def test_the_ladder_starts_at_a_nudge():
    assert next_rung(PRACTICE, HelpState()) is HelpRung.NUDGE


def test_the_ladder_climbs_one_rung_at_a_time():
    state = HelpState()
    for expected in (HelpRung.NUDGE, HelpRung.NEXT_STEP, HelpRung.NAME_METHOD):
        assert next_rung(PRACTICE, state) is expected
        state = record_help(state, expected)


def test_the_ladder_stops_at_the_base_maximum_without_effort():
    state = HelpState()
    for rung in (HelpRung.NUDGE, HelpRung.NEXT_STEP, HelpRung.NAME_METHOD):
        state = record_help(state, rung)
    assert ladder_exhausted(PRACTICE, state)
    assert not reveal_unlocked(PRACTICE, state), "one attempt is not documented effort"
    assert next_rung(PRACTICE, state) is None
    assert permitted_rung(PRACTICE, state) is HelpRung.NAME_METHOD


def test_effort_plus_an_exhausted_ladder_unlocks_the_reveal():
    state = HelpState()
    for rung in (HelpRung.NUDGE, HelpRung.NEXT_STEP, HelpRung.NAME_METHOD):
        state = record_help(state, rung)
    state = record_attempt(record_attempt(state))
    assert reveal_unlocked(PRACTICE, state)
    assert permitted_rung(PRACTICE, state) is HelpRung.FULL_REVEAL
    assert next_rung(PRACTICE, state) is HelpRung.FULL_REVEAL


def test_declines_do_not_climb_toward_a_reveal():
    """record_attempt is never called for a decline, so the counter stays put."""
    state = HelpState()
    for rung in (HelpRung.NUDGE, HelpRung.NEXT_STEP, HelpRung.NAME_METHOD):
        state = record_help(state, rung)
    assert not reveal_unlocked(PRACTICE, state)


def test_attempts_alone_do_not_unlock_a_reveal():
    state = record_attempt(record_attempt(record_attempt(HelpState())))
    assert not reveal_unlocked(PRACTICE, state)
    assert permitted_rung(PRACTICE, state) is HelpRung.NAME_METHOD


def test_taking_help_is_recorded_and_never_forgotten():
    state = record_help(HelpState(), HelpRung.NUDGE)
    assert state.help_taken
    assert state.rungs_used == (HelpRung.NUDGE,)


def test_nothing_is_left_after_a_reveal():
    state = HelpState(rungs_used=(HelpRung.FULL_REVEAL,), attempts=3)
    assert next_rung(PRACTICE, state) is None
```

- [ ] **Step 5: Write the hint ladder**

```python
# src/learnai/domain/help.py
from dataclasses import dataclass, replace

from learnai.domain.contracts import ModeContract
from learnai.domain.enums import HelpRung


@dataclass(frozen=True, slots=True)
class HelpState:
    """Per-task help history. Append-only: a rung once taken is never unrecorded."""

    rungs_used: tuple[HelpRung, ...] = ()
    attempts: int = 0

    @property
    def highest_rung(self) -> HelpRung:
        return max(self.rungs_used, default=HelpRung.NONE)

    @property
    def help_taken(self) -> bool:
        return bool(self.rungs_used)


def ladder_exhausted(contract: ModeContract, state: HelpState) -> bool:
    return state.highest_rung >= contract.base_max_rung


def reveal_unlocked(contract: ModeContract, state: HelpState) -> bool:
    condition = contract.unlock_full_reveal_after
    if condition is None:
        return False
    if state.attempts < condition.min_attempts:
        return False
    if condition.ladder_exhausted and not ladder_exhausted(contract, state):
        return False
    return True


def permitted_rung(contract: ModeContract, state: HelpState) -> HelpRung:
    """The highest rung the tutor may use right now."""
    if reveal_unlocked(contract, state):
        return HelpRung.FULL_REVEAL
    return contract.base_max_rung


def next_rung(contract: ModeContract, state: HelpState) -> HelpRung | None:
    """The single rung to offer next, or None when there is nothing left to give."""
    ceiling = permitted_rung(contract, state)
    candidate = HelpRung(min(state.highest_rung + 1, HelpRung.FULL_REVEAL))
    if state.highest_rung >= ceiling:
        return None
    return candidate if candidate <= ceiling else None


def record_help(state: HelpState, rung: HelpRung) -> HelpState:
    return replace(state, rungs_used=state.rungs_used + (rung,))


def record_attempt(state: HelpState) -> HelpState:
    """Count an *answered* attempt.

    Never called for a decline. If declining counted, the cheapest route to a
    full reveal would be: decline, decline, click through the ladder — zero
    effort, complete answer, which is precisely the hint abuse the effort
    condition exists to prevent.
    """
    return replace(state, attempts=state.attempts + 1)
```

- [ ] **Step 6: Run the ladder tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_help_ladder.py -v`
Expected: PASS — 9 tests.

- [ ] **Step 7: Commit**

```bash
git add src/learnai/domain/contracts.py src/learnai/domain/help.py \
        tests/domain/test_contracts.py tests/domain/test_help_ladder.py
git commit -m "feat: practice mode contract and hint ladder state machine"
```

---

### Task 13: Leak detection

**Files:**
- Create: `src/learnai/domain/leakguard.py`
- Test: `tests/domain/test_leakguard.py`

**Interfaces:**
- Consumes: `Verifier` protocol (Task 5), `AnswerSpec` (Task 3), `HelpRung` (Task 1).
- Produces: `LeakVerdict(leaked: bool, offending_expression: str | None)`; `detect_leak(verifier: Verifier, draft: str, answer_spec: AnswerSpec, permitted_rung: HelpRung) -> LeakVerdict`. A function rather than a class, because the verifier varies per skill once a second subject exists — binding one at construction would quietly police chemistry with the maths CAS.

**Why this exists:** a system prompt saying "never reveal the answer" is a hope. Models under pressure from a frustrated teenager will cave, and the contract in Task 12 would then be decorative. This closes the gap between the policy as written and the policy as enforced, deterministically and at no token cost.

- [ ] **Step 1: Write the failing test**

```python
# tests/domain/test_leakguard.py
import pytest

from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.domain.enums import HelpRung
from learnai.domain.items import AnswerSpec
from learnai.domain.leakguard import detect_leak

VERIFIER = SympyVerifier()
SPEC = AnswerSpec("(x + 1)*(x + 2)")


def inspect(draft: str, rung: HelpRung = HelpRung.NUDGE):
    return detect_leak(VERIFIER, draft, SPEC, rung)


@pytest.mark.parametrize(
    "draft",
    [
        "The answer is (x+1)(x+2).",
        "You should end up with x^2 + 3x + 2 once expanded.",
        "Try (x + 1)(x + 2) and check by expanding.",
        "Well, (x+2)(x+1) works.",
    ],
)
def test_a_draft_containing_the_answer_is_caught(draft):
    verdict = inspect(draft)
    assert verdict.leaked
    assert verdict.offending_expression is not None


@pytest.mark.parametrize(
    "draft",
    [
        "What two numbers multiply to give the constant term?",
        "Think about the pair of factors of 2.",
        "You have the right method. Check the sign on your second factor.",
        "Remember that expanding (a + b)(c + d) gives four products.",
    ],
)
def test_a_genuine_hint_is_not_a_leak(draft):
    assert not inspect(draft).leaked


def test_nothing_leaks_when_a_full_reveal_is_permitted():
    verdict = inspect("The answer is (x+1)(x+2).", HelpRung.FULL_REVEAL)
    assert not verdict.leaked


def test_prose_with_no_mathematics_is_not_a_leak():
    assert not inspect("Take your time and read the question again.").leaked


def test_unparseable_fragments_do_not_crash_the_guard():
    assert not inspect("Try +++ or ***(((").leaked
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_leakguard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.domain.leakguard'`

- [ ] **Step 3: Write the leak detector**

```python
# src/learnai/domain/leakguard.py
from dataclasses import dataclass

from learnai.domain.enums import HelpRung
from learnai.domain.items import AnswerSpec
from learnai.domain.ports import Verifier


@dataclass(frozen=True, slots=True)
class LeakVerdict:
    leaked: bool
    offending_expression: str | None = None


def detect_leak(
    verifier: Verifier,
    draft: str,
    answer_spec: AnswerSpec,
    permitted_rung: HelpRung,
) -> LeakVerdict:
    """Deterministic enforcement of the mode contract's answer-withholding policy.

    The verifier is passed in rather than held, because which one is correct
    depends on the skill being tutored.
    """
    if permitted_rung >= HelpRung.FULL_REVEAL:
        return LeakVerdict(leaked=False)
    for candidate in verifier.extract_candidate_expressions(draft):
        if verifier.matches_answer(candidate, answer_spec):
            return LeakVerdict(leaked=True, offending_expression=candidate)
    return LeakVerdict(leaked=False)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_leakguard.py -v`
Expected: PASS — 10 tests.

If a genuine-hint case fails, the fault is in `extract_candidate_expressions` being too greedy rather than in the guard. Tighten the extractor in `SympyVerifier` — never loosen `matches_answer`, because a false negative there is a leak reaching a student.

- [ ] **Step 5: Commit**

```bash
git add src/learnai/domain/leakguard.py tests/domain/test_leakguard.py
git commit -m "feat: CAS-backed leak guard over tutor drafts"
```

---

### Task 14: Turn contract, validation pipeline, and FakeTutor

**Files:**
- Create: `src/learnai/domain/turn.py`, `src/learnai/adapters/tutor/__init__.py`, `src/learnai/adapters/tutor/fake_tutor.py`
- Modify: `src/learnai/domain/ports.py` (add the `Tutor` protocol)
- Test: `tests/domain/test_turn_validation.py`, `tests/adapters/test_fake_tutor.py`

**Interfaces:**
- Consumes: `SkillGraph` (Task 1), `Item` (Task 3), `HelpRung` (Task 1), `detect_leak` (Task 13), `Misconception` (Task 1).
- Produces: `SkillPack`, `StudentSummary`, `TranscriptEntry`, `TurnContext`; `ProposalKind`, `Proposal`, `TutorTurn`; `RejectionReason`, `ValidationResult`; `validate_turn(turn, context, graph, verifier) -> ValidationResult`; `Tutor` protocol; `FakeTutor`.

- [ ] **Step 1: Write the turn types and the Tutor port**

```python
# src/learnai/domain/turn.py
from dataclasses import dataclass
from enum import Enum

from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId, SkillId
from learnai.domain.items import Item, StepDiff
from learnai.domain.leakguard import detect_leak
from learnai.domain.ports import Verifier
from learnai.domain.skills import Misconception


@dataclass(frozen=True, slots=True)
class SkillPack:
    skill_id: SkillId
    can_do_statement: str
    teaching_notes: str
    misconceptions: tuple[Misconception, ...]


@dataclass(frozen=True, slots=True)
class StudentSummary:
    strength: float
    is_fresh: bool
    calibration_gap: float
    prior_misconceptions: tuple[MisconceptionId, ...]


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    speaker: str  # "student" | "tutor"
    text: str


@dataclass(frozen=True, slots=True)
class TurnContext:
    skill_pack: SkillPack
    item: Item
    student_summary: StudentSummary
    step_diff: StepDiff | None
    diagnosis: MisconceptionId | None
    permitted_rung: HelpRung
    last_verdict: Verdict | None = None
    """NO_ANSWER means the student declined: there is no work to diagnose, so the
    tutor's opening move is orientation rather than error correction."""
    transcript: tuple[TranscriptEntry, ...] = ()


class ProposalKind(Enum):
    DROP_TO_PREREQUISITE = "drop_to_prerequisite"
    SERVE_EASIER_ITEM = "serve_easier_item"
    END_TASK_UNPRODUCTIVE = "end_task_unproductive"


@dataclass(frozen=True, slots=True)
class Proposal:
    """A request, never a command. The engine decides."""

    kind: ProposalKind
    target_skill_id: SkillId | None = None


@dataclass(frozen=True, slots=True)
class TutorTurn:
    message: str
    rung_used: HelpRung
    diagnosis: MisconceptionId | None = None
    proposals: tuple[Proposal, ...] = ()


class RejectionReason(Enum):
    RUNG_EXCEEDED = "rung_exceeded"
    ANSWER_LEAKED = "answer_leaked"
    INVALID_PROPOSAL = "invalid_proposal"
    EMPTY_MESSAGE = "empty_message"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    accepted: bool
    reason: RejectionReason | None = None
    detail: str | None = None


def validate_turn(
    turn: TutorTurn,
    context: TurnContext,
    graph: SkillGraph,
    verifier: Verifier,
) -> ValidationResult:
    """Gate every tutor turn before a character of it reaches the student.

    Order matters: cheap structural checks first, the CAS-backed leak check last.
    """
    if not turn.message.strip():
        return ValidationResult(False, RejectionReason.EMPTY_MESSAGE)

    if turn.rung_used > context.permitted_rung:
        return ValidationResult(
            False,
            RejectionReason.RUNG_EXCEEDED,
            f"used {turn.rung_used.name}, permitted {context.permitted_rung.name}",
        )

    for proposal in turn.proposals:
        if proposal.kind is ProposalKind.DROP_TO_PREREQUISITE:
            target = proposal.target_skill_id
            if target is None or target not in graph.hard_prereqs(context.skill_pack.skill_id):
                return ValidationResult(
                    False,
                    RejectionReason.INVALID_PROPOSAL,
                    f"{target} is not a hard prerequisite of {context.skill_pack.skill_id}",
                )

    verdict = detect_leak(
        verifier, turn.message, context.item.answer_spec, context.permitted_rung
    )
    if verdict.leaked:
        return ValidationResult(
            False, RejectionReason.ANSWER_LEAKED, verdict.offending_expression
        )

    return ValidationResult(True)
```

Append to `src/learnai/domain/ports.py`:

```python
class Tutor(Protocol):
    def respond(self, context: "TurnContext") -> "TutorTurn": ...
```

with `from learnai.domain.turn import TurnContext, TutorTurn` guarded under `if TYPE_CHECKING:` to avoid a circular import, since `turn.py` imports nothing from `ports.py`.

- [ ] **Step 2: Write the failing validation test**

```python
# tests/domain/test_turn_validation.py
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.domain.enums import HelpRung, PrereqStrength, VettingLevel
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import ItemId, SkillId, VerificationKind
from learnai.domain.items import AnswerSpec, Item, Provenance
from learnai.domain.skills import PrereqEdge, Skill
from learnai.domain.turn import (
    Proposal,
    ProposalKind,
    RejectionReason,
    SkillPack,
    StudentSummary,
    TurnContext,
    TutorTurn,
    validate_turn,
)

VERIFIER = SympyVerifier()


def _skill(sid: str) -> Skill:
    return Skill(SkillId(sid), "math", sid, f"can {sid}", VerificationKind("cas_symbolic"), (), ())


GRAPH = SkillGraph.build(
    [_skill("quad.expand.binomial"), _skill("quad.factor.monic"), _skill("unrelated")],
    [PrereqEdge(SkillId("quad.expand.binomial"), SkillId("quad.factor.monic"), PrereqStrength.HARD)],
)

ITEM = Item(
    id=ItemId("i1"),
    skill_id=SkillId("quad.factor.monic"),
    provenance=Provenance.authored(),
    statement="Factor x^2 + 3x + 2",
    answer_spec=AnswerSpec("(x + 1)*(x + 2)"),
    worked_steps=(),
    difficulty=0.0,
    vetting_level=VettingLevel.MACHINE_VERIFIED,
)


def context(permitted: HelpRung = HelpRung.NUDGE) -> TurnContext:
    return TurnContext(
        skill_pack=SkillPack(SkillId("quad.factor.monic"), "can factor", "notes", ()),
        item=ITEM,
        student_summary=StudentSummary(0.0, True, 0.0, ()),
        step_diff=None,
        diagnosis=None,
        permitted_rung=permitted,
    )


def test_a_clean_nudge_is_accepted():
    turn = TutorTurn("What multiplies to 2 and adds to 3?", HelpRung.NUDGE)
    assert validate_turn(turn, context(), GRAPH, VERIFIER).accepted


def test_a_turn_above_the_permitted_rung_is_rejected():
    turn = TutorTurn("Here is the method in full.", HelpRung.NAME_METHOD)
    result = validate_turn(turn, context(HelpRung.NUDGE), GRAPH, VERIFIER)
    assert not result.accepted and result.reason is RejectionReason.RUNG_EXCEEDED


def test_a_leaking_turn_is_rejected_even_at_a_permitted_rung():
    turn = TutorTurn("Just write (x+1)(x+2).", HelpRung.NUDGE)
    result = validate_turn(turn, context(HelpRung.NUDGE), GRAPH, VERIFIER)
    assert not result.accepted and result.reason is RejectionReason.ANSWER_LEAKED


def test_the_same_turn_is_fine_once_a_reveal_is_permitted():
    turn = TutorTurn("Just write (x+1)(x+2).", HelpRung.FULL_REVEAL)
    assert validate_turn(turn, context(HelpRung.FULL_REVEAL), GRAPH, VERIFIER).accepted


def test_a_valid_prerequisite_proposal_is_accepted():
    turn = TutorTurn(
        "Let us go back a step.",
        HelpRung.NUDGE,
        proposals=(Proposal(ProposalKind.DROP_TO_PREREQUISITE, SkillId("quad.expand.binomial")),),
    )
    assert validate_turn(turn, context(), GRAPH, VERIFIER).accepted


def test_a_proposal_to_an_unrelated_skill_is_rejected():
    turn = TutorTurn(
        "Let us try something else.",
        HelpRung.NUDGE,
        proposals=(Proposal(ProposalKind.DROP_TO_PREREQUISITE, SkillId("unrelated")),),
    )
    result = validate_turn(turn, context(), GRAPH, VERIFIER)
    assert not result.accepted and result.reason is RejectionReason.INVALID_PROPOSAL


def test_a_prerequisite_proposal_with_no_target_is_rejected():
    turn = TutorTurn(
        "Back a step.", HelpRung.NUDGE, proposals=(Proposal(ProposalKind.DROP_TO_PREREQUISITE),)
    )
    assert not validate_turn(turn, context(), GRAPH, VERIFIER).accepted


def test_an_empty_message_is_rejected():
    result = validate_turn(TutorTurn("   ", HelpRung.NUDGE), context(), GRAPH, VERIFIER)
    assert not result.accepted and result.reason is RejectionReason.EMPTY_MESSAGE
```

- [ ] **Step 3: Run the validation tests**

Run: `.venv/bin/pytest tests/domain/test_turn_validation.py -v`
Expected: PASS — 8 tests.

- [ ] **Step 4: Write FakeTutor and its test**

```python
# src/learnai/adapters/tutor/fake_tutor.py
from collections.abc import Sequence

from learnai.domain.enums import HelpRung
from learnai.domain.turn import TurnContext, TutorTurn

_GENERIC_NUDGES = (
    "What is the very next thing you could try?",
    "Look again at the step before this one.",
    "What does the method say to do first here?",
)


class FakeTutor:
    """Deterministic, scripted Tutor. No API key, no cost, no flakiness.

    With no script it answers with a bland, never-leaking nudge at the highest
    rung the context permits, which is enough to drive the whole engine.
    """

    def __init__(self, script: Sequence[TutorTurn] | None = None) -> None:
        self._script = list(script or [])
        self._index = 0
        self.contexts_seen: list[TurnContext] = []

    def respond(self, context: TurnContext) -> TutorTurn:
        self.contexts_seen.append(context)
        if self._index < len(self._script):
            turn = self._script[self._index]
            self._index += 1
            return turn
        message = _GENERIC_NUDGES[len(self.contexts_seen) % len(_GENERIC_NUDGES)]
        rung = context.permitted_rung if context.permitted_rung > HelpRung.NONE else HelpRung.NUDGE
        return TutorTurn(message=message, rung_used=rung, diagnosis=context.diagnosis)
```

```python
# tests/adapters/test_fake_tutor.py
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.enums import HelpRung, VettingLevel
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import ItemId, SkillId, VerificationKind
from learnai.domain.items import AnswerSpec, Item, Provenance
from learnai.domain.skills import Skill
from learnai.domain.turn import SkillPack, StudentSummary, TurnContext, TutorTurn, validate_turn

GRAPH = SkillGraph.build(
    [Skill(SkillId("s"), "math", "s", "can s", VerificationKind("cas_symbolic"), (), ())], []
)
ITEM = Item(
    ItemId("i"), SkillId("s"), Provenance.authored(), "Factor x^2 + 3x + 2",
    AnswerSpec("(x + 1)*(x + 2)"), (), 0.0, VettingLevel.MACHINE_VERIFIED,
)


def ctx(permitted=HelpRung.NUDGE) -> TurnContext:
    return TurnContext(
        SkillPack(SkillId("s"), "can s", "", ()),
        ITEM,
        StudentSummary(0.0, True, 0.0, ()),
        None,
        None,
        permitted,
    )


def test_the_default_response_always_passes_validation():
    tutor = FakeTutor()
    verifier = SympyVerifier()
    for _ in range(5):
        turn = tutor.respond(ctx())
        assert validate_turn(turn, ctx(), GRAPH, verifier).accepted


def test_the_script_is_played_in_order_then_falls_back():
    scripted = TutorTurn("scripted", HelpRung.NUDGE)
    tutor = FakeTutor([scripted])
    assert tutor.respond(ctx()) is scripted
    assert tutor.respond(ctx()).message != "scripted"


def test_contexts_are_recorded_for_assertions():
    tutor = FakeTutor()
    tutor.respond(ctx(HelpRung.NEXT_STEP))
    assert tutor.contexts_seen[0].permitted_rung is HelpRung.NEXT_STEP


def test_a_scripted_leak_is_caught_by_validation():
    tutor = FakeTutor([TutorTurn("It is (x+1)(x+2).", HelpRung.NUDGE)])
    result = validate_turn(tutor.respond(ctx()), ctx(), GRAPH, SympyVerifier())
    assert not result.accepted
```

- [ ] **Step 5: Run the fake tutor tests**

Run: `.venv/bin/pytest tests/adapters/test_fake_tutor.py -v`
Expected: PASS — 4 tests.

- [ ] **Step 6: Commit**

```bash
git add src/learnai/domain/turn.py src/learnai/domain/ports.py src/learnai/adapters/tutor \
        tests/domain/test_turn_validation.py tests/adapters/test_fake_tutor.py
git commit -m "feat: tutor turn contract, validation pipeline, and fake tutor"
```

---

### Task 15: Session state machine and planner

**Files:**
- Create: `src/learnai/domain/session.py`, `src/learnai/domain/planner.py`
- Test: `tests/domain/test_session.py`, `tests/domain/test_planner.py`

**Interfaces:**
- Consumes: `SkillGraph`, `Item`, `ModeContract`, `HelpState`, `SkillState`, `is_learned`, `is_fresh`, `ItemSource`, constants.
- Produces: `TaskState` enum (`PENDING`, `ACTIVE`, `COMPLETED`, `ABANDONED`); `Task(id, session_id, item, skill_id, state, help_state)`; `Session(id, student_id, course_id, contract, plan, cursor, started_at, ended_at, skills_taught)` with `current_task` and `is_finished`; pure transitions `replace_task(session, task)`, `advance(session)`, `end_session(session, now)`; `target_difficulty(state) -> float`, `select_skills(graph, states, course_skills, count, now) -> tuple[SkillId, ...]`, `plan_session(...) -> Session`.

- [ ] **Step 1: Write the session module**

```python
# src/learnai/domain/session.py
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from learnai.domain.contracts import ModeContract
from learnai.domain.help import HelpState
from learnai.domain.ids import CourseId, SessionId, SkillId, StudentId, TaskId
from learnai.domain.items import Item


class TaskState(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class Task:
    id: TaskId
    session_id: SessionId
    item: Item
    skill_id: SkillId
    state: TaskState = TaskState.PENDING
    help_state: HelpState = HelpState()


@dataclass(frozen=True, slots=True)
class Session:
    id: SessionId
    student_id: StudentId
    course_id: CourseId
    contract: ModeContract
    plan: tuple[Task, ...]
    cursor: int
    started_at: datetime
    ended_at: datetime | None = None
    skills_taught: frozenset[SkillId] = frozenset()
    """Skills instructed during this session; drives post_instruction weighting."""

    @property
    def current_task(self) -> Task | None:
        if self.cursor >= len(self.plan):
            return None
        return self.plan[self.cursor]

    @property
    def is_finished(self) -> bool:
        return self.ended_at is not None or self.cursor >= len(self.plan)


def replace_task(session: Session, task: Task) -> Session:
    plan = tuple(task if t.id == task.id else t for t in session.plan)
    return replace(session, plan=plan)


def advance(session: Session) -> Session:
    return replace(session, cursor=session.cursor + 1)


def end_session(session: Session, now: datetime) -> Session:
    return replace(session, ended_at=now)
```

- [ ] **Step 2: Write the failing session test**

```python
# tests/domain/test_session.py
from dataclasses import replace

from learnai.adapters.clock import FakeClock
from learnai.domain.contracts import PRACTICE
from learnai.domain.enums import VettingLevel
from learnai.domain.ids import CourseId, ItemId, SessionId, SkillId, StudentId, TaskId
from learnai.domain.items import AnswerSpec, Item, Provenance
from learnai.domain.session import Session, Task, TaskState, advance, end_session, replace_task


def item(n: int) -> Item:
    return Item(ItemId(f"i{n}"), SkillId("s"), Provenance.authored(), f"q{n}",
                AnswerSpec("1"), (), 0.0, VettingLevel.MACHINE_VERIFIED)


def session(n_tasks: int = 2) -> Session:
    clock = FakeClock()
    tasks = tuple(
        Task(TaskId(f"t{i}"), SessionId("sess"), item(i), SkillId("s")) for i in range(n_tasks)
    )
    return Session(SessionId("sess"), StudentId("stu"), CourseId("c"), PRACTICE,
                   tasks, 0, clock.now())


def test_current_task_follows_the_cursor():
    s = session()
    assert s.current_task.id == TaskId("t0")
    assert advance(s).current_task.id == TaskId("t1")


def test_a_session_finishes_when_the_plan_is_exhausted():
    s = advance(advance(session()))
    assert s.current_task is None and s.is_finished


def test_ending_a_session_marks_it_finished_early():
    clock = FakeClock()
    s = end_session(session(), clock.advance(0.01))
    assert s.is_finished and s.ended_at is not None


def test_replacing_a_task_leaves_the_others_untouched():
    s = session()
    updated = replace(s.plan[0], state=TaskState.COMPLETED)
    after = replace_task(s, updated)
    assert after.plan[0].state is TaskState.COMPLETED
    assert after.plan[1] == s.plan[1]


def test_transitions_never_mutate_the_original():
    s = session()
    advance(s)
    assert s.cursor == 0
```

- [ ] **Step 3: Write the failing planner test**

```python
# tests/domain/test_planner.py
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.domain.contracts import PRACTICE
from learnai.domain.enums import PrereqStrength
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import CourseId, SessionId, SkillId, StudentId, VerificationKind
from learnai.domain.mastery import SkillState
from learnai.domain.parameters import DEFAULT_PARAMETERS
from learnai.domain.planner import plan_session, select_skills, target_difficulty
from learnai.domain.skills import PrereqEdge, Skill

REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)


def _skill(sid: str) -> Skill:
    return Skill(SkillId(sid), "math", sid, f"can {sid}", VerificationKind("cas_symbolic"), (), ())


GRAPH = SkillGraph.build(
    [_skill("quad.expand.binomial"), _skill("quad.factor.monic"), _skill("quad.solve.factoring")],
    [
        PrereqEdge(SkillId("quad.expand.binomial"), SkillId("quad.factor.monic"), PrereqStrength.HARD),
        PrereqEdge(SkillId("quad.factor.monic"), SkillId("quad.solve.factoring"), PrereqStrength.HARD),
    ],
)
COURSE = (SkillId("quad.expand.binomial"), SkillId("quad.factor.monic"), SkillId("quad.solve.factoring"))


def learned(sid: str, clock: FakeClock, stability: float = 30.0) -> SkillState:
    return SkillState(StudentId("stu"), SkillId(sid), strength=2.0, stability=stability,
                      last_success_at=clock.now(), unassisted_correct_count=2)


def test_an_unknown_skill_targets_items_below_the_default_strength():
    assert target_difficulty(None) == -DEFAULT_PARAMETERS.target_logit_margin


def test_target_difficulty_tracks_strength():
    state = SkillState(StudentId("stu"), SkillId("s"), strength=2.0)
    assert target_difficulty(state) == 2.0 - DEFAULT_PARAMETERS.target_logit_margin


def test_an_empty_history_starts_at_the_graph_root():
    clock = FakeClock()
    chosen = select_skills(GRAPH, {}, COURSE, count=3, now=clock.now())
    assert set(chosen) == {SkillId("quad.expand.binomial")}


def test_the_frontier_advances_as_skills_are_learned():
    clock = FakeClock()
    states = {SkillId("quad.expand.binomial"): learned("quad.expand.binomial", clock)}
    chosen = select_skills(GRAPH, states, COURSE, count=2, now=clock.now())
    assert set(chosen) == {SkillId("quad.factor.monic")}


def test_a_stale_prerequisite_is_repaired_before_advancing():
    clock = FakeClock()
    states = {SkillId("quad.expand.binomial"): learned("quad.expand.binomial", clock, stability=2.0)}
    clock.advance(30.0)
    chosen = select_skills(GRAPH, states, COURSE, count=2, now=clock.now())
    assert chosen[0] == SkillId("quad.expand.binomial"), "repair before advance"


def test_the_plan_fills_the_requested_budget():
    clock = FakeClock()
    session = plan_session(
        session_id=SessionId("s1"), student_id=StudentId("stu"), course_id=CourseId("c"),
        contract=PRACTICE, graph=GRAPH, states={}, course_skills=COURSE,
        item_source=REGISTRY, budget_items=5, now=clock.now(), seed=11,
    )
    assert len(session.plan) == 5
    assert all(t.item.vetting_level >= PRACTICE.min_vetting_level for t in session.plan)


def test_planning_is_deterministic_for_a_given_seed():
    clock = FakeClock()
    kwargs = dict(
        session_id=SessionId("s1"), student_id=StudentId("stu"), course_id=CourseId("c"),
        contract=PRACTICE, graph=GRAPH, states={}, course_skills=COURSE,
        item_source=REGISTRY, budget_items=4, now=clock.now(), seed=11,
    )
    assert [t.item.id for t in plan_session(**kwargs).plan] == [
        t.item.id for t in plan_session(**kwargs).plan
    ]


def test_a_plan_never_repeats_an_item():
    clock = FakeClock()
    session = plan_session(
        session_id=SessionId("s1"), student_id=StudentId("stu"), course_id=CourseId("c"),
        contract=PRACTICE, graph=GRAPH, states={}, course_skills=COURSE,
        item_source=REGISTRY, budget_items=8, now=clock.now(), seed=3,
    )
    ids = [t.item.id for t in session.plan]
    assert len(ids) == len(set(ids))
```

- [ ] **Step 4: Write the planner**

```python
# src/learnai/domain/planner.py
from collections.abc import Sequence
from datetime import datetime

from learnai.domain.contracts import ModeContract
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import CourseId, SessionId, SkillId, StudentId, TaskId
from learnai.domain.mastery import SkillState, is_fresh, is_learned
from learnai.domain.parameters import DEFAULT_PARAMETERS, MasteryParameters
from learnai.domain.ports import ItemSource
from learnai.domain.session import Session, Task


def target_difficulty(
    state: SkillState | None, params: MasteryParameters = DEFAULT_PARAMETERS
) -> float:
    """Aim an item the student should clear about 75% of the time."""
    strength = 0.0 if state is None else state.strength
    return strength - params.target_logit_margin


def select_skills(
    graph: SkillGraph,
    states: dict[SkillId, SkillState],
    course_skills: Sequence[SkillId],
    count: int,
    now: datetime,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> tuple[SkillId, ...]:
    """Repair stale prerequisites before advancing to new material.

    Slice 1 has no spaced-review queue; freshness enters only through this
    repair rule. The full due-queue arbitration arrives with the scheduler.
    """
    learned = {sid for sid, state in states.items() if is_learned(state, params)}
    frontier = graph.frontier(learned) & set(course_skills)
    ordered_frontier = [sid for sid in course_skills if sid in frontier]

    repair: list[SkillId] = []
    for sid in ordered_frontier:
        for prereq in sorted(graph.hard_prereqs(sid)):
            state = states.get(prereq)
            if (
                state
                and is_learned(state, params)
                and not is_fresh(state, now, params)
                and prereq not in repair
            ):
                repair.append(prereq)

    ordered = repair + ordered_frontier
    if not ordered:
        return ()
    return tuple(ordered[i % len(ordered)] for i in range(count))


def plan_session(
    *,
    session_id: SessionId,
    student_id: StudentId,
    course_id: CourseId,
    contract: ModeContract,
    graph: SkillGraph,
    states: dict[SkillId, SkillState],
    course_skills: Sequence[SkillId],
    item_source: ItemSource,
    budget_items: int,
    now: datetime,
    seed: int,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> Session:
    skills = select_skills(graph, states, course_skills, budget_items, now, params)
    tasks: list[Task] = []
    for position, skill_id in enumerate(skills):
        item = item_source.next_item(
            skill_id,
            target_difficulty(states.get(skill_id), params),
            seed=seed * 1000 + position,
        )
        if item.vetting_level < contract.min_vetting_level:
            continue
        tasks.append(
            Task(
                id=TaskId(f"{session_id}:{position}"),
                session_id=session_id,
                item=item,
                skill_id=skill_id,
            )
        )
    return Session(
        id=session_id,
        student_id=student_id,
        course_id=course_id,
        contract=contract,
        plan=tuple(tasks),
        cursor=0,
        started_at=now,
    )
```

- [ ] **Step 5: Run both test modules**

Run: `.venv/bin/pytest tests/domain/test_session.py tests/domain/test_planner.py -v`
Expected: PASS — 13 tests.

- [ ] **Step 6: Commit**

```bash
git add src/learnai/domain/session.py src/learnai/domain/planner.py \
        tests/domain/test_session.py tests/domain/test_planner.py
git commit -m "feat: session state machine and frontier-based planner"
```

---

### Task 16: Append-only evidence log and projection

**Files:**
- Create: `src/learnai/domain/events.py`, `src/learnai/domain/projection.py`
- Create: `src/learnai/adapters/persistence/__init__.py`, `src/learnai/adapters/persistence/in_memory.py`
- Modify: `src/learnai/domain/ports.py` (add the `EvidenceLog` protocol)
- Test: `tests/domain/test_projection.py`

**Interfaces:**
- Consumes: mastery, evidence, calibration, propagation (Tasks 9–11).
- Produces: `AttemptRecorded`, `HelpTaken`, `EvidenceEvent` union; `apply_event(states, event, graph) -> dict[SkillId, SkillState]`; `project(events, graph, student_id) -> dict[SkillId, SkillState]`; `EvidenceLog` protocol with `append(event)` and `events()`; `InMemoryEvidenceLog`.

**Why this shape:** the same `apply_event` runs live in the engine and during a rebuild, so a replayed projection cannot drift from the running one. That is what makes P6 real rather than aspirational — and it is the only reason the mastery constants can be retuned later without stranding existing students.

- [ ] **Step 1: Write the events**

```python
# src/learnai/domain/events.py
from dataclasses import dataclass
from datetime import datetime

from learnai.domain.enums import Confidence, EvidenceClass, HelpRung
from learnai.domain.ids import ItemId, SkillId, StudentId, TaskId


@dataclass(frozen=True, slots=True)
class AttemptRecorded:
    at: datetime
    student_id: StudentId
    skill_id: SkillId
    item_id: ItemId
    task_id: TaskId
    item_difficulty: float
    outcome: float
    """1.0 correct, 0.0 wrong, the format's guess baseline for a decline."""
    evidence_class: EvidenceClass
    confidence: Confidence
    contract_weight: float

    @property
    def correct(self) -> bool:
        return self.outcome >= 1.0


@dataclass(frozen=True, slots=True)
class HelpTaken:
    at: datetime
    student_id: StudentId
    skill_id: SkillId
    item_id: ItemId
    task_id: TaskId
    rung: HelpRung


EvidenceEvent = AttemptRecorded | HelpTaken
```

- [ ] **Step 2: Write the failing projection test**

```python
# tests/domain/test_projection.py
from hypothesis import given
from hypothesis import strategies as st

from learnai.adapters.clock import FakeClock
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.domain.enums import Confidence, EvidenceClass, HelpRung, PrereqStrength
from learnai.domain.events import AttemptRecorded, HelpTaken
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import ItemId, SkillId, StudentId, TaskId, VerificationKind
from learnai.domain.mastery import is_learned
from learnai.domain.projection import apply_event, project
from learnai.domain.skills import PrereqEdge, Skill

STUDENT = StudentId("stu")
SKILL = SkillId("quad.factor.monic")
PREREQ = SkillId("quad.expand.binomial")


def _skill(sid: SkillId) -> Skill:
    return Skill(sid, "math", str(sid), "can", VerificationKind("cas_symbolic"), (), ())


GRAPH = SkillGraph.build(
    [_skill(PREREQ), _skill(SKILL)], [PrereqEdge(PREREQ, SKILL, PrereqStrength.HARD)]
)


def attempt(clock, *, skill=SKILL, correct=True, evidence=EvidenceClass.UNASSISTED_COLD,
            confidence=Confidence.FAIRLY_SURE, difficulty=0.0, outcome=None):
    return AttemptRecorded(
        at=clock.now(), student_id=STUDENT, skill_id=skill, item_id=ItemId("i"),
        task_id=TaskId("t"), item_difficulty=difficulty,
        outcome=(1.0 if correct else 0.0) if outcome is None else outcome,
        evidence_class=evidence, confidence=confidence, contract_weight=1.0,
    )


def test_a_cold_success_raises_strength_and_sets_stability():
    clock = FakeClock()
    states = project([attempt(clock)], GRAPH, STUDENT)
    assert states[SKILL].strength > 0.0
    assert states[SKILL].stability > 0.0


def test_assisted_attempts_move_nothing():
    clock = FakeClock()
    events = [attempt(clock, evidence=EvidenceClass.ASSISTED) for _ in range(20)]
    states = project(events, GRAPH, STUDENT)
    assert states[SKILL].strength == 0.0
    assert states[SKILL].stability == 0.0
    assert not is_learned(states[SKILL])


def test_help_events_never_change_state():
    clock = FakeClock()
    help_event = HelpTaken(clock.now(), STUDENT, SKILL, ItemId("i"), TaskId("t"), HelpRung.NUDGE)
    before = project([attempt(clock)], GRAPH, STUDENT)
    after = project([attempt(clock), help_event], GRAPH, STUDENT)
    assert before == after


def test_events_for_other_students_are_ignored():
    clock = FakeClock()
    other = AttemptRecorded(
        clock.now(), StudentId("someone_else"), SKILL, ItemId("i"), TaskId("t"),
        0.0, 1.0, EvidenceClass.UNASSISTED_COLD, Confidence.CERTAIN, 1.0,
    )
    assert project([other], GRAPH, STUDENT) == {}


def test_a_downstream_success_refreshes_a_learned_prerequisite():
    clock = FakeClock()
    events = [
        attempt(clock, skill=PREREQ, difficulty=-1.0),
        attempt(clock, skill=PREREQ, difficulty=-1.0),
        attempt(clock, skill=PREREQ, difficulty=-1.0),
    ]
    clock.advance(20.0)
    before = project(events, GRAPH, STUDENT)[PREREQ].last_success_at
    events.append(attempt(clock, skill=SKILL))
    after = project(events, GRAPH, STUDENT)[PREREQ].last_success_at
    assert after > before


def test_calibration_records_overconfidence():
    clock = FakeClock()
    events = [attempt(clock, correct=False, confidence=Confidence.CERTAIN) for _ in range(10)]
    assert project(events, GRAPH, STUDENT)[SKILL].calibration_gap > 0.0


def test_rebuilding_from_the_log_reproduces_the_live_projection():
    clock = FakeClock()
    log = InMemoryEvidenceLog()
    live: dict[SkillId, object] = {}
    for _ in range(6):
        event = attempt(clock)
        log.append(event)
        live = apply_event(live, event, GRAPH)
        clock.advance(3.0)
    assert project(log.events(), GRAPH, STUDENT) == live


def test_a_decline_never_counts_toward_the_mastery_gate():
    """It is scored near the guess baseline, which must not read as competence."""
    clock = FakeClock()
    events = [
        attempt(clock, outcome=0.03, confidence=Confidence.NO_IDEA) for _ in range(30)
    ]
    states = project(events, GRAPH, STUDENT)
    assert states[SKILL].unassisted_correct_count == 0
    assert not is_learned(states[SKILL])


def test_the_log_is_append_only():
    log = InMemoryEvidenceLog()
    clock = FakeClock()
    log.append(attempt(clock))
    snapshot = log.events()
    log.append(attempt(clock))
    assert len(snapshot) == 1, "events() must return an immutable snapshot"
    assert len(log.events()) == 2


@given(count=st.integers(min_value=1, max_value=40))
def test_no_amount_of_help_can_ever_produce_mastery(count):
    """The headline invariant: assistance cannot manufacture a learned skill."""
    clock = FakeClock()
    events: list[object] = []
    for _ in range(count):
        events.append(
            HelpTaken(clock.now(), STUDENT, SKILL, ItemId("i"), TaskId("t"), HelpRung.NAME_METHOD)
        )
        events.append(attempt(clock, evidence=EvidenceClass.ASSISTED))
        clock.advance(1.0)
    states = project(events, GRAPH, STUDENT)
    assert not is_learned(states[SKILL])
```

- [ ] **Step 3: Write the projection and the log**

```python
# src/learnai/domain/projection.py
from collections.abc import Iterable
from dataclasses import replace as dc_replace

from learnai.domain.calibration import update_calibration
from learnai.domain.events import AttemptRecorded, EvidenceEvent, HelpTaken
from learnai.domain.evidence import EVIDENCE_WEIGHT
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import SkillId, StudentId
from learnai.domain.mastery import SkillState, update_stability, update_strength
from learnai.domain.parameters import DEFAULT_PARAMETERS, MasteryParameters
from learnai.domain.propagation import propagate_success


def apply_event(
    states: dict[SkillId, SkillState],
    event: EvidenceEvent,
    graph: SkillGraph,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> dict[SkillId, SkillState]:
    """Fold one event into the projection. Used live and on replay — never diverge."""
    if isinstance(event, HelpTaken):
        return dict(states)  # help is audited, never credited

    assert isinstance(event, AttemptRecorded)
    weight = event.contract_weight * EVIDENCE_WEIGHT[event.evidence_class]
    current = states.get(event.skill_id) or SkillState(event.student_id, event.skill_id)

    updated = update_strength(current, event.item_difficulty, event.outcome, weight, params)
    if weight > 0.0:
        updated = update_stability(updated, event.correct, event.at, params)
    updated = dc_replace(
        updated,
        calibration_gap=update_calibration(
            current.calibration_gap, event.confidence, event.correct, params
        ),
    )

    result = dict(states)
    result[event.skill_id] = updated
    if event.correct and weight > 0.0:
        result = propagate_success(result, graph, event.skill_id, event.at, params)
    return result


def project(
    events: Iterable[EvidenceEvent],
    graph: SkillGraph,
    student_id: StudentId,
    params: MasteryParameters = DEFAULT_PARAMETERS,
) -> dict[SkillId, SkillState]:
    """Rebuild a student's whole mastery state from the log. The truth is the log."""
    states: dict[SkillId, SkillState] = {}
    for event in events:
        if event.student_id != student_id:
            continue
        states = apply_event(states, event, graph, params)
    return states
```

```python
# src/learnai/adapters/persistence/in_memory.py
from learnai.domain.events import EvidenceEvent


class InMemoryEvidenceLog:
    """Append-only event log. Plan 2 replaces this with Postgres, same protocol."""

    def __init__(self) -> None:
        self._events: list[EvidenceEvent] = []

    def append(self, event: EvidenceEvent) -> None:
        self._events.append(event)

    def events(self) -> tuple[EvidenceEvent, ...]:
        return tuple(self._events)
```

Append to `src/learnai/domain/ports.py`:

```python
class EvidenceLog(Protocol):
    def append(self, event: "EvidenceEvent") -> None: ...

    def events(self) -> tuple["EvidenceEvent", ...]: ...
```

- [ ] **Step 4: Run the projection tests**

Run: `.venv/bin/pytest tests/domain/test_projection.py -v`
Expected: PASS — 10 tests.

- [ ] **Step 5: Commit**

```bash
git add src/learnai/domain/events.py src/learnai/domain/projection.py \
        src/learnai/domain/ports.py src/learnai/adapters/persistence \
        tests/domain/test_projection.py
git commit -m "feat: append-only evidence log with replayable projection"
```

---

### Task 17: PracticeEngine — the whole loop

**Files:**
- Create: `src/learnai/domain/engine.py`
- Test: `tests/domain/test_engine.py`

**Interfaces:**
- Consumes: everything from Tasks 1–16.
- Produces: `SubmitOutcome(verdict, step_diff, diagnosis, evidence_class, tutor_turn, task_completed)`; `PracticeEngine(graph, misconceptions, item_source, verifiers, tutor, matcher, evidence_log, clock, contract, parameters, parameter_overrides)` — `verifiers` is a `Mapping[VerificationKind, Verifier]` resolved per skill — construction raises `UnregisteredVerifierError` if any skill's kind is missing from it — and `parameter_overrides` a `Mapping[SkillId, MasteryParameters]` with `start_session(...) -> Session`, `submit(session, states, steps, answer: Submission, confidence) -> tuple[Session, states, SubmitOutcome]`, `request_help(session, states) -> tuple[Session, TutorTurn | None]`.

**Two seams made real here.** The engine resolves a verifier per skill through
`verifiers[skill.verification_kind]`, so `verification_kind` is a live lookup rather than a
notional one — Slice 1 registers a single entry and physics adds a second without touching this
class. Construction checks every skill's kind against the registry and raises
`UnregisteredVerifierError` for any it cannot serve. The content loader cannot make that check,
since it treats the kind as opaque (Task 2), and without it a typo in `verification:` would
surface as a crash on some student's first attempt at that skill rather than at startup. Likewise `_params_for(skill_id)` consults `parameter_overrides`, which is what spec §7.8
step 3 needs when parameters start being fitted per skill.

**The cost shape to preserve:** a correct first attempt must invoke the tutor **zero** times. The generator serves the item, the CAS checks it, the engine records evidence. That is the property that makes Opus-tier tutoring affordable, and there is a test for it.

- [ ] **Step 1: Write the failing engine test**

```python
# tests/domain/test_engine.py
import pathlib

import pytest

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.contracts import PRACTICE
from learnai.domain.engine import PracticeEngine, UnregisteredVerifierError
from learnai.domain.enums import Confidence, EvidenceClass, HelpRung, Verdict
from learnai.domain.ids import CourseId, SessionId, StudentId
from learnai.domain.items import Submission
from learnai.domain.mastery import is_learned

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
COURSE = CLUSTER.graph.topological_order()


def right(task) -> Submission:
    """What a student who knows the answer enters."""
    return SympyVerifier().key_submission(task.item.answer_spec)


def build(tutor: FakeTutor | None = None, clock: FakeClock | None = None):
    clock = clock or FakeClock()
    verifier = SympyVerifier()
    engine = PracticeEngine(
        graph=CLUSTER.graph,
        misconceptions=CLUSTER.misconceptions,
        item_source=GeneratorRegistry(QUADRATICS_TEMPLATES),
        verifiers={CAS_SYMBOLIC: verifier},
        tutor=tutor or FakeTutor(),
        matcher=SympyMisconceptionRules(),
        evidence_log=InMemoryEvidenceLog(),
        clock=clock,
        contract=PRACTICE,
    )
    session = engine.start_session(
        student_id=StudentId("stu"),
        course_id=CourseId("quadratics"),
        course_skills=COURSE,
        states={},
        budget_items=4,
        session_id=SessionId("sess-1"),
        seed=7,
    )
    return engine, session, clock


def test_a_session_starts_with_a_plan_of_the_requested_size():
    _, session, _ = build()
    assert len(session.plan) == 4
    assert session.current_task is not None


def test_an_unregistered_verification_kind_is_refused_at_construction():
    """Fail at startup, not on some student's first attempt at the skill."""
    with pytest.raises(UnregisteredVerifierError, match="cas_symbolic"):
        PracticeEngine(
            graph=CLUSTER.graph,
            misconceptions=CLUSTER.misconceptions,
            item_source=GeneratorRegistry(QUADRATICS_TEMPLATES),
            verifiers={},
            tutor=FakeTutor(),
            matcher=SympyMisconceptionRules(),
            evidence_log=InMemoryEvidenceLog(),
            clock=FakeClock(),
            contract=PRACTICE,
        )


def test_a_correct_first_attempt_costs_no_tutor_turn():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    task = session.current_task
    session, states, outcome = engine.submit(
        session, {}, steps=[], answer=right(task),
        confidence=Confidence.FAIRLY_SURE,
    )
    assert outcome.verdict is Verdict.CORRECT
    assert outcome.evidence_class is EvidenceClass.UNASSISTED_COLD
    assert outcome.tutor_turn is None
    assert tutor.contexts_seen == [], "the model must not be invoked on a clean success"
    assert states[task.skill_id].strength > 0.0
    assert outcome.task_completed


def test_a_wrong_attempt_summons_the_tutor_with_a_localised_step():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    session, _, outcome = engine.submit(
        session, {}, steps=["(x+1)(x+2)", "x^2 + 2"], answer=Submission.of("x^2 + 2"),
        confidence=Confidence.UNSURE,
    )
    assert outcome.verdict is Verdict.WRONG
    assert outcome.tutor_turn is not None
    assert len(tutor.contexts_seen) == 1
    assert tutor.contexts_seen[0].step_diff is not None


def test_a_wrong_attempt_earns_nothing_but_is_still_recorded():
    engine, session, _ = build()
    task = session.current_task
    session, states, _ = engine.submit(
        session, {}, steps=[], answer=Submission.of("0"), confidence=Confidence.CERTAIN
    )
    assert states[task.skill_id].attempt_count == 1
    assert states[task.skill_id].strength < 0.0
    assert not is_learned(states[task.skill_id])


def test_requesting_help_climbs_one_rung_and_marks_the_attempt_assisted():
    engine, session, _ = build()
    task = session.current_task
    session, turn = engine.request_help(session, {})
    assert turn is not None and turn.rung_used is HelpRung.NUDGE

    session, states, outcome = engine.submit(
        session, {}, steps=[], answer=right(task),
        confidence=Confidence.CERTAIN,
    )
    assert outcome.verdict is Verdict.CORRECT
    assert outcome.evidence_class is EvidenceClass.ASSISTED
    assert states[task.skill_id].strength == 0.0, "P2: assistance never moves mastery"


def test_help_runs_out_at_the_base_rung_before_effort_is_documented():
    engine, session, _ = build()
    for _ in range(3):
        session, turn = engine.request_help(session, {})
        assert turn is not None
    session, turn = engine.request_help(session, {})
    assert turn is None, "no reveal until the effort condition is met"


def test_a_leaking_tutor_turn_never_reaches_the_student():
    from learnai.domain.turn import TutorTurn

    # Planning is deterministic for a seed, so probe once to learn the answer,
    # then rebuild with a tutor scripted to leak exactly it.
    _, probe, _ = build()
    answer = probe.current_task.item.answer_spec.expression

    leak = TutorTurn(f"Just write {answer}.", HelpRung.NUDGE)
    engine, session, _ = build(FakeTutor([leak, leak]))

    session, turn = engine.request_help(session, {})
    assert turn is None, "every retry leaked, so nothing may be delivered"


def test_declining_costs_the_same_as_a_wrong_answer():
    engine, session, _ = build()
    task = session.current_task
    session, states, outcome = engine.submit(
        session, {}, steps=[], answer=Submission.of(""), confidence=Confidence.CERTAIN
    )
    assert outcome.verdict is Verdict.NO_ANSWER
    assert outcome.evidence_class is EvidenceClass.UNASSISTED_COLD
    assert states[task.skill_id].strength < 0.0, "a decline is the same competence signal"
    assert outcome.tutor_turn is not None, "and it summons the tutor"


def test_declining_forces_the_no_idea_confidence_reading():
    engine, session, _ = build()
    engine.submit(session, {}, steps=[], answer=Submission.of("  "), confidence=Confidence.CERTAIN)
    recorded = engine.evidence_log.events()[0]
    assert recorded.confidence is Confidence.NO_IDEA


def test_declining_does_not_climb_toward_a_reveal():
    """Otherwise the cheapest route to the answer is two declines and three hints."""
    engine, session, _ = build()
    for _ in range(2):
        session, _, _ = engine.submit(
            session, {}, steps=[], answer=Submission.of(""), confidence=Confidence.NO_IDEA
        )
    for _ in range(3):
        session, turn = engine.request_help(session, {})
        assert turn is not None
    session, turn = engine.request_help(session, {})
    assert turn is None, "declines are not documented effort"


def test_the_tutor_is_told_the_student_declined():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    engine.submit(session, {}, steps=[], answer=Submission.of(""), confidence=Confidence.NO_IDEA)
    assert tutor.contexts_seen[0].last_verdict is Verdict.NO_ANSWER
    assert tutor.contexts_seen[0].step_diff is None


def test_the_session_advances_and_finishes():
    engine, session, _ = build()
    for _ in range(4):
        task = session.current_task
        assert task is not None
        session, _, _ = engine.submit(
            session, {}, steps=[], answer=right(task),
            confidence=Confidence.FAIRLY_SURE,
        )
    assert session.is_finished


def test_every_attempt_lands_in_the_append_only_log():
    engine, session, _ = build()
    task = session.current_task
    engine.submit(session, {}, steps=[], answer=right(task),
                  confidence=Confidence.CERTAIN)
    assert len(engine.evidence_log.events()) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'learnai.domain.engine'`

- [ ] **Step 3: Write the engine**

```python
# src/learnai/domain/engine.py
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from learnai.domain.contracts import ModeContract
from learnai.domain.enums import (
    Confidence,
    EvidenceClass,
    HelpRung,
    InterventionTiming,
    Verdict,
)
from learnai.domain.events import AttemptRecorded, HelpTaken
from learnai.domain.evidence import classify_evidence
from learnai.domain.graph import SkillGraph
from learnai.domain.help import next_rung, permitted_rung, record_attempt, record_help
from learnai.domain.ids import (
    CourseId,
    MisconceptionId,
    SessionId,
    SkillId,
    StudentId,
    TaskId,
    VerificationKind,
)
from learnai.domain.items import StepDiff, Submission
from learnai.domain.mastery import SkillState, is_fresh
from learnai.domain.misconceptions import MisconceptionMatcher, diagnose
from learnai.domain.parameters import DEFAULT_PARAMETERS, MasteryParameters
from learnai.domain.planner import plan_session
from learnai.domain.ports import Clock, EvidenceLog, ItemSource, Tutor, Verifier
from learnai.domain.projection import apply_event
from learnai.domain.session import Session, Task, TaskState, advance, replace_task
from learnai.domain.verification import CheckResult
from learnai.domain.skills import Misconception
from learnai.domain.turn import (
    SkillPack,
    StudentSummary,
    TurnContext,
    TutorTurn,
    validate_turn,
)

MAX_TUTOR_RETRIES = 2


class UnregisteredVerifierError(LookupError):
    """A skill names a verification kind that no registered Verifier serves."""


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    verdict: Verdict
    step_diff: StepDiff | None
    diagnosis: MisconceptionId | None
    evidence_class: EvidenceClass
    tutor_turn: TutorTurn | None
    task_completed: bool


class PracticeEngine:
    """Orchestrates one task's lifecycle. Every decision here is deterministic."""

    def __init__(
        self,
        *,
        graph: SkillGraph,
        misconceptions: Mapping[MisconceptionId, Misconception],
        item_source: ItemSource,
        verifiers: Mapping[VerificationKind, Verifier],
        tutor: Tutor,
        matcher: MisconceptionMatcher,
        evidence_log: EvidenceLog,
        clock: Clock,
        contract: ModeContract,
        parameters: MasteryParameters = DEFAULT_PARAMETERS,
        parameter_overrides: Mapping[SkillId, MasteryParameters] | None = None,
    ) -> None:
        self.graph = graph
        self.misconceptions = misconceptions
        self.item_source = item_source
        self.verifiers = dict(verifiers)
        needed = {skill.verification_kind for skill in graph.skills.values()}
        if missing := needed - self.verifiers.keys():
            raise UnregisteredVerifierError(
                f"no verifier registered for verification kinds {sorted(missing)}"
            )
        self._tutor = tutor
        self.matcher = matcher
        self.evidence_log = evidence_log
        self.clock = clock
        self.contract = contract
        self.parameters = parameters
        self.parameter_overrides = dict(parameter_overrides or {})

    # -- session lifecycle ---------------------------------------------------

    def start_session(
        self,
        *,
        student_id: StudentId,
        course_id: CourseId,
        course_skills: Sequence[SkillId],
        states: dict[SkillId, SkillState],
        budget_items: int,
        session_id: SessionId,
        seed: int,
    ) -> Session:
        return plan_session(
            session_id=session_id,
            student_id=student_id,
            course_id=course_id,
            contract=self.contract,
            graph=self.graph,
            states=states,
            course_skills=course_skills,
            item_source=self.item_source,
            budget_items=budget_items,
            now=self.clock.now(),
            seed=seed,
            params=self.parameters,
        )

    # -- the loop ------------------------------------------------------------

    def submit(
        self,
        session: Session,
        states: dict[SkillId, SkillState],
        steps: Sequence[str],
        answer: Submission,
        confidence: Confidence,
    ) -> tuple[Session, dict[SkillId, SkillState], SubmitOutcome]:
        """Submit an answer, or decline by leaving every field blank.

        A decline costs exactly what a wrong answer costs — it is the same
        competence signal, and making it cheaper would teach students to stop
        trying. What differs is the tutor's opening move and the calibration
        reading, which for an honest decline is near-perfect.
        """
        task = session.current_task
        if task is None:
            raise ValueError("session has no active task")

        answer.check_shape(task.item.answer_spec.kind)  # a wrong shape is a client bug
        declined = answer.is_blank
        params = self._params_for(task.skill_id)
        verifier = self._verifier_for(task.skill_id)
        if declined:
            confidence = Confidence.NO_IDEA
            result = CheckResult(Verdict.NO_ANSWER)
        else:
            result = verifier.check_answer(answer, task.item.answer_spec)
        correct = result.verdict is Verdict.CORRECT

        # A decline is scored at the guess baseline, not at zero, so that saying
        # "I don't know" never costs more in expectation than guessing would.
        if declined:
            outcome = params.guess_baseline.get(task.item.answer_spec.kind, 0.0)
        else:
            outcome = 1.0 if correct else 0.0

        step_diff: StepDiff | None = None
        diagnosis: MisconceptionId | None = None
        if not correct and not declined and steps:
            step_diff = verifier.diff_steps(steps)
            diagnosis = diagnose(step_diff, self._catalogue(task.skill_id), self.matcher)

        evidence_class = classify_evidence(
            attempt_index=task.help_state.attempts,
            help_taken=task.help_state.help_taken,
            taught_this_session=task.skill_id in session.skills_taught,
            timed=self.contract.timed,
        )

        event = AttemptRecorded(
            at=self.clock.now(),
            student_id=session.student_id,
            skill_id=task.skill_id,
            item_id=task.item.id,
            task_id=task.id,
            item_difficulty=task.item.difficulty,
            outcome=outcome,
            evidence_class=evidence_class,
            confidence=confidence,
            contract_weight=self.contract.evidence_weight,
        )
        self.evidence_log.append(event)
        states = apply_event(states, event, self.graph, params)

        if not declined:
            task = replace(task, help_state=record_attempt(task.help_state))
        tutor_turn: TutorTurn | None = None
        if not correct and self._should_intervene():
            # Unprompted feedback opens at the bottom of the ladder. The ceiling is
            # what the student may climb to on request, not where the tutor starts.
            tutor_turn = self._ask_tutor(
                session,
                task,
                states,
                step_diff,
                diagnosis,
                rung_override=HelpRung.NUDGE,
                last_verdict=result.verdict,
            )

        task = replace(
            task, state=TaskState.COMPLETED if correct else TaskState.ACTIVE
        )
        session = replace_task(session, task)
        if correct:
            session = advance(session)

        return (
            session,
            states,
            SubmitOutcome(
                verdict=result.verdict,
                step_diff=step_diff,
                diagnosis=diagnosis,
                evidence_class=evidence_class,
                tutor_turn=tutor_turn,
                task_completed=correct,
            ),
        )

    def request_help(
        self, session: Session, states: dict[SkillId, SkillState]
    ) -> tuple[Session, TutorTurn | None]:
        task = session.current_task
        if task is None:
            raise ValueError("session has no active task")

        rung = next_rung(self.contract, task.help_state)
        if rung is None:
            return session, None

        self.evidence_log.append(
            HelpTaken(
                at=self.clock.now(),
                student_id=session.student_id,
                skill_id=task.skill_id,
                item_id=task.item.id,
                task_id=task.id,
                rung=rung,
            )
        )
        task = replace(task, help_state=record_help(task.help_state, rung))
        turn = self._ask_tutor(session, task, states, None, None, rung_override=rung)
        return replace_task(session, task), turn

    # -- internals -----------------------------------------------------------

    def _verifier_for(self, skill_id: SkillId) -> Verifier:
        # Construction guarantees every skill's kind is registered.
        return self.verifiers[self.graph.skills[skill_id].verification_kind]

    def _params_for(self, skill_id: SkillId) -> MasteryParameters:
        return self.parameter_overrides.get(skill_id, self.parameters)

    def _should_intervene(self) -> bool:
        return self.contract.intervention_timing is not InterventionTiming.NEVER

    def _catalogue(self, skill_id: SkillId) -> tuple[Misconception, ...]:
        skill = self.graph.skills[skill_id]
        return tuple(self.misconceptions[m] for m in skill.misconception_ids)

    def _build_context(
        self,
        task: Task,
        states: dict[SkillId, SkillState],
        step_diff: StepDiff | None,
        diagnosis: MisconceptionId | None,
        rung_override: HelpRung | None = None,
        last_verdict: Verdict | None = None,
    ) -> TurnContext:
        skill = self.graph.skills[task.skill_id]
        state = states.get(task.skill_id)
        now = self.clock.now()
        return TurnContext(
            skill_pack=SkillPack(
                skill_id=skill.id,
                can_do_statement=skill.can_do_statement,
                teaching_notes="",
                misconceptions=self._catalogue(task.skill_id),
            ),
            item=task.item,
            student_summary=StudentSummary(
                strength=state.strength if state else 0.0,
                is_fresh=is_fresh(state, now, self._params_for(task.skill_id)) if state else False,
                calibration_gap=state.calibration_gap if state else 0.0,
                prior_misconceptions=state.active_misconceptions if state else (),
            ),
            step_diff=step_diff,
            diagnosis=diagnosis,
            last_verdict=last_verdict,
            permitted_rung=(
                rung_override
                if rung_override is not None
                else permitted_rung(self.contract, task.help_state)
            ),
        )

    def _ask_tutor(
        self,
        session: Session,
        task: Task,
        states: dict[SkillId, SkillState],
        step_diff: StepDiff | None,
        diagnosis: MisconceptionId | None,
        rung_override: HelpRung | None = None,
        last_verdict: Verdict | None = None,
    ) -> TutorTurn | None:
        """Ask, validate, and retry. A turn that fails validation never reaches the student."""
        context = self._build_context(
            task, states, step_diff, diagnosis, rung_override, last_verdict
        )
        for _ in range(MAX_TUTOR_RETRIES):
            turn = self._tutor.respond(context)
            verifier = self._verifier_for(task.skill_id)
            if validate_turn(turn, context, self.graph, verifier).accepted:
                return turn
        return None
```

- [ ] **Step 4: Run the engine tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_engine.py -v`
Expected: PASS — 14 tests.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS, purity test included.

- [ ] **Step 6: Commit**

```bash
git add src/learnai/domain/engine.py tests/domain/test_engine.py
git commit -m "feat: practice engine orchestrating verify, evidence, and tutor"
```

---

### Task 18: Simulated students

**Files:**
- Create: `tests/simulation/__init__.py`, `tests/simulation/personas.py`, `tests/simulation/test_simulated_students.py`
- Test: as above

**Interfaces:**
- Consumes: the whole engine.
- Produces: `run_term(persona, *, days, sessions_per_week, items_per_session) -> TermResult` with `states`, `log`, `sessions_run`.

**Why this task exists:** it is the only way to test a forgetting curve before five weeks of real users exist, and it is where the treadmill problem gets caught before a student feels it.

- [ ] **Step 1: Write the personas**

```python
# tests/simulation/personas.py
"""Synthetic students. Each decides what to submit and whether to ask for help."""
import pathlib
from dataclasses import dataclass, field

import sympy as sp

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.parse import parse_math
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.contracts import PRACTICE
from learnai.domain.engine import PracticeEngine
from learnai.domain.enums import Confidence
from learnai.domain.ids import CourseId, SessionId, SkillId, StudentId
from learnai.domain.items import Submission
from learnai.domain.mastery import SkillState
from learnai.domain.session import Task

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
COURSE = CLUSTER.graph.topological_order()
_KEYS = SympyVerifier()  # turns an answer key into what a student would enter


class Persona:
    name = "base"
    asks_for_help = False
    confidence = Confidence.FAIRLY_SURE

    def answer(self, task: Task) -> Submission:
        return _KEYS.key_submission(task.item.answer_spec)


class Diligent(Persona):
    name = "diligent"


class HintAbuser(Persona):
    """Climbs the whole ladder on every task, then answers correctly."""

    name = "hint_abuser"
    asks_for_help = True
    confidence = Confidence.CERTAIN


class MisconceptionCarrier(Persona):
    """Believes (a + b)^2 == a^2 + b^2 and gets everything else right."""

    name = "misconception_carrier"
    confidence = Confidence.CERTAIN

    def answer(self, task: Task) -> Submission:
        if task.skill_id != SkillId("quad.expand.square"):
            return _KEYS.key_submission(task.item.answer_spec)
        return Submission.of(self._believed_expansion(task))

    def _believed_expansion(self, task: Task) -> str:
        correct = parse_math(task.item.answer_spec.expression)
        x = sp.Symbol("x")
        poly = sp.Poly(correct, x)
        constant = poly.coeff_monomial(1)
        return sp.sstr(x**2 + constant)

    def steps(self, task: Task) -> list[str]:
        if task.skill_id != SkillId("quad.expand.square"):
            return []
        return [task.item.statement.split(": ", 1)[-1], self._believed_expansion(task)]


class Overconfident(Persona):
    """Always certain, always wrong."""

    name = "overconfident"
    confidence = Confidence.CERTAIN

    def answer(self, task: Task) -> Submission:
        return Submission.of("0")


@dataclass
class TermResult:
    states: dict[SkillId, SkillState] = field(default_factory=dict)
    sessions_run: int = 0
    log: InMemoryEvidenceLog = field(default_factory=InMemoryEvidenceLog)
    clock: FakeClock = field(default_factory=FakeClock)


def run_term(
    persona: Persona,
    *,
    days: int = 84,
    days_between_sessions: float = 2.0,
    items_per_session: int = 6,
) -> TermResult:
    result = TermResult()
    verifier = SympyVerifier()
    engine = PracticeEngine(
        graph=CLUSTER.graph,
        misconceptions=CLUSTER.misconceptions,
        item_source=GeneratorRegistry(QUADRATICS_TEMPLATES),
        verifiers={CAS_SYMBOLIC: verifier},
        tutor=FakeTutor(),
        matcher=SympyMisconceptionRules(),
        evidence_log=result.log,
        clock=result.clock,
        contract=PRACTICE,
    )

    elapsed = 0.0
    while elapsed < days:
        session = engine.start_session(
            student_id=StudentId(persona.name),
            course_id=CourseId("quadratics"),
            course_skills=COURSE,
            states=result.states,
            budget_items=items_per_session,
            session_id=SessionId(f"{persona.name}-{result.sessions_run}"),
            seed=result.sessions_run + 1,
        )
        result.sessions_run += 1
        while not session.is_finished:
            task = session.current_task
            if persona.asks_for_help:
                for _ in range(3):
                    session, _ = engine.request_help(session, result.states)
            steps = getattr(persona, "steps", lambda _t: [])(task)
            session, result.states, outcome = engine.submit(
                session,
                result.states,
                steps=steps,
                answer=persona.answer(task),
                confidence=persona.confidence,
            )
            if not outcome.task_completed:
                session = _abandon(session)
            result.clock.advance(0.01)
        result.clock.advance(days_between_sessions)
        elapsed += days_between_sessions
    return result


def _abandon(session):
    from learnai.domain.session import advance

    return advance(session)
```

- [ ] **Step 2: Write the simulation tests**

```python
# tests/simulation/test_simulated_students.py
from learnai.domain.ids import SkillId
from learnai.domain.mastery import is_fresh, is_learned, retrievability

from tests.simulation.personas import (
    CLUSTER,
    Diligent,
    HintAbuser,
    MisconceptionCarrier,
    Overconfident,
    run_term,
)


def test_a_diligent_student_learns_the_cluster_over_a_term():
    result = run_term(Diligent())
    learned = [sid for sid, state in result.states.items() if is_learned(state)]
    assert len(learned) >= 6, f"only learned {learned}"


def test_a_diligent_student_ends_the_term_with_long_intervals():
    result = run_term(Diligent())
    matured = [s for s in result.states.values() if is_learned(s)]
    assert max(s.stability for s in matured) > 20.0, "stability never matured"


def test_the_hint_abuser_answers_correctly_all_term_and_masters_nothing():
    """The headline guarantee, end to end rather than as a unit property."""
    result = run_term(HintAbuser())
    assert result.sessions_run > 10
    assert all(not is_learned(s) for s in result.states.values())
    assert all(s.strength == 0.0 for s in result.states.values())


def test_the_hint_abuser_never_advances_past_the_graph_roots():
    result = run_term(HintAbuser())
    roots = {sid for sid in CLUSTER.graph.skills if not CLUSTER.graph.hard_prereqs(sid)}
    assert set(result.states), "the abuser did attempt work"
    assert set(result.states) <= roots, "answering correctly all term must not unlock anything"


def test_the_misconception_carrier_is_diagnosed_by_name():
    from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
    from learnai.adapters.cas.sympy_verifier import SympyVerifier
    from learnai.domain.misconceptions import diagnose
    from tests.simulation.personas import CLUSTER

    persona = MisconceptionCarrier()
    verifier = SympyVerifier()
    from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
    from learnai.adapters.content.registry import GeneratorRegistry

    registry = GeneratorRegistry(QUADRATICS_TEMPLATES)
    from learnai.domain.session import Task
    from learnai.domain.ids import SessionId, TaskId

    item = registry.next_item(SkillId("quad.expand.square"), target_difficulty=-0.5, seed=1)
    task = Task(TaskId("t"), SessionId("s"), item, SkillId("quad.expand.square"))

    diff = verifier.diff_steps(persona.steps(task))
    assert diff is not None
    skill = CLUSTER.graph.skills[SkillId("quad.expand.square")]
    catalogue = tuple(CLUSTER.misconceptions[m] for m in skill.misconception_ids)
    assert diagnose(diff, catalogue, SympyMisconceptionRules()) is not None


def test_an_overconfident_student_accumulates_a_positive_calibration_gap():
    result = run_term(Overconfident(), days=20)
    gaps = [s.calibration_gap for s in result.states.values()]
    assert gaps and max(gaps) > 0.3


def test_memory_decays_across_a_long_absence():
    result = run_term(Diligent(), days=30)
    learned_states = [s for s in result.states.values() if is_learned(s)]
    assert learned_states
    state = max(learned_states, key=lambda s: s.stability)
    far_future = result.clock.advance(365.0)
    assert not is_fresh(state, far_future)
    assert retrievability(state, far_future) < 0.5


def test_an_earned_achievement_survives_the_decay():
    """is_learned is a badge, is_fresh is a reading. Decay must not revoke the badge."""
    result = run_term(Diligent(), days=30)
    learned_before = {sid for sid, s in result.states.items() if is_learned(s)}
    result.clock.advance(365.0)
    learned_after = {sid for sid, s in result.states.items() if is_learned(s)}
    assert learned_before == learned_after
```

- [ ] **Step 3: Run the simulation suite**

Run: `.venv/bin/pytest tests/simulation -v`
Expected: PASS — 8 tests. These are the slowest tests after the generator contracts; a full term is a few thousand CAS calls.

If `test_a_diligent_student_learns_the_cluster_over_a_term` finds fewer than six skills learned, the cause is almost certainly `MIN_UNASSISTED_CORRECT` interacting with `STRENGTH_THRESHOLD` — a student needs several successes per skill at the served difficulty. Retune `TARGET_LOGIT_MARGIN` or `K0` in `constants.py` rather than weakening the assertion; the point of the test is that the parameters produce a sane trajectory.

- [ ] **Step 4: Run everything and record the timing**

Run: `.venv/bin/pytest -q --durations=10`
Expected: PASS, whole suite. Note the ten slowest tests in the commit message so Plan 2 knows where the time goes.

- [ ] **Step 5: Commit**

```bash
git add tests/simulation
git commit -m "test: simulated students over a term against a fake clock"
```

---

## Definition of done for Plan 1

- `pytest` is green, including the domain purity test.
- A `Diligent` simulated student learns most of the cluster over a term; a `HintAbuser` who answers every question correctly for twelve weeks masters nothing.
- No tutor turn above the permitted rung, and no turn containing the answer, can reach a student — proven by the adversarial corpus and the engine test.
- A correct first attempt invokes the tutor zero times.
- Every generator's answer key is verified by the CAS over hundreds of seeds.
- `project(log.events())` reproduces the live projection exactly.

## Spec coverage

| Spec §13 deliverable | Task |
|---|---|
| 1. Skill graph for the cluster | 1, 2 |
| 2. One template per skill, contract-tested | 7 |
| 3. SymPy verifier: equivalence, form, step diff | 4, 5, 6 |
| 4. Mastery engine with calibration | 9, 10, 11 |
| 5. Practice contract, hint ladder, evidence classes | 9, 12 |
| 6. LeakGuard with adversarial corpus | 13 |
| 7. Tutor port and `FakeTutor` | 14 |
| 8. Session planner and evidence log (in-memory half) | 15, 16, 17 |
| 11. Simulated-student suite | 18 |
| 9. Web session UI | **Plan 2** |
| 10. Tutor eval set | **Plan 2** |
| 8. Durable persistence | **Plan 2** |

Spec sections deliberately unimplemented here, each with a reason: §7.6 scheduler priority (no due queue until Review mode, Slice 2), §7.7 placement (Slice 2), §8.3 `initial_strategy` (Learn mode, Slice 3), §9.2 tutor tools and §10 model routing (Plan 2, with the real adapter), §11 durable storage (Plan 2).
