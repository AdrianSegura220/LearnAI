# Independent judge evaluation: first scenario set

## Status and purpose

The user approved the original twelve categories and two additional cases about
students who cannot locate or explain their mistake. These fourteen briefs now
have executable fixtures in `eval/independent/`, with exact authored items and
real-engine replay. All fourteen pass keyless semantic readiness after contextual
work verification resolved five representation blockers described below. No live
quality evaluation has been performed for this set. The mathematics below
is authored explicitly; do not silently substitute generator seeds or exercises.

Use these situations to generate actual tutor replies, then compare human and
judge assessments. Do not write ideal replies or predetermined quality scores.
Existing authored calibration examples are development checks. This set shares
their general teaching principles but must not be used to tune the judge before
its first independent assessment. It is still a small authored sample, not a
representative student study or evidence of learning gains.

This fresh fourteen-case set is separate from the earlier fourteen-case
regression selection, which reuses known development scenarios.

## Evaluation procedure

- Freeze `rubric_judge@2` at SHA-256
  `a3f4451236fa1b9e434425162d2b8a6996e28e46e800d01cff81297b2d240a4d`
  and record the effective model/settings before execution. See the
  [calibration review](../notes/2026-10-31-judge-v2-calibration.md).
- Initially collect one tutor reply per case using a fixed tutor configuration.
  Record every failed request, rejected candidate and missing tutor opportunity;
  do not replace cases or rerun selectively to obtain a desired score distribution.
- Human review sees the complete student situation and delivered reply, without
  judge scores, judge reasons or provider/model labels. Record scores and reasons
  before revealing judge assessments. Judge inputs exclude human labels.
- Assess mathematics, helpfulness, diagnosis and tone. Keep tool-verification
  honesty in a separate trace review because the judge packet lacks tool results.
- Preserve disagreements and abstentions. If these results inform a prompt
  revision, these cases become development material; use fresh cases for the next
  independent evaluation. A set with no weak tutor replies cannot establish how
  well the judge distinguishes weak responses.
- Paid generation/judging needs an agreed execution scope. No calls are
  authorized or performed merely by writing this document.

## Shared scenario conventions

All fourteen current moments are draft questions during practice, not graded final
submissions; cases 13 and 14 follow an earlier incorrect submission. Student work
is quoted exactly, including intended errors. Student
age is unspecified. No specific solution method is required unless the exercise
explicitly says so; current briefs allow method choice. Matching a preferred
worked solution is not a criterion.

The proposed help ceiling is NAME_METHOD for every case: useful explanation and
intermediate guidance are allowed; revealing an active final answer is not.
This is a replay requirement to validate, not authority to overwrite engine
permission counters. Historical help in case 9 must be delivered through real
replay and remain subject to its gate. If any brief cannot be represented by the
current runner, document the limitation before changing it.

The review focus in each case is for evaluator preparation. Do not inject it into
the tutor's student message or include expected judge scores. Current-session
history is empty unless specified; learner mastery metadata must be fixed and
documented when executable fixtures are prepared, not used to infer age.

## 01 — Correct alternative method

**Exercise:** Solve `x^2 + 6x + 5 = 0` over the real numbers. Any valid method.

**Current work:** `x^2 + 6x = -5`; `x^2 + 6x + 9 = 4`;
`(x + 3)^2 = 4`. No roots entered.

**Question:** "I completed the square instead of factoring. Is my work so far
valid, and can I keep going this way?"

**Review focus:** Recognize a valid alternative and the actual partial work.
There is no requirement to redirect to factoring or supply roots. Evaluator
facts: the transformations are valid; the roots are -1 and -5.

## 02 — Correct but unfinished work

**Exercise:** Solve `2x^2 + 7x = 4` over the real numbers.

**Current work:** `2x^2 + 7x - 4 = 0`. No answer entered.

**Question:** "Before I do anything else, was subtracting 4 from both sides
allowed? I only want to check that step."

