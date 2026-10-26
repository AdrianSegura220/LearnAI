# Provider-neutral evaluation and OpenAI adapters

**Date:** 2026-10-26. **Status:** draft for user review; no implementation authorized by this document.

**Builder check:** a fresh independent reviewer found no important unanswered questions on 2026-10-26. Detailed implementation interfaces remain the plan's responsibility. User approval of this written design is pending.

**Baseline:** merged Plan 2A, `40d2559`; 1,219 keyless tests passed in the user's merged checkout. Parent: [platform design](2026-09-14-ai-tutoring-platform-design.md). This extension preserves its engine and pedagogy rules. See [Plan 2A design](2026-10-16-anthropic-tutor-eval-design.md) for existing exchanges and evaluation semantics.

## 1. Intent and agreed scope

Allow explicit, independent selection of Anthropic or OpenAI for tutor routes and the offline rubric judge. Provider-specific API and construction logic belongs to each provider adapter. Scenarios, replay, judge packets, rubric semantics, reporting and comparison use shared contracts.

The user selected independent tutor/judge providers: an OpenAI tutor can be evaluated by an Anthropic judge and vice versa. They also agreed to preserve Anthropic support, add OpenAI tutor and judge implementations, and test mixed-provider execution. This document's detailed module boundaries, migration choices and defaults are the author's proposals unless identified as existing behavior.

Success means the same real-engine corpus runs through either provider, an evaluator can remain fixed while tutor providers change, and saved responses can be rejudged with either provider without tutor generation. A second provider must preserve existing guarantees rather than introduce alternate mastery or validation behavior.

### Approaches considered

1. **Select one provider for an entire run.** Simpler construction, but switching the tutor also switches the judge and confounds comparisons. Rejected in the conversation.
2. **Shared role contracts with explicit provider implementations and construction modules.** Selected. Independent routing and one evaluator pipeline, with provider-owned transport and usage interpretation.
3. **A universal model gateway or dynamic plugin framework.** Adds an abstraction for providers and features not needed here. Outside this extension. Two explicit registrations are sufficient.

### Non-goals

No automatic fallback, dynamic provider discovery, model ensembles, multi-judge voting, hosted agent framework, extra subjects or modes, persistence, HTTP/auth, UI, validated streaming delivery or strict CAS worker isolation. Those service/product boundaries remain unchanged. This work does not authorize paid calls, promise equivalent teaching quality across models, or replace human calibration.

## 2. Current coupling to remove

The domain already uses `Tutor` / `TutorExchange`. Shared context selection, read-tool handlers, prompt loading and `ResponseBudget` can be reused. However:

- `anthropic/routing.py` defines shared route/profile types and rejects every other adapter; shared runtime imports it.
- `eval/judge.py` combines neutral packets/scores with an Anthropic SDK entry point.
- `eval/__main__.py` checks one provider's key and constructs its clients/tutors directly, including smoke.
- `eval/accounting.py` decodes Anthropic raw usage, while `eval/runner.py` summarizes vendor-specific counters.
- Trace types and package placement are inconsistent: tutor traces are shared, judge traces live in the Anthropic package.
- CLI preflight, manifests, admission tests and live probes contain provider assumptions that a new directory alone would not remove.

The extension must address these boundaries together. Copying the evaluation runner per provider or placing SDK calls behind provider-named branches in shared evaluation is not the selected architecture.

## 3. Responsibility and dependency boundaries

| Component | Owns | Must not own |
|---|---|---|
| Domain | Current work, history, verification, assistance, mastery, turn validation and exchange protocol | SDKs, credentials, provider selection, judge execution |
| Shared tutor infrastructure | Route/profile data, budgets, context selection, read-tool contracts, semantic turn parsing, normalized observations | Provider request schemas, SDK exceptions, vendor usage interpretation |
| Shared evaluation | Replay, exact captured contexts, references/packets, rubric loading, strict scores, reporting/comparison and ledgers | Vendor clients, raw vendor usage parsing, provider-specific argument validation |
| Provider adapter | Wire schemas, prompt/message encoding, tool/result pairing, continuation items, retries/errors, raw usage normalization and local admission | Scoring policy, scenario expectations, mastery changes, full evaluation orchestration |
| Application composition | Explicit provider registration, route validation, credential requirements, client lifecycle and constructing role implementations | Judging correctness, overriding engine state or silent provider substitution |

