# Plan 2A implementation handoff — 2026-10-26

## Provider extension status — 2026-10-27

The provider-neutral/OpenAI extension is implemented and keyless verified on local
branch `plan-openai-provider`. All eight tasks have scoped reviews. Whole-branch
review identified an Important judge-scope boundary gap and a Minor nonfinite
timing gap; both are implemented in one final fix wave, pending scoped re-review.
See the [current provider handoff](2026-10-27-openai-provider-implementation-handoff.md)
for final verification, immutable-artifact guarantees, limitations and the complete
provider decision ledger. No push, merge, publication or paid model call has run.
The sections below retain the earlier Plan 2A baseline and Task 8 evidence.

Both providers now support independent tutor/judge selection through the same
engine/evaluation contracts. Defaults remain Anthropic; `tutor_openai` and
`rubric_judge_openai` are named examples that require explicit selection. Real
model identifiers remain only in `config/llm_routes.yaml`. See the
[operator guide](../../../eval/README.md) for installation, per-job tutor activation,
independent `--judge-route`, subset/no-smoke runs, judge-only rejudge credentials,
and read-only comparison. `compare --tutor-treatment tutor_dialogue` declares a
tutor experiment; `--allow-tutor-dependency-changes` cannot waive a shared judge
dependency change. Both current SDKs use `httpx2`.

OpenAI is pinned at `openai==3.39.0` in the OpenAI/dev extras, with native
`httpx2==2.16.0` verified locally. Anthropic stays in base dependencies. Selected
roles alone require keys/packages; all selected roles preflight before any client.
Operation-owned clients close after use; injected clients remain caller-owned.
Artifacts write v2; immutable v1 inputs adapt read-only. Provider-aware cost
estimates retain known subtotals and explicit missing counts/rates/conditions;
returned/requested/default/unknown condition provenance stays visible. The current
price snapshot supplies no OpenAI rates, so OpenAI costs are incomplete.

The 71 original fixtures and 54 tutor opportunities remain unchanged. Full-corpus
production admission retains the original output/time/tool/round budgets and
8,192 units of required continuation headroom. Limiting Anthropic tutor/judge
margins beyond the 2,048 output reservation are 9,043/16,454 units; corresponding
OpenAI framing margins are 9,346/16,347. Named route/settings activation requires
rechecking admission. Task 7 also fixed initial-context foreign-history scope
filtering without changing domain pedagogy or mastery policy.

Exactly four live cases are collected, two per provider; explicit no-key selection
skips all four. Ordinary/default provider-marker selection excludes live cases,
even with both keys set. Paid commands require explicit authorization and
`-o addopts='' -m 'live and PROVIDER'`. **No paid live probe, paid corpus evaluation,
latency acceptance, reviewed live reference summary or human judge calibration
has been executed.** The OpenAI cache minimum for selected tools/schema/effort is
not established by the current guide; the probe requires observed repeat reads
and never treats a miss as proof of prompt leakage.

OpenAI continuation stays local with `store=false`, ordered encrypted-reasoning
and function-result replay. This does not override provider caching/retention
policy. Delivery stays buffered until deterministic engine validation. Private
operational artifacts remain ignored; the fixed synthetic v1 compatibility
fixture is the explicit test-data exception. No arbitrary traces or credentials
are committed. Task evidence is in
`.superpowers/sdd/2026-10-26-provider-neutral-evaluation-openai/`; compatibility and
source snapshot details are in [the OpenAI note](2026-10-26-openai-provider-compatibility.md).

Historical Task 8 keyless verification (2026-10-27; superseded by the current provider handoff):

- `env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY .venv/bin/python -m pytest` —
  **1,547 passed, 4 deselected in 79.57s** after the compatibility fixes.
- Explicit `live` collection lists **4 cases**; explicit execution with both
  keys removed yields **4 skipped**. Dummy-key default/provider-only checks use
  collection only. All seven selection regressions pass.
- Domain/import boundaries and both-provider full-corpus admission —
  **12 passed in 3.89s**, with the unchanged margins above.
- Final source wheel built with `--no-index --no-deps --no-build-isolation`;
  base/optional/dev metadata, offline target installation and SDK-free CLI help
  verified. Detailed evidence and earlier resolved failures are recorded in
  `.superpowers/sdd/2026-10-26-provider-neutral-evaluation-openai/task-8-report.md`.

## Plan 2A baseline status

The fifteen planned tasks are implemented and independently reviewed for the authorized keyless scope. The final whole-branch review identified two Important evaluation integration gaps; one fix wave addressed both and scoped re-review approved them. The work remains on local branch `plan-phase2a-tutor`; nothing was pushed or merged.

