# Tutor quality refinement design

Status: proposed design for review; implementation and further paid evaluation
have not started. Teaching expectations below were agreed with the user;
technical choices and calibration examples are proposals for this pass.

## Purpose and evidence

Improve the usefulness and presentation of tutoring within the existing session,
and make the offline judge assess the same teaching policy. The
[live pilot review](../notes/2026-10-28-openai-live-pilot.md) records nine accepted
Luna responses, nine Sol assessments and one expected non-tutored completion.
It identified four replies containing control characters, two questionable
help-level penalties, and one inconclusive mathematical tool call. These are
small-sample findings, not estimates of production quality or failure rates.

## Approaches

1. Prompt changes alone are smallest, but cannot reliably prevent control
   characters from reaching students.
2. **Recommended:** versioned tutor/judge prompts, shared adapter text validation,
   clearer existing tool guidance, and explicit calibration examples. This uses
   current interfaces and repair budgets while enforcing a concrete text rule.
3. A new dialogue planner or branching session model could manage teaching moves
   explicitly, but introduces state and evaluation requirements beyond the
   evidence from this pilot. Learning detours are deferred until after the MVP.

The user requested this design and plan together. Approach 2 is the author's
recommendation, not a claim of approval of its implementation details.

## Agreed teaching policy

- Help ceilings are cumulative: `NONE < NUDGE < NEXT_STEP < NAME_METHOD <
  FULL_REVEAL`. Lower levels are allowed beneath the current ceiling.
- Answer the actual question. A request for an explanation can receive a complete
  explanation without an obligatory follow-up exercise. One pedagogical focus
  may involve several explanatory sentences or worked steps.
- Use the least assistance likely to help, preserving meaningful student work.
  This is not a mandate to start every response at the lowest rung.
- Use current work and delivered history to decide what helps next. When earlier
  help fails, change the explanation or demonstrate a concrete smaller step;
  repeating ineffective hints is not useful progression.
- A full worked solution is a last resort and requires engine permission.
  Permission alone does not make revealing the answer the best teaching move.
  Do not require students to exhaust a fixed number of hints either.
- Recognise corrections without carrying an obsolete diagnosis forward. Use
  friendly, natural prose without inventing the student's age or ability.
- The engine remains authoritative for help permissions, verification scope,
  delivery, assistance accounting and mastery.

For the pilot's factoring request, a factor-pair question beneath `NAME_METHOD`
is appropriate help (2/2), not a ceiling violation. For the corrected expansion,
explain equivalence before considering a further question. For the earned-reveal
case, the previous hints were vague: demonstrate one multiplication and let the
student try the other before recommending the complete answer.

## Versioned prompts and activation

Create `prompts/tutor_math/v2.md` and `prompts/rubric_judge/v2.md`; preserve v1
bytes. Carry forward existing privacy, injection, verification-scope and
permission instructions. Tutor v2 incorporates the agreed policy and requests
ordinary readable text/Markdown and mathematical notation without terminal
escape sequences. It must not equate concision with always ending in a question.
Do not assume a teenage learner solely because the exercise is quadratic.

Judge v2 states the full ordered ladder with short descriptions, evaluates the
actual help in the prose as well as its declared rung, and assesses usefulness
against previous delivered assistance. It must not demand questions after every
explanation or reward answer withholding when the response stalls learning.
Preserve the four dimensions, integer 0–2 scores, whole-turn abstention and
existing JSON contract. Do not automatically assign full tone scores to visibly
broken formatting. Mathematical accuracy and evidence of tool verification are
distinct: a correct explanation need not be described as tool-verified.

During implementation, select v2 through local evaluation route copies. Keep
checked-in prompt defaults at v1 until the calibration/quality review supports
promotion. Promotion is a subsequent explicit decision. Both providers must
resolve and transmit v2 correctly; no provider migration or model change is part
of this work.

## Student-visible text validation

Proposed shared adapter contract: `parse_turn` rejects a `message` containing
U+0000–U+001F except TAB (U+0009), LF (U+000A), CR (U+000D), or any code point
U+007F–U+009F. Raise `TurnSchemaError` identifying the disallowed code point
without echoing the full rejected reply. Preserve valid text exactly, including
Unicode mathematics, accents, Markdown, backslashes, tabs and line breaks.

Use existing format-repair paths and their shared budgets in Anthropic and
OpenAI. Do not silently strip characters: stripping can leave ANSI fragments or
change mathematical content. A repaired reply still passes normal engine
validation. Exhausted repair delivers no invalid reply. Raw rejected output is
retained in private traces, never student history. This guard covers provider
adapters using the shared parser, not arbitrary fake/domain TutorTurn producers
or retroactive rewriting of saved artifacts. No browser sanitisation claim is
made by this character rule.

## Inconclusive mathematical checks

Clarify `check_expression` in its canonical tool definition: with a reference it
compares two supported mathematical expressions/relations for equivalence; it
does not accept brace-delimited root sets as a substitute for a structured
solution-set checker. Without a reference, it grades the supplied single field
against the active item's answer specification, subject to its existing shape
requirements. Do not expand supported answer shapes in this pass.

Keep the `expression_uncheckable` code and error semantics. Improve its detail
to explain the supported request form without implying mathematical falsity or
disclosing an answer key. Tutor v2 distinguishes unavailable verification from
a wrong answer. It may reformulate a genuinely supported check within the
remaining budget, ask for clearer notation, or explain a justified step without
claiming a successful tool result. It must not repeatedly send the same
unsupported input or substitute invented tool evidence.

