# Current OpenAI Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the optional OpenAI routes to current Luna/Sol with compatible cache settings and disjoint cache-write usage accounting.

**Architecture:** Extend the existing provider-owned configuration/usage helpers, preserving neutral composition, evaluation and domain contracts. Two sequential reviewable tasks: provider capability/accounting support, then configured routes/live gates/operator documentation.

**Tech Stack:** Python 3.12+, existing pinned OpenAI SDK and native HTTP transport, pytest.

**Spec:** `docs/superpowers/specs/2026-10-27-openai-current-models-design.md` (user-authorized migration).

## Global Constraints

- No paid calls, remote publication, domain policy changes, or Anthropic default changes.
- Real commercial model identifiers remain only in `config/llm_routes.yaml`; tests use fictional labels with explicit API profiles.
- Retain the existing SDK pin unless a demonstrated wire incompatibility requires changing it.
- Preserve SDK-free preflight/runtime payload parity, local opaque continuation, strict output/tool schemas, shared response budgets, buffered delivery, and four explicit live cases.
- Missing usage and required billing evidence remain unknown; do not invent zeros, rates, duration defaults or complete costs. Legacy usage and saved artifacts remain readable and immutable.
- Both checked-in and fallback profiles must admit all 54 actual tutor opportunities from 71 fixtures, with next-output reservation plus at least 8,192 extra units. No budget inflation.

## Review Focus

1. A required-reasoning route with omitted/none effort must resolve low/reject none before clients; local profile metadata must not leak into SDK arguments (Task 1).
2. Legacy and current cache options mixed together, or nested unknown fields, must fail locally rather than be silently forwarded (Task 1).
3. Inclusive cached/write/reasoning subsets must be billed once; missing duration details, inconsistent sums, booleans and excessive subsets retain known-only incomplete observations (Task 1).
4. Actual SDK tutor/judge requests and returned nested write details must agree with preflight and mapper output without changing retry/partial-stream behavior (Task 1).
5. Updated routes and cache probe must preserve default Anthropic behavior, original corpus admission, and no-spend live selection (Task 2).

### Task 1: Current API profiles and disjoint cache-write observations

**Files:** Modify `src/learnai/adapters/tutor/openai/{config,usage}.py`, `tests/adapters/tutor/openai/{test_config,test_usage,test_adapter,test_judge}.py`; add literal accounting regressions to `tests/eval/test_accounting.py` and extend `tests/support/scripted_openai.py` only if useful. Avoid unrelated transport/engine changes.

**Interfaces:** Preserve existing public signatures. `provider_options.api_profile` is `legacy`/`current`/`reasoning`, default legacy, removed from actual SDK payloads. Current/reasoning profiles resolve omitted effort to low and `prompt_cache_options` to `{'mode': 'implicit', 'ttl': '30m'}`; allow TTL `12h`, reject other/unknown nested options or mixed `prompt_cache_retention`. Of the two new profiles, only current permits explicit none. Both current profiles allow max. Legacy retains existing defaults/settings. Mapper/config identity becomes `openai-responses@2`; new disjoint categories `cache_write_30m` and `cache_write_12h` are provider-normalized before ledger emission.

- [ ] Add behavioral RED tests for profile defaults/local rejection, SDK payload/preflight parity, complete mixed-TTL normalization, absent/malformed/inconsistent/partial write detail, subset bounds, reasoning counted once, native returned nested fields and unknown condition preservation. Literal complete example: input 12000, reads 4000, writes 7000 split 3000/4000, output 200 yields input 1000/read 4000/write30m 3000/write12h 4000/output 200. No cache-write fields is legacy evidence, not an error. A positive aggregate without duration details remains partial; never assign it from requested TTL.
- [ ] Run the new tests before implementation and record meaningful expected failures.
- [ ] Implement the minimal provider helpers. With partial/conflicting evidence avoid fabricated uncached totals; preserve independently known subtotals and raw dictionaries. Add an independent literal Decimal pricing test using synthetic category rates so shared pricing demonstrably needs no vendor decoding. Keep unknown extra usage fields explicitly incomplete.
- [ ] Verify new cases plus existing OpenAI, observation, composition, accounting and import-boundary suites; run one full keyless suite before committing, both keys removed. Native SDK tests cover both tutor/judge and partial or failed response usage. No live calls.
- [ ] Self-review and commit `feat: support current OpenAI cache profiles and write accounting`; record exact helper behavior and tests in the task report for Task 2.

### Task 2: Current routes, live gates, admission and operator notes

**Files:** Modify `config/llm_routes.yaml`, `tests/adapters/tutor/openai/{test_live,test_live_protocol}.py`, affected route/composition/admission test helpers, `eval/README.md`, `docs/superpowers/notes/2026-10-26-openai-provider-compatibility.md`; add a concise current migration handoff. Do not rewrite historical fixtures or historical review evidence.

**Interfaces:** `tutor_openai`: Luna, low, api_profile current. `rubric_judge_openai`: latest Sol, low, api_profile reasoning. Add `tutor_openai_sol`: latest Sol, low, api_profile reasoning, normal tutor budget. Actual model IDs come from verified model pages and appear only in YAML. Each selected current route uses implicit 30m caching and standard service tier. Existing Anthropic job bindings/default judge remain fixed.

- [ ] Add or adapt meaningful configured-route/native request acceptance tests, preserving legacy-profile coverage. Test actual selected current-profile settings and rejection before clients rather than only constant values. Update admission helpers to measure the current profile through real factory preparation while retaining fictional test labels, original configured limits, all 71 fixtures/54 opportunities, and both budget sources.
- [ ] Update routes and existing live probe metadata/assertions to current cache settings and documented 1,024-visible-token minimum. Positive observed repeat reads establish actual eligibility; byte admission measurements do not prove billable prefix length. Do not add live cases, padding or paid calls. Keep retry-to-request attribution intact.
- [ ] Update current docs with profiles/models, cache-read/write categories and TTL prices/uncertainty, installation/commands and explicit live-unverified status. No invented price coverage or change to the frozen baseline artifacts. Record design choices and exact modified-file count in handoff.
- [ ] Run focused current/legacy SDK, mixed-provider/comparison, architecture and both corpus-admission suites. Explicitly collect four live cases and run only no-key skip gates; dummy keys may appear only in collection subprocesses. Finish one full keyless suite after final behavior changes; build the package offline if source/package compatibility warrants it.
- [ ] Self-review and commit `feat: configure Luna and Sol for OpenAI evaluations`; task review then whole-branch review close execution. No push/PR automatically.