**Review focus:** Answer the narrow validity question without treating unfinished
work as an error or completing the exercise. Roots: -4 and 1/2.

## 03 — Correct answer with invalid reasoning

**Exercise:** Solve `x^2 - 5x + 6 = 0` over the real numbers.

**Current work:** `x^2 - 5x + 6 = 0`; `(x - 2)(x + 3) = 0`;
`x = 2 or x = 3`. Draft answer fields: `2`, `3`.

**Question:** "I got the roots. Does every line of my working follow?"

**Review focus:** Separate correct final values from invalid intermediate work.
The proposed factors expand to `x^2 + x - 6`, and the stated roots do not both
follow from those factors. Do not invent a psychological diagnosis from this.

## 04 — Multiple errors and intervention priority

**Exercise:** Expand and simplify `(2x - 3)(x + 4)`.

**Current work:** `(2x - 3)(x + 4)`;
`2x^2 + 8x + 3x - 12`; `2x^2 + 11x - 9`.

**Question:** "I think I made a mistake somewhere. Which part should I look at first?"

**Review focus:** Choose a useful first intervention rather than list every
problem or give the final expression. The first error is the sign of `(-3)x`;
a later line also changes the constant. Correct result: `2x^2 + 5x - 12`.

## 05 — A conceptual question about a repeated root

**Exercise:** Solve `x^2 - 6x + 9 = 0` over the real numbers.

**Current work:** `b^2 - 4ac = 36 - 36 = 0`;
`x = (6 +/- sqrt(0))/2`. No final answer entered.

**Question:** "Why doesn't the plus-or-minus give two different answers here?"

**Review focus:** Explain what happens when the square-root term is zero.
A direct explanation is sufficient; an extra exercise is optional. The unique
root is 3, which need not be disclosed to answer the question.

## 06 — An incorrect generalization

**Exercise:** Solve `x^2 - x - 12 = 0` over the real numbers.

**Current work:** `x^2 - x - 12 = 0`; `(x - 4)(x + 3) = 0`.
Draft answer fields: `4`, `-3`.

**Question:** "This one has two answers. Does every quadratic have two different
real answers because the power is two?"

**Review focus:** Address the general claim while recognizing the valid current
work. Distinguish two, one and no distinct real roots; do not mark this particular
solution wrong or unnecessarily repeat its roots.

## 07 — Ambiguous reference in a question

**Exercise:** Solve `x^2 - 4x - 5 = 0` over the real numbers.

**Current work:** `a = 1, b = -4, c = -5`;
`b^2 - 4ac = (-4)^2 - 4(1)(-5)`.

**Question:** "Why is that negative?"

**Review focus:** There are several plausible referents: b, c, or the subtraction
in the discriminant. A focused clarification or clearly qualified explanation is
appropriate. Do not assert which sign the student means without evidence.
Discriminant: 36; roots: -1 and 5.

## 08 — Specific local confusion

**Exercise:** Solve `2x^2 - 3x - 2 = 0` over the real numbers.

**Current work:** `a = 2, b = -3, c = -2`;
`x = (-(-3) +/- sqrt((-3)^2 - 4*2*(-2)))/(2*2)`.

**Question:** "I know the formula. I'm only confused about -(-3) at the front.
Why does that become positive?"

**Review focus:** Explain the local sign operation without restarting the entire
method or solving the equation. The substituted expression is valid; roots are
-1/2 and 2.

## 09 — Assistance that has not helped

**Exercise:** Rewrite `x^2 + 8x + 3` in completed-square form.

**Earlier student question:** "I don't understand how to start completing the square."
**Delivered tutor reply:** "Take half the coefficient of x, square it, and add
and subtract that amount."

**Current work:** Only the original expression; no attempted answer.
**Current question:** "I can repeat that rule, but I don't understand why adding
and subtracting helps. Can you show the idea another way?"

**Review focus:** Address the conceptual obstacle using a different explanation
or smaller concrete step rather than repeat the procedure. Do not infer the
student is refusing to try. Correct completed-square form: `(x + 4)^2 - 13`.

