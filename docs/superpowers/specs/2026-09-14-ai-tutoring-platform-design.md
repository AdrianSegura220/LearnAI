# AI Tutoring Platform — Design

**Date:** 2026-09-14
**Status:** Approved design, pending implementation plan
**Scope:** Full architecture, with Slice 1 scoped for implementation

---

## 1. Problem

Students increasingly use general-purpose LLM chat for schoolwork, and it produces a specific,
measurable failure: they obtain correct answers without constructing understanding, and mistake
fluent exposure for competence. The gap is invisible until an exam forces unassisted performance.

The failure is not that students receive answers. It is that **nothing afterwards ever tests them
without the AI in the room.** No feedback loop distinguishes "I watched this get solved" from
"I can solve this."

This platform is a unified place where a student works a subject across learning, practice, and
retention, and where the measure of what they know is derived exclusively from work they did
unassisted.

## 2. Goals

- A student picks a course and a mode, and gets a session that adapts to what they actually know.
- Tutoring that behaves like a good human tutor: generous with explanation, relentless about
  keeping the student constructing rather than receiving.
- A mastery signal that cannot be inflated by assistance, and that decays the way memory decays.
- Retention as a first-class outcome, driven by the same engine as learning, not a bolted-on
  flashcard feature.
- Subject extensibility: mathematics first, with physics, chemistry, and non-symbolic subjects
  (e.g. history) reachable by writing adapters, not by rewriting the engine.
- Inference economics that support Opus-tier quality on the turns that matter.

## 3. Non-goals

- Replacing teachers or classroom instruction.
- Content breadth before content quality. One cluster done properly precedes a catalogue.
- A general-purpose chat assistant. The system serves bounded tutoring interactions.
- Original pedagogical research. The design applies established findings; it does not seek new ones.

## 4. Design principles

These are the load-bearing decisions. Everything else follows from them.

**P1 — The engine decides; the model speaks.**
A deterministic tutoring engine owns every consequential decision: what to teach next, which item
to serve, what help is permitted, whether an attempt counts, how mastery updates, when review is
due. The language model explains, diagnoses, converses, and judges free text. It never mutates
state.

**P2 — The model has no write path to mastery.**
Not a policy expressed in a prompt; an absence in the tool surface. No amount of prompt injection,
student persuasion, or model drift can move a mastery number. Only unassisted evidence, verified
by code, can.

**P3 — Verification before language.**
Where a deterministic checker exists, it runs first and the model receives its output. A CAS
localises the broken step; the model explains why it broke. The model is never asked to do
arithmetic it can get wrong in front of a student.

**P4 — Assistance is free; credit is not.**
The tutor is warm and generous, because integrity is carried by the unassisted gate rather than by
withholding. Help costs the student nothing except credit toward mastery.

**P5 — Performance is not learning.**
Evidence gathered immediately after instruction is recorded but weighted near zero. Mastery is
earned by cold attempts delayed from teaching.

**P6 — Evidence is append-only.**
Attempts and help events are an immutable log; mastery state is a projection. The mastery algorithm
will change; student history must survive the change.

## 5. Architecture

Hexagonal. The domain core is pure Python — no I/O, no framework imports, no LLM — and is
exhaustively unit-testable. Everything else is an adapter behind a port.

```
                    ┌──────────────────────────────────────┐
                    │            DOMAIN CORE               │
   HTTP/API ──────► │  SkillGraph   MasteryModel           │
                    │  Scheduler    SessionPlanner         │
                    │  ModeContract GenerosityPolicy       │
                    │  LeakGuard    EvidenceRules          │
                    └───┬───────┬───────┬───────┬──────────┘
                        │       │       │       │
                   Verifier ItemSource Tutor  Repositories / Clock
                        │       │       │       │
                    SymPy   Generator  Anthropic  Postgres
                    Rubric  LLM bank   FakeTutor  FakeClock
                    (judge) Imported
```

### 5.1 Ports

| Port | Responsibility | First adapter | Later |
|---|---|---|---|
| `Verifier` | Judge an attempt; localise error; test expression equivalence | SymPy (`cas_symbolic`) | Units checker (physics), rubric judge (history) |
| `ItemSource` | Supply the next item for a skill at a difficulty | Generator registry | LLM-generated vetted bank, imported bank |
| `Tutor` | Produce one validated tutoring turn | Anthropic (Opus 5) | Alternative providers/orchestration; `FakeTutor` for tests |
| `EvidenceLog` | Append-only attempt and help-event record | Postgres | — |
| `Repositories` | Skill graph, items, sessions, projections | Postgres | — |
| `Clock` | Current time | System | `FakeClock` (essential — decay testing) |
| `ContentPipeline` | Offline generation and vetting of items, cards, teaching notes | Anthropic Batch API | — |

### 5.2 Orchestration is deliberately late-bound

The `Tutor` port is the seam. Choosing between the SDK Tool Runner, a hand-written loop, or
Managed Agents is an adapter-level decision deferred to implementation; the domain is unaffected
by it.

**Do not build a generic provider-neutral `LLMClient` beneath the adapter.** Such abstractions
converge on the lowest common denominator and forfeit precisely the features this design depends
on: prompt-cache breakpoint placement, adaptive thinking and effort control, mid-conversation
system messages, structured outputs, and the Batch API. If a second provider is ever needed,
write a second `Tutor` adapter that uses that provider well. Task-level ports stay swappable;
token-level ones rot.

### 5.3 Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.x + Alembic, PostgreSQL.
- **CAS:** SymPy (in-process; it is the reason the backend is Python).
- **Frontend:** React + TypeScript (Vite). Math rendering via KaTeX; math input library to be
  chosen by spike (see §14).
- **LLM:** Anthropic Python SDK.
- **Testing:** pytest, Hypothesis (property tests), plus a simulated-student harness.

---

## 6. Domain model

### 6.1 Skill graph

The unit of mastery is a **Skill**, and it must be fine-grained: *"solve a quadratic by factoring
when the leading coefficient is 1"*, not *"quadratics"*. Every skill is phrased as a single
sentence describing what the student can **do**. Fine granularity is what makes step-level
tutoring, targeted diagnosis, and honest mastery accounting possible.

Prerequisite edges encode genuine dependency, not curricular convention. The graph knows nothing
about any national curriculum.

**A cycle in hard edges is rejected, never repaired.** If A needs B and B needs A, neither can
reach the frontier, so the cycle is a contradiction in the content rather than noise to smooth
over. Breaking it automatically would mean deciding which dependency is false — or missing that
the real fix is a shared prerequisite nobody has authored — and the graph has no information to
make that call: edges carry no weights, and every hard edge is equally hard. So loading fails and
names the path (`a → b → c → a`), leaving the judgement to the author; an assistant that proposes
fixes is deferred (D11). Soft edges may form cycles, since they gate nothing.

```python
Subject(id, name, default_verification)        # an opaque VerificationKind token
Skill(id, subject_id, name, can_do_statement,
      verification_kind,                       # overrides subject default where needed
      concept_ids, misconception_ids)
PrereqEdge(from_skill, to_skill, strength)     # hard | soft

Concept(id, subject_id, kind, prompt, answer, introduced_by)
                                               # definition | claim | rule | procedure | fact
Misconception(id, subject_id, name, description, signature)

Course(id, name, curriculum_tag, level, skill_sequence, exam_blueprint)
```

