# Tutor Quality Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver evaluable v2 tutor/judge policies and prevent the pilot's text-format failures while clarifying inconclusive mathematical checks.

**Architecture:** Keep pedagogy in versioned prompts and exact text requirements in the shared adapter parser. Use existing provider repair loops, canonical tools and evaluation artifacts. Keep default activation separate from implementation acceptance.

**Tech Stack:** Python 3.12+, pytest, existing native SDK test transports, SymPy, YAML, Markdown; no new dependency.

**Spec:** [Tutor quality refinement design](../specs/2026-10-28-tutor-quality-refinement-design.md).

Status: all five tasks implemented and scoped-reviewed on 2026-10-29. Whole-branch review and its single fix-wave re-review are complete; no open findings remain. Final clean-clone suite: 1,824 passed, 4 live tests deselected. See the [implementation handoff](../notes/2026-10-29-tutor-quality-implementation-handoff.md). Subsequent paid evaluation and default promotion remain unexecuted.

## Global Constraints

- Python 3.12+; no new dependency, SDK upgrade, model switch, budget increase, domain permission/mastery change, new CAS capability, session detour, UI, pricing snapshot or live deployment.
- Keep v1 prompt bytes, original scenario fixtures, v1 artifacts and the pilot run immutable.
- Keep checked-in prompt defaults at v1 until the calibration/quality review supports promotion.
- Preserve the 8,192-unit continuation headroom after next-call output reservation.
- Existing credentials and raw run data stay private. Further paid execution requires explicit authorization.

## Review Focus

- Valid mathematical Unicode and literal backslashes survive text validation exactly (Task 1).
- Invalid replies and their repairs do not reset budgets or enter student history (Task 1).
- An unsupported root-set check never becomes a wrong-answer verdict or a fabricated successful check (Task 2).
- Permission to reveal does not force a solution, while lower permitted hints are not penalised (Task 3 calibration cases).
- Revised work, explanation-only replies and unseen scenarios are evaluated without claiming scripted tests prove model behavior (Tasks 3–5).

## File responsibilities

- `src/learnai/adapters/tutor/turn_schema.py`: shared provider-output message validation.
- `src/learnai/adapters/tutor/tools.py`: canonical checking-tool descriptions and actionable error detail.
- `prompts/tutor_math/v2.md`, `prompts/rubric_judge/v2.md`: candidate teaching/evaluation policies.
- `eval/calibration/tutor_quality_v2.yaml`: synthetic review examples, outside normal corpus discovery.
- `tests/adapters/tutor/`: parser, actual provider repair, tool and prompt-wiring coverage.
- `tests/eval/test_quality_calibration.py`: calibration structure and source-scenario checks.
- `src/learnai/eval/calibration.py`: offline case preparation, judge-only operator command and distinct calibration results.
- `tests/eval/test_calibration_execution.py`: dry-run isolation, judge dispatch and calibration artifacts.
- `tests/eval/test_provider_admission.py`: v2 real-payload budget checks.
- `eval/README.md`: offline verification and authorized comparison workflow.

### Task 1: Reject control characters through existing repair paths

**Files:** Modify `src/learnai/adapters/tutor/turn_schema.py`, `tests/adapters/tutor/test_turn_schema.py`, `tests/adapters/tutor/test_adapter.py`, `tests/adapters/tutor/openai/test_adapter.py`.

**Interfaces:** Retain `parse_turn(payload: Mapping[str, object]) -> TutorTurn` and `TurnSchemaError`. Both providers already call this parser. No new domain rejection reason or public API.

- [x] Add `test_message_rejects_disallowed_control_characters`, parameterized over every character U+0000–U+001F except U+0009/U+000A/U+000D, and U+007F–U+009F. Assert `TurnSchemaError` names the code point and does not echo a unique surrounding message sentinel.
- [x] Add `test_message_preserves_readable_math_and_whitespace`: valid text containing Unicode minus, superscripts, accents, Markdown, literal LaTeX backslashes, TAB/LF/CR round-trips byte-for-byte as a Python string. Keep empty/whitespace-only message behavior owned by existing engine validation.
- [x] Run `.venv/bin/python -m pytest tests/adapters/tutor/test_turn_schema.py`; confirm the new rejection test fails before implementing the guard.
- [x] Add the character check to shared `parse_turn` after its string-type check. Reject, do not strip or reinterpret text.
- [x] In both provider adapter test modules, use their native scripted transport helpers to emit an invalid control-containing reply, then a valid repair. Assert only the valid reply is delivered/history-recorded, raw invalid output remains in the private trace, `format_retries == 1`, and the same exchange and input context are retained.
- [x] Cover repeated invalid output and a budget exhausted before repair: bounded request count, no delivered invalid reply, existing typed termination. Exercise Anthropic tool-submit and text-final paths as well as OpenAI structured output; no runtime change outside the parser unless a regression exposes an existing bypass.
- [x] Run `.venv/bin/python -m pytest tests/adapters/tutor/test_turn_schema.py tests/adapters/tutor/test_adapter.py tests/adapters/tutor/openai/test_adapter.py` and confirm all pass.
- [x] Commit this focused parser/repair change after inspecting the diff.

