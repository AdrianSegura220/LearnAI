# Judge v2 calibration — 2026-10-31

After reviewing the authored examples, the user confirmed six `help_level`
labels and the separate manual trace-review criterion, then explicitly authorized
one six-case paid judge batch. No tutor generation or additional paid rerun was
performed. Prompt defaults remain v1.

## Run and evidence

Private artifact:
`eval/reports/calibration-bf3c7daf-304c-44b2-8017-0bd17d818cae/calibration.json`.
The artifact remains ignored and unmodified after execution; it captures the
reviewed YAML content/hash, prepared packets, engine outcomes, request/response
records and traces. Source revision: `587919b11828cf473eb0dad31cfa1615c9efc0b3`.
The confirmed labels were local edits captured in the calibration material.
Configuration fingerprint:
`3159b2a221b33ce53ea8eb937f59e5044999226bf39d448184cac18e8ef89ee2`.

Selected route: `rubric_judge_openai`, requested and returned model
`gpt-6.1-sol`, low effort, `rubric_judge@2`, substantial budget, 2,048 maximum
output tokens. Six requests completed, each with one model call, no API errors,
API retries, format repairs or abstentions. Total operation time was 27.34s;
median request latency 4.52s, range 3.10–5.45s. These are judge timings.
Raw usage totals: 18,234 input and 672 output tokens. No OpenAI pricing snapshot
was configured, so this run does not establish a monetary cost.

## Confirmed-label comparison at execution

| Authored case | Human help score | Judge help score |
| --- | ---: | ---: |
| Useful factor-pair hint | 2 | 2 |
| Premature root | 0 | 0 |
| Explain corrected work | 2 | 2 |
| Unnecessary correction rework | 1 | 0 |
| Concrete multiplication | 2 | 2 |
| Repeated vague hint | 0 | 0 |

Exact agreement is 5/6 confirmed dimensions (83.3%), with no exclusions.
Mathematics, diagnosis and tone were each scored 2 for all six responses, but
those dimensions have no human-confirmed expected labels in this collection.
The seventh case remains `manual_review_required`, with no numerical score;
agreement to the review criterion is not an executed tool-trace check.

## Interpretation and follow-up decision

The judge distinguishes useful guidance from answer leakage and repeated vague
hints, and recognizes a direct explanation of corrected work. Its one mismatch
concerns severity: it scored unnecessary re-expansion 0 because it delays the
student's explicit question without explaining equivalence. Human review scored
1 for acknowledging the correction and suggesting relevant, albeit redundant,
work. The saved run retains that initial target and disagreement.

Following discussion, the user approved a clearer scoring boundary and revised
this case's expected help score from 1 to 0. Acknowledging a correction alone
does not advance the student's understanding; repeating valid work without new
explanation delays the actual question. The agreed definitions are:

- 0: inappropriate help or no useful progress toward the current need, including
  unnecessary repetition.
- 1: some useful explanation or guidance, with a material gap.
- 2: useful, appropriate and actionable help addressing the current need.

The candidate judge v2 policy, current calibration label/rationale and existing
collection assertion were updated together. V1 policies and route defaults are
unchanged. The paid artifact remains byte-identical: do not relabel its result
as 6/6 agreement or claim that it tested the revised rubric. Its captured prompt,
labels and 5/6 result remain historical evidence. No additional paid call was
made for this clarification.

This small authored set overlaps examples explicitly described in the rubric;
it is a targeted sanity check, not independent validation of broad judge quality
or learning gains. Immediately after the boundary clarification, the collection
had expected help scores only at 0 and 2, leaving a partial-credit coverage gap.
The revised rubric remains untested live. Human review of actual comparison
responses remains necessary before relying on aggregate scores.
The paired 14-scenario tutor comparison, further paid calls and default promotion
remain unexecuted and require their own authorized scope.

## Offline verification after clarification

The calibration preparation/execution, prompt-loading and provider/corpus
admission tests passed: `98 passed in 10.63s`. The keyless dry run prepared six
judge cases and one manual case. `git diff --check` passed. A SHA-256 comparison
confirmed the original paid artifact is byte-identical; v1 prompts and checked-in
route defaults also match HEAD. These checks do not establish live behavior of
the revised judge rubric.

## Confirmed partial-credit development example

At the user's request, a seventh judge case was added to the current collection:
`incomplete-corrected-work-explanation`, using `ladder-corrected-draft`.
Its response is: "Your corrected line follows the distributive property."
The user confirmed help score 1: naming the relevant rule offers some orientation,
but leaves unexplained how the corrected terms arise and why the expressions
are equivalent. The user also raised the risk of tailoring the judge to the
examples. The response was authored for an existing scripted scenario, rather
than generated by the tutor during a live run. This is a confirmed development
label, not independent evidence that the judge generalizes to unfamiliar replies.
The collection now contains seven judge cases and one manual trace case.
This addition has not been evaluated live and does not alter the historical
six-case run.

## Fixed rubric and independent evaluation protocol

The user agreed to retain these authored cases as development checks and use
fresh cases for independent evaluation. Candidate `rubric_judge@2` is fixed for
that next evaluation at SHA-256:
`a3f4451236fa1b9e434425162d2b8a6996e28e46e800d01cff81297b2d240a4d`.
Use the selected judge model/settings recorded above and capture the effective
configuration in the new run. Verify the prompt hash before execution; this is
a documented procedure, not a runtime lock or a promotion of defaults.

Choose new student situations and reasoning demands before generating actual
tutor responses. Avoid treating coefficient changes or paraphrases of these
development cases as independent coverage. Record human scores and reasons
without viewing judge scores, then compare all cases, including disagreements,
errors and abstentions. Accept different valid explanations rather than matching
an ideal sentence. Any cases used to refine the prompt become development data;
subsequent independent evaluation needs a fresh set.

The previously planned fourteen-case tutor comparison includes development
scenarios, so it remains a useful regression comparison rather than independent
validation of judge quality. No fresh independent set or blind human labels
have been prepared yet. The original paid run and its 5/6 agreement remain
historical evidence of the development check only.
