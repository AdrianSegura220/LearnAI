# Slice 1 plan review — status & resume note

**Date:** 2026-10-15 (started 2026-10-14)
**Purpose:** handoff so a fresh session can resume the task-by-task review of
`docs/superpowers/plans/2026-09-19-slice1-tutoring-engine.md` after a context compaction.
All corrections — task-by-task and final-pass — are applied to the plan and spec on disk and
verified (uncommitted). Nothing is committed yet.

## How the review works

- Task by task: for each task, a **short, simple breakdown with context** (the reviewer has not
  read the spec/plan in weeks — restate why each piece exists, contained and understandable).
  Skip deep test walkthroughs; wait for acknowledgment before starting the next task.
- Confirmed findings are **applied directly** to the plan (and spec where relevant). The plan
  file is the artifact under review; nothing is committed yet.
- Reviewer is **terminal-only**: plain-text math (no LaTeX), no Obsidian. HTML artifacts are
  opened with `open`.
- Side questions are welcome mid-review (math reminders, design questions); when a decision is
  made, record it in the plan rather than leaving it in conversation.

## Progress

- **Reviewed, corrections applied and verified:** Tasks 8–18. The task-by-task review is complete.
- **Final full-diff pass:** complete, including executable checks of all 18 tasks. All findings
  fixed and verified — the reconstructed plan now passes **479 / 479** tests.
- **Remaining:** decide about committing (nothing is committed yet).

## Final full-diff pass — 2026-10-15

### Evidence

- Independent read-only review of the working-tree diff against
  `20217b0ed5ce9a089323b5d1a5b6e439f82f066c`, with cross-task checks through Tasks 1–18 and
  the spec. Each runtime finding was then reproduced independently.
- Reconstructed 63 inline files (61 Python files) in an isolated temporary sandbox, applying
  only the anonymous extensions and import additions explicitly directed by the plan.
  Interpreter: Python 3.12; dependencies include the plan's pinned SymPy 1.14.0.
- All reconstructed Python files compile. The full planned suite, after its intentional
  first-run golden-snapshot bootstrap, reports **479 passed, 0 failed** — the 474-test
  baseline plus five new regression tests. The failing cross-rule test was fixed by input
  guards, and every finding below now has a test and a reproduced behavioural check.
  Syntax-only verification in the earlier review did not establish this.
- HTML explorer script boots under a DOM stub; the 14-review trajectory matches
  S = 194.6 days / due gap = 29.6 days, and assisted attempts leave strength unchanged.
  This is an execution/math smoke check, not a visual browser review.
- `git diff --check` passes. All final-pass corrections are applied to the plan, spec, and
  explorer; each was re-reproduced after the fix.

### Final-pass findings — all fixed and verified

1. **Readable alternative steps can crash diagnosis (Task 8).** The shared reader turns
   `x = 7 or x = 8` into a Tuple for the rules. Expression-only rules call `sp.expand` on it,
   raising an uncaught `AttributeError` before the engine records evidence. The new canonical
   cross-rule test reproduces the crash. Guard supported input types in expression-only rules
   rather than assuming every `sp.Basic` is an expression. See plan lines 3844–3985.
2. **LET_RUN confuses shown work with an equivalence break (Tasks 8/17).**
   `12x^2 + 18x` → `2(6x^2 + 9x)` is mathematically equivalent but fails `FULLY_FACTORED`.
   The verifier gives WRONG, `diff_steps` gives None, the partial-factor rule is never called,
   and `has_work=step_diff is not None` summons the tutor immediately on the first attempt.
   Use submitted working for the self-correction window, and retain/route form-failure
   information for diagnosis even when equivalence holds. See plan lines 6970–7008.
3. **A decline leaves cold credit available after tutoring (Task 17).** Blank submission →
   immediate orientation → correct answer still classifies as UNASSISTED_COLD and increments
   unassisted-correct evidence. Separate readable submission history from reveal-effort
   accounting: declines spend the cold submission but must not count as genuine effort;
   malformed input spends neither. See plan lines 6980–7020.