**`verification_kind` is the subject-extensibility seam.** It selects the `Verifier` adapter for
an attempt. Adding chemistry means writing one adapter and authoring skills, not touching the
engine — and to keep that literally true it is an **opaque token**, not an enumeration of adapter
kinds: each adapter declares its own, and the engine resolves skill → verifier through a registry.
`ConceptKind` and `AnswerKind` stay closed enumerations because they name subject-neutral shapes
(a claim, an unordered set of values), not subject-specific ones.

**The default is declared by content, never by code.** Which checker grades a skill is a fact
about the content, so the content states it: until subjects have a file of their own, a cluster
declares `verification:` beside `subject:`, and a skill may override it. A fallback in the loader
would quietly send any cluster that forgot the key to SymPy — a history cluster graded as algebra
— and would couple the content adapter to one verifier adapter. The loader never interprets the
token. Whether a verifier exists for it is the engine's check, made at construction so that a
typo fails at startup rather than on some student's first attempt at the skill.

**`Course` is a thin curricular overlay** — an ordered path through the graph plus metadata.
"1º Bachillerato Matemáticas" and "AP Calculus AB" are two courses sharing most of the same
skills in different orders. This is how the system stays curriculum-agnostic at its core while
still presenting a student with *their* course in *their* sequence.

**Concepts and misconceptions are shared, not owned.** Both are subject-scoped, and
`Skill.concept_ids` / `Skill.misconception_ids` carry the relationship many-to-many. Giving either
a single owning skill would be arbitrary and, worse, would force duplication: the
Nyquist–Shannon theorem serves sampling-rate calculation, aliasing identification, reconstruction
and filter choice, and `(a+b)² → a²+b²` afflicts both expanding a square and completing it.
Duplicating a concept duplicates its **memory state**, so a student would rehearse one theorem on
four independent schedules and be told they had forgotten something they demonstrably know.
Content loading enforces that every catalogue entry is referenced by at least one skill, so
sharing never becomes orphaning.

`Concept.introduced_by` is an **override**, not the link: it names where a Learn session should
first teach the concept, defaulting to the earliest referencing skill in topological order, and
authors set it only when they want it taught somewhere else. Loading rejects an `introduced_by`
that is not itself one of the referencing skills, which would otherwise be silently incoherent —
and which also catches a mistyped skill id, since nothing reads the field until Slice 3.

Because the link is authored on the skill side, the reverse direction is a **derived index built
at load time** — `skills_for_concept: dict[ConceptId, frozenset[SkillId]]` — in exactly the way
`SkillGraph` precomputes incoming and outgoing prerequisite edges from a flat list. Review mode
needs it twice: to place a concept in the graph, and to decide eligibility, which is true when
*any* referencing skill has reached the frontier. `introduced_by` cannot serve either purpose, as
a student may reach a skill needing the concept by a route that never passes through the skill
that introduces it. The index arrives in Slice 2 with its first consumer.

The relationship is many-to-many, and gets the representation that suits each layer: an id list
on the skill in YAML (how an author thinks), an adjacency tuple plus derived reverse index in the
domain (how traversal reads), and a junction table with a composite key in Postgres (how
integrity is enforced). A link becomes a first-class entity only when it carries data of its own
— which is exactly why `PrereqEdge` is one and `concept_ids` is not.

**Misconceptions are first-class objects**, not prose inside a prompt. Each carries a signature
describing how it manifests in written work. They earn their place three times: the CAS step diff
plus a misconception match tells the tutor *what the student believes* rather than merely *that
they are wrong*; feedback can address the belief; and generators can produce distractors by
deliberately applying the misconception, turning multiple choice from guessing into diagnosis
(an available item format, not one Slice 1 uses).

**A skill need not list any.** Many honestly have none catalogued: a new skill before any
student has made its errors, a recall skill where a wrong answer means not knowing rather than
believing something false, a skill whose errors are slips rather than beliefs. Diagnosis already
reports an unmatched error as novel and the tutor works from the step diff, so nothing depends on
the list being non-empty — and requiring an entry would push authors to invent one to get past the
loader. A coverage report can flag thin skills later; it is not a load error.

**A misconception's `signature` keys its rule, and that rule should be a transform.** The
signature is an opaque token — like `verification_kind` and form constraints — that the subject's
matcher adapter resolves to code; the domain never interprets it. It is deliberately separate
from the misconception's `id`, which is content identity an author may rename, whereas the
signature is a contract with a registered rule.

Rules start life as *predicates*: given the step before and the step after, does this transition
exhibit the belief? That is all diagnosis needs. Distractor generation needs the other direction
— given the correct expression, what would this belief produce? — and the transform is already
written inside most predicates on their way to comparing. When distractors are built, rules
should be defined as `transform(expr) -> Expr | None` with the predicate derived from it, so one
definition serves both and a misconception can never diagnose one way and generate another.

**Concepts are separate from skills.** Declarative knowledge — the statement of the chain rule,
the definition of a limit — attaches to a skill but is retrieved differently. A student can know
the theorem and be unable to apply it, or apply it mechanically without knowing what it says.
Both are tracked.

### 6.2 Content model

```python
ItemTemplate(id, skill_id, difficulty_band, sampler,
             answer_fn, form_constraints, distractor_rules)
Item(id, skill_id, provenance, statement, answer_spec,
     worked_steps, difficulty, vetting_level)
Card(id, concept_id, kind, prompt, answer)     # cloze | qa

# provenance: Generated(template_id, seed) | Authored | LlmBatch(run_id)
# vetting_level: machine_verified | human_reviewed | llm_only
```

**Form constraints are opaque to the core.** `AnswerSpec.form_constraints` carries tokens the
domain never interprets — `"fully_factored"`, later `"correct_units"` — and each `Verifier`
adapter declares the vocabulary it can judge through `supported_constraints`. The CAS adapter
owns the mathematical forms; a physics adapter will own units and significant figures without
editing the core. Content is validated against the responsible verifier's vocabulary, so a token
no adapter understands fails loudly rather than silently passing a wrongly-formed answer. Without
this the form vocabulary would accumulate every subject's terms inside the shared domain, which
is precisely the coupling `verification_kind` exists to prevent.

A **generator** is code written once per skill, not a problem written once per problem. For
"solve a quadratic by factoring" it samples integer roots in a constrained range, expands, and
returns both the problem and the exact answer. The answer key is correct by construction, there
are unlimited non-repeating variants, and serving costs nothing.

Generators cover the drillable core. LLM generation covers word problems, conceptual questions,
and subjects with no CAS — produced offline via the Batch API, vetted, and stored. **Items are
never generated live at serve time in the normal path.**

**Serve policy differs by mode.** A generator item with a CAS-computed answer may gate mastery;
an LLM-written word problem that has only been spot-checked may be served in tutored practice but
must not gate mastery until vetted. This is the one place to be strict: a wrong answer key in an
unassisted check punishes a student for being right, which is the fastest way to lose their trust.

