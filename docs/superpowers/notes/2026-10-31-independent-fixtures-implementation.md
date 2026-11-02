# Independent fixtures implementation checkpoint

## Implemented scope

The fourteen [approved scenario briefs](../specs/2026-10-31-independent-judge-evaluation-design.md)
have executable YAML at `eval/independent/scenarios/cases.yaml` and exact authored
items at `eval/independent/items.yaml`. `learnai.eval.authored` provides strict
catalogue loading, AUTHORED provenance and HUMAN_REVIEWED vetting; authored seed
0 is a lookup convention. Existing generated items remain available to tools.

`learnai.eval run --items PATH` explicitly selects an authored catalogue and
captures its loaded content/hash alongside the generated item snapshots in the
manifest. This is separate from ordinary default runs. The original 71-case
corpus remains intact. No method-requirement engine changes were made.

## Initial readiness result

```sh
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m learnai.eval.independent
```

The command is keyless and intentionally exits 1: fourteen tutor opportunities,
all with NAME_METHOD permission, nine ready and five semantic blockers. All 28
tutor payloads across Anthropic and OpenAI are admitted with the required
headroom. Actual judge payloads await generated replies; no paid calls occurred.

- Case 05: chained equality is unreadable to the existing verifier.
- Cases 07, 08, 10: coefficient assignments followed by calculation/substitution
  are treated as erroneous equivalence transitions, although the work is valid.
- Case 12: following a single zero-product branch is treated as loss of solution
  equivalence; the intended branch cannot be represented by the linear checker.

The fixtures preserve these observations without endorsing them as student
errors. Do not silently rewrite or omit cases to get a green semantic preflight.
The next decision is how to represent mixed calculations and branching work
faithfully before running this full independent quality evaluation.

Cases 13/14 replay real wrong submissions, scoped checks and no delivered tutor
reply. The assumed UI feedback "That answer isn't correct yet" is retained in
evaluator notes; the engine stores the structured verdict, not a system-prose
event. No invented tutor message substitutes for that feedback.

## Review and verification

The authored-loader tests failed before implementation, then the source/CLI
suite passed 59 tests. New independent fixture tests failed for missing data,
then passed after actual replay assertions were pinned. Independent review
found one Important integration error: the authored capture path was outside
the manifest allowlist. An end-to-end manifest-construction assertion reproduced
the failure. Capturing under `eval/fixtures/selected-authored/items.yaml` fixed
it without broadening the allowlist; all 19 focused tests then passed.

Reviewer minor observations were also addressed: NewType constructors preserve
domain annotations, exact assumed UI feedback is recorded, and documentation
status distinguishes executable fixtures from live-evaluation readiness.
The initial full suite passed 1,843 tests with four live probes deselected;
after the manifest fix, the final full keyless suite again passed: **1,843 passed,
four deselected in 99.46s**. `git diff --check` passed. All review findings within
this initial implementation scope were addressed; the five semantic blockers
were subsequently resolved as described below.

The original paid calibration artifact's SHA-256 remains
`de12e86f34b0b663a036ba567e76c4a09d2dc6765b4c11c679053b45a04f1dc9`.
The fixed judge SHA-256 remains
`a3f4451236fa1b9e434425162d2b8a6996e28e46e800d01cff81297b2d240a4d`.
V1 prompts and checked-in route defaults match HEAD. No additional live API call,
prompt revision, default promotion, commit, push or PR occurred in this task.


## Contextual verifier follow-up

The user authorized fixing the five representation blockers. The verifier now
checks mixed calculations in item context and records revision-bound scope notes.
Strict equation equivalence remains available unchanged; partial zero-product
branches are accepted only for draft questions and explicitly leave completeness
pending. Complete final-answer grading is unchanged. Coefficients may refer to a
verified equivalent rearrangement, including normalization. Old snapshots decode
with empty notes only for the exact legacy field shape.

The keyless readiness command now exits **0**, with **14 ready**, no blockers and
all 28 tutor payloads admitted. Original work/questions and the frozen judge
prompt remain intact. See the [implementation plan](../plans/2026-10-31-contextual-work-verification.md)
for final verification and review results. This establishes fixture readiness,
not tutor quality; no new paid calls were made.
