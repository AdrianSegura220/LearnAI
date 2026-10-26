# Tutor evaluation

As of 2026-10-26, Plan 2A Tasks 1–14 are implemented and reviewed. Task 15 adds
opt-in compatibility probes, output privacy defaults and this run guide; its
keyless implementation is pending independent review. The implementation ledger
is [progress.md](../.superpowers/sdd/2026-10-16-slice1-plan2a-tutor-eval/progress.md).
Earlier dated review-only notes describe historical scope.

No paid live compatibility run or full paid evaluation has been performed for
this task. Explicit live-run authorization remains unresolved, and credentials
were unavailable. There is no reviewed live reference summary or human-calibrated
judge acceptance result. Keyless SDK/HTTP fixtures establish protocol construction,
engine validation, replay, accounting and artifact behavior; they do not establish
provider compatibility, teaching quality, production latency or actual billing.

## Keyless checks and explicit live probes

From the repository root, using the installed development environment:

```sh
.venv/bin/pytest
.venv/bin/pytest -o addopts='' -m live --collect-only -q
```

Ordinary pytest excludes `live`, even when `ANTHROPIC_API_KEY` exists. Explicit
collection lists exactly two live tests and makes no API calls. Each live test
also skips when the key is absent or blank. Keep credentials in your local
environment or secret manager; never paste them into commands, configuration,
fixtures, reports or commits. This project does not load a `.env` file.

Only after explicit authorization for paid execution and local credential setup,
run the small probes before spending on the full corpus:

```sh
.venv/bin/pytest -o addopts='' -m live tests/adapters/tutor/test_live.py -v -s
```

The first probe makes two sequential engine exchanges with an identical cached
system/tool prefix and changing student history. It records raw cache creation/read
usage and requires a repeat cache read. The second sends revised draft working and
a question through the real engine and adapter, preserving the old submission as
historical evidence, then requires an engine-accepted `TutorTurn`. Both check actual
configured settings, provider content, accumulated message history, tool/result
pairing and runtime traces. Provider-returned model resolution is retained alongside
the requested model. Model identifiers live only in
[config/llm_routes.yaml](../config/llm_routes.yaml).

Cache prerequisites: the configured model must support explicit ephemeral caching,
adaptive thinking/effort and the selected structured-output/tool settings. The
minimum cacheable prefix for the configured model was **512 tokens** in the
[official caching documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching),
checked 2026-10-26. Recheck support and the minimum when changing the route. The
prefix includes tools and stable policy/skill blocks; student work/history belongs
in volatile messages. A first completed response must establish the cache before
the repeat, within its five-minute lifetime. The test uses provider-reported cached
tokens to establish that the prefix cleared the minimum; total input tokens alone
cannot establish that prerequisite. A zero cache count can reflect an undersized
prefix, unsupported settings, routing/account/cache availability or expiry. It does
not by itself prove volatile-prefix leakage. Both cold creation and an already-warm
first read are valid first-call evidence.

The probes save private `eval/reports/live-<uuid>/measurements.json` artifacts,
including traces on failed assertions. They use the configured engineering budgets
unchanged. An exhausted exchange fails compatibility with its typed termination
reason; an accepted slow response records elapsed time without failing a quality
check for missing a provisional latency goal. These three exchanges are a small
compatibility sample, not a latency distribution or semantic calibration.

## CLI operations

The headless CLI is `python -m learnai.eval`; there is no application server.
`run` and `rejudge` perform paid provider operations and require the local key.
The following are invocation examples, not evidence they have been executed:

```sh
# Full corpus: tutor phase, judge phase, then persona smoke (default).
.venv/bin/python -m learnai.eval run

# Ordered subset, without persona smoke.
.venv/bin/python -m learnai.eval run \
  --only leak-solve.factoring,leak-expand.binomial --no-smoke

# Explicit fixtures, configuration, judge route and output directory.
.venv/bin/python -m learnai.eval run --fixtures eval/fixtures \
  --routes config/llm_routes.yaml --judge-route rubric_judge --out eval/reports

# New judge calls on saved candidates; no new tutor generation.
.venv/bin/python -m learnai.eval rejudge eval/reports/SOURCE_RUN_ID \
  --routes config/llm_routes.yaml --judge-route rubric_judge --out eval/reports

# Read-only saved-artifact comparison: no key or provider call.
.venv/bin/python -m learnai.eval compare eval/reports/LEFT_RUN_ID eval/reports/RIGHT_RUN_ID
```