## 10 — Student changes approach

**Exercise:** Solve `3x^2 + x - 2 = 0` over the real numbers. Any valid method.

**Earlier student message:** "I'm trying to factor this, but I can't find the pair."
No tutor response was delivered.

**Current work:** `a = 3, b = 1, c = -2`;
`x = (-1 +/- sqrt(1 - 4*3*(-2)))/(2*3)`.

**Question:** "I've switched to the quadratic formula. Is this setup right?"

**Review focus:** Follow the valid current approach and answer the setup question
instead of carrying on with factoring advice. Roots: -1 and 2/3.

## 11 — Algebraic solutions and physical constraints

**Exercise:** A rectangle has area 40 cm². Its length is 3 cm greater than its
width. Find its width.

**Current work:** `w(w + 3) = 40`; `w^2 + 3w - 40 = 0`;
`(w + 8)(w - 5) = 0`; `w = -8 or w = 5`.
Final width field remains blank.

**Question:** "Both numbers solve my equation. Why can't the negative one be
the width? Is it algebraically wrong?"

**Review focus:** Distinguish satisfying the equation from representing a physical
length. Negative width is inadmissible in this context; it is still an algebraic
root. Avoid inventing a broader rule that negative solutions are always invalid.

## 12 — Local checking near the answer boundary

**Exercise:** Solve `x^2 - 6x + 8 = 0` over the real numbers.

**Current work:** `x^2 - 6x + 8 = 0`; `(x - 2)(x - 4) = 0`;
`x - 2 = 0`. No answer entered.

**Question:** "For this last line, should I subtract 2 from both sides? Just
tell me whether that move helps."

**Review focus:** Explain the useful inverse operation within the help ceiling.
Subtracting from both sides is legal but does not isolate x efficiently; it is
not itself an invalid equation transformation. Do not confuse an inefficient
move with a mathematical error or reveal a final root to answer this question.

## 13 — Correct value, incomplete answer, unexpected rejection

**Exercise:** Find all real solutions of `x^2 = 9`.

**History:** The student submitted the single answer field `3`, with working
`3^2 = 9`. The answer-set check rejected the incomplete set. The student saw
only "That answer isn't correct yet", without a diagnosis or tutor explanation.

**Current work:** The same value and check are retained in a draft question.
No other solution is entered.

**Question:** "It says my answer is wrong, but 3 squared is 9. What am I missing?"

**Review focus:** Acknowledge that the submitted value satisfies the equation
while recognizing that the requested answer set is incomplete. Help the student
look for another possibility without immediately revealing the missing root.
Do not describe the valid substitution as an arithmetic error or assert that
the positive root is invalid. Evaluator facts: the full solution set is {-3, 3}.
The displayed rejection wording must be captured as part of the scenario; this
brief does not prescribe that wording for the product's feedback design.

## 14 — Incorrect answer with no working to locate the error

**Exercise:** Solve `x^2 + 5x + 6 = 0` over the real numbers.

**History:** The student submitted answer fields `1`, `6`, with no working.
The answer check rejected them. The student saw only "That answer isn't correct
yet", without a diagnosis or tutor explanation.

**Current work:** The same draft answer fields are retained; no steps are shown.

**Question:** "I got 1 and 6, but it says they're wrong. I don't know where I went
wrong or what I should try now."

**Review focus:** The evidence establishes that the submitted values are wrong,
but not how the student obtained them. Ask for a useful piece of working or
offer one manageable starting step. Do not confidently diagnose a sign error,
factor-pair confusion, or a specific misconception from the answer alone. Avoid
overwhelming the student with several questions or revealing the roots.
Evaluator facts: the roots are -2 and -3; neither submitted value satisfies the
equation. Historical checks apply to their recorded revision, not unseen edits.

## Method-specific learning: design issue identified during review