4. **Help history records requested ceilings instead of delivered rungs (Task 17).** A scripted
   tutor delivering four accepted NUDGE turns is logged as NUDGE, NEXT_STEP, NAME_METHOD,
   FULL_REVEAL; the fifth request is refused although no reveal reached the student. Validation
   currently permits lower-rung turns. Record the delivered rung (and do not count NONE), or
   require the requested rung before consuming it. See plan lines 7049–7077.
5. **Timed contracts can still deliver unsolicited help (Tasks 12/17).** A timed contract with
   base rung NONE and no reveal unlock accepts intervention_timing=IMMEDIATE, then the engine's
   NUDGE override delivers help. Require NEVER for timed contracts and keep unsolicited rung
   overrides within the contract's help ceiling. See plan lines 5068–5078 and 7005–7020.
6. **An earned badge can disappear after a later cold error (Tasks 9/10/16; existing issue).**
   Six distinct cold successes at difficulty 2.0 yield strength 1.648402 and is_learned=True;
   one cold failure at difficulty 0.0 lowers strength to 1.390348 and is_learned=False.
   Spec §7.3 says the badge never un-earns, but both spec and plan use the current threshold.
   Preserve a historical achievement marker through the shared live/replay update path;
   keep current qualification distinct. The existing achievement test only advances time,
   so it does not cover a later negative observation. See plan lines 4243–4295, 4663–4668,
   6361–6374 and spec lines 507, 517–520.

How each was resolved, and the re-run behaviour: expression-only rules guard with
`_comparable` (no crash; the attempt records); LET_RUN keys on submitted working and a
form-only failure still diagnoses on the final transition (no tutor call on the first miss;
diagnosis = `mc.gcf.partial`); declines spend the cold attempt via `HelpState.submissions` /
`record_submission` (later success = `ASSISTED`, count 0); help records `turn.rung_used` and a
NONE turn is delivered but never consumed (four NUDGEs logged as four NUDGEs, ladder not
exhausted); timed contracts require `NEVER` and unsolicited rung overrides clamp to the ceiling
(timed + IMMEDIATE refused at construction); `SkillState.ever_learned` is latched by
`_earn_if_due` in the projection and honoured by `is_learned` (badge survives 1.648 → 1.390).
New tests: +3 engine (24 total), +1 projection (11), +1 help ladder (10).

### Documentation/artifact corrections — applied

- **Completion wording:** spec §8.4 still says wrong answers close the item and advance, while
  the approved Practice behavior keeps it active. Task 17's reveal-exit prose also needs to
  say that the subsequent correct submission completes the task; `request_help` itself does
  not advance it. See spec lines 743–745 and plan line 6459.
- **Stale tuning instructions:** Task 18 refers to uppercase constants in `constants.py`;
  the actual settings are `MasteryParameters.target_logit_margin` and `k0` in `parameters.py`.
  See plan line 7463.
- **Minor explorer readout:** the “elapsed” label prints `mem.now`, not the already-computed
  `elapsed` since the last success. A success at day 1 therefore displays elapsed = 1 day
  while R(now) = 1. Fix the displayed variable (HTML line 476). The permanent-badge issue
  above also affects the explorer's threshold-based display.

## Corrections applied, by task

