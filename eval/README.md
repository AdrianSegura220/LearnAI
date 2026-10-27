# Tutor evaluation

As of 2026-10-27, the Plan 2A baseline is implemented and reviewed. The
provider-neutral/OpenAI extension implements independent tutor/judge selection,
mixed-provider execution, normalized accounting, immutable legacy reads and v2
artifacts. Extension Tasks 1–7 are reviewed; Task 8's live gates and operator guide
are implemented pending independent task and whole-branch review. See the
[handoff](../docs/superpowers/notes/2026-10-26-plan2a-implementation-handoff.md) and
[OpenAI compatibility snapshot](../docs/superpowers/notes/2026-10-26-openai-provider-compatibility.md).

No paid live compatibility probe or full paid evaluation has been performed for
this extension. Paid execution requires separate explicit authorization. There is
no reviewed live reference summary or human-calibrated
judge acceptance result. Keyless SDK/HTTP fixtures establish protocol construction,
engine validation, replay, accounting and artifact behavior; they do not establish
provider compatibility, teaching quality, production latency or actual billing.

## Keyless checks and explicit live probes

From the repository root, using the installed development environment:

```sh
.venv/bin/pytest
.venv/bin/pytest -o addopts='' -m live --collect-only -q
```

Ordinary pytest excludes `live`, even when either or both provider keys exist.
Explicit collection lists exactly four cases: two Anthropic, two OpenAI, without
API calls. Each probe checks only its own key and constructs only that provider's
client; absent/blank keys skip its two cases. Provider markers `openai` and
`anthropic` do not enable live execution. A repository collection guard preserves
the configured `not live` exclusion even when CLI `-m openai` or `-m anthropic`
would normally replace pytest's default expression. Explicit opt-in must remove
that default with `-o addopts=''` and select `live`. Keep credentials in your local
environment or secret manager; never paste them into commands, configuration,
fixtures, reports or commits. This project does not load a `.env` file.

Only after explicit authorization for paid execution and local credential setup,
run the small probes before spending on the full corpus:

```sh
.venv/bin/python -m pytest -o addopts='' -m 'live and anthropic' \
  tests/adapters/tutor/test_live.py -v -s
.venv/bin/python -m pytest -o addopts='' -m 'live and openai' \
  tests/adapters/tutor/openai/test_live.py -v -s
```

For each provider, the first probe makes two sequential engine exchanges with
stable policy/tools/settings and changing student history. It records raw usage
and requires an observed repeat cache read. The second sends revised draft working and
a question through the real engine and adapter, preserving the old submission as
historical evidence, then requires an engine-accepted `TutorTurn`. Both check actual
configured settings, provider content, accumulated message history, tool/result
pairing and runtime traces. Provider-returned model resolution is retained alongside
the requested model. Model identifiers live only in
[config/llm_routes.yaml](../config/llm_routes.yaml).

Anthropic cache prerequisites: the configured model must support explicit ephemeral caching,
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