**Difficulty starts declared and becomes measured.** Authors tag a band; once response data
exists, the Elo co-estimation in §7.1 replaces it with an empirical value.

### 6.3 Authoring load

Algebra through single-variable calculus is roughly 250–350 skills. The realistic path is to have
a model draft the graph — skills, can-do statements, prerequisite edges, misconception catalogues
— and have a human review and correct it. This is a legitimate use of AI: drafting a structure a
human verifies, not deciding what a student knows.

---

## 7. Mastery and scheduling engine

Two quantities per `(student, skill)`, because *"did they learn it"* and *"do they still have it"*
are different questions.

Every tuned parameter named in this section lives on an injected `MasteryParameters` value object
rather than as a module constant, so `r_target` can genuinely vary per skill (§7.2), parameters can
be fitted per skill (§7.8), and two configurations can be compared side by side.

```python
SkillState(student_id, skill_id,
           strength,              # Elo-style competence
           stability,             # memory half-life, days
           last_success_at, last_reviewed_at,
           attempt_count, unassisted_correct_count,
           calibration_gap, active_misconceptions)
```

### 7.1 Strength — Elo

Elo is chosen over Bayesian Knowledge Tracing for a cold-start reason: BKT requires per-skill
slip/guess parameters fitted from data that will not exist for months, whereas Elo needs only a
K-factor, works from the first attempt, and co-estimates item difficulty from the same stream —
which supplies the empirical difficulty values §6.2 defers.

```
p_expected = 1 / (1 + exp(-(strength - item.difficulty) / SCALE))
strength'  = strength + K * w * (outcome - p_expected)
```

`outcome` is 1 for a correct answer and 0 for a wrong one. It is a real number rather than a bit
so that a decline can be scored at the format's guess baseline (§8.2), which is what makes
honesty and guessing cost the same.

**Units.** Strength and difficulty share one latent scale, and only their difference enters the
formula, so the units are a free choice — and choosing them *is* choosing `SCALE`. Use **logits**
(`SCALE = 1`, the Rasch/1PL convention), because the numbers then mean something:

| `strength − difficulty` | −2 | −1 | 0 | +1 | +2 | +3 |
|---|---|---|---|---|---|---|
| `p_expected` | 0.12 | 0.27 | 0.50 | 0.73 | 0.88 | 0.95 |

Both quantities are unbounded in principle and sit in roughly `[−4, +4]` in practice. This is what
makes the §7.3 mastery threshold expressible as *"1.5 logits above the skill's core difficulty
band"* — i.e. ~82% expected success on a core item — rather than as an uninterpretable constant.
The scale is **per skill**: `difficulty = 0` means a median item *for that skill*, so strengths on
different skills are not comparable. If Elo-style display numbers are ever wanted, convert at the
presentation layer (`SCALE = 400/ln(10) ≈ 173.7`); never store display units.

**The three multipliers.**

- `outcome ∈ {0, 1}` — did the attempt succeed. Binary, deliberately. A correct method with an
  arithmetic slip is a 0; the error *type* is recorded separately for diagnosis and misconception
  tracking, where it is useful, rather than blurred into the competence estimate as partial credit.
- `K` — step size, in logits; the **statistical** dial, governing how fast any estimate may move.
  ≈0.3–0.5 early, decayed with observation count (`K = K₀ / (1 + c·n)`) so estimates adapt quickly
  when little is known and stabilise once well-determined.
- `w` — evidence weight (§8.2); the **policy** dial, governing how much *this* observation is
  permitted to count: `unassisted_cold` and `timed_exam` → 1.0, `post_instruction` → ≈0.1,
  `assisted` → **0.0**. Principle P2 is arithmetic, not prose: an assisted attempt multiplies to
  exactly zero change.

`(outcome − p_expected)` is the *surprise* term — the estimate moves only insofar as reality
differed from prediction, so a correct answer on a hard item moves strength far more than a
correct answer on an easy one, and neither moves it much once the model already expected that
result.

**Identifiability.** Adding a constant to every strength and every difficulty leaves all
predictions unchanged, so a model where both sides update is unidentified up to a shift, and
difficulty values will drift as the population improves. Anchor it: freeze difficulty for a seed
set of items per skill, or periodically re-centre each skill's item difficulties to mean zero.
Item difficulty otherwise updates symmetrically with a smaller constant, and only once its
template has accumulated a minimum response count.

### 7.2 Stability — half-life with a spacing effect

```
retrievability(t) = 2 ** (-(t - last_success_at) / stability)

on success:   stability' = stability * (1 + A * (1 - retrievability_at_attempt))
on failure:   stability' = max(S_MIN, stability * F)        # F ≈ 0.3
first success: stability  = S_0                              # ≈ 1 day
```

Retrieval at low retrievability strengthens more than retrieval at high retrievability — the
spacing effect, and the same reason `post_instruction` evidence earns almost nothing.

**What stability means.** Strength (§7.1) and stability answer different questions. Strength is
whether the student can do it at all when fresh — competence, which does not decay. Stability is
how long that competence survives without practice — durability, expressed as the number of days
for recall probability to fall to 50%. A student can be strong but unstable (learned it properly
yesterday, will have lost it by next month) or weak but stable (they will not forget the little
they do have), which is why one number cannot carry both. Stability is never observed directly;
it is inferred from successes and failures at varying delays.

**Units.** `t` is the evaluation instant — normally *now*, supplied by the `Clock` port.
`t − last_success_at` is **elapsed wall-clock time in days, as a float**, matching `stability`,
which is a half-life in days; the ratio is dimensionless, so the two must share units. Fractional
days matter — two retrievals in one afternoon are not two retrievals on consecutive days — so
store UTC instants and subtract, never quantise to calendar days. Elapsed time is wall-clock, not
study time: memory decays on the days a student does not open the app.

**The half-life is not the review interval.** With `R_TARGET = 0.9`, the interval to the next
review is `stability × log₂(1/0.9) ≈ 0.152 × stability`:

| `stability` | interval at 90% target retention |
|---|---|
| 1 day | ~3.6 hours |
| 10 days | 1.5 days |
| 60 days | 9 days |
| 180 days | 27 days |
| 365 days | 55 days |

Intervals lengthen because stability grows multiplicatively on each successful retrieval, not
because the target moves. A student experiences "this keeps coming back less often"; the engine
holds recall probability roughly constant.

**`R_TARGET` is the retention-versus-effort dial**, and the single most consequential scheduling
parameter. It fixes what fraction of a half-life elapses before the next review:

| `R_TARGET` | interval | consequence |
|---|---|---|
| 0.95 | 0.074 × stability | frequent reviews, few lapses, high time cost |
| 0.90 | 0.152 × stability | the default; Anki's long-standing choice |
| 0.85 | 0.234 × stability | ~50% longer intervals, noticeably more lapses |
| 0.80 | 0.322 × stability | double the default interval |
| 0.50 | 1.00 × stability | review at the half-life; half of all reviews fail |

It need not be global. Raising it for exam-blueprint skills inside the exam horizon (§7.6) buys
confidence exactly where it matters; lowering it for long-consolidated maintenance material buys
session time back. Treat it as a per-skill policy value, not a constant.