- **Task 8 (diagnosis):** `_claimed_values` single Tuple-aware version inline (trailing "extend
  it" note removed); shared step reader promoted to public `parse_step` / `Alternatives` / `Step`
  in `sympy_verifier.py` (Task 8 rules consume it; `_parse_current` deleted); `_drops_cross_terms`
  rewritten on the multiplication grid (no Wild match, both diagonals, cancel-case guard);
  `_incomplete_common_factor` gains `is_Mul` guard (it fired on correct expansions); skills.yaml
  documents "list order = diagnosis priority" + a 6×6 rule-disjointness guard test; test count
  16→25; "rules pool per verification kind" growth note; File Structure gains
  `cas/misconception_rules.py`.
- **Task 9 (strength/evidence):** `classify_evidence` — contamination beats timing; `TIMED_EXAM`
  only for a clean first attempt (help or retry → `ASSISTED`); timed tests reworked
  (`test_timed_beats_everything` → three precise cases), evidence count 8→10; both recorded
  interpretations (retry-not-cold, timed-clean-only) flagged for the spec owner.
- **Task 10 (stability):** `due_at` subtracts `timedelta.resolution` so
  `is_fresh(state, due_at(state))` holds despite microsecond quantisation.
- **Task 11 (propagation/calibration):** deferral note extended with "**Where this lands**"
  (Slice 2 plan; `END_TASK_UNPRODUCTIVE` first, `DROP_TO_PREREQUISITE` next, `SERVE_EASIER_ITEM`
  last; moves into Plan 2 if the UI makes the escape hatch actionable).
- **Task 12 (contracts):** timed-contract-no-help invariant (`__post_init__` + test, count 7→8);
  Deferred paragraph cross-references the escape hatch.
- **Task 13 (LeakGuard):** test count 10→11.
- **Task 14 (turn contract):** TYPE_CHECKING note corrected (`turn.py` imports `Verifier` from
  `ports.py`, not the other way); "Deferred — acting on proposals" note added (request channel
  validated, engine has no policy yet).
- **Task 15 (session/planner):** deferred-descent note expanded — tutor-side `Proposal` channel
  exists and is validated; engine deliberately does not act yet.
- **Task 16 (log/projection):** `test_a_downstream_success_refreshes_a_learned_prerequisite`
  fixture fixed — old fixture (3 easy successes) reached strength 0.286 < 1.5, so propagation
  correctly skipped; now 6 cold successes at difficulty 2.0 (strength 1.648 ≥ 1.5).
- **Task 15 (amended during Task 17 review):** `Task` gains `last_step_diff` / `last_diagnosis`
  (the last wrong submission's break, kept for the tutor's walk-back on a later help request);
  interfaces line and imports updated.
- **Task 17 (the engine):** intervention timing made spec-faithful — `_should_intervene` is now
  verdict/attempt aware: NEVER silent; IMMEDIATE answers every failure; BY_ERROR_TYPE on
  recognised errors; LET_RUN (practice) = one self-correction beat — a first wrong submission
  with a localised break gets no tutor call, the next failure summons the walk-back, and a help
  request mid-beat carries the break back. `request_help` asks first and records `HelpTaken` /
  consumes the rung only on delivery. Reveal-unlock positive test added (effort accounting was
  otherwise unpinned). `TaskId` unused import dropped. Tests 16 → 21; three new prose paragraphs
  (intervention timing; "wrong answers do not close the task"; deferred session memory —
  `skills_taught` and `TurnContext.transcript` have no producers in Slice 1).
- **Task 18 (simulated students):** interfaces line corrected (`days_between_sessions`, not
  `sessions_per_week`; `clock` listed on `TermResult`); `_abandon` now marks
  `TaskState.ABANDONED` before advancing — documented as the harness's skip (the engine itself
  never advances past a wrong task), which also gives `ABANDONED` its only Slice 1 consumer;
  import hygiene in both simulation files (hoisted, duplicate `CLUSTER` import removed).
  Trajectory assertions checked against the stability constants (">20" and "R(365) < 0.5"
  both comfortably safe); `tests.`-package imports fine (Task 1 scaffold touches
  `tests/__init__.py`).
- **Spec §6.1:** "Signatures are a flat, subject-wide namespace" paragraph added.

## Open observations (recorded here; not yet acted on)

- `reveal_price` and `mixes_skills` are declared on `ModeContract` but consumed nowhere in
  Slice 1. (`intervention_timing` is now fully consumed — Task 17 implements the spec §8.4
  mapping.) Fresh-variant price enforcement arrives with the reveal flow later.
- Calibration updates on every attempt, including assisted (defensible; one line if ever wanted).
- `unassisted_correct_count` increments on any correct attempt with weight > 0 (includes
  post-instruction 0.1) — count gate can be satisfied in-session while the strength gate cannot.
- Event/projection folder question answered: keep `events.py` / `projection.py` flat; split when
  event kinds multiply (one module per family, re-export via `__init__` then).

## Artifacts

- Interactive visual (strength Elo + stability/forgetting):
  `docs/superpowers/notes/2026-10-14-mastery-explorer.html` — open with `open`.
- All review edits are uncommitted; `git diff` on the plan is the review's product.

## To resume

1. Read this note.
2. Nothing is pending: the task-by-task and final-pass reviews are complete, all findings are
   fixed and verified (479/479 on the reconstructed plan). The remaining decision is whether
   and how to commit the plan, spec, and explorer changes.