Dependency rule: domain imports no adapters or evaluation. Shared evaluation may import neutral tutor infrastructure and shared evaluation contracts. Only composition and provider packages import provider implementations/SDKs. Adapters implementing the judge port may depend on neutral evaluation packet/score definitions; shared evaluation never imports them back. Enforce this with architecture tests, including transitive shared helpers such as runtime/routing.

### Proposed module organization

- `adapters/tutor/routing.py`: provider-neutral `Route`, `BudgetProfile`, YAML loading and job-to-route resolution.
- `adapters/tutor/turn_schema.py`: semantic `TutorTurn` parser and field definitions. A provider owns its actual JSON Schema encoding.
- `adapters/tutor/runtime.py` and `observations.py`: existing shared budget machinery and normalized attempt/exchange data.
- `adapters/tutor/anthropic/`: existing tutor and judge execution, provider schema encoding, usage mapping and `wiring.py`.
- `adapters/tutor/openai/`: Responses API tutor and judge execution, provider schema encoding, usage mapping and `wiring.py`.
- `eval/judge.py`: preserve existing packet/reference/score classes, packet serialization, rubric requirements and strict score parser; remove SDK imports and provider construction.
- `eval/ports.py`: small `Judge` protocol consuming `JudgePacket` and returning `JudgeScores`; errors and observations use neutral types.
- `application/providers.py`: a static registry and operation-scoped composition. It calls provider-owned construction modules through explicit callbacks.
- `application/tutor_router.py`: job-to-route/provider dispatch behind the existing domain `Tutor` port.
- `eval/__main__.py`: preflight, phase orchestration and finalization through the composition interfaces; no SDK imports or provider-name conditionals.

The implementation plan must fix exact signatures and reviewable task boundaries. This layout is a design decision, not permission to refactor unrelated application code. No new generic agent loop is required: provider loops retain their wire-specific behavior and reuse common budgets/tools/validation contracts.

## 4. Role selection and construction

A route continues to identify its name, adapter, model, versioned prompt and budget profile. Existing job names and enabled/disabled complex behavior remain. Select a tutor route at `begin_turn` using the engine-authored response job; bind one provider/model for the full exchange, including retries. The router must not select another provider midway through a turn.

The offline judge is independently selected by `--judge-route`. Smoke uses the same configured tutor job routing and remains phase `smoke`; it never creates another accounting stream or requires the judge provider.

The composition layer uses explicit registrations for `anthropic` and `openai`, each supporting route validation, required credential names, client construction, tutor construction and judge construction. No importing arbitrary modules named in YAML. Provider wiring owns SDK options and endpoint choice; evaluation receives only role objects and normalized observations.

Construct one client per actually used provider per operation, reuse it where appropriate, and close every constructed client in `finally`, including partial construction failures. Do not mutate shared sinks to change phases or attribution: each exchange has immutable observation scope identifying tutor/judge/smoke and scenario/session as applicable. Client reuse must not share exchange histories or budgets.

### Preflight before side effects

1. Parse configuration and validate structural route/profile/prompt references locally.
2. Load/select and replay fixtures, or validate every saved packet/hash for rejudge.
3. Resolve the actual operation's role routes and applicable provider settings, serialize request framing needed for admission, and validate output/captured input paths.
4. Determine credential and optional SDK requirements from only those roles. Check local availability without creating SDK clients or making network calls.
5. Capture resolved settings/provenance, then construct clients and execute.

Unknown providers, unsupported selected options, missing selected prompts/SDKs/keys and invalid input artifacts fail with local exit 2 before any client/network call. Structural errors anywhere in the configuration still fail parsing. Unused reserved routes do not cause credential checks, client construction or model-compatibility requests. There is no remote model discovery during preflight.

`run --no-smoke` resolves selected eligible tutor jobs and the judge only if accepted candidates can be produced; `rejudge` resolves only the chosen judge, never source-run tutor credentials. A selection containing exclusively expected non-tutored operations executes deterministically and requires no provider credentials/client. Because smoke can produce tutor questions, enabling smoke requires its configured tutor routes even when selected scenarios have no tutor opportunity. Read-only comparison/import/review requires no credentials, provider SDK imports or calls.

