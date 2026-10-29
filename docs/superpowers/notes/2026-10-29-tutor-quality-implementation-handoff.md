# Tutor quality implementation handoff — 2026-10-29

The five implementation tasks are implemented and offline verification is
recorded below. The whole-branch review requested one test-isolation fix; that
change and its verification are recorded below. Scoped rereview of the fix
remains pending. Teaching-quality acceptance, further paid execution, default
promotion and deployment remain separate, unexecuted gates.

Workspace: existing `LearnAI-worktrees/plan-phase2a-tutor` linked worktree, branch
`feat-tutor-quality-refinement`. Initial revision:
`99d79de2a39aa318f6a07c93f25c73071b26930c`. Documentation baseline: `40358aa`.
See the [design](../specs/2026-10-28-tutor-quality-refinement-design.md),
[plan](../plans/2026-10-28-tutor-quality-refinement.md),
[pilot evidence](2026-10-28-openai-live-pilot.md) and
[operator gate](../../../eval/README.md#authored-calibration-and-the-tutor-quality-comparison-gate).

## Implemented behavior

- `ca105a4`: shared `parse_turn` rejects C0 controls except TAB/LF/CR, DEL and
  C1 controls, preserving valid text exactly. Both provider adapters use existing
  bounded format-repair paths; rejected drafts stay in private traces and are
  never delivered. This is neither retroactive artifact cleanup nor browser
  sanitization.
- `69eb7f6`: canonical `check_expression` guidance distinguishes supported
  expression/relation equivalence from unsupported brace-delimited root sets
  and active-item answer-field grading. `expression_uncheckable` remains
  inconclusive; error transport and existing supported checks are covered.
- `0e232dc`: candidate `tutor_math@2` / `rubric_judge@2` preserve the engine's
  authority and cumulative help ladder, address the actual question, permit
  useful explanations without compulsory questions, recognize corrections and
  favor meaningful progression over repeated vague hints. Separate authored
  calibration includes positive and negative examples with real replay/CAS
  validation and explicit expected rejections. `PreparedCalibrationCase` and
  `prepare_calibration` provide one production preparation interface.
- `8e6b490`: standalone `python -m learnai.eval.calibration` prepares the entire
  collection before clients, supports a keyless dry run and executes only the
  selected judge when authorized. Expected labels, rationale, review status and
  actual gate outcomes stay outside judge messages. Private incremental
  `kind: tutor_calibration`, `schema_version: 1` artifacts include captured YAML
  and its hash, prepared cases, gate results, selected policy/settings,
  provenance, raw traces/usage, explicit statuses and agreement denominators.
  Proposed observations stay separate; `trace_review` remains manual-only.
  Original run/rejudge/compare schemas, readers and eligibility are unchanged.
- Task 5 extends actual production-payload admission across v1/v2, Anthropic /
  OpenAI, and checked-in / fallback budgets using local policy YAML copies.
  Configured models, effort and budgets are preserved across policy versions;
  actual updated checking-tool descriptions are included. Operator instructions
  now distinguish offline completion from the later paid comparison gate.

## Offline evidence

The controller's initial keyless baseline was `1670 passed, 4 deselected in
138.83s`. Scoped task evidence: Task 1 `168 passed in 6.81s`, Task 2
`130 passed in 2.61s`, Task 3 `262 passed in 3.21s`, Task 4
`62 passed in 6.83s`; each implementer recorded its actual RED/GREEN evidence in
the private coordination workspace. Task 5 adds verification tests and operator
documentation, with no production implementation or policy shortening required;
its first expanded admission run passed, so it has no missing-feature RED phase.

Task 5 focused command:

```sh
.venv/bin/python -m pytest tests/eval/test_provider_admission.py tests/eval/test_corpus_admission.py -s
```

Result: `11 passed in 6.66s` (exit 0). The original 71 scenarios yield 54 actual
tutor opportunities, all with response job NORMAL; this does not establish
whole-corpus coverage of other response jobs. Eight version/provider/profile
combinations prepare all 54 tutor and 54 judge requests (864 preparations).
SDK import, client creation and socket construction traps remain active during
measurement; a fresh process also verifies SDK-free admission-module imports.
The serialized payload is recounted with the production conservative counter.

Minimum remaining units after reserving the next maximum output, identical for
checked-in and fallback profiles:

| Policy | Provider | Tutor | Judge |
| --- | --- | ---: | ---: |
| v1 | Anthropic | 8,827 | 16,454 |
| v1 | OpenAI | 9,019 | 16,278 |
| v2 | Anthropic | 8,402 | 15,119 |
| v2 | OpenAI | 8,594 | 14,943 |

The largest payload is `ladder-long-conversation` in every arm. The tightest
margin exceeds the required 8,192 by 210 units; no budget increase, removed
scenario or policy shortening was needed. These conservative admission units
are not provider token counts or a guarantee that arbitrary future history fits.

Standalone dry run:

```sh
.venv/bin/python -m learnai.eval.calibration \
  --calibration eval/calibration/tutor_quality_v2.yaml \
  --routes eval/runs/tutor-quality-v2/routes.yaml \
  --judge-route rubric_judge_openai --dry-run
```

Result: `{"status": "dry_run", "judge_route": "rubric_judge_openai", "judge_cases": 6, "manual_review_cases": 1}`
(exit 0). This validates engine outcomes and composition without evaluating
teaching quality.

Full keyless command:

```sh
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m pytest
```

Result: `1824 passed, 4 deselected in 133.74s (0:02:13)` (exit 0), with no
failures or warnings. The four ordinary live probes stayed deselected; this
repository does not load local `.env` files. Existing live-selection regressions
also cover dummy provider keys and explicit provider-marker selection.

`git diff --check` passed, the complete Task 5 diff was inspected and local
documentation links resolve. No full-suite repetition was needed after the
passing run; subsequent changes only record results in documentation.

## Whole-branch review fix verification

The review found one Important issue: `test_calibration_execution.py` depended
on ignored `eval/runs/tutor-quality-v2/routes.yaml`. The earlier workspace suite
result above did not prove clean-checkout reproducibility. Commit `ab4f7c9`
replaces that dependency with a `tmp_path` route fixture derived from tracked
`config/llm_routes.yaml`, substituting only v2 prompt references. Every CLI
helper call and configuration-mutation test receives the path explicitly.
In-process open guards and a subprocess audit hook reject access beneath
repository `eval/runs`, so an existing private file cannot mask a regression.
No production code or operator route file changed.

Before the fixture fix, the guarded execution module failed as expected with
`12 failed, 1 passed in 6.17s`; failures identified ignored-route access in
the main process, subprocess, and mutation tests. After the fix, the same
keyless command passed: `13 passed in 8.62s` (exit 0):

```sh
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m pytest tests/eval/test_calibration_execution.py
```

A Git archive of committed `ab4f7c9` excluded ignored/private files but lacked
revision metadata: `2 failed, 1822 passed, 4 deselected in 129.88s`. Both
failures were existing mixed-provider controlled-comparison tests reporting
only `unknown source revision`. A clean local clone of the same commit retains
the required provenance. Those two tests passed there (`2 passed in 4.74s`)
without any code changes.

The clone is `/private/tmp/learnai-final-fix-vstakiix/clone`, created with
`git clone --local --no-hardlinks --single-branch`; no linked worktree or
dependency installation was needed. Before testing, its Git status was clean,
HEAD was exactly `ab4f7c9f71606b388814a3c975fb06ad47a99d8d`, and `eval/runs`,
`.env`, `.venv`, and the current private coordination folder were absent.
Explicit import assertions verified `learnai` and calibration under the clone's
`src` and the execution tests under its `tests`, overriding the original venv's
editable source with `PYTHONPATH`.

Full keyless command from that clone:

```sh
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY PYTHONPATH=/private/tmp/learnai-final-fix-vstakiix/clone/src /Users/adrianseguralorente/LearnAI-worktrees/plan-phase2a-tutor/.venv/bin/python -m pytest
```

Clean-clone result: `1824 passed, 4 deselected in 128.74s (0:02:08)` (exit 0),
with no failures or warnings. The ordinary live probes remained deselected.
Scoped rereview of this fix remains pending; paid quality acceptance and
promotion remain separate gates.

## Preservation and privacy

`git diff --exit-code 99d79de --` over both v1 prompt files, `eval/fixtures/`,
`tests/fixtures/eval_v1/run/`, `config/llm_routes.yaml`, the shared runtime budget
source, `src/learnai/domain/` and `pyproject.toml` passed. V1 prompt SHA-256 values:

- `prompts/tutor_math/v1.md`:
  `ce5a46df811ce5d59982f36046db5f3df8b5377e3fbc3d0c7f30020f20d7d44c`.
- `prompts/rubric_judge/v1.md`:
  `b79fe63ca00b2950864f65f3cde0a99b7b216d63314d62974a1a724fbc285ac8`.

The pilot `d3101f5d-36be-40a3-bef6-0f0517aea5ef` loads through `load_saved_run`
with 19 request records and nine judge packets; the frozen v1 fixture loads as
schema 1 with one request and one packet. A private before/after SHA-256 snapshot
covers 159 pilot and frozen-v1 artifact files. The after-check passed: all 159
were byte-identical, with no added/deleted files. Saved control-character
responses remain historical bytes.

`git check-ignore` confirms root `.env`, candidate local routes and pilot raw
artifacts remain ignored. No credentials or `.env` content were accessed, no
paid calls were made and no defaults were promoted during this implementation.
No dependencies/SDKs/models/budgets, domain permissions/mastery, CAS capability,
UI, pricing snapshot, session detours or deployment were changed.

## Controller rulings retained

These decisions come from this plan's local progress ledger; they do not change
the later quality/promotion gate:

- Keep the existing linked worktree, create local
  `feat-tutor-quality-refinement`, and commit approved documentation/ignore
  changes as the implementation baseline. This protects the pushed migration
  branch and preserves authored decisions; an incorrect choice costs reversible
  local branch/commit cleanup. Implementation proceeds sequentially where tasks
  share provider test files.
- Use the existing Python 3.12 venv without installing Poetry: packaging uses
  Hatchling and dependencies already exist. Any correction is local dependency
  work, not an authorized dependency upgrade.
- Move reusable `PreparedCalibrationCase` / `prepare_calibration` construction
  into Task 3 for its real-gate tests. Task 4 consumes that unchanged production
  helper for CLI/runner/artifacts, avoiding a duplicate test-only loader; a wrong
  boundary would need only bounded task rework.
- Judge v2 covers accepted replies and evaluator-authored undelivered drafts
  without being told gate outcomes, resolving the conflict between
  accepted-only wording and negative calibration. Exact authored text still
  passes the shared parser; intentional engine rejections stay evaluator-only,
  never delivered or added to history. The engine is never weakened.
- Keep the planned standalone calibration module with explicit helper
  boundaries despite a projected roughly 400 lines; line count alone does not
  justify a new abstraction. It finished at 314 lines. A necessary correction
  would be a focused split before final acceptance.
- Preserve raw rejected traces, canonical error codes and existing verification
  capability. Tool evidence is absent from the judge packet, so trace review
  stays manual. Updated tool descriptions must be part of real admission
  payloads. Candidate v2 uses private local YAML; checked-in defaults stay v1.
- Keep calibration artifacts distinct without existing-reader/schema changes.
  Run focused checks per task and reserve the full suite for Task 5. No
  additional paid execution is authorized. Task 5 owns final frozen-byte,
  unchanged-default/budget and whole-corpus headroom checks.
- Tasks 1–4 scoped reviews were clean. Task 1 preservation/privacy evidence was
  accepted, with final budget/admission checks assigned here; Task 2 had no
  changed default/artifact/budget sources; Task 3 preservation was accepted;
  Task 4's unchanged-preparation item was resolved through the completed Task 3
  review and combined 62-test evidence. The subsequent whole-branch review
  requested the test-isolation fix recorded above; scoped rereview of that fix
  remains pending.
- Verify the final fix in a clean local clone with Git metadata. Controlled
  comparisons intentionally reject an unknown source revision, and the clone
  must still exclude ignored files. A wrong choice costs an extra local
  verification run and temporary disk use; an archive-only failure does not
  justify a second code-fix wave.

## Remaining paid quality and promotion gate

Review labels and retain unresolved disagreements before judge-v2 paid
calibration. Review actual confirmed-label disagreements, proposed observations,
abstentions and errors before relying on scores. Optional pilot rejudging is
judge-only and preserves old candidates. The private candidate configuration
selects v2 policies but retains Anthropic tutor defaults; construct explicit
Luna comparison arms before tutor execution.

After agreeing sample count/spend, compare new `tutor_math@1` and `tutor_math@2`
arms on the same final source, Luna low-effort settings and unchanged budgets,
holding `rubric_judge@2` / Sol low fixed. Use the ten pilot IDs plus the four
preselected untouched cases: `diagnosis-square-1-help`, `extra-nonmonic`,
`ladder-after-rejected-help`, `leak-word.area`. Skip persona smoke. Repeated
samples need explicit paid scope. The operator guide contains the exact ordered
fourteen-case list and invocation forms.

Review responses, failures, repairs, mathematics, useful progression, latency,
usage and disagreements under the same criteria for both arms. Tool honesty
requires traces; the judge cannot infer unseen successful checks. OpenAI cost
coverage remains incomplete; zero known cost is not free use. Preserve
`compare`'s prompt-difference caveat and document all actual differences in a
paired review. Changed source/judge/fixtures or returned judge models prevent a
controlled tutor-only claim. The new v1 arm is the contemporary baseline;
the original pilot is historical evidence.

Human review must decide revision or default promotion. Promotion requires a
separate explicit change to applicable YAML prompt references and cache-key
names, followed by offline routing/admission checks. No aggregate score target
replaces examining actual responses or proves learning gains. No automatic
rollout follows a better average score.