**`R_TARGET` is measurable, not merely tunable**, and it is the primary monitoring signal for the
memory model. It is a prediction about the system's own behaviour: if stability is calibrated, the
observed success rate on scheduled reviews should equal `R_TARGET`. Reviews failing materially
more often than `1 − R_TARGET` mean stability is running high and intervals are too long; failing
far less often means the student is being reviewed more than necessary. Track this per skill and
in aggregate.

Note also that raising `R_TARGET` is not straightforwardly better: knowledge retained per minute
of study peaks at an intermediate value, since a very high target spends most of the session
re-reviewing well-consolidated material. Fit it from data rather than assuming.

**A trajectory.** Reviewed on time at the 90% target, each success multiplies stability by
`1 + A × (1 − retrievability)`; with `A = 5` that is a constant ×1.5 per review. Starting from
`S_0 = 1` day:

| Successful reviews | `stability` | gap to the next review |
|---|---|---|
| 1 | 1.0 d | 3.6 hours |
| 3 | 2.3 d | 8 hours |
| 5 | 5.1 d | 19 hours |
| 6 | 7.6 d | 1.2 days |
| 8 | 17 d | 2.6 days |
| 10 | 38 d | 6 days |
| 12 | 87 d | 13 days |
| 14 | 195 d | 30 days |

Fourteen successful retrievals carry a skill from "gone by tomorrow" to monthly upkeep — a
plausible arc across a school year. Same-day repetition early is correct, not a defect: freshly
learned material genuinely needs it.

Two asymmetries fall out of the same rule. A **late** successful review earns more, because
retrievability has fallen further — at `R = 0.6` the multiplier is ×3.0 rather than ×1.5, so a
student who returns after a gap and still remembers is rewarded for the harder retrieval. A
**failure** multiplies by `F ≈ 0.3`, dropping roughly three reviews' worth of progress and
returning the skill to short intervals until it is re-earned.

`A`, `F`, `S_0` and `R_TARGET` are shapes here, not tuned values; calibration is §7.8.

**Known simplification.** A constant half-life decays faster in the long tail than human
forgetting actually does — the empirical curve is closer to a power law, which is what FSRS uses.
The exponential form is adequate to start and far easier to reason about, and replacing it later
means changing one function and replaying the evidence log. This is precisely the scenario P6
exists for.

### 7.3 Derived states

```python
is_learned(state)   # strength >= THRESHOLD and unassisted_correct_count >= 2 on distinct items
is_fresh(state, now) # retrievability(now) >= R_TARGET
due_at(state)       # last_success_at + stability * log2(1 / R_TARGET)
```

One caveat scales with item format: a lucky guess is a correct answer and does increment the
count. On free response that is rare enough to be covered by the strength threshold; on
four-option multiple choice it would not be, so diagnostic MCQ items will need a higher bar
before they may gate mastery.

**Mastery decays; achievement does not.** `is_learned` is a badge earned by proving it cold, and
it never un-earns. `is_fresh` is a separate, quieter state meaning this one needs a tune-up. Same
data, deliberately different psychology: a system that revokes an earned achievement reads as
theft, and that reaction is what makes spaced systems feel like a treadmill.

### 7.4 Prerequisite propagation

Success on a downstream skill is weak evidence for its hard prerequisites. A student who correctly
differentiates a product of polynomials has demonstrated they can still expand binomials, so the
prerequisite receives an implicit retrieval at reduced weight rather than the student sitting
through a review of it. This is the main reason a graph beats a flat skill list: it buys back
session time.

It runs downward too. Repeated failure on a skill whose error diagnosis is prerequisite-shaped
moves the frontier *down* rather than drilling at the wrong level.

### 7.5 Calibration

Before the verdict is revealed, the student states their confidence. The engine tracks the gap
between stated confidence and actual correctness, per skill and overall.

This addresses the core problem directly. The failure is not that students cannot do the work —
it is that **they do not know they cannot**. An overconfidence gap is that failure, measured. It
makes the invisible visible ("on these six you said you were sure and got two"), it feeds the
scheduler (high confidence-but-wrong rates are re-checked sooner, because that is where an exam
will hurt), and a shrinking gap over a term is a genuinely meaningful thing to show a student or
a parent in a way that a problem count is not.

Five levels, because "I have no idea" is not the same statement as a low-confidence guess:
`no_idea` (the student declined to answer), `guessing`, `unsure`, `fairly_sure`, `certain`. Each
maps to a probability, and `calibration_gap` is an exponential moving average of
`stated_probability - outcome`. Positive means overconfident.

Two properties of that mapping matter more than the numbers in it.

**It is item-format specific.** P(correct | guessing) is around 0.03 on free response and 0.25 on
four-option multiple choice. Borrowing multiple-choice values for free-response items records
every honest guesser as overconfident, inverting the signal for exactly the students it should
reassure. The defaults are free-response; the mapping is keyed by answer kind once diagnostic
multiple choice exists.

**It is fitted at population level and held fixed for individuals.** Fitting each student's
mapping to their own observed rate makes every student perfectly calibrated by construction and
the metric measures nothing. The statement the platform needs to be able to make is "when people
say they are certain they are right 93% of the time, and you are right 40% of the time", which
requires a shared reference. Collect from the first day; show a student their number only once
the mapping has been fitted.

### 7.6 Scheduler priority

Three demands compete. The arbitration rule is explicit:

1. **Exam pressure wins.** If a course has an exam date inside the horizon (≈21 days), its
   blueprint skills dominate and unrelated review is suspended outright. A student nine days from
   finals must never be handed last term's material.
2. **Otherwise, overdue reviews first**, ordered by how overdue, **capped at ~40% of the session
   budget.** Reviews are short and cheap; letting them consume a whole session is what makes these
   systems feel like a chore with no progress.
3. **Then frontier learning** — skills whose hard prerequisites are fresh and which are not yet
   learned, in course order. A prerequisite that is learned but no longer fresh and is blocking a
   frontier skill takes priority over starting something new ("repair before advance").

### 7.7 Placement

A new student on a course gets a short adaptive probe rather than a long test. Start near the
course midpoint and use the graph to skip: success on a downstream skill provisionally credits its
prerequisites; failure walks down. Ten to fifteen items localises the frontier, versus a
forty-question placement nobody finishes. Provisional credit is marked as such and is superseded
by direct evidence.

### 7.8 Parameter calibration

`R_TARGET` is a **policy** choice and can simply start at a published default. `A`, `F`, `S_0` and
the Elo `K₀`/`c` are **empirical** and must eventually be fitted — but there is no data on day one,
so calibration proceeds in three stages.

**Stage 1 — derive from target behaviour.** Reviewed on time, each success multiplies stability by
`m = 1 + A × (1 − R_TARGET)`. Deciding how many successes should carry a skill to maintenance
therefore fixes `m`, and `m` fixes `A`:

```
m = (S_maintenance / S_0) ** (1 / n)
A = (m - 1) / (1 - R_TARGET)
```

Choosing "a month between reviews after roughly fourteen successes", with `S_0 = 1` day, gives
`m = 1.5` and `A = 5`. `F` follows the same way from how much a lapse should cost: forfeiting `k`
reviews' worth of progress means `F = m ** -k`, so `k = 3` gives `F ≈ 0.3`. Both constants are
consequences of product decisions that can be made before any student exists.

