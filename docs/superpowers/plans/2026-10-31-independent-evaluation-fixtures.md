# Independent Evaluation Fixtures Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution of these dependent tasks.

**Goal:** Make the approved fourteen briefs executable through real engine replay,
with keyless validation and no paid execution.
**Architecture:** An opt-in authored evaluation item source supplements the existing
generator registry. Separate scenario YAML uses the existing fixture schema,
replay, references and runner. A keyless preflight command validates the complete
set and fixed judge policy before later live execution.
**Tech stack:** Existing Python 3.12, pytest, YAML, SymPy; no new dependencies.
**Spec:** ../specs/2026-10-31-independent-judge-evaluation-design.md

## Global constraints

- Preserve all fourteen exercises, student questions, raw work and declared history.
- Never seed authoritative counters or verification results from expectations.
- Keep the original corpus, saved paid run and fixed judge prompt unchanged.
- No method-requirement engine work, paid calls, model/default changes or promotion.
- Report representation limitations explicitly rather than hiding them by rewriting cases.

## Review focus

1. Authored keys must not acquire generated/machine-derived provenance.
2. Unknown items, duplicate identifiers and unsupported metadata must fail before clients.
3. Incomplete solution sets and no-work errors must not acquire invented diagnoses.
4. Historical scripts must actually be delivered, and only on their recorded revisions.
5. References and expected findings must not leak into tutor requests; judge hash must match.

## Task 1 — Authored item source and explicit CLI selection

Files: `src/learnai/eval/authored.py`, `src/learnai/eval/__main__.py`,
`tests/eval/test_authored_items.py`.

Interface: `load_authored_items(path: Path) -> EvaluationItems`, a
`GeneratorRegistry` subclass supporting authored IDs with seed 0, honest AUTHORED
provenance and HUMAN_REVIEWED vetting, alongside existing generated templates.
The CLI `run --items PATH` loads the source and captures its exact YAML in manifest
supplemental inputs. Default runs retain the generator-only registry.

- [x] Write failing tests for authored round trips, bad schema/IDs/seeds and CLI capture.
- [x] Implement strict loading and explicit opt-in CLI integration.
- [x] Run the focused tests and existing CLI preflight tests.

## Task 2 — Fourteen concrete replay fixtures

Files: `eval/independent/items.yaml`, `eval/independent/scenarios/cases.yaml`,
`tests/eval/test_independent_fixtures.py`.

- [x] Test exact count, item provenance, unchanged fixed judge hash, all actual tutor
  opportunities, evaluator-only references, and key mathematical/history distinctions.
- [x] Author items and scenarios with exact statements, raw work/questions, genuine
  history actions and independent expected findings/progress.
- [x] Validate through real `validate_corpus`/`prepare_scenario`; document any parser
  limitations and flag cases that need a separate representation change, without inventing student actions.

## Task 3 — Keyless operator command, documentation and final verification

Files: `src/learnai/eval/independent.py`, `eval/README.md`, the scenario design note.

- [x] Add `python -m learnai.eval.independent` preflight with no SDK/client/network;
  output scenario count and actual permission/verification summaries.
- [x] Verify current provider payload admission and reference construction.
- [x] Document how to prepare the set and the distinction from the old regression selection.
- [x] Run the full keyless suite, inspect the diff and obtain a final independent review.

## Execution record

Ruling: Continue in the existing named worktree with the user's uncommitted review
edits intact — execution is authorized and moving them risks losing context —
cost if wrong is separating changes later before PR publication.
Ruling: Use an opt-in authored item source — exact exercises cannot reliably be
selected from current generators — cost if wrong is a small evaluation-only loader.
Task 1: authored-source tests failed 14/14 before implementation; focused source
and existing CLI tests then passed 59/59. Explicit CLI capture is additionally
covered with the real fourteen-case catalogue in Task 2.
Task 2: initial fixture test failed for missing scenarios; all fourteen now
validate/replay with actual NAME_METHOD opportunities. Current source and fixture
tests passed 18/18 before the independent key-check test was added.
Ruling: Preserve five verifier limitations and fail the semantic readiness gate
instead of changing valid student work or core verification — avoids contaminating
judge evaluation with false student-error findings — cost is a separate verifier
design/fix before the full paid set can run faithfully.
Ruling: Record generic rejection prose as a UI assumption while replaying the
actual WRONG verdict — the domain has no system-feedback prose event — cost is
adding such an event later if exact product feedback becomes an evaluation input.
Task 3: keyless command implemented; intended exit 1 reports 14 opportunities,
9 ready and 5 blocked. Independent review found one Important manifest-path issue;
a regression reproduced it before correction. Focused verification then passed
19/19; the final full keyless suite passed 1,843 tests with four live probes
deselected in 99.46s. No review findings remain open in this implementation scope.
The five pre-existing semantic blockers remain explicitly unresolved.
