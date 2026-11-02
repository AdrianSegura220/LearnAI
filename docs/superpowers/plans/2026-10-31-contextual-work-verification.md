# Contextual Work Verification Implementation Plan

**Goal:** Resolve five independent-evaluation blockers without weakening final
answer checks or conflating intermediate branches with complete solutions.

## Root cause and scope

The existing `diff_steps` checks consecutive lines for expression/solution-set
equivalence. Its reader treats comma-separated equations as alternatives and
rejects multiple equals signs. It has no active item to validate coefficient
bindings and no representation of a partial branch. These are limitations of
the linear work model, not incorrect student mathematics.

Add a subject-neutral `WorkCheck` result with a first difference and scope notes,
and a `Verifier.check_work(steps, item, allow_partial=...)` operation. The SymPy
adapter owns contextual recognition; the domain only transports findings.
Keep `diff_steps` strict for callers asking specifically about equivalence.
This change does not establish that a required solution method was demonstrated.

## Tasks

- [x] Write regression tests for the five concrete patterns and counterexamples:
  wrong coefficients, incorrect arithmetic/substitution, lost final roots, a
  non-factor branch and malformed input. Prove failures before implementation.
- [x] Add `WorkCheck` and default-empty scoped work notes on verification snapshots.
  Route domain preparation through contextual checking, with partial branch
  interpretation restricted to draft questions. Render notes only when present.
- [x] Implement bounded contextual checks in the CAS adapter: validate explicit
  a/b/c assignments against a single-variable quadratic item; evaluate discriminant
  calculation links; compare formula solution claims against the source equation;
  recognize an explicitly written zero-product factor branch while noting that
  the remaining branches are still required. Fallback to strict checks elsewhere.
- [x] Preserve historical snapshot decoding with an explicit legacy field shape,
  not general acceptance of missing artifact fields. Test old saved packets.
- [x] Update the five fixture observations and replace known-blocker diagnostics
  with assertions on faithful scoped findings. Keep the frozen judge policy and
  original paid artifacts unchanged.
- [x] Run targeted regressions, the complete keyless suite and independent review.

## Required distinctions

Calculation checks, coefficient bindings and solution transformations are
different claims. No successful check of a calculation establishes the final
answer. A draft branch may be locally valid while completeness remains pending.
An incorrect submitted solution set must still be WRONG, and strict dropped-root
tests must continue to fail equivalence. Ambiguous or unsupported structures
must not acquire an invented misconception diagnosis.

## Compatibility and boundaries

Existing prompts/defaults and dependencies stay fixed. Snapshot notes are
revision-bound and included in tutor/judge contexts and saved packets. The exact
old artifact shape maps to empty notes; all other unexpected field shapes still
fail. No paid calls. No method-specific mastery policy is added.

Ruling: Implement scoped contextual checks alongside strict equivalence rather
than make every subset of roots equivalent — this preserves existing safety
properties — cost is one additional generic verifier operation and snapshot field.
Ruling: Recognize only bounded, demonstrable structures; broader proofs and
arbitrary branch trees remain unsupported — avoids guessing student intent —
cost is explicit limits for future extensions.

## Review and verification

The original contextual regressions failed before implementation. Calculation
chain and normalized-coefficient cases also demonstrated failures before their
fixes. Independent review found two additional problems: a simple numeric
calculation after definitions was still compared with the whole equation, and
coefficient substitution could evaluate away undefined denominators. Both now
have reproductions and passing regressions. Unsupported ancillary definitions
remain unreadable instead of becoming invented mathematics errors; substitution
preserves written expression trees. The reviewer rechecked both fixes and found
no further important issues.

The focused contextual, snapshot, independent-fixture and strict-differ suite
passed **52 tests**. The independent preflight exits **0**, reports **14 ready**
and no blockers, and admits all **28** tutor payloads. The frozen judge and prior
paid artifact hashes remain unchanged. No live calls were made.

Final full keyless suite:
`env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m pytest`
— **1,869 passed, 4 deselected in 98.12s**. `git diff --check` also passed.