**Stage 2 — sanity-check by simulation.** Run the Layer 2 simulated students (§12) against the
chosen constants and inspect the trajectories: do intervals reach maintenance on a plausible
timetable, does a lapse recover without a punitive spiral, does review load stay within the §7.6
cap. This catches bad constants before a student meets them.

**Stage 3 — fit from the evidence log.** Every scheduled review is a labelled prediction: the model
asserted a retrievability, the outcome was 0 or 1. Fit `A`, `F`, `S_0` by minimising log loss over
held-out reviews, monitored by the calibration check in §7.2. Fit globally first; move to per-skill
parameters shrunk toward the global prior only once a skill has the volume to support it. Replay
from the append-only log (P6) is what makes refitting possible at all.

**Interval jitter is required for identifiability, not for load-balancing.** A scheduler that
always reviews at `R_TARGET` observes the forgetting curve at exactly one point, and its own policy
then censors the data needed to improve it. Randomise scheduled intervals by roughly ±20% and
deliberately place a small fraction of reviews early or late, so the log contains outcomes across a
range of retrievabilities. Without this, no volume of accumulated data will improve the memory
model.

**`S_0` should become a function, not stay a constant.** Initial stability after a first cold
success plausibly depends on how that success went — strength margin over item difficulty, stated
confidence, hesitant versus immediate. Begin with a constant and promote it once the log supports
the comparison.

---

## 8. Sessions and modes

### 8.1 Mode contracts

A mode is a contract the engine enforces, expressed as data rather than prose.

```python
ModeContract(
  base_max_rung,            # none | nudge | next_step | name_method | full_reveal
  unlock_full_reveal_after, # EffortCondition | None
  reveal_price,             # none | self_explain | fresh_variant_cold
  evidence_weight,
  min_vetting_level,
  intervention_timing,      # let_run | immediate | by_error_type | never
  timed, mixes_skills,
)
```

| Mode | Base rung | Full reveal | Price | Evidence | Intervention |
|---|---|---|---|---|---|
| **Learn** | full_reveal | — | self_explain | `post_instruction` (≈0.1) | let_run |
| **Practice** | name_method | after ≥2 genuine attempts and ladder exhausted | fresh_variant_cold | `unassisted_cold` → 1.0 | let_run |
| **Review** | nudge | never | — | `unassisted_cold` → 1.0 | immediate |
| **Mock exam** | none | never | — | `timed_exam` → 1.0 | never |

- **Learn** — tutoring a new or weak skill. Follows the worked-example fade: full worked example →
  example with the final step blanked → more steps blanked → full problem. Evidence is collected
  but weighted near zero.
- **Practice** — the main loop. Frontier skills plus due reviews (due-review arbitration
  arrives with the scheduler in Slice 2; see §13). First attempt cold counts;
  taking a hint marks the attempt assisted and it earns nothing toward mastery, though the
  tutoring continues in full. The escape hatch offered first is always "drop to the
  prerequisite"; a full reveal is never offered, and unlocks only when the student asks for it
  after documented effort — at least two genuine attempts with the hint ladder exhausted — and it
  carries the **fresh-variant price**: the engine immediately serves a new instance of the same
  skill (same generator, different parameters) which the student must solve unaided.

  That immediate variant is the *price*, not the *evidence*. Served in the same session as the
  reveal, it classes as `post_instruction` under §8.2 and barely moves mastery — by P5, succeeding
  minutes after seeing a solution demonstrates working memory, not learning. Its purpose is to
  convert a passively received solution into an act of construction. The evidence comes from a
  further variant the reveal **queues for a later session**, where a cold success counts in full.
  A variant rather than a repeat of the same problem, because re-solving the identical item would
  measure recall of a remembered procedure instead of the skill — which is exactly what generators
  (§6.2) make free.
- **Review** — the spaced mode. Mixes Cards (declarative retrieval) with fresh generator variants
  (procedural re-checks). This is the flashcard experience, driven by the same scheduler as
  everything else rather than living in a silo.
- **Mock exam** — timed, zero help, mixed skills, weighted to the course exam blueprint, with a
  diagnostic report afterwards.

A **checkpoint** — three cold problems, explicitly framed as proving it — is a ritual inside
Practice, not a fifth mode. Students value the moment; it needs no separate architecture.

### 8.2 Evidence classes

```python
Session(id, student_id, course_id, mode, plan, started_at, ended_at)
Task(session_id, item_id, skill_id, state)
Attempt(task_id, steps, verdict, confidence, assistance_level, evidence_class, at)
HelpEvent(task_id, rung, at)
```

**Declining is a first-class answer.** A student may answer "I don't know" instead of submitting
work, and it is scored at the format's **guess baseline** rather than as a flat zero. That makes
declining and guessing cost exactly the same in expectation, at any guess rate.

Both alternatives teach something false. Scoring a decline as a wrong answer makes guessing
marginally the better play — negligibly so on free response (about 0.012 logits) but around 0.1
logits an item on four-option multiple choice, which is worth gaming — and a system that pays
students to guess rather than admit they are stuck is training the exact habit this platform
exists to break. Scoring a decline as free makes it cheaper than attempting, which trains
disengagement instead. The guess baseline sits between them by construction rather than by a
tuned compromise.

A decline never increments unassisted-correct evidence, so it cannot contribute to mastery. It
differs from a wrong answer in two further ways: the tutor opens with orientation rather than
error diagnosis, there being no work to diagnose, and the calibration reading for an honest
decline is near-perfect rather than a penalty. It also does not count toward the effort condition
that unlocks a reveal — otherwise the cheapest route to the answer would be two declines and a
walk up the hint ladder.

`evidence_class ∈ {unassisted_cold, post_instruction, assisted, timed_exam}`.
**Only `unassisted_cold` and `timed_exam` move mastery.** An attempt is `post_instruction` if the
same skill was taught in the current session; `assisted` from the moment any help event lands on
the task.

Mastery evidence is therefore collected **continuously** — every first attempt before any hint —
rather than in a separate examination ceremony. The student simply practises, and the honest
signal accumulates underneath.

### 8.3 Contingent generosity

Help level is not a policy constant. For a novice on new material a fully worked example beats
struggle (worked-example effect); for a student who holds the prerequisites, struggle wins
(expertise reversal). The engine resolves this from the student model:

```python
initial_strategy(contract, skill_state) -> TeachingStrategy
# worked_example | faded_example | completion_problem | cold_problem
```

This is the *assistance dilemma* (Koedinger & Aleven) resolved contingently rather than by a fixed
rule. It is also why the mastery model is not merely a progress bar — it is the input that decides
how the tutor behaves.

### 8.4 Intervention timing and lapses

When the CAS detects that equivalence broke at a step, the tutor stays quiet for a step or two and
lets the student meet the contradiction themselves, then walks back to where the error entered.
This matches observed expert-tutor behaviour and preserves the productive-failure benefit.
`intervention_timing` governs only **when the tutor speaks about a wrong step inside a problem**.
It never ends a task or a session: a wrong answer closes the item, records the evidence, and the
session proceeds to the next task.

