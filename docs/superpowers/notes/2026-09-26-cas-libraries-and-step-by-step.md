# CAS Libraries and Step-by-Step Solutions — Research Notes

**Date:** 2026-09-26
**Status:** Research notes, not a decision. The open decision is spec §14 D18.
**Context:** Written while reviewing Plan 1, Task 4 (parsing and equivalence), after finding how
far SymPy's defaults are from the classroom's (spec D12–D17).

---

## 1. Three different jobs

A CAS gets asked to do three things, and they are not equally hard.

| Job | Question | How hard | What we use |
|---|---|---|---|
| **Grading** | Is this answer right? | Usually easy: it is *verification* — substitute, differentiate, compare | SymPy, through first-year university |
| **Solving** | What is the answer? | Can be hard or impossible in closed form | Mostly avoided: generators build problems backwards (pick the roots, expand for the question) |
| **Explaining** | How do you get there, step by step? | The gap: no general Python library does it | See §4 |

The asymmetry matters. SymPy cannot integrate everything, but checking an antiderivative only
needs differentiation, which it does completely. It cannot solve every ODE, but `checkodesol`
verifies a proposed solution by substitution. Grading rarely needs the solver at all.

## 2. What SymPy covers

| Level | Topics | Fit |
|---|---|---|
| Primary | arithmetic, fractions, decimals, percentages | ✓ exact rationals are native; the hard part is input notation (mixed numbers), not maths |
| Lower secondary (ESO, GCSE) | linear equations and systems, powers, roots, Pythagoras | ✓ |
| Upper secondary (Bachillerato, A-level, AP) | functions; polynomial, rational, radical, exponential and log equations; trigonometry; sequences; limits; derivatives; integrals; matrices; vectors; probability | ✓ for grading, once items declare assumptions for logs, trig and roots (D13) |
| First-year university | multivariable calculus, linear algebra, ODEs, recurrences, logic, number theory | ✓ largely |
| Proof-based | analysis, abstract algebra | ✗ — a different kind of checker (D10) |

By area:

- **Differentiation** (`diff`): complete for elementary functions; a derivative answer is a plain
  equivalence check.
- **Integration** (`integrate`): Risch-based plus heuristics — strong, not universal, and its
  answer may differ from a student's by a constant. Grade by differentiating (D15).
  `sympy.integrals.manualintegrate.integral_steps` returns the method as a rule tree
  (substitution, by parts, trig substitution) — the one built-in source of steps.
- **Limits** (`limit`, Gruntz algorithm): robust at school level. **Series:** `series`,
  `summation`.
- **ODEs** (`dsolve`): separable, first-order linear, exact, Bernoulli, homogeneous, second-order
  constant-coefficient, Cauchy–Euler, series solutions; `checkodesol` to verify. PDEs: first-order
  linear only.
- **Linear algebra** (`Matrix`): row reduction, determinants, inverses, eigenvalues — exact.
- **Also:** `sympy.stats` (probability), `sympy.logic` (equivalence is decidable, so easier than
  algebra), `rsolve` (recurrences), `sympy.ntheory` and `diophantine`, `sympy.physics.units`.

## 3. Other engines

| Library | Strength | From Python | Licence / cost | When we'd reach for it |
|---|---|---|---|---|
| **SymEngine** | C++ core, much faster at expansion and differentiation | `symengine` bindings, SymPy-compatible subset | MIT | CAS latency becomes a problem |
| **Giac/Xcas** | the CAS behind GeoGebra; fast, strong on school maths | `giacpy` bindings | GPL | a second opinion, or speed on school topics |
| **Maxima** | mature; strong integration and ODEs | subprocess, or via Sage | GPL | hard integrals or ODEs beyond SymPy |
| **SageMath** | bundles Maxima, PARI, FLINT, Singular | its own Python environment | GPL; very heavy | only as a separate service |
| **Wolfram Engine** | the strongest general solver (`Solve`, `Integrate`, `DSolve`, …) | `wolframclient` (official) | free for development; production needs a paid licence | topics SymPy cannot solve, if generators cannot sidestep them |
| **Wolfram\|Alpha API** | step-by-step solutions, natural-language input | HTTPS | paid per call | explaining (§4) |
| **SciPy / mpmath** | numerical ODEs (`solve_ivp`), integration, root finding | native | BSD | numeric cross-checks; applied problems with no closed form |
| **Pint** | units and dimensional analysis | native | BSD | physics (D14) |
| **ChemPy** | balancing equations, equilibria | native | BSD | chemistry |
| **NetworkX** | graph theory | native | BSD | discrete maths, CS |
| **Lean 4 + mathlib** | real proof checking | subprocess | Apache | not for school use; proofs will more likely go to an LLM rubric (D10) |

GPL tools run as a separate server-side process in a hosted product are usually unproblematic;
confirm before shipping anything that bundles them.