### Task 2: Clarify supported checks and inconclusive results

**Files:** Modify `src/learnai/adapters/tutor/tools.py`, `tests/adapters/tutor/test_tools.py`, and both provider adapter test modules from Task 1 as needed for error transport.

**Interfaces:** Preserve the `check_expression` argument keys, `Toolbox.execute(name, arguments, context) -> str`, successful result scopes and `ToolError.code`. `expression_uncheckable` remains a tool error, not a verdict. Canonical descriptions flow into both wire schemas.

- [x] Add `test_root_set_equivalence_is_uncheckable_with_actionable_detail`: execute the observed brace-delimited pair `{-3-sqrt(5),-3+sqrt(5)}` and `{3-sqrt(5),3+sqrt(5)}` with the real Toolbox. Assert error code `expression_uncheckable`; detail explains supported expression/relation checks and unsupported brace-delimited sets without supplying a reference answer. Existing error type may already pass; the actionable-detail assertion must fail first.
- [x] Add or reuse a positive real-CAS test checking `x+x` against `2*x`, and an equation-equivalence case supported by `diff_steps`. Assert `scope == 'equivalence_only'`; no active answer grade is inferred. Preserve active-item field/shape tests and malformed-input semantics.
- [x] Run `.venv/bin/python -m pytest tests/adapters/tutor/test_tools.py` to establish the new failing expectation.
- [x] Update the canonical tool description and unreadable-equivalence error detail only. Do not implement a root-set parser, change successful payloads, or turn unsupported input into `WRONG`/`equivalent: false`.
- [x] Add a scripted tool-error continuation in both providers. Assert the exact typed error reaches the next request, calls/results stay paired and a subsequent valid response uses the original shared budget. A scripted explanation is transport coverage only, not evidence of model honesty.
- [x] Run the tools and both adapter test modules; verify existing successful checks and error handling still pass, then commit.

### Task 3: Add v2 policies and reviewable calibration examples

**Files:** Create `prompts/tutor_math/v2.md`, `prompts/rubric_judge/v2.md`, `eval/calibration/tutor_quality_v2.yaml`, `tests/eval/test_quality_calibration.py`. Modify `tests/adapters/tutor/test_prompts.py` and provider request-construction tests where needed.

**Interfaces:** Use existing `load_prompt(reference, root=PROMPTS_ROOT)` and route prompt references. No score-schema or JudgePacket changes. Calibration YAML has top-level `version: 1` and `cases`; each case has `id`, `scenario_id`, `candidate` (normal tutor payload), `expected_scores` (subset of mathematics/help_level/diagnosis/tone), `rationale`, `review_status` (`proposed` or `user_confirmed`), `assessment_source` (`judge_packet` or `trace_review`), and `expected_engine` (`accepted`: bool, `reason`: null or RejectionReason member name).

- [x] Create seven authored synthetic examples grounded in existing scenarios: useful factor-pair hint (help 2, user-confirmed), a leaked root below permission (help 0, proposed), direct corrected-work explanation (help 2, proposed), unnecessary rework of the correction (help 1, proposed), a concrete multiplication after vague hints (help 2, proposed), another vague repeated hint (help 0, proposed), and an unsupported claim of successful verification (trace-review only, empty expected scores, proposed). Labels beyond the explicitly agreed case require human review; never label them user-confirmed merely because the general principle was agreed.
- [x] Validate unique IDs, referenced scenario existence, candidate shape, score names/range, review statuses and nonempty rationale. `trace_review` entries have empty expected scores because the present judge packet lacks tool evidence. Use `parse_turn` for structurally valid authored candidates. Specify expected engine acceptance for legal replies, including unhelpful ones; specify `{accepted: false, reason: ANSWER_LEAKED}` for the deliberate leaked-root example. A rationale alone is insufficient to identify a deliberately rejected case.
- [x] Prepare each example through the production replay and call `validate_turn(candidate, context, graph, verifier)`. Assert positive examples pass and the leak is rejected for exactly its declared reason. Fail for missing tutor opportunities or gate mismatches before any judge call. If a preferred explanation is rejected, revise the example within the current rules or report the conflict explicitly; do not bypass the gate or change domain policy in this task.
- [x] Add tests resolving both v2 prompt IDs and constructing provider tutor/judge requests with exactly the selected policy text. Confirm initial tests fail because v2 files are absent; no calls or keys are needed.
- [x] Write tutor v2 from v1, implementing every agreed rule in the spec and Task 2's inconclusive-check guidance. Preserve current-state authority, scoped history, data/instruction separation and leak restrictions. Replace the unconditional teenage-student assumption with age-neutral accessible language. Do not require all replies to end in questions or full-reveal permission to result in full solutions.
- [x] Write judge v2 from v1, with the explicit cumulative ladder and criteria for actual usefulness, concrete progression, explanation-only replies and legibility. Preserve exact seven-key score output and abstention semantics. Do not infer tool verification from a packet lacking the tool result, and do not grade by matching preferred wording.
- [x] Prepare an ignored local copy at `eval/runs/tutor-quality-v2/routes.yaml`: preserve all existing route settings and change only `tutor_math@1` references to `tutor_math@2` and `rubric_judge@1` references to `rubric_judge@2`. This is the explicit candidate configuration for dry runs; preserve the checked-in YAML. Later comparison arms use separate copies with judge v2 fixed and tutor prompt version selected explicitly.
- [x] Run `.venv/bin/python -m pytest tests/adapters/tutor/test_prompts.py tests/eval/test_quality_calibration.py` plus affected request-construction tests. Review prompt meaning directly; avoid keyword-count tests presented as proof of teaching quality.
- [x] Verify v1 files and original `eval/fixtures/` bytes are unchanged, then commit candidate prompts and calibration data. Keep checked-in route references at v1.