Mock exam is `never` — no feedback of any kind during the exam, as in the real thing. Review is
`immediate`, because review items are short, often single-step, and there is no later contradiction
for the student to discover; letting a broken two-line derivation run has no productive-failure
value.

**A Review lapse schedules; it does not tutor.** At most one nudge and a retry; if the item is
still wrong, show the correction briefly, mark the lapse (stability × `F`, §7.2), and move on. A
student may explicitly choose "work on this now", which switches modes into Practice on that skill
— but it is never automatic. The reason is tempo: a ten-minute review session containing three
lapses must not become a forty-minute tutoring session, because a student who learns that reviews
are unpredictably long stops doing them, and retention is the entire purpose of the mode. Skills
that lapse repeatedly are returned to the frontier by the repair-before-advance rule (§7.6), which
is where the real relearning belongs.

### 8.5 Planning

At session start the planner assembles a task queue from the frontier, the due queue, and the mode
contract, sized to the student's chosen duration. After each task it re-plans on the outcome.
Deterministic and inspectable: given a student state and a mode, assert the queue.

---

## 9. The tutor turn contract

```python
class Tutor(Protocol):
    def respond(self, ctx: TurnContext) -> TutorTurn: ...

TurnContext(
  skill_pack,        # can-do statement, teaching notes, misconception catalogue
  item,              # statement, answer, worked solution
  student_summary,   # strength/freshness here and nearby, calibration gap, prior misconceptions
  step_diff,         # from the Verifier: which step broke equivalence, and how
  permitted_rung,    # what the contract allows right now
  transcript,
)

TutorTurn(
  message,           # what the student sees
  rung_used,
  diagnosis,         # misconception_id | novel_error | none
  proposals,         # requests, not commands
)
```

**`step_diff` is one defect shape, not the only one.** It assumes work decomposes into ordered
steps, that each step transforms the previous one, and that validity is a local property of
consecutive pairs. That holds for algebra, calculus manipulation, stoichiometry, physics
derivations and code refactoring. It does not hold for a geometry or induction proof, where each
line *adds* a justified statement rather than transforming the last, nor for an essay, where the
defect is an unsupported claim rather than a broken transition. The boundary is transformational
versus non-transformational work — not mathematics versus other subjects, which is why a maths
proof falls outside it.

Nothing breaks in the meantime: a `Verifier` with no notion of steps returns `None`, and
diagnosis degrades to a novel error. When proofs or rubric-judged subjects arrive, `TurnContext`
gains a sibling field carrying that verifier's defect shape — `UnjustifiedStep(line, cited_rule)`
for a proof, a rubric finding for an essay — rather than `StepDiff` being generalised. One
example is too few to design an abstraction from; the second will say what it should be. See §14
D10.

**What "equivalent" means to the CAS verifier.** Two expressions are equivalent when they agree
wherever both are defined. An isolated hole is ignored — simplifying `(x²−1)/(x−1)` to `x+1` is
the exercise, not an error — but disagreement over a region is not: `log(x²)` and `2 log x`
differ for every negative x. Two equations are equivalent when they have the same real
solutions, holes respected, which is what flags the classic solving errors: dividing by
something that can be zero loses a root, and multiplying through by it or squaring both sides
admits one. Holes must be read from the student's *written* form, because SymPy's evaluation
cancels them — `(x−1)²/(x−1)` is already `x−1` by the time any solver sees it — so the parser
can return either form, and form constraints use the written one too. Where real solutions
cannot be listed, the verifier falls back to proportionality (D12).

### 9.1 Proposals

The model may request: drop to a prerequisite, serve an easier item, switch to a worked example,
or end the task as unproductive. **The engine decides.** The tutor is genuinely agentic in the
sense that matters — it observes and initiates — while every state change remains in testable code.

### 9.2 Tools: read and verify, never write

| Tool | Purpose |
|---|---|
| `check_expression` | Ask the CAS rather than doing algebra in its head |
| `get_worked_example` | Fetch a vetted analogous example instead of inventing one |
| `lookup_misconception` | Retrieve the catalogue entry matching a signature |
| `get_student_summary` | Read-only student state |

Nothing in that surface touches mastery. P2 is enforced by absence, not by instruction.
`check_expression` is also the single largest reliability win available: arithmetic is where
models embarrass themselves in front of students, and it is exactly what a CAS never gets wrong.

### 9.3 Validation pipeline

Every turn, before a character reaches the student:

1. **Rung check** — `rung_used <= permitted_rung`.
2. **LeakGuard** — extract mathematical expressions from the draft message and ask the CAS whether
   any is equivalent to the item's answer. A leak above the permitted rung fails the turn. This
   also catches a "nudge" that quietly contains the next line of algebra.
3. **Proposal validation** — is the proposed prerequisite actually a prerequisite, and is the
   student permitted there?

On failure the turn is regenerated with a corrective instruction appended as a **mid-conversation
system message**, which preserves the cached prefix and is the injection-safe operator channel.
Student-authored text is untrusted input throughout.

A system prompt saying "never reveal the answer" is a hope; models under pressure from a
frustrated teenager will cave. The LeakGuard closes the gap between the policy as written and the
policy as enforced.

### 9.4 Streaming

Streaming and the LeakGuard conflict: text cannot be shown before it is checked, but a
multi-second pause before every reply feels dead. Resolution — when the contract permits full
reveal (Learn mode working an example), stream straight through. Otherwise stream into a buffer
and release at sentence boundaries as each clears the guard, so the student sees progressive text
with at most one sentence of lag.

---

## 10. Model routing and economics

Routes are named by **job**, never by model, and resolved from configuration so a model change is
a config edit. The same mechanism supports running two configurations against one route for
canary comparison.

```yaml
routes:
  tutor_dialogue:   {adapter: anthropic,       model: claude-opus-5,    effort: high,  thinking: adaptive, stream: true}
  error_diagnosis:  {adapter: anthropic,       model: claude-opus-5,    effort: xhigh, thinking: adaptive}
  intent_classify:  {adapter: anthropic,       model: claude-haiku-4-5, max_tokens: 256}
  rubric_judge:     {adapter: anthropic,       model: claude-opus-5,    effort: high,  thinking: adaptive}
  content_generate: {adapter: anthropic_batch, model: claude-opus-5,    effort: high}
```

### 10.1 Caching layout

Stable content first, volatile last, four breakpoints:

1. **Global tutor policy** — identical for every student; warm essentially always.
2. **Skill pack** — teaching notes and misconception catalogue; shared by everyone working that skill.
3. **Session preamble** — student profile; stable for the whole session.
4. Item and turn data — uncached.

Verified by asserting `cache_read_input_tokens > 0` in adapter integration tests. A zero means
something volatile entered the prefix.

### 10.2 Cost

Approximately **$0.015 per tutor turn** at Opus 5 with the cache working. The decisive property is
how few turns there are: a student who solves an item correctly on the first attempt costs
**nothing** — the generator serves it, the CAS checks it, the engine records evidence, and no model
is involved. Model turns occur on errors, hints, and Learn mode.

Expected **$4–10 per active student per month with Opus 5 throughout**, which fits the quality-first
budget without routing pedagogy down to cheaper models. Offline content generation runs through the
Batch API at 50% off, as none of it is latency-sensitive.