The plan should remove/replace the CLI's single `client_factory` injection with explicit per-provider test factories at the composition boundary. Preserve command meanings and keyless scripted integration coverage, not a vendor-specific internal injection signature.

## 5. Configuration and shared contracts

Keep existing Anthropic YAML valid and default routes unchanged. Real commercial model identifiers remain in `config/llm_routes.yaml`; fictional labels are allowed in tests. OpenAI examples/settings in that file can be activated explicitly; adding the dependency does not switch the default tutor or judge.

Retain common route fields, including the existing `max_tokens` as a logical per-call output ceiling. Provider encoding maps it to its API parameter; it is capped by the shared remaining output allowance. Keep legacy Anthropic `effort`, `thinking`, `temperature` and `stream` syntax readable. Shared parsing validates types and identity; provider validators own allowed values/combinations. OpenAI must reject an Anthropic `thinking: adaptive` option rather than silently ignoring it. A small `provider_options` mapping may carry genuinely provider-specific options; each provider validates an explicit closed set. No arbitrary SDK kwargs escape hatch.

Resolved manifests record exact effective settings and defaults, not only the original YAML. Model-specific supported combinations and the OpenAI SDK version must be verified and pinned during implementation using official documentation and an offline scripted request. The author delegates initial optional OpenAI model selection to the implementer, with documented rationale and capabilities; no unverified model identifier or commercial rate is invented by this spec. Actual service compatibility remains a separately authorized live gate.

The domain's turn contract, `MAX_TUTOR_RETRIES`, assistance policy and verification behavior do not change. Provider wire schemas may differ. Both feed the same semantic parser and deterministic validator. In particular, OpenAI strict schemas must express optional semantic fields using the supported required/nullable representation, then normalize to the existing turn semantics. Do not impose vendor schema restrictions on domain dataclasses or assume the existing Anthropic JSON Schema can be sent unchanged.

`Judge.evaluate(packet)` returns the existing strictly parsed `JudgeScores` or raises neutral `JudgeError`. Provider adapters translate operational failures; an abstention is still a valid explicit insufficient-evidence score result. Shared evaluation retains rubric text/version, references and scoring semantics. Providers only encode and execute the judgment request. Moving classes must not change saved packet type identifiers: keep the existing `learnai.eval.judge` definitions in place.

## 6. OpenAI Responses exchange

Use the official Python SDK and Responses API directly. Preserve LearnAI's own request-scoped loop; no hosted agent orchestration, remote tools, stored Conversations or server-side history ownership is introduced.

- Build provider instructions from the existing stable policy/skill/profile layers and the selected current context. No automatic answer keys or evaluator-only references enter tutor input.
- Manage the complete ordered Responses item history locally. Pair each custom `function_call` with the correct `function_call_output` by `call_id`; support multiple calls in one response without dropping or duplicating results.
- Carry opaque reasoning/continuation items forward as required by the selected API/model, including encrypted continuation data where needed. Request `store=false`; use supported encrypted-item inclusion when applicable. Preserve returned items as data, never request or expose private chain-of-thought, fabricate reasoning, or reconstruct an incomplete streamed item as a completed one.
- Repeat the required effective instructions on each request. Do not rely on a previous remote response ID to supply policy/context, or assume it avoids input billing. Record state/caching options in provenance.
- Encode final `TutorTurn` and judge scores as supported structured outputs. Refusals, incomplete responses, malformed payloads and empty text are distinct operational outcomes. They do not bypass local validation or produce a partial student reply.
- Existing read-only tools remain local; the engine has no new write path. Validation correction uses provider-supported instructions plus retained rejected output/history, not student-authored instruction text.
- At the soft threshold disable further exploration in provider-supported encoding, retain schemas/history compatibly, and reserve final output. At hard/token/context/tool/round limits return traced silence. Do not discard an unmatched tool call to force finalization.
- Set SDK automatic retries to zero. Preserve existing bounded API retry policy and one response budget across API, format and engine validation retries. A partially received response is not blindly replayed; retain observed usage and mark incompleteness.

Buffered delivery remains the product boundary. If an implementation uses SDK streaming internally for deadlines/trace capture, it must retain complete final item ordering and account for missing terminal usage. This does not add student-visible streaming or a strict preemption guarantee for synchronous socket/CAS work.

