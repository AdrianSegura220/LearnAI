# Independent tutor generation — 2026-10-31

## Execution scope and status

The user authorized the next step after all fourteen fresh scenarios passed
semantic readiness. One tutor exchange was run per case, using the existing
pilot configuration with `tutor_math@2`: OpenAI `gpt-6-luna`, low effort,
2,048 maximum output tokens and the normal job budget. Existing bounded format
and validation repairs remained enabled. No case was selectively rerun, and no
judge or persona-smoke calls were made.

Private saved run:
`eval/reports/0e5b202f-b9f0-45a6-9608-bdb900a2f315/`.
Configuration fingerprint:
`621d159bd2522e63950d0f291633d26b104bbbfcceba39b1edd045b1900e7df3`.
The manifest captures dirty source contents, exact fixtures/items, prompt text,
effective settings, dependencies and the private operator script. The script and
route copy are under `eval/runs/2026-10-31-independent-v2/`; per-case checkpoints
also preserve intermediate outcomes. Raw artifacts remain private and ignored.

The standard command performs generation and judging together. A private operator
used the same provider services, replay runner, manifest builder and report writer
for this tutor-only run. The saved run has `status: incomplete`, `phase: tutor`:
generation finished; human review subsequently completed, while judge review
remains pending. Saved artifacts
load successfully through the production loader.

## Observed execution results

- Selected/executed: 14/14; accepted replies: 13; failed opportunities: 1.
- Judge calls and scores: 0. Human labels were recorded in the subsequent review
  described below, after generation and before any judge scoring.
- Model calls: 25; tool calls: 3; format repairs: 4; validation repairs: 4;
  API retries: 0. Repairs belong to the original exchanges, not extra samples.
- Accepted response latency: median 2.704 seconds; p95 6.420 seconds, n=13.
- Raw provider usage: 51,213 input tokens and 2,270 output tokens. No applicable
  OpenAI price snapshot is configured, so monetary cost remains unknown.

Case 04, `independent-04-multiple-errors`, ended with `format_exhausted` after
three drafts and two format repairs, in 6.263 seconds. All three drafts contained
the U+001B terminal escape character. The text guard rejected them; no reply was
delivered. The failed case remains in the denominator and review sheet. Private
rejected drafts and repair evidence remain in the trace. Do not substitute a
successful rerun for this result.

## Human review before judging

Read `human-review/review.md` inside the saved run. It includes all fourteen
student situations, delivered replies or missing-response status, earlier
session events, confirmed scores/reasons and links to complete context/reference
JSON. `human-review/human-scores.json` stores labels bound to response hashes.
The initial exporter checked fourteen cases, blank labels and omission of provider/model
labels and judge scores. Prior conversation may identify the configuration;
this is not a fully blinded model comparison.

The user reviewed all thirteen delivered replies and explicitly confirmed scores
and reasons before judge scoring. This was assistant-facilitated discussion, not
unaided independent human rating. Cases 1, 2, 3, 5, 6, 8, 10, 11 and 13 received
2 in all four dimensions. Other confirmed scores, in the order mathematics,
helpfulness, diagnosis, tone, are: case 7 (2, 1, 1, 1), case 9 (2, 2, 2, 1),
case 12 (0, 0, 0, 1), and case 14 (2, 1, 1, 1). Case 4 has no delivered reply
and remains unscored. Tool-verification honesty remains a separate trace review;
no completed manual honesty audit is claimed.

Suggested alternatives and future presentation improvements are saved separately
in private `human-review/discussion-examples.md`. They are discussion examples,
not replacements for the actual replies or additions to judge inputs. The user
endorsed clearer separation of reasoning steps and subsequently discussed a
structured-content contract; its proposed design is recorded separately in
`docs/superpowers/specs/2026-10-31-structured-tutor-content-design.md`.

Then judge the thirteen saved packets without regenerating tutor replies, using
the captured `rubric_judge@2` settings: `gpt-6.1-sol`, low effort, 2,048 maximum
output tokens. Verify the frozen prompt SHA-256
`a3f4451236fa1b9e434425162d2b8a6996e28e46e800d01cff81297b2d240a4d`
and route configuration first. Preserve all disagreements, errors and abstentions.
Do not tune prompts against this set while treating it as untouched evaluation.