This is not full live acceptance of Plan 2A. Provider compatibility/cache behavior, measured latency and teaching quality, human content review, and judge calibration remain pending separately authorized paid execution and human review.

## Verification and review

- Fresh controller verification: `env -u ANTHROPIC_API_KEY .venv/bin/python -m pytest` — **1,219 passed, 2 deselected in 48.84s**.
- Explicit collection selects exactly two live tests. Keyless explicit execution skips both; ordinary collection excludes them even when a dummy key is present. No paid call ran.
- Corpus: **71 fixtures, 54 actual tutor opportunities**, including 15 ladder and 12 diagnosis opportunities (two per supported signature). The 17 expected non-tutored operations remain separate regressions.
- Production-counter admission covers every eligible tutor context and judge packet with continuation headroom. Context allowances are now brief16,000, normal40,000, substantial48,000, complex64,000; output and latency ceilings are unchanged.
- Final code/docs fix commits: `f9d5c87`, `00b2cb5`. Per-task and final review evidence remains in `.superpowers/sdd/2026-10-16-slice1-plan2a-tutor-eval/`.
- Whole execution whitespace check reports one cosmetic extra blank line at `tests/eval/test_runner.py:283`; it is deferred, not a functional failure. Optional parser test additions from Task6 remain deferred too. No Critical or Important review finding remains open.

## Resume and boundaries

Read `.superpowers/sdd/2026-10-16-slice1-plan2a-tutor-eval/resume.md` and `progress.md` before resuming. Preserve the linked worktree and ignored generated reports. See [eval guide](../../../eval/README.md) for CLI run/rejudge/compare, privacy, accounting and opt-in live procedures. Local integration is still the user's decision; no merge, push, publication or paid run is authorized by this handoff.

Durable persistence, authenticated service boundaries, cross-session history, strict CAS isolation and proposal execution remain Plan2B work. UI/progress and validated streaming remain later work. The implemented API buffers responses until engine validation.

## Rulings I made

The following is the complete ordered export of ledger entries containing `Ruling:`. Original rationale and stated costs are retained. For entries without a specific cost, the cost if wrong is localized implementation/configuration rework plus repeating the affected verification; these decisions do not establish live acceptance.

1. Ruling: Preserve existing revision field names on planned dataclasses while documenting work_revision semantics; same-revision raw steps/answer equality is mandatory — names are already used in the plan’s cross-task interfaces — changing them later costs a mechanical migration.

2. Ruling: Task 1 defines the HistoryReader protocol (Task 5 implements it) and ResponseJob enum in interaction.py; an immutable context.history snapshot supplies the reader at begin_turn — resolves production/consumption order without provider imports in domain — wrong placement costs a small refactor.

3. Ruling: For Task 1 default ResponseJob and ask_question validation, BRIEF/NORMAL/SUBSTANTIAL are enabled and COMPLEX requires explicit opt-in; route binding starts Task 3/7 — engine job policy must exist before provider integration — wrong defaults cost configuration changes.

4. Ruling: The verification helper preserves existing answer/step/form-diagnosis behavior; draft questions may request step checks but never final grading evidence — existing engine is authority over new corpus assumptions — wrong extraction risks grading drift, covered by parity tests.

5. Ruling: A delivered task reply creates one assistance fact even if multiple history-view records refer to it; ladder advancement and independence flags updated once — transcript/help views must not double-count delivery — wrong handling costs incorrect replay counts.

6. Ruling: ScenarioOutcome gains an exact captured context field in Task 11 despite the abbreviated old positional signature omitting it; engine-created/eval outcomes retain context when an exchange occurred — Task 12/13 require it — wrong optionality costs a constructor update.

7. Ruling: Task 13 ledger sink hooks may be introduced as backward-compatible optional dependencies in Tasks 7/12 then completed in Task 13; no later-owned ledger imports in domain — task order stays executable — wrong choice costs adapter integration refactoring.

8. Ruling: Task 13 tests CLI with --no-smoke until Task 14; Task 14 adds complete smoke/ledger integration — plan sequential order takes precedence over historical “either order” prose — wrong order costs an import failure.

9. Ruling: SDK/model compatibility and current billing semantics are verified from official docs when the corresponding tasks begin; illustrative model identifiers are not API promises — plan explicitly defers those facts — unsupported combinations require route/schema changes.

10. Ruling: Baseline and task commits use explicit tracked paths; no push/merge/publish. The user invoked a workflow that specifies local commits — keep reviews concrete and preserve documentation baseline — mistaken scope costs a reversible local commit.