---

## 11. Data and persistence

**Evidence is an append-only log; `SkillState` is a projection.**

The mastery algorithm will change — the K-factor, the stability curve, the propagation weight.
With an event log, every attempt ever recorded can be replayed to recompute every student's state
under the new model. Without one, every tuning change either strands existing students on the old
algorithm or silently corrupts their history.

The projection lives in ordinary tables and is rebuilt from the log on demand. Rebuild-from-log is
itself a tested operation, not an emergency script.

Personal data is minimised: the log records attempts, timings, verdicts, and confidence — not free
text beyond what tutoring requires. Minors' data handling is a launch requirement (see §14).

---

## 12. Testing strategy

**Layer 1 — Property tests over the pure domain (Hypothesis).**
The invariants the integrity claim rests on, made executable:
- Assisted evidence never increases mastery.
- Retrievability is monotonically non-increasing in time since last success.
- A correct unassisted attempt never decreases strength.
- No sequence of help events can produce `is_learned`.

**Layer 2 — Simulated students against a `FakeClock`.**
Scripted synthetic students — the diligent one, the hint-abuser, one carrying a specific
misconception, one who crams the night before — run a term of study in milliseconds. This is the
only way to test a forgetting curve before five weeks of real users exist, and it is how the
treadmill problem gets caught before a student feels it.

**Layer 3 — Generator contract tests.**
Per template, sample several hundred seeds and assert: the CAS answer is valid, no degenerate
parameters (zero divisors, trivial answers, roots outside the intended range), difficulty within
the declared band. This is what keeps a wrong answer key from ever reaching an unassisted check.

**Layer 4 — Adversarial LeakGuard corpus and a graded tutor eval set.**
The first is unit tests over messages that leak the answer in non-obvious ways. The second is a
graded rubric over real tutoring turns — the instrument that makes model routing a measurement
rather than a preference. The eval set is a first-class deliverable, not a nice-to-have.

`FakeTutor` — scripted, deterministic — lets the entire engine, every mode contract, and the full
session flow be tested without an API key, without cost, and without flakiness. Only the real
adapter requires live testing.

---

## 13. Slice 1 — first buildable slice

> **One skill cluster, Practice mode only, end to end.**

**Cluster: quadratics** — 12–15 skills, rich in real misconceptions, strong prerequisite
structure, entirely CAS-verifiable.

**Execution.** Slice 1 is built as two plans, split at the hexagonal boundary so each produces
working, testable software on its own.

- `docs/superpowers/plans/2026-09-19-slice1-tutoring-engine.md` — deliverables 1–8 and 11 below:
  the domain core plus the CAS and content adapters, driven by a fake tutor and a fake clock.
  Runs with no API key, no database and no UI.
- A second plan attaches the I/O: persistence, HTTP, the Anthropic tutor adapter with model
  routing and caching, the graded eval set, and the web session UI — deliverables 9 and 10, plus
  the durable half of 8.

### Deliverables

1. Skill graph for the cluster: skills with can-do statements, prerequisite edges, misconception
   catalogues.
2. At least one `ItemTemplate` per skill, each passing generator contract tests over ≥300 seeds.
3. `SymPyVerifier`: final-answer equivalence, form constraints, pairwise step-equivalence diff.
4. Mastery engine: strength, stability, derived states, prerequisite propagation, calibration —
   with the Layer 1 property tests.
5. Practice `ModeContract` with hint ladder, effort-gated reveal, evidence classification.
6. `LeakGuard` with its adversarial corpus.
7. `AnthropicTutor` (Opus 5) behind the `Tutor` port, plus `FakeTutor`.
8. Session planner covering frontier selection and difficulty targeting within the cluster —
   spaced-review arbitration is Slice 2 — and the append-only evidence log with a tested
   rebuild-from-log path.
9. Web session UI: item view, math input, step entry, confidence tap, hint request, session summary.
10. Tutor eval set: ≥50 graded turns spanning hint rungs, misconception diagnoses, and leak attempts.
11. Simulated-student suite (Layer 2).

### Acceptance criteria

- A student can run a 20-minute Practice session end to end on the cluster.
- Mastery moves only on `unassisted_cold` evidence; a property test proves no help sequence can
  produce `is_learned`.
- A wrong step is localised by the CAS and diagnosed against the misconception catalogue before
  any model call.
- No tutor turn above the permitted rung reaches the student, verified against the adversarial corpus.
- A simulated term of study produces sensible mastery and scheduling trajectories under `FakeClock`.
- Measured cost per session is within the §10.2 estimate.

### Explicitly not in Slice 1

Learn and Review modes; courses and curriculum overlays; mock exams; bring-your-own-problem;
photo input; non-mathematics subjects; parent dashboards; mobile; billing. The skill graph and
content model are designed to accommodate all of them; none is built.

### Roadmap after Slice 1

| Slice | Content | Why this order |
|---|---|---|
| 2 | Review mode, spaced scheduler, Cards | Needs Slice 1's evidence to be worth anything; `FakeClock` validates it before real time passes |
| 3 | Learn mode with faded worked examples | Richer content authoring; depends on teaching notes maturing |
| 4 | Courses, curriculum overlay, mock exams | Turns the engine into a product a student enrols in |
| 5 | Physics | Proves the `Verifier` seam is real rather than theoretical |
| 6 | Bring-your-own-problem with a practice tail | Highest-value retention feature; highest risk, so it goes last |

---

## 14. Deferred decisions

These are recorded deliberately, each with the trigger that will force a decision.

On answer kinds specifically: `AnswerKind` names a general *shape*, and each `Verifier` decides
how to compare the elements of that shape — an ordered list of expressions by symbolic
equivalence, an ordered list of historical causes by rubric. So a new subject never forces a new
kind, and a new kind never forces every adapter to implement it: one that cannot judge a shape
raises `UnsupportedAnswerKindError` rather than guessing. The trigger for adding a kind is an
item that wants it, not a subject that arrives.