OpenAI cache behavior is provider-owned. Preserve stable-prefix placement, but do not send Anthropic cache-control blocks or claim identical cache write/TTL semantics. Capability/minimum/retention prerequisites for the selected model are verified and documented before live cache assertions.

## 7. Observations, usage and prices

Every new attempt identifies `provider`, API family, logical exchange/attempt identity, role phase, scenario/session, requested and returned model, effective settings, UTC/monotonic timing, outcome/retry reason and provider request ID when available. Preserve raw request/response/usage privately. Missing returned model or usage stays unknown. SDK objects never enter shared ledgers.

Introduce a neutral usage observation containing disjoint billable category counts, completeness status and explicit incompleteness reasons; retain supplementary nonbillable details separately. Provider mappers produce it before emission. Shared ledgers aggregate/prorate normalized counts only; they must not inspect vendor raw keys or infer provider identity from model names. Missing counts are distinguishable from explicit zero.

- Anthropic preserves existing uncached input, cache read, duration-specific write and output normalization. Do not double-charge aggregate plus nested creation counts.
- OpenAI subtracts documented cached input from inclusive input totals to obtain disjoint uncached input; reasoning output is a subset of output and is not added again. Validate nonnegative counters and subset bounds. Additional reported categories such as cache writes must be explicitly mapped according to the selected API's documented semantics, or make cost incomplete; they cannot silently disappear or be assigned Anthropic rates.
- Partial streams/API failures preserve observed known counts plus incompleteness. Unknown fields/billing conditions/rates/models retain known subtotals with reasons; no fabricated zero, invoice claim or budget upper bound.

Price lookup is keyed by provider, returned model and applicable billing conditions, using dated/source-linked snapshots. Provider-specific billing categories/conditions remain representable without branching in shared evaluation. Extend the configuration loader for multiple provider snapshots; accept legacy single-provider pricing as explicitly Anthropic during migration. Missing rate coverage makes an estimate incomplete, not a credential/startup error. Decimal arithmetic and phase reconciliation remain; retry cost is an overlapping breakdown, not an additional charge.

The runner's convenience usage summary must consume neutral observations instead of adding Anthropic raw keys. Artifacts retain raw provider details separately. The same attempt cannot be charged once through its trace and again through a scenario summary.

## 8. Artifacts, compatibility and comparisons

Write an explicit new observation/manifest schema version for new provider-aware runs. Include provider IDs per requested/returned role, API family, SDK versions actually used, effective defaults/settings, policy/rubric IDs, schema/usage-mapper versions, token-counter identity, captured source/fixtures/references, saved packet input hashes and billing snapshots. Preserve existing unique run identity versus material-input fingerprint rules. Secrets and credentials never enter captured artifacts.

Read existing Plan 2A artifacts. Legacy version-1 request records are identified as Anthropic only through an explicit, version-gated compatibility reader; never default arbitrary new records to Anthropic. Keep original artifacts immutable, validate saved packets before client construction, and emit linked version-2 runs for rejudging. Cross-version comparison must disclose schema/normalization differences rather than claim fixed inputs. Unknown versions fail read-only/local validation clearly.

Providers are part of model identity even if labels coincide. Separate tutor-provider/model changes from judge-provider/model changes. A tutor comparison may intentionally change tutor provider/model; it must keep scenario/reference material, judge provider/requested settings/observed returned model, rubric and relevant execution inputs fixed. Generic configuration equality and controlled tutor comparison are distinct report judgments: changing the tutor changes the full fingerprint but does not by itself invalidate the declared treatment comparison. Changes to judge/provider or missing evaluator identity require a comparability caveat. Surface setup differences before score deltas; preserve abstention/error denominators.

`run` still executes all selected tutor scenarios before judge calls, then optional smoke. The provider for each role/response job is explicit; phase order, captured context/candidate pairing and partial artifacts survive mixed-provider failures. `rejudge` only evaluates saved candidates using the selected judge and records source run hashes, without tutor generation or requiring original tutor credentials. Provider-aware error finalization must retain earlier completed requests and close clients even when a later provider fails.

## 9. Verification and acceptance

### Keyless architectural and behavioral checks