### Task 4: Execute authored calibration candidates through the judge

**Files:** Create `src/learnai/eval/calibration.py`, `tests/eval/test_calibration_execution.py`. Reuse and extend `tests/eval/test_quality_calibration.py` from Task 3. Update `eval/README.md` with the command.

**Interfaces:** Define frozen `PreparedCalibrationCase(id: str, packet: JudgePacket, validation: ValidationResult, expected_scores: Mapping[str, int], review_status: str, assessment_source: str)` and `prepare_calibration(path: Path, *, scenarios: Mapping[str, Scenario], graph: SkillGraph, items: GeneratorRegistry, catalogue: Mapping[MisconceptionId, Misconception], verifier: Verifier, matcher: MisconceptionMatcher) -> tuple[PreparedCalibrationCase, ...]` in the new module. Move the Task 3 validation logic into this reusable function rather than maintaining test-only duplicate rules. Its packets come from existing `prepare_scenario` and `build_reference`. Define `main(argv: list[str] | None = None) -> int` as the standalone module entry point; no changes to the existing evaluation CLI are required.

- [x] Add offline preparation tests: exact exercise/work/revision/history from production replay reach each packet; preferred examples pass the engine; a known leaked root fails with `ANSWER_LEAKED`; a deliberately mismatched expected gate result and a completed/no-opportunity scenario fail the whole preparation. Snapshot prepared contexts/history before and after to verify no candidate is delivered or recorded. Run the new tests before implementation to confirm the missing function fails.
- [x] Implement preparation with strict YAML validation from Task 3, including rejecting unknown keys, booleans posing as scores and inconsistent expected acceptance/reason pairs. Return both gate-accepted and explicitly gate-rejected evaluator cases, retaining their actual ValidationResult. Do not call `request_validated_turn` to deliver or repair authored candidates.
- [x] Add `--calibration` (required Path), `--routes` (Path, repository route default), `--judge-route` (default `rubric_judge_openai`), `--out` (default `eval/reports`) and `--dry-run`. Dry-run prepares all cases and validates the selected judge route/prompt configuration without credentials, clients or network. Test absent keys and network/client traps. Live mode validates all cases and output writability before creating any clients; use existing `ProviderServices` with `resolve_operation_routes(..., rejudge=True)` and no tutor dependencies, plus its judge trace ledger and existing request preparation.
- [x] With a fake Judge/provider factory, verify one evaluation per `judge_packet` case and zero for `trace_review`; no tutor construction; accepted and rejected authored candidates retain their exact prose. Inspect outgoing judge messages to ensure expected scores, rationale, review status and gate outcomes are absent. Preserve existing `JudgePacket`/score schemas.
- [x] Test agreement calculation: compare only specified dimensions for user-confirmed labels; report proposed labels separately. Abstentions, JudgeErrors and manual-only entries have explicit statuses and denominators. No aggregate teacher-quality claim follows a passing fake judge.
- [x] Write unique private calibration artifacts with the distinct envelope in the spec, using existing encoding/canonical hashing and a base source/configuration manifest. Store calibration content/hash and case snapshots in the enclosing fingerprint material; changing a candidate or label changes that fingerprint. Persist completed per-case results incrementally with final status on error/interrupt, raw usage/traces, and client cleanup. Test a second-case failure and interruption preserve the first result; reruns never overwrite; fingerprint excludes generated output/time/IDs. This is an additional artifact kind, not an extension of normal run/rejudge report schemas.
- [x] Run `.venv/bin/python -m pytest tests/eval/test_quality_calibration.py tests/eval/test_calibration_execution.py`, then `.venv/bin/python -m learnai.eval.calibration --calibration eval/calibration/tutor_quality_v2.yaml --routes eval/runs/tutor-quality-v2/routes.yaml --judge-route rubric_judge_openai --dry-run`; confirm no provider calls. Document the paid invocation separately, then commit.