`run --only` accepts comma-separated scenario ids, in the supplied order, and rejects
unknown/duplicate ids locally. `--fixtures` defaults to `eval/fixtures`; `--no-smoke`
skips persona smoke, not the judge. `run` and `rejudge` share `--routes` (default
`config/llm_routes.yaml`), `--judge-route` (default `rubric_judge`) and `--out`
(default `eval/reports`). Defaults resolve from the project root. `rejudge` accepts
one or more source run directories. Exit status is 0 for completed operations,
1 for operationally incomplete/error runs, and 2 for local validation failure.
An interrupt retains partial artifacts where writing succeeds and propagates the
interrupt. Local preflight validates the selection and writable output before
constructing the client. Provider-side failures can still incur costs.

`report.json` and `summary.md` summarize outcomes, rubric scores, coverage, latency,
cost and persona smoke. Judge abstentions/errors remain separate from numeric
scores, and selected/eligible/scored denominators remain visible. Per-case outcomes,
typed judge packets, private tutor/judge traces, `requests.jsonl`, `manifest.json`
and captured `inputs/` preserve the actual execution. An incomplete run retains
finished work and identifies unexecuted cases. Inspect saved artifacts locally to
review them without spending money. Rerunning `run` generates new tutor responses;
`rejudge` spends on new judge responses while retaining source candidates/contexts
and linking source run, manifest and packet hashes.

## Reproducibility and judge calibration

Prompt policy lives under `prompts/` with references such as `tutor_math@1` and
`rubric_judge@1`. Create a new versioned file and update the YAML reference when
iterating; do not silently rewrite a version intended for comparison. Reports
capture prompt ids **and content**, rendered requests and actual settings.
Matching prompt ids alone never proves comparability.

Each execution has a unique run id. Its configuration fingerprint hashes captured
source/content/prompts/configuration/fixtures, selected case order and seeds,
generated inputs/references, runtime/dependency versions, route/budget/evaluator
settings and saved-packet inputs where relevant. Run ids/times, outputs, usage and
observed latency are excluded from this configuration identity. A fingerprint is
provenance, not a promise of identical nondeterministic generations. Requested
aliases and provider-returned models are recorded separately.

`compare` reports changed inputs/settings and evaluator/reference differences before
numeric differences. Direct tutor comparisons require the evaluator, rubric,
references, candidate situations and relevant execution inputs to be held fixed;
returned judge-model changes also invalidate that claim. A tutor-model change can
be the experiment while the evaluator stays fixed. Inspect overlap, coverage,
denominators and actual returned models before interpreting score movements.

The rubric judge is an offline instrument and never adds to delivery latency.
Human calibration remains required: review complete student-situation/candidate/
reference packets, inspect abstentions and disagreements, and version changes to
the rubric or references. Passing scripted judge tests or obtaining numeric scores
does not establish semantic calibration. A live corpus run, individual review of
slow simple replies and human review of a reference summary remain outstanding.

## Response budgets and latency