1. Architecture tests prohibit provider/SDK imports in domain and shared eval/runtime/routing/accounting, allowing only the designated application/provider construction modules.
2. Existing Anthropic configuration, behavior, 71 fixtures and 54 actual opportunities remain; all original engine/evidence/history/assistance tests pass.
3. A shared tutor conformance suite exercises both adapters through real engine transitions: tools, multiple calls, corrected turn, revised work/stale verification, history retrieval, delivered NONE, silence/refusal/limits and no mastery write path.
4. Strict SDK-boundary OpenAI scripts inspect actual Responses requests/items/settings and replay complete, incomplete, malformed, refusal, retry and partial-stream responses. No paid calls or fake successful usage on failure.
5. Both providers admit all actual corpus tutor contexts and judge packets using their real framing, checked-in/fallback profiles, production counter and useful continuation/output headroom. Existing overflow tests remain. Schema differences never weaken the semantic parser/validator.
6. All four tutor/judge provider combinations use the same replay/report orchestration. Script tutor A/B before judge A/B; assert matching captured moments and candidates, immutable observation scope, one record per attempt, phase-only smoke and client closure.
7. Selected-provider-only credentials/SDKs: an unused missing key/package is harmless; either selected missing key fails before constructing any client; rejudge needs only the judge; read-only comparison needs neither. A deterministic no-tutor/no-smoke selection creates no clients.
8. Literal accounting tests cover OpenAI inclusive/cache/reasoning subsets, Anthropic duration writes, unknown/malformed/partial usage, colliding model labels across providers, mixed phase/retry totals and incomplete rates. Shared code cannot parse vendor raw usage.
9. Legacy artifacts remain readable/rejudgeable and immutable. Provider-aware new packets roundtrip; unsupported versions, malformed packets and changed hashes fail before any client. Comparison distinguishes intentional tutor treatment changes from changed evaluator/reference inputs.

The ordinary suite stays keyless and excludes all `live` tests even when either/both keys exist. Existing Anthropic probes remain; add two OpenAI probes (cache prerequisites/read observations and a real engine-accepted turn), so explicit collection contains four tests total unless the implementation plan deliberately specifies an equivalent parameterization with the same four collected cases. Each requires only its own provider key and explicit selection; key presence alone never spends money.

### Separate live and quality gates

During implementation, pin the OpenAI SDK and record official model/API/schema/cache/usage compatibility notes. Paid probes execute only with explicit authorization and locally configured keys; report unexecuted probes as unverified. Mixed-provider live runs and full-corpus spend remain separately selected operations, not automatic post-test steps.

When actual provider comparison is authorized, keep one judge/rubric/reference set fixed and disclose provider/returned model differences. Human review/calibration remains necessary before trusting judge thresholds. Model support, passing scripts and schema adherence do not establish mathematical teaching quality, latency targets or actual account billing.

## 10. Implementation sequencing and decisions delegated to the plan

First establish neutral configuration/contracts/observations and migrate Anthropic plus shared evaluation without behavior changes. Then implement OpenAI against those contracts, wire mixed-provider execution, and add the cross-provider conformance/accounting/artifact/live gates. Each task needs a reviewable deliverable and exact consuming/producing interfaces; extraction must not leave a half-migrated shared runner depending on SDK details.

The plan fixes exact factory/registry/observation signatures, migration helpers, test fixtures and module splits. The implementer chooses a supported initial OpenAI model/SDK pin using official evidence, records those choices in configuration/notes, and preserves the existing default provider. SDK installation and production code are implementation work, not part of drafting this spec.

## 11. Official OpenAI evidence and remaining verification

Consulted 2026-10-26. These sources support the API approach; they do not establish live compatibility for a particular account/model or authorize execution:

- [Responses migration](https://developers.openai.com/api/docs/guides/migrate-to-responses): typed input/output items, function result mapping, instruction/state handling and local continuation considerations.
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling): custom tools, call identifiers and multi-step function loops.
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs): supported JSON Schema subset and provider-specific strictness requirements.
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching): prefix identity, cached-token reporting and model-specific prerequisites.
- [Responses reasoning items](https://developers.openai.com/cookbook/examples/responses_api/reasoning_items): retaining reasoning/continuation items across tool interactions and encrypted state.

Before implementation, verify current SDK request/usage types and the exact selected model's options against those sources. Do not use the Agents API's similar usage fields as proof of Responses billing semantics. Date/source commercial price snapshots separately when selected.