### Task 5: Verify admission and document the comparison gate

**Files:** Modify `tests/eval/test_provider_admission.py`, `eval/README.md`, and `docs/superpowers/notes/2026-10-28-openai-live-pilot.md`. Add an implementation handoff under `docs/superpowers/notes/` when execution is actually complete.

**Interfaces:** Use existing provider factories, `prepare_tutor`/`prepare_judge`, `load_saved_run`, `run`, `rejudge`, and `compare`. Select v2 through local YAML copies preserving route models, effort and budgets. Do not extend comparison eligibility or artifact schemas.

- [x] Parameterize actual eligible-corpus admission over v1/v2 policies, both providers and checked-in/fallback profiles. Build real production payloads including updated tool descriptions; assert all admit and retain at least 8,192 units after reserving the next maximum output. For this measurement, no client, network or SDK construction is allowed. Run `.venv/bin/python -m pytest tests/eval/test_provider_admission.py tests/eval/test_corpus_admission.py`.
- [x] If v2 exceeds headroom, shorten policy text while preserving requirements; do not raise budgets or remove difficult scenarios. Verify the final copy again.
- [x] Document the separate offline and paid gates below, including the fixed pilot ID, selected scenarios, explicit candidate prompt versions, incomplete cost accounting and the fact that tool honesty is reviewed from traces. Keep raw runs and `.env` ignored.
- [x] Run the full keyless suite: `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m pytest`. Require no failures; ordinary live tests remain deselected even with a local `.env`.
- [x] Run `git diff --check`; inspect the complete diff, verify v1/frozen fixtures unchanged, and record actual results in the handoff. Commit after checks pass. No paid calls or default promotion are part of this offline task.

## Subsequent paid evaluation: explicit authorization required

1. Review calibration labels before executing; retain unresolved disagreements.
   Run the new calibration command with `--dry-run` to verify exact contexts and
   engine outcomes. After paid authorization, omit `--dry-run` to evaluate the
   authored good and bad examples with judge v2. Review confirmed-label
   disagreements, proposed observations, abstentions and errors before using
   the judge for the tutor comparison. Calibration artifacts capture the YAML
   and its SHA-256 outside the ordinary manifest input allowlist.
   Optionally rejudge saved pilot `d3101f5d-36be-40a3-bef6-0f0517aea5ef` with judge v2 using
   `python -m learnai.eval rejudge ... --routes LOCAL_YAML --judge-route rubric_judge_openai`.
   This makes judge calls only. Compare score reasons with human expectations;
   do not demand all scores increase. Saved control-character replies remain
   unchanged historical candidates.
2. With an agreed run count/spend scope, run v1 and v2 tutor policies on the same
   final code, Luna settings, budgets and fixed judge v2. Use the ten pilot IDs
   plus the four preselected untouched cases in the spec; skip persona smoke
   for this focused comparison. Repeating samples is a separate explicit part
   of that paid scope, not an implicit unlimited rerun loop.
3. Review actual responses, failures, repairs, latency and usage, alongside
   uncalibrated/confirmed score distinctions. Check the same criteria for both
   arms. Never silently exclude failures from the conclusion.
4. Existing `compare` will report prompt differences; preserve that caveat.
   Record the intended treatment and all actual differences in a paired review.
   Do not call a run with changed source/judge/fixtures a controlled tutor-only
   comparison. The new v1 arm is the contemporary baseline.
5. Decide whether v2 deserves default promotion or needs revision. If approved,
   update the applicable YAML prompt references and relevant cache-key naming
   consistently in a separate change, then rerun offline routing/admission tests.
   No automatic production rollout follows a better average score.

## Plan self-review

All design requirements map to Tasks 1–5 or the explicit subsequent paid gate.
Both provider paths, exact text preservation, tool uncertainty and immutable
history are covered. Teaching quality remains a human/live review question;
scripted tests prove only executable contracts. The plan intentionally defers
new dialogue state, answer-set tooling and changes to comparison eligibility.

Critical review follow-up (2026-10-29): Task 4 now provides an actual execution
path for authored calibration examples, separate from pilot rejudging. Tasks 3–4
require real engine gate results for every candidate and explicit expected
rejections for negative cases. Calibration provenance, partial results and
expected-label isolation are specified to make the new path reviewable.