11. Ruling: Use exact enabled_response_jobs constructor name from Task 3, default BRIEF/NORMAL/SUBSTANTIAL; COMPLEX explicit opt-in — resolves task brief cross-reference omission — alternate name would cost a rename.

12. Ruling: Add defaulted Task.last_verification to preserve findings tied to work revisions; expose only matching current-revision findings — state must retain checked results across requests without rediagnosing history — wrong shape costs a small state migration.

13. Ruling: No new interface-guidance engine API in headless 2A; predefined UI guidance remains application-owned for 2B/2C. Test the actual free-form boundary with delivered assessed-terminology assistance and timed-question refusal, not a vacuous no-action UI test — no implemented UI exists to exercise — wrong scope costs one later application test.

14. Ruling: Add HistoryKind.HELP_REQUEST for explicit textless help requests, retain typed interaction/history even on silence, do not fabricate student prose — provenance otherwise disappears or is mislabeled as a question — old full-session equality expectations for silent help must instead assert unchanged assessment/assistance and recorded request. Malformed submissions retain their no-state-change guarantee.

15. Ruling: HistoryReader protocol is read(scope: HistoryScope, query: HistoryQuery) -> HistoryPage, per Task 5. Scope is supplied from context by application code, never model arguments — prevent incompatible protocol implementation — read(query) would require downstream rewrite.

16. Ruling: Task3 resolves placeholder models/settings using current official docs; use Opus5.5 adaptive, omit sampling temperature, effort brief low/normal medium/explanation high/judge high/reserved diagnosis xhigh. Reference provider-compatibility-notes.md — supported current API and latency-sensitive job defaults — eval may change model/settings later; no live compatibility claim. New model forbids forced tool choice, so Task7 uses supported schema final text/auto tool handling rather than forcing a submit call.

17. Ruling: Controller performs future task staging/commits after implementer report, using explicit task-owned paths and approved escalation — child approval waits were not visible/responsive and cost several minutes — changing commit actor has no code consequence; task review remains mandatory.

18. Ruling: Mandatory protected content plus policy/skill/framing must fit or ContextLimitError. Earlier task raw groups/summaries are optional ranked selections within remaining budget; do not require every omitted group’s summary — prevents unbounded older history causing silence despite fitting active work — omitted originals remain retrievable, and included summaries preserve correction timeline/provenance. L3 may be omitted without useful stable profile.

19. Ruling: Actual HistoryReader protocol is in domain/ports.py; use it unchanged despite planned history.py location — Task1 chose cycle-safe protocol location — no runtime consequence.

20. Ruling: check_expression(expression, reference=None) supports equivalence-only intermediate checking via verifier.diff_steps when reference is supplied, and explicitly scoped active-item answer/form checking otherwise. Unreadable is cannot-check/error, never false — tutor needs checking beyond final-answer grading and must not confuse equivalence with form acceptance — extra optional argument is small backward-compatible surface. Both modes read only.

21. Ruling: Installed/current Anthropic SDK2.3.0 uses httpx2.Client, not httpx.Client (inspected constructor); httpx2.MockTransport exists. Task7 uses native httpx2 transport and declares appropriate dependency (anthropic~=2.3.0, httpx2 compatible dev range), replacing stale httpx transport assumption — current SDK compatibility takes precedence — dependency change may need adapter update on future major upgrades. No paid API call made by installation/inspection.

22. Ruling: For current always-adaptive provider with no forced tool choice, Task7 can finalize via structured JSON text with auto/none tool choice rather than forcing submit_turn. At soft budget, disable exploration without editing prior provider history/schema context incompatibly; tool_choice none plus unchanged schemas and JSON final format is acceptable — current provider support overrides historical transport assertions — scripted tests must prove same final validated turn and shared budget, not unsupported API shape.

23. Ruling: No prior real adapter exists, so Task7 defines events_seen as ordered raw event/block dictionaries and usages as SDK Usage records; consumers normalize via actual types in report. Optional sleeper injection supports deadline-aware fake backoff tests — preserves intended trace/usage seams without inventing an obsolete adapter — later report code must consume actual interface.

24. Ruling: Delivered HistoryRecord is insufficient for exact historical engine replay (confidence, original template/seed and private validation attempts omitted). Add evaluator-only history_actions tuple of frozen HistoricalAction(operation submit|ask_question|request_help, at aware UTC, task_id, template_id, seed, interaction=None, confidence=None, response_job=NORMAL, tutor_script tuple[TutorTurn|None]=()). Submit requires SUBMISSION interaction + explicit confidence; ask_question TASK_QUESTION; request_help uses stored work, interaction=None. Matching task ids, stable template/seed per task, nondecreasing times. No check_steps switch: engine owns it. Historical tutor drafts/None remain private script inputs, not delivered history; replay checks script consumption and rejects unspecified responses when engine called — enables real deterministic replay without fabricating missing facts — adds fixture-only schema complexity, no production domain changes.