| # | Decision | Status |
|---|---|---|
| D1 | **Math input library.** Needs a spike — step-by-step entry UX is load-bearing for Slice 1 and no library is obviously right. KaTeX handles rendering; input is the open part. | Spike before UI build |
| D2 | **Step entry granularity.** Whether students must enter every step or may submit a final answer with optional work. Proposal: optional but encouraged; if a final-answer-only submission is wrong, the tutor asks for the work. | Settle during UI design |
| D3 | **Session UI and layout.** Deliberately unspecified here; to be settled with mockups. | Next, before Slice 1 build |
| D4 | **Orchestration adapter** — Tool Runner vs. manual loop. Domain is unaffected. | At `AnthropicTutor` implementation |
| D5 | **Accounts, minors' data, and GDPR posture.** Minimal auth in Slice 1; a real compliance position is required before any public launch with minors. | Before launch, not before Slice 1 |
| D6 | **UI language (Spanish/English).** Content is curriculum-agnostic; copy is not yet decided. | Before launch |
| D7 | **Bring-your-own-problem mode.** Agreed in principle with a practice tail — the tutor helps under the strictest contract, then the engine queues generated variants of the skills involved for later cold practice. Deferred to Slice 6; the skill-identification hook is designed for now. | Slice 6 |
| D8 | **`ORDERED_SEQUENCE` answer kind.** Reaction mechanisms, chronologies, algorithm steps — and, within mathematics, "list these steps in order". Cheap: the CAS comparison is `len(a) == len(b) and all(expressions_equivalent(x, y) for x, y in zip(a, b))`, reusing the element comparison and the comma parsing that `VALUE_SET` already has. Not added yet only because no item wants it and the input widget cannot be designed in the abstract. Adding the member without a branch would compare a list as one expression, which is why the verifier raises `UnsupportedAnswerKindError`. | First item that wants an ordered answer — plausibly in mathematics, not necessarily a new subject |
| D8b | **`MAPPING` answer kind.** Matching terms to definitions. Genuinely more design than D8: delimiter and key normalisation, and whether a missing or extra pair is wrong or partially wrong — which drags in D9. Weak mathematics use case. | A subject built on matching items |
| D9 | **Composite answers and partial credit — one change, not two.** Fill-three-blanks and tables need `AnswerSpec.parts: tuple[AnswerSpec, ...] = ()`, which is additive and migrates nothing. The real cost is that a composite answer is inherently partially correct, so `Verdict` stops being binary and `CheckResult` gains a score. The mastery half is already done: `update_strength` takes `outcome: float`. Until then, model each blank as its own item — usually fine, occasionally wrong. | When an item genuinely cannot be split |
| D10 | **A sibling defect shape for non-transformational work.** `StepDiff` assumes each step transforms the previous one and that validity is local to consecutive pairs — true of algebra, stoichiometry and derivations, false of a geometry or induction proof (each line *adds* a justified statement) and of an essay (the defect is an unsupported claim, not a broken transition). See §9. `TurnContext` should gain a sibling field carrying that verifier's defect shape rather than `StepDiff` being generalised from a single example. Nothing breaks meanwhile: a verifier with no notion of steps returns `None` and diagnosis degrades to a novel error. | First proof-based or rubric-judged skill |
| D11 | **Assisted cycle resolution.** When loading rejects a hard-prerequisite cycle (§6.1), an authoring-time step — plausibly LLM-assisted — could propose how to break it: soften one edge, merge two skills that are really one, or add the shared prerequisite whose absence created the loop. It proposes and the author decides; the result goes back through the same loader. Never an automatic repair at load time, for the reason §6.1 gives. Until then the error names the path and the author fixes it by hand. | When content is generated at volume (LLM batch generation of the long tail) or authoring tools are built |
| D12 | **Equation equivalence where solutions cannot be listed.** "Same real solutions" (§9) is computed only for one-variable equations whose solutions form a finite list. Otherwise — several variables (`y = 2x + 1`), infinitely many solutions (`sin x = 0`), no closed form (`x = cos x`), or no real solutions on either side, where two empty sets would accept any slip between `x² + 1 = 0` and `x² + 4 = 0` — the verifier falls back to proportionality: one side a nonzero constant multiple of the other. Proportional equations share their solutions, holes aside, but the fallback rejects genuine rewrites such as `(x−1)² = 0 → x − 1 = 0` and cannot see holes. Quadratics reach it only on steps with no real solutions. | First skill whose worked steps are trigonometric, transcendental or multi-variable equations |

---

## 15. Decision log

| Decision | Chosen | Rationale |
|---|---|---|
| Intelligence location | Engine-centric; model as voice | Deterministic, testable, evaluable pedagogy; integrity becomes an architectural guarantee; cost scales with explanation, not with every decision |
| Mastery evidence | Unassisted gate **with decay** | Retention is a stated goal; a non-decaying mastery number relocates the false-confidence failure into the progress bar |
| Competence model | Elo over BKT | Works from the first attempt with no fitted parameters; co-estimates item difficulty |
| Memory model | Half-life with spacing effect | Drives both scheduling and the honest freshness display from one quantity |
| Tutor policy | Contingent generosity with priced reveals | Expert tutors explain freely; the research (VanLehn, Chi ICAP, worked-example/expertise reversal) says granularity of interaction matters more than withholding. Integrity is carried by the unassisted gate, so the tutor can be warm |
| Intervention timing | Let it run, then backtrack (Review excepted) | Matches expert-tutor behaviour; preserves productive failure and the skill of self-catching |
| Answer-withholding enforcement | CAS LeakGuard | A prompt instruction is a hope; a deterministic check is a fact |
| Content | Generators + CAS, LLM for the long tail | Ground-truth answers, unlimited variants, zero serve cost, where it matters most |
| Curriculum | Dependency graph with course overlays | Curriculum-agnostic core, curriculum-specific presentation |
| Verification kind | Opaque token plus a registry | Enumerating adapter kinds in the core would mean every new subject edits the engine, contradicting the seam it names |
| Tuned parameters | Injected value object | Module constants cannot be varied per skill or A/B compared, which §7.2 and §7.8 both require |
| Concepts and misconceptions | Subject-scoped, shared many-to-many | A single owning skill is arbitrary and forces duplication, and duplicating a concept duplicates its memory state |
| Default verification kind | Declared by content; no fallback in code | Which checker grades a skill is a fact about the content; a code default grades any cluster that forgets the key with SymPy, silently |
| Misconceptions per skill | Optional | Diagnosis already handles no match as a novel error; a mandatory entry invites invented ones |
| Hard-prerequisite cycles | Rejected with the path named, never auto-repaired | Breaking a cycle means deciding which dependency is false, a judgement the graph has no information to make |
| Mathematical equivalence | Expressions agree wherever both are defined; equations share their real solutions, holes respected | Accepts the simplifications school teaches while catching lost and extraneous roots, the errors that matter most in solving |
| Parsing untrusted maths | Safety by construction (alphabet, resolved names, bounded powers), no blocklist | `eval` inserts every builtin into the namespace it is given, so a blocklist is the only barrier and blocklists leak |
| Declining to answer | Scored at the guess baseline | Makes honesty and guessing cost the same in expectation; zero would pay students to guess, free would pay them to disengage |
| Confidence mapping | Population-fitted, per item format | Per-student fitting makes everyone calibrated by construction; MCQ priors libel honest free-response guessers |
| Form vocabulary | Opaque tokens, adapter-owned | An enum of math forms in the domain core would grow a union of every subject's vocabulary and break the `verification_kind` seam |
| Provider abstraction | Task-level ports only | A generic `LLMClient` forfeits caching, thinking, structured outputs, and Batch — the features carrying the economics |
| Persistence | Append-only evidence log with projection | The mastery algorithm will change; student history must survive it |
| First slice | Quadratics, Practice only | Proves or kills the thesis with the smallest honest end-to-end system |

---

## 16. References

The pedagogical choices draw on: VanLehn (2011) on interaction granularity in human and computer
tutoring; Chi's ICAP framework and the 2001 human-tutoring study on student construction versus
tutor explanation; Sweller and Renkl on worked examples, fading, and expertise reversal; Kapur on
productive failure; Bjork on desirable difficulties and the performance/learning distinction;
Koedinger & Aleven on the assistance dilemma; and the Cognitive Tutor literature on gaming
hint systems.