OpenAI uses the unselected `tutor_openai` configuration example. Its official
[cache guide](https://developers.openai.com/api/docs/guides/prompt-caching), checked
2026-10-27, describes implicit caching with a settings-dependent minimum for this
model generation. A numeric minimum for the selected tools/schema/effort is **not
established**. The probe checks stable instructions, tools, schema and cache
settings across sequential reuse, then requires positive provider-reported
`input_tokens_details.cached_tokens`. Zero reports an unmet prerequisite/read
gate; positive reads are runtime evidence. Neither total input nor our byte-based
admission counter proves a cacheable prefix. Recheck support when changing routes.

The probes save private `eval/reports/live-<uuid>/measurements.json` artifacts,
including traces on failed assertions (`live-openai-<uuid>` for OpenAI). They use the configured engineering budgets
unchanged. An exhausted exchange fails compatibility with its typed termination
reason; an accepted slow response records elapsed time without failing a quality
check for missing a provisional latency goal. These three exchanges per provider are a small
compatibility sample, not a latency distribution or semantic calibration.

## Installation and independent routes

Use Python 3.12+ and an editable checkout from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .           # Base Anthropic installation
.venv/bin/python -m pip install -e '.[openai]' # Add the verified OpenAI SDK pin
.venv/bin/python -m pip install -e '.[dev]'    # Both SDKs and offline test tools
```

The OpenAI extra pins `openai==3.39.0`; its native transport is `httpx2`, verified
at 2.16.0. Base Anthropic support remains installed. Unused named routes require
neither their credentials nor their optional SDK. New evaluation runs preflight
every **selected** role's package, configuration and credential before constructing
any client; a missing selected key prevents all calls, including a valid first
provider. Operation-owned clients are lazy, shared per provider and closed on
completion/failure. Caller-injected clients remain caller-owned.

All real model identifiers live in [config/llm_routes.yaml](../config/llm_routes.yaml).
The named `tutor_openai` and `rubric_judge_openai` examples are resolvable but never
selected automatically. Defaults remain Anthropic: BRIEF → `tutor_brief`, NORMAL →
`tutor_dialogue`, SUBSTANTIAL → `tutor_explanation`, judge → `rubric_judge`.
To activate an OpenAI tutor, copy `tutor_openai`'s adapter/model/effort/options into
the desired job route in a local YAML copy; retain that route's prompt and budget
profile and remove Anthropic `thinking`. Do this separately for each job you want
to change. Select the independent OpenAI judge with
`--judge-route rubric_judge_openai`, without changing tutor routes. An Anthropic
judge remains available with `--judge-route rubric_judge`. No fallback occurs.
OpenAI temperature requires effort `none`; omitted effort resolves to `none`.

Set only selected credentials through your environment/secret manager:
`ANTHROPIC_API_KEY` for Anthropic, `OPENAI_API_KEY` for OpenAI. Rejudge needs only
the selected judge's credentials/SDK, even if the source tutor used another
provider. Read-only comparison needs neither key nor SDK.

## CLI operations

The headless CLI is `python -m learnai.eval`; there is no application server.
`run` and `rejudge` perform paid provider operations and require selected role keys.
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

# Anthropic tutors with the independently selected OpenAI judge.
.venv/bin/python -m learnai.eval run --only leak-solve.factoring --no-smoke \
  --routes config/llm_routes.yaml --judge-route rubric_judge_openai

# New judge calls on saved candidates; no new tutor generation.
.venv/bin/python -m learnai.eval rejudge eval/reports/SOURCE_RUN_ID \
  --routes config/llm_routes.yaml --judge-route rubric_judge_openai --out eval/reports

# Read-only saved-artifact comparison: no key or provider call.
.venv/bin/python -m learnai.eval compare eval/reports/LEFT_RUN_ID eval/reports/RIGHT_RUN_ID

# Declare the tutor route(s) changed as the experiment.
.venv/bin/python -m learnai.eval compare eval/reports/LEFT_RUN_ID eval/reports/RIGHT_RUN_ID \
  --tutor-treatment tutor_dialogue

# Optional acknowledgement of attributable tutor-only dependency changes.
.venv/bin/python -m learnai.eval compare eval/reports/LEFT_RUN_ID eval/reports/RIGHT_RUN_ID \
  --tutor-treatment tutor_dialogue --allow-tutor-dependency-changes
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

New runs/rejudges write schema v2 provider/API identities, normalized usage,
condition provenance, role dependencies and pricing snapshots. V1 artifacts are
adapted in memory by the fixed Anthropic legacy reader; originals remain immutable.
Unknown legacy evidence stays unknown, and legacy adaptation does not establish
an identical evaluator. The committed synthetic `tests/fixtures/eval_v1/run`
compatibility fixture is the explicit test-data exception to private run artifacts.

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

Without `--tutor-treatment`, changed execution settings are reported as such.
With it, list changed tutor route names (comma-separated); only attributable tutor
provider/model/wire settings may vary. Prompts, candidate situations, references,
source, pricing snapshot and evaluator identity/dependencies must still be held
fixed. `--allow-tutor-dependency-changes` requires a treatment and acknowledges
tutor-only dependency differences; it cannot waive a judge dependency change.
Both current SDKs use `httpx2`: upgrading that shared dependency changes the judge
too, so a controlled tutor comparison is blocked even with the flag. The tool
reports invalidating reasons rather than promising a clean experiment.

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
active work or history. The limiting initial Anthropic requests leave 9,043 units
for tutor continuation and 16,454 for the judge, beyond their 2,048 output reservation.
The equivalent OpenAI framing leaves 9,346 and 16,347 units. These measurements
cover the existing default job routes under each provider's preparation; activating
different named routes/settings requires repeating admission checks.
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

OpenAI repeats instructions and locally replays ordered output items, encrypted
reasoning and matched function-call results with `store=false`; it does not use
`previous_response_id` or hosted conversation storage. This limits reliance on
provider continuation state, but is not a promise of zero provider retention:
cache settings and the provider/account data policy still apply. Both adapters
buffer until deterministic engine validation, including when SDK streaming is
selected. No raw model chunks are delivered to students.

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

Usage is normalized by the provider adapter into disjoint billable counts; the
shared ledger does not interpret raw vendor keys or infer provider from a model
name. Cached input and reasoning output subsets are not added twice. Provider/API,
requested/returned model and usage status remain explicit. Billing conditions
carry value, source (`returned`, `requested`, `documented_default` or `unknown`)
and evidence. A requested tier is not proof of the executed tier; mismatches stay
visible, and geography remains unknown without endpoint evidence. Missing counts
remain different from zero. The checked-in price snapshot covers Anthropic only:
OpenAI costs remain incomplete until an applicable, verified provider-aware
snapshot is supplied. A v2 price book may contain separate provider snapshots;
matching model labels never make their prices interchangeable.