The fourteen briefs above permit method choice. Required-method exercises need an
explicit contract, rather than inferring a restriction from a skill ID or the
author's preferred worked solution. The following is a proposal for discussion,
not implemented behavior or an approved mastery-policy change.

Distinguish an unrestricted method, a recommended method, and a required method
with required evidence. State a requirement in the exercise before the student
starts. Track answer correctness separately from whether the required process
is demonstrated: demonstrated, not demonstrated, or insufficient evidence to
assess. A correct final answer alone cannot establish which method was used.

In learning/practice, acknowledge a correct alternative and request the relevant
method step. Completion of the targeted method objective may remain pending;
missing method evidence should not automatically become evidence of inability.
Credit for another skill needs its own validated evidence and policy, rather
than automatic transfer. Assessment scoring should follow an explicit mark
scheme separating result marks and method marks.

Keep requirements and evidence generic in the domain, with subject adapters
owning identifiers and validation rules. Require evidence of the process, not
literal matching of a canonical solution. Valid variants of the required method
must count; unparseable or omitted work requires uncertainty rather than an
invented finding. Tutor and judge must see the same task requirements and scoped
validation results; the tutor must not independently override mastery credit.

Current code has answer-form constraints and mathematical step-equivalence
checks, but no required-method contract or verifier. `solve_by_factoring` prompts
"Solve for x" and checks the roots without requiring factoring steps.
`Engine.submit` records evidence against the task's skill from the verification
verdict. Consequently, method-specific mastery is not established merely by
passing that answer check. See `domain/items.py`, `domain/engine.py`,
`adapters/cas/sympy_verifier.py` and the quadratic generators.

After this contract is designed, add a separate contrast pair using the same
mathematics and alternative solution: one unrestricted task and one explicitly
requiring factoring. Also cover missing working and a valid noncanonical
factoring solution. These are future coverage, not extra executed cases in this
fourteen-case set. If they require changing the frozen judge prompt, explicitly
version that change and establish a new evaluation baseline.

## Executable fixture findings

`python -m learnai.eval.independent` checks all fourteen opportunities and reports
the semantic readiness separately from successful replay. All current moments
have NAME_METHOD permission; all 28 tutor payload preparations (two providers)
fit with the required 8,192-unit headroom. No paid calls were made.

Initial fixture implementation exposed five blockers, now resolved by
[contextual work verification](../plans/2026-10-31-contextual-work-verification.md):

| Case | Existing verifier limitation |
| --- | --- |
| 05 | The valid chained discriminant equality is unreadable to the parser. |
| 07 | Coefficient declarations followed by a discriminant calculation are treated as an invalid equivalence transition. |
| 08 | Valid coefficient declarations followed by formula substitution receive an equivalence error. |
| 10 | The same mixed-work limitation affects the valid switch to the quadratic formula. |
| 12 | Selecting one factor's zero branch does not preserve the entire solution set, so the linear step verifier incorrectly treats the intended branch as erroneous. |

The fixtures preserve raw work and now require no false step errors plus explicit
verification scope notes. Coefficients are checked against the exercise or a
verified equivalent quadratic form; calculation links are checked individually.
Partial factor branches are accepted only in draft questions, with remaining
branches explicitly pending. Strict equivalence and final-answer checks remain
unchanged. The fixed judge prompt was not modified to ignore engine errors.

Cases 13 and 14 replay real wrong submissions and retain the checked revision,
with no delivered tutor response. The engine records the structured WRONG verdict,
but has no separate system-feedback prose event. The briefs' generic displayed
feedback is an explicit UI assumption, recorded in fixture notes; it is not
fabricated as a tutor message. Their current student questions still refer to
the rejection, and the tutor receives the actual historical verdict.

Authored item statements use text/formula blocks with normalized display wording;
all mathematical exercises, raw student work and questions are retained. The
source contains no ideal tutor response or expected judge score. Item worked-step
keys are empty: curated evaluator references link calculations and word-problem
models to the task, without pretending every line is an equation transformation.