25. Ruling: Scenario.now default2026-01-01T00:00:00Z, bound ids default eval-student / eval-session:{id} / eval-task:{id}, optional explicit top-level overrides; histories cannot choose actor identity. Current confidence defaults Confidence.UNSURE; historical submit confidence explicit. now >= historical timestamps. Starting strength/is_fresh/calibration/prior-misconceptions seed initial learner state at earliest action (or now absent history); replay/current engine operations derive actual current summary. Supplied history/transcript/progress/expected findings assert derived results, never set counts/findings — resolves original snapshot-vs-replay ambiguity in favor of actual engine semantics — authored fixtures must account for preceding evidence updates. Task9 parses; Task10 builds replay/preflight, Task11 executes real current tutor.

26. Ruling: Task10 may add focused eval/replay.py and eval/corpus.py modules; keep fixtures.validate_corpus thin delegation and avoid putting engine orchestration into the648-line schema loader — each module one responsibility and Task11 reuse — wrong factoring costs a localized refactor. Fix Task9 minor mixed-key error contract locally with a regression while touching loader.

27. Ruling: PreparedScenario capture includes actual current operation’s recorded student event in redundant history/transcript assertions; malformed adds none, correct may advance cursor, retain original task by id. context=None means no tutoring opportunity and fixture permitted_rung=NONE; report expected non-tutoring separately from operational silence. Task11 build_context may return TurnContext|None to represent this legitimate case instead of fabricating a tutor opportunity.

28. Ruling: Task11 fixes confirmed adapter missing-prompt silent fallback with a focused regression (explicit live tutor prompt requirement from Task3/7), without changing reserved configuration parsing. Extend owner file only for that defect/necessary request-local trace seam — prevents configuration/provenance drift before eval runner integration — localized startup compatibility correction.

29. Ruling: Task12 may split provider-specific judge transport into adapters/tutor/anthropic/judge.py; eval/judge.py owns frozen packet/reference/scores and strict parsing/public wrapper. Optional per-call trace_sink retains raw attempts/usage for Task13 without global last-trace state — maintains provider boundary and focused modules — localized API extension costs small extra surface.

30. Ruling: Task13 dated model-keyed pricing can live as an additional section in config/llm_routes.yaml, parsed by accounting separately, preserving sole-model-id-location constraint. Official pricing/caching pages checked2026-10-26; notes task-13-provider-pricing-notes.md. Only standard direct API conditions priced unless supported modifiers explicitly handled; unknown billing conditions incomplete.

31. Ruling: Task13 may add artifacts.py for explicit allowlisted typed roundtrip serialization and reference.py for independent verified JudgeReference construction, plus minimal shared runtime per-attempt timing/returned-model sink metadata — separates persisted schema, reference ownership and orchestration without huge modules — added surface covered by roundtrip/exactly-once tests. Artifact loader must never import arbitrary artifact-selected Python types.

32. Ruling: Task15 may add pytest pythonpath=["."] while configuring live exclusions, because existing cross-test helper imports fail under direct .venv/bin/pytest (module invocation worked); makes documented direct commands reliable — changes test import resolution only — wrong choice costs localized config revert.

33. Ruling: Finalfixwave may revise provisional context admission allowances and matching fallback defaults/docs based on measured wholecorpus production-counter sizes, preserving overflow guard/protected rawwork and latency/output ceilings — accepted-reply fixtures must be runnable by checked-in configuration, profile inputs were explicit engineering starting values — larger admitted contexts may cost more and require future latency/cost measurements.

34. Ruling: Finalfixwave preserves original55no-opregressions while adding real opportunities so diagnosis12actual/2each6signatures and ladder15actual familyfloors are meaningful; NONEcoverage is actual historical delivery, not an impossiblePRACTICENONEceiling — evaluatorfamilies should exercise modelratherthaninflate tagcounts — costs additional fixture/evalcalls whenpaidrunlaterauthorised.

35. Ruling: Preserve the SDD recovery workspace and linked worktree while integration/live acceptance remain pending, honoring user compaction preference rather than destructive scratch cleanup now — checkpoint and review evidence remain recoverable — costs local disk until deliberate cleanup.

36. Ruling: Defer cosmetic extra blank line at tests/eval/test_runner.py EOF and optional Task6 non-object-proposal/non-string-target coverage; no runtime defect or unresolved Important review finding — one final fix wave is complete and broad tests pass — costs a minor style cleanup and optional test additions later.