The current judge packet does not include tutor tool results. Do not extend it
implicitly or claim the judge can establish tool honesty from evidence it never
received. Review this aspect against saved traces separately. Automated tests
can prove error transport and bounded execution, not that the model will always
choose the right explanation.

## Calibration and validation

Keep original scenario fixtures, v1 artifacts and the pilot run immutable.
Add a separate, synthetic calibration collection under `eval/calibration/`,
outside `eval/fixtures/`, so normal corpus selection is unchanged. Each entry
references an existing scenario, carries an authored candidate turn, specifies
the dimension(s) under review, and includes expected score(s), rationale and
review status. No blanket four-score labels where only help level was reviewed.
Proposed labels remain distinct from user-confirmed expectations.
Each entry additionally declares `expected_engine: {accepted: bool, reason:
null | rejection-reason-name}`. Construct its exact context with
`prepare_scenario`, require an actual tutor opportunity, and run `validate_turn`
with the real graph and verifier. Positive examples must be accepted. An
intentional leak must explicitly expect rejection such as `ANSWER_LEAKED`;
pedagogically poor but legal hints may expect acceptance and a low help score.
Any mismatch invalidates the collection before provider client creation. Never
weaken engine rules to accommodate an authored example. Expected engine outcomes
are separate from quality scores and review status.

Add an explicit standalone operator command:

```sh
.venv/bin/python -m learnai.eval.calibration \
  --calibration eval/calibration/tutor_quality_v2.yaml \
  --routes LOCAL_YAML --judge-route rubric_judge_openai --dry-run
```

Omitting `--dry-run` is paid judge-only execution and requires authorization.
The dry run validates the whole collection and prepares packets without keys,
clients or network. Live execution uses the existing independent judge provider
composition, not a tutor client. Construct `JudgePacket` from replayed context,
authored candidate and existing curated reference. The judge sees those fields,
never expected scores, calibration rationale, human review status or engine-gate
results. Evaluator-only rejected candidates may be assessed without delivery,
assistance consumption or mastery updates. Their rejection remains explicit in
the calibration result; they must never enter a student session's history.

Entries marked `trace_review` are listed as requiring manual review and never
sent to the judge. Compare numeric results only for the specified dimensions
with user-confirmed expected labels. Report proposed-label observations
separately. Preserve abstentions, judge errors, skipped entries and all relevant
denominators; do not count missing scores as correct agreement or as zero.

Write unique, private `eval/reports/calibration-<uuid>/` artifacts with a distinct
`kind: tutor_calibration`, `schema_version: 1`, rather than claiming they are
ordinary tutor run reports. Capture calibration YAML content/hash, prepared
packets and engine results, expected labels/review statuses, actual selected
judge policy/settings/dependencies, source/content inputs via an existing base
manifest, raw judge traces/usage and per-case results. The calibration fingerprint
hashes the base configuration material plus the calibration content and prepared
cases, excluding outcomes, IDs and timing. The ordinary manifest does not capture
`eval/calibration/`; wrapping its material here explicitly covers that omission.
Save results incrementally so completed cases survive later errors/interrupts,
and close operation-owned clients. Do not feed calibration artifacts to existing
`run`, `rejudge` or `compare` readers or change those artifact schemas.

Cover useful factor-pair guidance, premature answer leakage, a direct explanation
without a question, needless rework of a correction, meaningful escalation,
repetition of vague hints, and unsupported claims that a checker verified work.
The final case is trace-review evidence unless tool results are actually present
in the packet. Include negative examples, not merely preferred prose.

Offline acceptance requires shared parser and both-provider repair regressions,
real-CAS error/valid-form checks, v2 prompt wiring, and corpus admission under
existing checked-in and fallback budgets. Preserve the 8,192-unit continuation
headroom after next-call output reservation; shorten prompts if necessary.
Scripted tests demonstrate plumbing, not pedagogical improvement.

Further paid execution requires explicit authorization. First assess the fixed
authored calibration candidates with judge v2, then optionally rejudge the saved
pilot responses. Review disagreements against the agreed
expectations. Then compare tutor v1/v2 on the same final runtime, models, effort,
budgets, scenarios and judge v2. Keep all relevant prompts available in both
runs. Add untouched cases selected before execution: `diagnosis-square-1-help`,
`extra-nonmonic`, `ladder-after-rejected-help`, `leak-word.area`. Use multiple
samples when drawing comparative conclusions, within an agreed paid scope.

Existing `compare --tutor-treatment` intentionally does not waive prompt changes.
Retain that restriction and report its caveats; use explicitly documented paired
review for a prompt experiment. The original pilot is historical evidence, not
an identical-runtime control after code or judge changes. Record acceptance,
failures, repairs, mathematical/tool correctness, useful progression, latency,
usage and judge disagreements. Do not claim learning gains from these proxies.

## Boundaries and completion

Python 3.12+; no new dependency, SDK upgrade, model switch, budget increase,
domain permission/mastery change, new CAS capability, session detour, UI, pricing
snapshot or live deployment. Existing credentials and raw run data stay private.
The current source's free-text diagnosis versus catalogue-id handling is a
separate contract concern; do not silently broaden this pass to redesign it.

Implementation completion means offline gates pass and candidate v2 prompts are
available for evaluation. Teaching-quality acceptance and default promotion
remain explicit review outcomes. There is no preselected aggregate score target
that can replace examining the actual responses.
