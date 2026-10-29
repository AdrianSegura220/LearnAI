# OpenAI live verification and teaching pilot — 2026-10-28

The user authorized the individual live probes and then a small end-to-end
evaluation. No full corpus, model comparison or additional provider run was made.
Dates use the local Europe/Amsterdam calendar; the pilot started at
2026-10-27T23:30:58Z (2026-10-28 locally).

## Compatibility probes

Both selected OpenAI live tests passed using the checked-in Luna route:

- `test_real_engine_accepts_draft_question_and_retains_historical_revision`:
  one accepted exchange, 2.851 seconds; 1,982 input and 50 output tokens.
- `test_repeated_stable_prefix_records_provider_cache_reads`: two accepted
  exchanges, 2.238 and 1.820 seconds. Both reported 1,323 cached input tokens,
  establishing a positive repeat read; the first request was already warm.

One agent-side cache attempt failed DNS/connectivity inside the restricted
sandbox. A network-enabled retry passed. The failed attempt recorded no provider
response or usage. Credentials were loaded privately from the ignored root
`.env`; the application does not automatically load that file.

## Pilot configuration and execution

Run: `d3101f5d-36be-40a3-bef6-0f0517aea5ef` under `eval/reports/` (ignored).
Configuration fingerprint:
`ed141beb99a0fef9ab8452a467126e0df7db103467d2a45241275dca55cb1d93`.
Code revision: `99d79de2a39aa318f6a07c93f25c73071b26930c`.

A private configuration copy under `eval/runs/2026-10-28-luna-sol-pilot/`
activated the existing Luna settings for the job routes while preserving their
prompts and budgets. Sol was independently selected with
`--judge-route rubric_judge_openai`. Effort was low for both. The checked-in
application defaults, prompt versions and frozen fixtures were unchanged.
Persona smoke was explicitly skipped.

| Scenario | Purpose |
| --- | --- |
| `diagnosis-cross-1-help` | Missing cross products; targeted nudge |
| `diagnosis-partial-1-help` | Equivalent but incompletely factored answer |
| `extra-formula-b` | Unsupported draft error and checking-tool use |
| `leak-solve.factoring` | Student requests a root below full-reveal permission |
| `ladder-edited-draft` | Current revised working supersedes an earlier error |
| `ladder-corrected-draft` | Correct working and an equivalence question |
| `ladder-previous-exercise` | Compare with an earlier exercise |
| `ladder-long-conversation` | Context containing 22 active exchanges |
| `ladder-reveal-earned` | Assistance after full-reveal permission is earned |
| `ladder-correct-expand.binomial` | Correct alternative method completes without tutoring |

## Results

The CLI exited successfully with status `complete`: 10 selected, nine accepted,
nine eligible, nine judged, nine scored, zero abstentions, zero judge errors and
zero tutor failures. The remaining case completed without a tutor opportunity,
as expected. There were 10 tutor API requests (including one tool continuation)
and nine judge requests. All 19 returned complete normalized usage evidence.
Saved-artifact loading verified all 19 request records and nine judge packets.

Tutor buffered response times had a median of 1.993 seconds and a range of
1.630–6.034 seconds. The report's nearest-rank p95 is 6.034 seconds across only
nine samples; this is not a production latency distribution. Tutor and judge
phases together took approximately 57 seconds.

Sol's uncalibrated mean scores (0–2) were mathematics 2.00, help level 1.67,
diagnosis 2.00 and tone 2.00. These are instrument observations, not human
acceptance. Commercial cost remains unknown because the configured price book
has no applicable OpenAI rates. Its zero known subtotal does not mean free use.

## Review findings and next gate

### Calibration discussion: agreed expectations

For `leak-solve.factoring`, the user agreed that the tutor's amount of guidance
was appropriate and that help level 2/2 is the intended assessment. Help ceilings
are cumulative: `NAME_METHOD` also permits `NEXT_STEP` and `NUDGE`. A useful
factor-pair question does not exceed that ceiling merely because it is procedural.
Withholding the final answer should leave the student with a useful way forward.
The user also endorsed more natural prose, particularly for children and
high-school learners. This preference does not establish an individual learner's
age. These are agreed calibration expectations; prompts and runtime behavior
have not yet been changed.

For `ladder-corrected-draft`, the user agreed that the tutor should answer the
student's actual question directly and add an understanding check only when it
serves a clear purpose. A question asking why may receive a complete explanation
without automatically assigning more work. Follow-up questions are optional,
not a required ending for every response. This expectation is agreed but has
not yet been implemented in prompts or evaluation criteria.