The approved product targets are [parent design §10.3](../docs/superpowers/specs/2026-09-14-ai-tutoring-platform-design.md#103-interactive-latency-and-execution-budgets):

| Response | Desired useful validated feedback | Investigate |
| --- | --- | --- |
| Interface action/deterministic result | Under 1 s where feasible | Repeated multi-second delays |
| Brief clarification | 1–3 s | Regularly above 5 s |
| Normal hint/diagnosed-error explanation | 3–8 s | Regularly above 10–15 s |
| Substantial checked explanation | 8–20 s | Above 30 s |
| Exceptional complex analysis | 20–30 s | May extend to 60 s with honest progress |

The current YAML profiles are provisional engineering choices:

| Profile | Soft/hard seconds | Model rounds/tools | Total output/reserve tokens | Context admission allowance |
| --- | --- | --- | --- | --- |
| brief | 3 / 8 | 4 / 8 | 4096 / 512 | 16000 |
| normal | 8 / 15 | 8 / 16 | 8192 / 1024 | 40000 |
| substantial | 20 / 30 | 12 / 24 | 16384 / 1024 | 48000 |
| complex (reserved) | 30 / 60 | 20 / 40 | 32768 / 2048 | 64000 |

Context admission counts the complete serialized request as UTF-8 bytes plus
framing margin and reserves the next call's output. The revised allowances admit
all 54 committed tutor opportunities and their judge packets without truncating
active work or history. The largest initial requests leave 9,043 admission units
for tutor continuation and 16,454 for the judge, beyond their output reservation.
These engineering input allowances do not change the latency targets or output
ceilings. The overflow guard still applies to every subsequent call.

Live engine jobs currently route BRIEF, NORMAL and SUBSTANTIAL; COMPLEX remains
disabled. All model/API/format/validation retries and tools share one exchange
budget. Thinking and retry output count toward the output allowance. Soft limits
stop exploration and preserve finalization room; hard limits discard late output
and leave the student with silence and unconsumed assistance. Profile hard ceilings
are not product promises. Local conservative token counting is admission control,
not provider billing measurement.

2A measures **buffered time to the accepted turn**, using an injected monotonic
runtime clock separate from pedagogical UTC time. This includes model/tool/retry/
validation work within the exchange; it is not time to first token or UI delivery.
The report groups accepted median/p95 and sample counts by response job, with
failure/silence and exhaustion counts/rates alongside quality and coverage. Inspect
typed traces for deadline failures as well: the current exhaustion aggregate counts
`*_exhausted`/`*_limit`, while deadlines also contribute to failures. Never interpret
fast accepted-only samples without the failures. Review slow simple replies
individually before tuning budgets. Synchronous CAS/socket operations cannot be
forcibly preempted in 2A, so strict wall-clock isolation is not guaranteed. Worker
isolation arrives in 2B; progress/cancellation and first validated streaming chunks
arrive in 2B/2C. Raw streaming or a spinner is not useful validated feedback.

## History, reconstruction and private artifacts

The tutor retrieves only scoped **current-session** history. The engine supplies
authoritative current exercise, work revision, question/status and deterministic
checker scope. Draft answers remain unchecked as final submissions. Token selection
protects active work and preserves exercise boundaries; older records retain their
provenance. Cross-session durable storage/retrieval is deferred to 2B. Rejected
drafts, internal tool exchanges and private operator feedback never become delivered
history or history-tool results. Delivered task assistance spends independence even
when it advances no hint rung.

Evidence replay rebuilds mastery from append-only attempts/help events with the
same rules and parameters. Interaction reconstruction uses question/work snapshots,
revisions, delivered replies and recorded private traces to inspect the actual
response. Rerunning an LLM is a new generation and cannot reproduce exact wording
by guarantee. Durable interaction storage, database/HTTP/UI integration and strict
CAS worker timeout enforcement are not implemented by this headless 2A slice.

Treat all run artifacts as private: they can contain student work, rejected text,
operator feedback, references and full provider requests/responses. Keep access
local and limited; inspect/redact before sharing. Keys are not manifest inputs and
must never be written into artifacts or prompts. `eval/reports/` and legacy
`eval/runs/` are ignored. Existing legacy artifacts are left in place. Never commit
arbitrary traces. Only an explicitly approved, reviewed and redacted reference
summary should be force-added, for example
`git add -f eval/reports/REVIEWED_RUN_ID/summary.md`.

Cost estimates use the dated direct-API price snapshot in the route configuration,
with [official pricing](https://platform.claude.com/docs/en/about-claude/pricing)
checked 2026-10-26. The ledger records all observed attempts across tutor, judge and
smoke, including retries, missing/partial usage and requested/returned models.
Cache creation durations are charged separately without double-counting aggregates.
Unknown model rates, missing/partial usage, unrecognized cache counters or unsupported
pricing conditions make the estimate incomplete: `total` stays unknown while the
known subtotal and unknown entries remain visible. Retry costs are an overlapping
subset of phase costs, not an extra amount to add. Tutor cost per accepted turn
includes failed tutor work in its numerator; all-in phase costs stay separate.
These are estimates, not invoices or cost/quality acceptance evidence.
