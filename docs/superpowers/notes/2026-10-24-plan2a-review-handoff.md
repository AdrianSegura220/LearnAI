> **Implementation is now authorized and underway (current pointer updated 2026-10-26).** The earlier review-only
> scope below is historical. Resume from
> `.superpowers/sdd/2026-10-16-slice1-plan2a-tutor-eval/resume.md` and `progress.md`.
> Tasks 1–14 are implemented/reviewed; Task 15's keyless implementation is pending review.
> See [eval/README.md](../../../eval/README.md) for current scope and verification limits. Paid live execution and human calibration remain unverified. Trust the ledger and Git for latest state.

# Plan 2A review handoff

**Updated:** 2026-10-25
**Historical resume state (2026-10-25):** five original issues and final review refinements approved and recorded; the review-only task awaited the user’s next instruction. This historical section did not authorize implementation; the current pointer above supersedes it.
**Historical mode:** Discuss review points individually with the user; do not implement the plan within that earlier review-only task.

## Project and review objective

LearnAI is a generic learning platform for primary through high school/early university,
starting with mathematics. The headless Practice engine exists; Plan 2A adds a real tutor
and evals, 2B durable service/history, 2C UI. Read AGENTS.md and the current specs/plan.
The user authorized documentation edits recording the discussion, not product implementation.

## Agreed and recorded

- Preserve original context and accumulated provider tool exchanges across tools and
  corrective validation retries. One request-scoped TutorExchange owns one shared budget.
- Explicit current exercise, raw working, answer fields, question/reference, draft/submitted/
  revised status and revision. Verifier scope/revision and engine-computed task progress are
  authoritative. Draft questions do not create final-answer evidence or reveal effort.
- Delivered task-related assistance makes later answers on that item ASSISTED (weight 0),
  even if no hint rung advances. Silence/rejected drafts consume no independence. Prior cold
  evidence is immutable. Predefined interface-only guidance is exempt; ambiguous assessed
  terminology clarification is conservatively assistance. Post-instruction weight remains 0.1.
- Protect active work using token budgets/exercise boundaries; summarize earlier outcomes
  deterministically with provenance and retrieve original records on demand. Separate
  evidence, interaction history and private response traces. Current-session read-only
  retrieval in 2A; durable cross-session retrieval in 2B.
- Rebuild assessment state from evidence/rule versions; reconstruct tutor interactions from
  recorded inputs/tool results/validations/delivered outputs. LLM regeneration is not exact replay.
- Initial latency targets: brief 1–3 s, normal 3–8 s, substantial 8–20 s, exceptional 20–30 s
  with up to 60 s. Shared soft/hard execution allowances; no universal six-call cap. Numeric
  profile/token defaults in the plan are provisional engineering choices, not measured facts.
  Synchronous CAS isolation/strict wall-clock enforcement remains D17 in 2B.

## Final review refinements approved 2026-10-25

- Same work revision identifies identical raw steps/structured answer. Edits need a newer work
  revision; question-only changes retain it with distinct interaction ids. Reject conflicts early.
- History preserves typed skill/item/task/time/kind/revision metadata and related-record links.
  Filters are optional; session-wide browsing includes other skills. Bind each exchange to a
  reader of the full immutable history snapshot, independent of rendered context selection.
- ResponseJob travels through engine context into actual route/model/settings/profile selection.
  Brief/normal/substantial are configured; complex requires explicit enablement and route.
- Slice 1 already handles form-constraint diagnosis; extract and reuse existing preparation in
  engine/eval. No equivalence break is required for incomplete factoring. Correct submissions
  complete without tutoring; questions about correct work use explicit draft-question semantics.
- The retained parser snippet now guards enum types and rejects unknown nested proposal fields;
  add regression cases. This is planned code text only, not a product-source change.
- Task 10 checks no longer collect later tasks' tests; old estimated cost is not an acceptance gate.

## Files and verification

Uncommitted documentation edits:
- specs/2026-09-14-ai-tutoring-platform-design.md
- specs/2026-10-16-anthropic-tutor-eval-design.md
- plans/2026-10-16-slice1-plan2a-tutor-eval.md

Paths above are relative to docs/superpowers/. Affected inline task implementations were
replaced by concise interfaces, behaviors and checks; tasks remain 1–15. The original twelve teaching notes remain intact. Issue 4 deliberately replaces the five
inconsistent YAML corpus examples and wrong-only tests with explicit authoring/validation tasks.

Documentation checks passed: balanced fences, tasks 1–15 once/in order, retained
Python snippets parse (syntax only; snippet count changed after replacing Task 12), approved requirement coverage, removal of conflicting
history-loop/window instructions, and git diff --check. No implementation or live tests run;
no product source changed and nothing committed. AGENTS.md is an earlier untracked contributor
guide; preserve it. This handoff is also untracked until explicitly committed.

## Remaining discussion

1. Issue 3 resolved: exact student-moment packet, separate evaluator-only references, ceiling-based
   helpfulness, appropriate no-diagnosis, and explicit insufficient-evidence outcomes. Tasks 12–13
   record interfaces, prompt/schema tests and report integration. No product code executed.
2. Issue 4 resolved in documentation: generated statement anchors/copy-error cases, structured
   answer shapes, balanced verdict coverage, exact diagnosis expectations, event-derived progress,
   corrected CLI response ordering and keyless preflight. Tasks 9–13 specify the work; actual
   seeds/corpus checks await implementation. No claim that planned tests pass.
3. Issue 5 resolved in documentation: unique run id versus configuration fingerprint, captured
   inputs/dirty source, fixed-evaluator comparisons and rejudging saved outputs, shared per-attempt
   tutor/judge/smoke ledger, dated model/cache prices, incomplete estimates for unknown usage,
   coverage/latency/cost denominators and partial artifacts. Task 13 replaces obsolete report/CLI
   code with interfaces/tests; Tasks 7/11/12/14 must integrate its ledger during implementation.
4. Math-specific toolbox versus a generic subject registry remains a separate design question.

Do not restart the completed research/discussion or declare the whole plan ready. Re-read the
current files before subsequent edits. All five discussed issues are recorded. Do not start implementation without a new instruction.
The separate subject-generic tool registry question remains available for discussion.