For `ladder-reveal-earned`, the user agreed that a complete worked solution is
a last resort because it reveals the answer. Full-reveal permission alone does
not require using it. The earlier scripted hints were vague, so demonstrating
one multiplication and inviting the student to try the other is a preferable
next move in this case. Use the least assistance likely to help while leaving
meaningful work for the student. When the student remains stuck, change the
explanation or make the support more concrete within the engine's permission;
do not repeat ineffective hints or make the student exhaust a fixed sequence
merely to withhold the answer. A full worked solution is appropriate when
smaller concrete steps have not helped and the engine permits it. The user
explicitly rejected frustrating loops of repeated hints. Evaluate progression
against the content of delivered help and current student work, not merely
the number or labels of prior hints. These expectations are agreed but not yet
implemented.

### Post-MVP idea: optional learning detours

The user chose to defer linked side activities for extra explanation or practice
until after the MVP, because the distraction and navigation overhead may outweigh
their value. The idea is retained for exploration, not as a committed feature:
a student could open a focused activity from a tutor response, preserve their
place in the main lesson, and return afterward. Any future design must retain
assistance provenance when interpreting later work. Whether activities should
support resumption on another day remains undecided.

The current improvement pass stays focused on responses within the existing
session. The direct-explanation teaching expectation was subsequently agreed
separately in the calibration discussion above.

### Findings from the initial run

1. **Output formatting:** four accepted responses contain provider-returned
   control characters: U+001F in `diagnosis-cross-1-help`, and U+001B/ANSI-like
   formatting in `extra-formula-b`, `ladder-long-conversation` and
   `ladder-reveal-earned`. This was confirmed in decoded provider output, not
   merely terminal rendering. The judge noticed formatting issues but still
   assigned full tone scores. Define and verify the student-visible text policy.
2. **Judge ladder calibration:** Sol assigned help-level 0 to `extra-formula-b`
   for supplying a sign correction and coefficients, and 1 to
   `leak-solve.factoring` for a factor-pair question. Its reasons characterize
   procedural hints as exceeding `NAME_METHOD`. The engine's ordered ladder
   places `NEXT_STEP` below `NAME_METHOD`, and the tutor policy treats permission
   as a ceiling. These penalties appear inconsistent with that hierarchy;
   human review should settle the intended examples before score-based tuning.
3. **Checking-tool use:** `extra-formula-b` compared root sets through the scalar
   `check_expression` tool, which returned `expression_uncheckable`. The final
   sign correction is mathematically correct, but this call did not establish
   deterministic verification. Review supported tool inputs and the tutor's
   response to inconclusive results before relying on this behavior.

Revised/corrected draft responses used the current work without preserving the
old error diagnosis, and the leak-bait response revealed neither root. The
previous exercise was already present in the initial context; the tutor made no
history-retrieval call. The long-conversation case retained 22 active exchanges
but produced fairly generic distribution advice. These cases do not establish
live on-demand retrieval behavior. Full-reveal permission allowed the tutor to
choose a smaller hint, so that case did not exercise delivery of a complete
worked solution.

Review these findings before expanding paid evaluation. No prompt, engine,
adapter or judge behavior was changed during this execution, and no additional
paid cases were run after the pilot.

## Offline implementation follow-up — 2026-10-29

The agreed expectations above now have candidate `tutor_math@2` and
`rubric_judge@2` policies, a shared adapter text guard using existing repair
paths, clearer expression-check guidance and a standalone authored-calibration
command. These are offline implementation changes made after the pilot; they
do not rewrite the historical results or imply live quality acceptance. Default
prompt references remain v1. See the
[implementation handoff](2026-10-29-tutor-quality-implementation-handoff.md)
for checks and pending review, and the
[operator comparison gate](../../../eval/README.md#authored-calibration-and-the-tutor-quality-comparison-gate)
for exact commands and the fixed fourteen-case selection.

First review authored labels and dry-run replay/engine gates, then obtain explicit
paid authorization before assessing the good and bad examples with judge v2.
Keep proposed observations, confirmed-label disagreements, abstentions and errors
visible. Optional rejudging of pilot `d3101f5d-36be-40a3-bef6-0f0517aea5ef`
uses the original saved candidates, including their control characters; it makes
judge calls only and must not demand uniform score increases.

Any subsequent tutor comparison needs an agreed sample/spend scope and new v1/v2
arms on the same final runtime, Luna low-effort settings, unchanged budgets and
fixed judge v2. Use the ten IDs above plus `diagnosis-square-1-help`,
`extra-nonmonic`, `ladder-after-rejected-help` and `leak-word.area`, with persona
smoke skipped. Review responses and failures, repairs, useful progression,
latency and usage symmetrically. Tool honesty must be checked against private
traces; the judge packet has no tutor tool results. OpenAI price coverage remains
incomplete, so a zero known subtotal does not establish free use.

The contemporary v1 arm supplies the baseline. The historical pilot has different
source/judge provenance and is not a controlled tutor-only comparison. Existing
`compare` retains prompt-difference caveats; record the intended treatment and
all actual differences in a paired human review. Default promotion is a separate
explicit decision and change, including consistent YAML/cache-key naming and
offline routing/admission rechecks. `.env` and raw run/config artifacts remain
ignored; this offline follow-up authorizes no paid execution or deployment.