## 4. Where step-by-step solutions can come from

| Source | Coverage | Correctness | Cost | Notes |
|---|---|---|---|---|
| **Generator-authored steps** | every templated item | exact by construction; the contract test already checks no step breaks equivalence | free | A generator builds the problem backwards, so it knows every step. **Today's quadratics generators emit thin steps** (prompt then answer, or none): enriching them is content work, and it is the cheapest win here. |
| **SymPy `integral_steps`** | integration only | exact | free | Method names, not student-facing prose; a hint source for the tutor. |
| **LLM + CAS verification** | anything the model can do | every transformation checked by `diff_steps`, the result by `check_answer`; a failing step is fed back for a retry | tokens; offline via the Batch API for bank items | Turns "errors are possible" into "errors are caught" for transformational maths. Not checkable: prose explanations, and modelling steps (word problem → equation), though the final answer still is. |
| **Wolfram\|Alpha API** | broad, polished | high, but not ours to verify unless it passes our check too | per call | Terms on caching and attribution; the student's problem leaves our system (D5). |
| **Wolfram Engine** | strongest *solver* | high | licence | As far as we know, step-by-step is a Wolfram\|Alpha feature: the Engine reaches it through its `WolframAlpha[]` function, which calls the same online service. **Confirm with Wolfram.** |

Whatever the source, steps pass through the `Verifier` before a student sees them (P3), and carry
a provenance and vetting level the student can see — "checked step by step" is a different claim
from "AI-written; final answer checked".

## 5. Where the product needs steps

- **Learn mode worked examples** (Slice 3): generator steps suffice for the drillable core.
- **The `FULL_REVEAL` rung in Practice**: a step-by-step solution *is* a full reveal, so every
  source sits behind the same effort gate, and it earns no mastery credit.
- **Bring-your-own problems** (D7, Slice 6): no generator wrote them, so this is the real consumer
  of LLM or Wolfram steps.
- **LLM-written long-tail items**: steps generated with the item, offline, and verified before the
  item enters the bank.

## 6. Architecture sketch

A task-level port, consistent with §5.2's rule against generic provider abstractions:

```python
class WorkedSolutionSource(Protocol):
    def solve_with_steps(self, problem: str, skill_id: SkillId) -> WorkedSolution | None: ...

@dataclass(frozen=True)
class WorkedSolution:
    steps: tuple[str, ...]
    final_answer: str
    provenance: str            # "generator", "llm", "wolfram_alpha"
    vetting_level: VettingLevel
```

Adapters: `GeneratorSteps`, `VerifiedLlmSteps`, `WolframAlphaSteps`. A router picks one by topic,
plan tier and availability, the way §10 routes models: generator first, then LLM with
verification, then Wolfram when verification fails or the topic is flagged as hard. A solution
whose steps fail the check is either downgraded to "final answer checked" or dropped.

## 7. Billing

- **Per-student economics:** generator steps are free; LLM steps ride on the inference budget
  (§10); Wolfram is a per-call cost on top.
- **Cache per problem, not per student**, where the terms allow: a generated item is
  deterministic (template + seed), so its steps are computed once. Check whether Wolfram|Alpha's
  terms permit storing results, and for how long.
- **Tier options:**
  1. a premium plan that includes Wolfram-backed steps for your own problems and harder topics;
  2. metered credits;
  3. included for everyone, but routed to Wolfram only when LLM + CAS verification fails —
     which keeps the call volume, and the cost, small.
- **Caution on positioning.** Selling "step-by-step solutions" as the headline premium feature
  markets the product as a homework solver — the exact failure the product exists to fix (spec
  §1). If Wolfram steps are sold, they fit as "harder topics and your own problems, taught
  properly": still behind the attempt and effort gates, and followed by generated variants to
  practise cold (D7).
- **Constrained moments (open question).** Steps offered only at chosen moments — after documented
  effort, inside a Learn worked example, in a post-session review of an item the student missed —
  teach; steps available on demand are a solver whatever the plan. Decide which moments first,
  then whether a paid tier widens them. The engine already owns every such gate (P1), so this is
  a policy in the mode contracts, not a feature of the step source.
- **Who pays and whose data:** usually a parent or a school; a minor's problem sent to a third
  party needs D5's compliance position first.

## 8. Adjacent: photo input

For the later "photo of paper work" milestone: Mathpix (image to LaTeX) or Claude's own vision.
Either way the parser would need a LaTeX front end, or the structured editor's format (D1).

## 9. Open questions for Wolfram

1. Price per call at our expected volume; education or startup programmes.
2. Which API plan includes step-by-step solutions.
3. Terms: storing results, attribution and branding, commercial use in a product for minors.
4. Is step-by-step available from a locally licensed Wolfram Engine, or only via Wolfram|Alpha?
5. Latency per call — measure before designing any synchronous use.
6. Data processing agreement and EU hosting (GDPR, D5).
