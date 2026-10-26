# Provider-neutral Evaluation and OpenAI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve Anthropic behavior while adding OpenAI tutor/judge adapters behind shared evaluation, independently selectable per role.

**Architecture:** Keep domain semantics and the existing request-scoped exchange protocol. Extract neutral configuration, observations and judge contracts; place provider construction, SDK framing and usage mapping behind explicit application composition. Both providers use one corpus, ledger, report and artifact pipeline.

**Tech Stack:** Python 3.12+, existing Anthropic SDK, official OpenAI Python SDK/Responses API, PyYAML, pytest, existing SymPy-backed verification. Verify and pin the OpenAI SDK when Task 5 establishes its actual offline wire contract; no dependency installation is part of writing this plan.

**Spec:** `docs/superpowers/specs/2026-10-26-provider-neutral-evaluation-openai-design.md` (approved 2026-10-26). Parent engine/pedagogy rules remain binding.

**Status:** planning only; all implementation checkboxes are open. Baseline: merged `main` at `40d2559`; user verified 1,219 passed and 2 deselected. Planning branch: `plan-openai-provider` in the existing isolated worktree. No paid execution, push, merge or production code is authorized by this plan's creation.

## Global Constraints

- Domain imports no adapters or evaluation. Every consequential pedagogical decision and mastery update remains engine-owned.
- Existing job names and enabled/disabled complex behavior remain.
- Keep existing Anthropic YAML valid and default routes unchanged.
- Real commercial model identifiers remain in `config/llm_routes.yaml`; fictional labels are allowed in tests.
- SDK automatic retries are zero; API, formatting, tools and engine validation share one response budget. Preserve existing output/time/tool/round limits and `MAX_TUTOR_RETRIES`.
- No automatic fallback, dynamic provider discovery, model ensembles, multi-judge voting or hosted agent framework.
- Provider wire schemas may differ. Both feed the same semantic parser and deterministic validator.
- Shared ledgers aggregate normalized counts only; they must not inspect vendor raw keys or infer provider identity from model names.
- Missing counts are distinguishable from explicit zero. Unknown usage/rates retain known subtotals and explicit incompleteness.
- Keep original artifacts immutable; validate saved packets before client construction.
- Ordinary tests stay keyless and exclude all `live` tests even when either/both keys exist. Paid execution requires separate explicit authorization.
- All original 71 fixtures and 54 actual tutor opportunities remain; preserve protected active work, history scope/provenance and existing overflow guards.
- Buffered engine-validated delivery remains the boundary; persistence, UI, cross-session access and strict CAS isolation remain deferred.

## Review Focus

1. A mixed run has one missing selected credential: no provider client or paid call starts; unused credentials/packages remain irrelevant (Tasks 4, 6, 8).
2. Tool output and a validation retry follow opaque OpenAI continuation items: retain order/call IDs, budget and checked context without leaking rejected text into delivered history (Tasks 5, 7).
3. An API failure supplies only partial usage, or cached/reasoning subsets overlap totals: keep honest disjoint accounting without duplicate charges (Tasks 2, 3, 5, 6).
4. A version-1 saved run is rejudged with a new provider: verify original hashes, require only the new judge, preserve source files and disclose evaluator/schema changes (Tasks 3, 4, 6).
5. A long active conversation fits one provider's framing but not the other's: actual configuration/payload admission must protect work and preserve useful output/continuation headroom (Task 7).

## File and interface map

| Area | Files and responsibility |
|---|---|
| Shared configuration/turn parsing | `adapters/tutor/routing.py`, `turn_schema.py`; legacy Anthropic import shims retain type identity |
| Observations | `adapters/tutor/observations.py`; existing `runtime.py` retains budgets and `TurnTrace`, imports neutral configuration/observations |
| Anthropic provider | `anthropic/{config,usage,wiring,legacy}.py`, existing adapter/judge; no orchestration copy |
| OpenAI provider | `openai/{__init__,config,encoding,transport,usage,adapter,judge,wiring}.py`; split wire encoding, SDK I/O and role loops |
| Shared judge | existing `eval/judge.py` retains serialized classes; `eval/ports.py` defines the judge port |
| Application composition | `application/{__init__,ports,providers,tutor_router,artifacts}.py`; registry, clients, role construction and legacy-reader selection |
| Evaluation/artifacts | existing `eval/{accounting,runner,manifest,report,artifacts,__main__}.py`; neutral normalized records, v2 artifacts, orchestration |
| Tests/docs | provider-specific transport suites, shared conformance/architecture tests, legacy synthetic artifacts, four collected live probes, `eval/README.md` |

Paths above are under `src/learnai/` unless stated. Exact interfaces below are authoritative across tasks; internal helpers may remain private. Do not combine these into a universal provider loop. Existing unrelated domain code is unchanged.

### Task 1: Extract shared routing and semantic turn parsing

**Files:** Create `src/learnai/adapters/tutor/{routing,turn_schema}.py`, `src/learnai/adapters/tutor/anthropic/config.py`; modify `anthropic/{routing,turn_schema,adapter,judge}.py`, shared `runtime.py`; add `tests/adapters/tutor/test_shared_contracts.py`; update affected routing/parser tests.

**Interfaces:**
- Move `BudgetProfile`, `Route`, `parse_routes`, `load_routes`, `load_budget_profiles`, `resolve_route`, `resolve_tutor_route` to neutral `routing.py`, preserving public names/signatures and current profile values (16k/40k/48k/64k context allowances).
- Preserve `Route`'s existing fields; append `provider_options: Mapping[str, object]` with a fresh empty mapping default. Copy mappings on construction. Shared validation checks types, positive limits and prompt references; it does not impose Anthropic-only adapter/effort/thinking values.
- Move `TurnSchemaError` and `parse_turn(payload: Mapping[str, object]) -> TutorTurn` to neutral `turn_schema.py`. Anthropic retains its wire `TURN_SCHEMA` and imports the same parser/error objects. Old import paths re-export the same classes/functions, never duplicate dataclass/enum definitions.
- `anthropic.config.validate_route(route: Route, *, role: str) -> None` rejects the wrong adapter, unsupported values/options and missing selected prompt. `request_settings(route: Route) -> dict[str, object]` replaces the SDK-free part of `_request_kwargs`. Role is exactly `tutor` or `judge`. Unknown provider identity is validated by Task 4's static registry.

- [ ] **Step 1: Add failing contract tests.** Preserve existing YAML and parser behavior; prove neutral `Route` accepts the structurally valid fictional OpenAI route, while the Anthropic validator rejects it and unsupported selected options. Test aliases with identity assertions:

```python
def test_old_routing_imports_are_identity_preserving():
    from learnai.adapters.tutor import routing
    from learnai.adapters.tutor.anthropic import routing as old
    assert old.Route is routing.Route
    assert old.BudgetProfile is routing.BudgetProfile
```

- [ ] **Step 2: Run RED:** `.venv/bin/python -m pytest tests/adapters/tutor/test_shared_contracts.py -v`; expect the missing shared modules/interfaces.
- [ ] **Step 3: Extract and update imports.** Keep Anthropic behavior strict through its validator. Preserve existing JSON optional fields, enum parsing, unknown-field rejection and domain validation; do not simply rename the Anthropic wire schema as a universally supported schema.
- [ ] **Step 4: Verify GREEN:** run shared-contract, routing, turn-schema, adapter, runtime and judge tests. They must pass without changing policy, configured defaults or requiring OpenAI installation.
- [ ] **Step 5: Commit focused files:** `refactor: separate shared tutor contracts from Anthropic encoding`.

### Task 2: Normalize observations at the provider boundary

**Files:** Create `src/learnai/adapters/tutor/observations.py`, `anthropic/usage.py`; modify `runtime.py`, `anthropic/{adapter,judge}.py`; add `tests/adapters/tutor/test_observations.py`, `tests/adapters/tutor/test_anthropic_usage.py`; update affected trace tests.

**Interfaces:**
- `UsageObservation(counts: Mapping[str, int], status: UsageStatus, reasons: tuple[str, ...] = (), details: Mapping[str, object] = {})` has frozen fields and defensive deep copies of input maps; validate exact non-bool nonnegative integer counts and explicit status. Use factories for mapping defaults. Details/raw emission contain only JSON-compatible finite values with string mapping keys; reject SDK objects and nonfinite numbers. The ledger snapshots observations on record; no generic immutable-JSON collection framework is required. Status values remain `missing`, `partial`, `complete`. Billable categories are disjoint; nonbillable details never enter cost multiplication.
- Move `UsageStatus`, `ProviderAttempt` and `JudgeTrace` to `observations.py`; re-export old names during migration. Preserve existing attempt metadata and raw `usage`; add `normalized_usage: UsageObservation`, initially a missing observation. On emission its status must agree with observed completeness.
- `RequestTrace` is a protocol describing `provider: str`, `api_family: str`, `request_id`, `model`, `settings`, `attempts`, `provider_requests`, and `to_dict()`. `TraceSink = Callable[[RequestTrace], None]`. Both `TurnTrace` and `JudgeTrace` satisfy it; every newly emitted trace requires explicit provider/API identity, with no default inference.
- `normalize_anthropic_usage(raw: Mapping[str, object] | None, *, status: UsageStatus) -> UsageObservation`, in provider `usage.py`, is SDK-free. Preserve categories `input`, `cache_read`, `cache_write_5m`, `cache_write_1h`, `output` and existing incomplete-condition behavior.

- [ ] **Step 1: Write RED tests** for frozen fields/copy-isolated input maps and ledger snapshots, unknown versus explicit zero, malformed nested cache writes, aggregate/nested mismatch, nonzero unknown tool usage, partial usage and per-attempt attribution. Include literal disjoint counts; preserve raw dictionaries unchanged.

```python
def test_unknown_usage_is_not_known_zero():
    value = normalize_anthropic_usage(None, status=UsageStatus.MISSING)
    assert value.counts == {}
    assert value.status is UsageStatus.MISSING
    assert value.reasons
```

- [ ] **Step 2: Run RED:** the two new test files with `-v`; expect missing interfaces before implementation.
- [ ] **Step 3: Implement neutral records and Anthropic mapping.** Normalize each actual attempt before exchange finalization, including failure/partial streams. Keep raw wire responses/private continuation, request IDs, retries, output allowances and sink identity. Judge trace may no longer require importing an Anthropic module to inspect it. This task does not yet remove the old ledger consumer; Task 3 switches it atomically.
- [ ] **Step 4: Verify GREEN:** new observation/usage tests plus existing adapter/judge/runner/smoke tests. Nested-request sinks still retain the originating trace and normalized counts, without provider-global last-response state.
- [ ] **Step 5: Commit:** `refactor: emit normalized provider usage observations`.

### Task 3: Provider-aware accounting and versioned saved runs

**Files:** Modify `eval/{accounting,runner,manifest,report,artifacts,__main__}.py`; create `adapters/tutor/anthropic/legacy.py`, `application/{__init__,artifacts}.py`; add `tests/eval/test_provider_artifacts.py`, `tests/adapters/tutor/test_anthropic_legacy.py`, synthetic `tests/fixtures/eval_v1/`; update accounting/manifest/report tests.

**Interfaces:**
- Extend `RequestRecord` with required `provider`, `api_family`, `normalized_usage`; new serialized records carry `schema_version: 2`. Preserve raw usage/request/response separately. `RequestLedger.record` upserts immutable attempt identity including provider; `sink(*, phase: str, scenario_id: str | None = None) -> TraceSink` consumes Task 2 observations only.
- `PriceSnapshot` gains required `provider`; `PriceBook(snapshots: tuple[PriceSnapshot, ...])`; `load_prices(path: Path) -> PriceBook`; `estimate_cost(ledger: RequestLedger, prices: PriceBook) -> CostSummary`. Provider/model/conditions identify prices. Duplicate ambiguous snapshots fail locally. Empty/missing price coverage is allowed and yields incomplete estimates for actual requests, not startup failure.
- Extend `CostSummary` with `known_by_currency: Mapping[str, Decimal]`. Existing scalar `known_subtotal`, `total`, `currency`, `by_phase`, `retry_subtotal` become nullable when no single currency can represent the actual requests. Preserve their existing values for single-currency runs. Mixed currencies preserve literal per-currency known subtotals, set scalar totals to null and `complete=False` with reasons; do not add USD and EUR. An empty ledger reports zero requests, not an invented currency. Only currencies applicable to actual attempts affect the result; unused price snapshots do not contaminate a run.
- Legacy top-level `pricing` remains readable as explicitly Anthropic. New form: `pricing: {schema_version: 2, snapshots: [{provider, version, date, currency, unit, rates, source_url, retrieved_at, conditions}]}`. Do not combine different currencies/units without explicit conversion: incompatible currencies make the combined estimate incomplete; retain per-currency known subtotals rather than adding unlike amounts. Existing single-currency report fields remain populated only when meaningful.
- Keep packet/reference/score type identifiers unchanged in `learnai.eval.judge`. New manifest/observation schema is 2. `SavedRun` in `eval/artifacts.py` contains `directory: Path`, `manifest: Mapping[str, object]`, `records: tuple[RequestRecord, ...]`, `packets: Mapping[str, JudgePacket]`, `report: Mapping[str, object]`, `compatibility_notes: tuple[str, ...]`.
- `read_run_v2(directory: Path) -> SavedRun` validates version, safe paths, structure and packet hashes without SDK imports. `anthropic.legacy.read_run_v1(directory: Path) -> SavedRun` is SDK-free and uses Task 2's mapper, marking provider inference explicitly as a legacy adaptation. `application.artifacts.load_saved_run(directory: Path) -> SavedRun` dispatches a fixed version-to-reader mapping; unknown versions fail locally, never import artifact-selected types/modules.
- `compare_runs(left: SavedRun, right: SavedRun) -> dict[str, object]` replaces path reads in shared reporting. Preserve changed hashes/settings/order/seeds/runtime/returned-model disclosures and numeric-only averages. Add `controlled_tutor_comparison` with explicit eligibility/reasons separate from full configuration equality: permit only declared tutor-route provider/model/settings changes while evaluator, references/cases and relevant execution material remain fixed. SDK versions for the changed tutor and configuration-file hash changes must be explained as treatment changes, not indiscriminately invalidate the comparison. Unknown evaluator identity, unrelated source changes or unclassified material differences prevent a held-fixed claim. Schema migrations disclose nonidentical normalization.

- [ ] **Step 1: Add RED accounting/artifact tests.** Synthetic prices input2/cache-read1/cache-write3/output4 per million with counts100/200/300/400 still cost `Decimal('0.0029')`. Test identical model labels across two providers at different rates; missing rate/usage; upsert collisions; mixed phases/retry overlap; no raw vendor-key access by shared ledger/cost code. Add a minimal synthetic v1 saved run and assert re-reading never changes file hashes.

```python
def test_provider_is_part_of_model_identity(two_provider_ledger, two_provider_prices):
    result = estimate_cost(two_provider_ledger, two_provider_prices)
    assert result.complete
    assert result.known_subtotal == Decimal('0.0006')
```

For that fixture: each provider returns model label `same-name`, each uses100 uncached input tokens, rates are2 and4 per million; no other billable usage.

- [ ] **Step 2: Run RED:** new artifact/legacy tests and new accounting cases; expect missing provider-aware constructors/readers. Do not count existing failing assertions from signature migrations as the behavioral RED evidence.
- [ ] **Step 3: Implement atomically.** Switch runner summaries and ledger pricing to observations, remove shared `normalize_usage` vendor decoding, move v1 interpretation into its provider-owned SDK-free reader, and update CLI comparison to load runs through application composition. Keep `load_packets` safe typed validation. Extend manifests with provider/API/schema/mapper/counter identities and actual selected SDK versions (supplied by operation composition, not hardcoded vendor discovery). Price snapshots and relevant schema/material identities participate in captured inputs; times/output remain excluded from fingerprints.
- [ ] **Step 4: Verify GREEN:** accounting, manifest, report/CLI, runner, artifact and legacy suites; include v1 re-read, v2 roundtrip, unsupported versions, tampered hashes, malformed nested candidates and unknown-model costs. A changed judge provider must invalidate controlled comparison even when model labels match. An intentional tutor-only change must be labeled separately from an identical setup.
- [ ] **Step 5: Commit:** `feat: record provider-aware evaluations with legacy artifact support`.

### Task 4: Neutral judge port and operation-scoped composition for Anthropic

**Files:** Create `eval/ports.py`, `application/{ports,providers,tutor_router}.py`, `adapters/tutor/anthropic/wiring.py`, `tests/support/provider_fakes.py`; modify `eval/{judge,__main__}.py`, Anthropic judge, architecture/report tests; add `tests/application/test_provider_composition.py`, `tests/test_provider_boundaries.py`.

**Interfaces:**
- `Judge` in `eval/ports.py`: `evaluate(self, packet: JudgePacket) -> JudgeScores`. Keep packet construction, strict `parse_scores`, rubric requirements and `JudgeError` in `eval/judge.py`; no SDK/runtime provider import. `run_judge(judge: Judge, *, packet: JudgePacket) -> JudgeScores` is a neutral compatibility facade. Type-only imports prevent a circular module dependency.
- `AnthropicJudge` in provider `judge.py` implements this port, taking a bound route/client/profile/prompt-root/sink and using the existing provider exchange plus common parser. Do not move rubric policy into transport or change abstention semantics.
- `TutorDependencies(items: GeneratorRegistry, catalogue: Mapping[MisconceptionId, Misconception])` is a frozen application construction value. No mastery repository or write capability is added.
- `ProviderFactory` in `application/ports.py` exposes SDK-free metadata `provider`, `api_family`, `credential_env`, `sdk_distribution`, `sdk_module`, `usage_mapper_id`, `schema_ids: Mapping[str, str]` (keys `tutor`, `judge`), plus `validate_route(route: Route, *, role: str) -> None`, `create_client(*, api_key: str) -> ProviderClient`, `create_tutor(*, route: Route, client: ProviderClient, dependencies: TutorDependencies, profiles: Mapping[str, BudgetProfile], prompts_root: Path, trace_sink: TraceSink) -> Tutor`, and `create_judge(*, route: Route, client: ProviderClient, profiles: Mapping[str, BudgetProfile], prompts_root: Path, trace_sink: TraceSink) -> Judge`. Metadata IDs identify versioned mapper/schema implementations and are captured with actual schema hashes, not inferred from SDK/model labels. `ProviderClient` requires only `close() -> None`; provider wiring safely narrows its own SDK client type.
- `ProviderRegistry(factories: Mapping[str, ProviderFactory])`, `get(provider: str) -> ProviderFactory`; `default_registry() -> ProviderRegistry` statically registers SDK-free construction objects. SDK/adaptor execution imports occur inside selected create methods. No dynamic import names from configuration.
- `OperationRoutes(tutors: Mapping[ResponseJob, Route], judge: Route | None)`; `resolve_operation_routes(*, routes: Mapping[str, Route], contexts: Iterable[TurnContext], judge_route_name: str, smoke: bool, rejudge: bool) -> OperationRoutes`. Run includes jobs of actual eligible contexts, adds NORMAL for current deterministic smoke, and selects the judge only when eligible/rejudge packets exist. Rejudge passes nonempty saved-packet intent through `rejudge=True`; empty saved runs are rejected earlier. Resolve only the required jobs, preserving complex opt-in.
- `ProviderServices(*, selected: OperationRoutes, registry: ProviderRegistry, environment: Mapping[str, str], dependencies: TutorDependencies | None, profiles: Mapping[str, BudgetProfile], prompts_root: Path, ledger: RequestLedger)` is an operation context manager. `validate() -> None` checks all selected settings/prompts/SDK/key availability before any client construction; configuration-wide unknown provider names fail structurally first. Credential values stay private and never enter artifacts. Clients are lazy, shared per provider and closed once in `__exit__`, including partial construction failure.
- `services.tutor(*, phase: str, scenario_id: str | None = None) -> Tutor` returns a `TutorRouter` bound to a fresh immutable phase/scenario sink. `services.judge(*, scenario_id: str) -> Judge` binds the chosen judge/sink. `TutorRouter.begin_turn(context)` picks the fixed job route and returns that provider's exchange; it never switches provider during retries. `respond` remains the existing one-exchange convenience contract.
- `main(argv: list[str] | None = None, *, provider_factories: Mapping[str, ProviderFactory] | None = None) -> int` replaces the single-vendor `client_factory` injection. Public CLI flags/exit codes remain. `RecordingFactory(provider: str)` in test support exposes client construction/closure and role-request logs; fake ports use scripted semantic results, not vendor usage assumptions.

- [ ] **Step 1: Write RED composition/boundary tests.** Include two fictional registry factories so independent selection is testable before OpenAI exists. Required behavior:

```python
def test_missing_selected_judge_key_prevents_every_client(mixed_services, factories):
    with pytest.raises(ValueError, match='JUDGE_TEST_KEY'):
        mixed_services.validate()
    assert sum(factory.clients_created for factory in factories.values()) == 0
```

Also test unused missing package/key, no-tutor/no-smoke zero clients, rejudge judge-only, smoke NORMAL only, route fixed through a rejected turn, nested sink identity, client reuse/closure and failure during second-provider construction. No test fixture may silently default to Anthropic when provider metadata is absent.

- [ ] **Step 2: Run RED:** new composition/architecture tests. Expect missing factories/ports and the existing eval SDK imports to fail the final dependency rules.
- [ ] **Step 3: Implement composition and migrate Anthropic/CLI.** Preserve local preflight before constructors, all tutors before judges then smoke, exact captured-context packets, original-error retention and partial report finalization. Selected provider SDK absence is checked without network. Build manifests from selected metadata and capture all effective settings, without credentials. Old vendor-specific constructor injections in tests are migrated to factory overrides. Shared modules import no SDK/provider packages except the designated application composition/legacy loading modules.
- [ ] **Step 4: Verify GREEN:** existing Anthropic adapter/judge/runner/report/smoke tests plus new composition/dependency cases. Use an import-blocking subprocess to demonstrate read-only comparison and registry metadata loading work when provider SDK imports are unavailable. Finish this migration checkpoint with one full keyless suite; do not begin OpenAI until it passes.
- [ ] **Step 5: Commit:** `refactor: compose tutor and judge providers outside evaluation`.

### Task 5: OpenAI tutor exchange and SDK-boundary tests

**Files:** Create `adapters/tutor/openai/{__init__,config,encoding,transport,usage,adapter,wiring}.py`, `tests/support/scripted_openai.py`, `tests/adapters/tutor/openai/{test_config,test_usage,test_adapter}.py`; modify `pyproject.toml`, `config/llm_routes.yaml`; add `docs/superpowers/notes/2026-10-26-openai-provider-compatibility.md`.

**Interfaces:**
- `openai.config.validate_route(route: Route, *, role: str) -> None` and SDK-free `request_settings(route: Route) -> dict[str, object]` translate the logical call limit to Responses `max_output_tokens`; selected unsupported settings fail rather than disappear. Anthropic `thinking: adaptive` is invalid. Pin the supported effort/temperature/cache options for the selected documented model, never pass arbitrary `provider_options` through.
- `normalize_openai_usage(raw: Mapping[str, object] | None, *, status: UsageStatus) -> UsageObservation`: inclusive input minus cached subset becomes `input`; cached subset becomes `cache_read`; output includes reasoning and is billed once. Unknown or malformed subsets/categories/conditions yield reasons and known-only counts, never negative uncached counts.
- `OpenAITutor(route: Route, client: OpenAI, items: GeneratorRegistry, catalogue: Mapping[MisconceptionId, Misconception], *, budget_profiles: Mapping[str, BudgetProfile], prompts_root: Path = PROMPTS_ROOT, monotonic: Callable[[], float] = time.monotonic, count_tokens: Callable[[str], int] = conservative_token_count, trace_sink: TraceSink | None = None, sleep: Callable[[float], None] = time.sleep)` implements domain `Tutor`, bound to one route. `begin_turn` returns its request-local exchange implementing the existing port. Expose a shared `TurnTrace` with provider `openai`, API family `responses`.
- `encoding.py` owns provider schemas, instruction/current-context encoding and correction items. Final schema requires supported strict keys/nullability but produces the same semantic parser input. Tools come from the existing local `Toolbox`; no remote tools are registered. When strict function schemas turn an optional canonical tool argument into a required nullable wire field, normalize null back to absence only for that declared optional field before dispatch. Preserve zero, false and empty strings and do not silently drop nulls that violate a required argument's contract. Test optional `check_expression.reference` and session-history filters through actual wire calls.
- `transport.py` owns actual SDK calls/stream assembly, exception translation, bounded API retries and attempt observations. It accepts the existing shared `ResponseBudget` and never allocates another budget for retries. Role loops remain in adapter/judge; transport never imports engine validators or rubric policy.
- `ScriptedOpenAI` test support exposes `.client`, ordered captured `.requests`, and scripted `ResponseReply`/failure/stream events. Use the selected official SDK over its native in-memory HTTP transport; do not assume Anthropic's `httpx2` client is compatible.

- [ ] **Step 1: Verify compatibility evidence and write RED tests.** Before adding the SDK dependency, inspect official Responses/model/schema/cache/usage docs and record the chosen optional model, supported settings and exact release to pin. Add SDK to an `openai` optional extra and the dev extra for reproducible keyless tests; retain existing base installation behavior. Real IDs/examples live only in `config/llm_routes.yaml`, initially as inactive commented opt-in configuration; defaults stay Anthropic. Install/pin only when implementing, not planning. Then write behavioral tests before exchange code.

Required wire examples: a final structured response; two function calls with distinct `call_id`s; tool result followed by rejected final turn/correction; opaque/encrypted continuation through those calls; refusal/incomplete/empty/malformed output; pre-response retryable failure; partial-stream disconnect; context/output/deadline exhaustion. Assert `store=false`, required instructions on every request, no reliance on `previous_response_id`, native strict schemas, SDK retries0 and unchanged retained output-item order.

```python
def test_openai_usage_counts_cached_and_reasoning_subsets_once():
    result = normalize_openai_usage({
        'input_tokens': 1000, 'input_tokens_details': {'cached_tokens': 300},
        'output_tokens': 200, 'output_tokens_details': {'reasoning_tokens': 80},
    }, status=UsageStatus.COMPLETE)
    assert result.counts == {'input': 700, 'cache_read': 300, 'output': 200}
```

- [ ] **Step 2: Run RED:** OpenAI config/usage/adapter files with `-v`. Record missing exchange/incorrect wire behavior, not dependency import errors alone, as the relevant RED evidence.
- [ ] **Step 3: Implement the request-scoped tutor.** Preserve model output/opaque continuation items as returned, add matched tool results, use provider-supported corrections, disable exploration after the soft threshold without corrupting history, and retain one budget across all retry layers. Do not replay a partially received response blindly. SDK retries0, maximum3 API attempts per model call and maximum2 formatting retries remain bounded again by shared round/output/time caps. Engine validation still owns its existing maximum attempts. All delivered text remains buffered until accepted.
- [ ] **Step 4: Verify GREEN:** OpenAI wire/config/usage tests and existing domain/neutral observation/parser tests. Prove failed/refused/truncated/expired exchanges consume no assistance, preserve unknown usage and report one attempt record per actual request. Verify supported local configuration before client calls; no paid test runs.
- [ ] **Step 5: Commit:** `feat: add request-scoped OpenAI tutor adapter`.

### Task 6: OpenAI judge and mixed-provider evaluation

**Files:** Create `adapters/tutor/openai/judge.py`, `tests/adapters/tutor/openai/test_judge.py`, `tests/eval/test_mixed_providers.py`, `tests/support/provider_contracts.py`; complete `openai/wiring.py` and static registration in `application/providers.py`; update application/CLI integration tests. Adapter/application paths are under `src/learnai/`, as in the file map.

**Interfaces:**
- `OpenAIJudge(route: Route, client: OpenAI, *, budget_profiles: Mapping[str, BudgetProfile], prompts_root: Path = PROMPTS_ROOT, trace_sink: TraceSink | None = None, monotonic: Callable[[], float] = time.monotonic, count_tokens: Callable[[str], int] = conservative_token_count, sleep: Callable[[float], None] = time.sleep)` implements `Judge.evaluate(packet)`. Use common packet serialization/rubric/score parsing and Task 5 transport, but no tools or tutor reference lookup. Emit `JudgeTrace(provider='openai', api_family='responses', ...)` even on operational failure.
- `OpenAIProviderFactory` implements Task 4's exact construction port, with `OPENAI_API_KEY` metadata and lazy SDK imports. Anthropic factory keeps `ANTHROPIC_API_KEY`. Both construct clients with automatic retries0 and close them through services.
- `default_registry` registers both SDK-free factories; independent job routes and judge selection determine actual use. Tests may provide fictional route files; active default configuration remains unchanged.
- In `tests/support/provider_contracts.py`, `run_scripted_pair(*, tutor_provider: str, judge_provider: str, tmp_path: Path, monkeypatch) -> PairRun` scripts the actual SDK clients for existing scenarios `leak-solve.factoring` and `extra-nonmonic`, in that order, and invokes `main`. `PairRun` contains `outcomes`, `packets`, `request_roles`, `request_providers`, `wire_judge_payloads` and `records`. Extract wire judge JSON from each provider's actual request, rather than returning a locally reconstructed expected packet. Task 7 extends the same support module for engine/admission fixtures.

- [ ] **Step 1: Write RED judge/matrix tests.** Judge payload must contain the matching captured moment/candidate plus isolated reference. Assert strict scored/abstention parsing, supported wire schema, no tools, retained usage on failure and shared budget through formatting/API retries. Parameterize all four provider pairs using actual SDK scripted transports rather than substituting a generic successful role.

```python
@pytest.mark.parametrize('tutor_provider,judge_provider', [
    ('anthropic', 'anthropic'), ('anthropic', 'openai'),
    ('openai', 'anthropic'), ('openai', 'openai'),
])
def test_two_cases_keep_phase_order_and_candidate_pairing(
    tutor_provider, judge_provider, tmp_path, monkeypatch,
):
    run = run_scripted_pair(tutor_provider=tutor_provider,
        judge_provider=judge_provider, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert run.request_roles == ('tutor', 'tutor', 'judge', 'judge')
    assert run.request_providers == (tutor_provider, tutor_provider, judge_provider, judge_provider)
    assert len({record.request_id for record in run.records}) == 4
    for index, case_id in enumerate(run.outcomes):
        packet = run.packets[case_id]
        assert packet.context is run.outcomes[case_id].context
        assert packet.turn is run.outcomes[case_id].turn
        expected = json.loads(build_judge_messages(packet)[0]['content'])
        assert run.wire_judge_payloads[index] == expected
```

Pin request order and packet contents, not only counts. Include mixed provider choices across BRIEF/NORMAL/SUBSTANTIAL tutor jobs and unchanged complex opt-in behavior. The helper uses test-only delegating wrappers around the actual `run_scenario` and selected factory judge, retaining exact objects without adding production observer parameters or bypassing either SDK request. Serialized roundtrip equality is checked separately for persisted artifacts.

- [ ] **Step 2: Run RED:** the new judge/mixed suites; expect missing judge/provider registration before implementation.
- [ ] **Step 3: Implement judge/wiring and finalize integration.** All tutor cases precede all judges, smoke remains its own phase, selected missing second-provider credentials prevent every client, and a later judge failure preserves earlier outcomes/requests/scores and closes both clients. Rejudge old Anthropic candidates using only an OpenAI key and zero tutor calls; repeat in reverse for v2 artifacts. No hidden rerun or fallback.
- [ ] **Step 4: Verify GREEN:** mixed SDK tests, composition/import-blocking cases, accounting/artifact/comparison suites and existing Anthropic integration. Include changed returned judge identity versus intentional tutor treatment change, identical model labels across providers, and literal reconciled retry/phase costs.
- [ ] **Step 5: Commit:** `feat: evaluate tutor and judge providers independently`.

### Task 7: Shared engine conformance and full-corpus admission

**Files:** Create `tests/adapters/tutor/test_provider_conformance.py`, `tests/eval/test_provider_admission.py`; refactor existing `test_adapter_engine.py`/`test_corpus_admission.py` into reusable fixtures where helpful, without deleting unique regression assertions; extend Task 6's `tests/support/provider_contracts.py`.

**Interfaces:**
- Test fixture `provider_tutor` is parameterized over the two SDK-scripted adapters, supplies a real `Tutor`, captured requests and normalized traces, and uses the existing real-engine dependency builder. No new production test-only methods.
- Admission helper takes the actual bound provider role/config and uses its real SDK-free encoding plus the production counter. It is test-owned; do not copy a simplified approximation of request framing or use `len(text)//4`.

- [ ] **Step 1: Write RED shared conformance/admission tests.** Both providers must preserve revised work/current unchecked scope, help ladder and delivered NONE assistance, cold credit on silence/rejection, retrieval provenance, paired multiple tools/corrections and finite shared budgets. For admission, replay every actual opportunity from all71 fixtures; use a real-validator-accepted representative candidate for the judge and independently constructed references.
- [ ] **Step 2: Run RED:** new shared suites; confirm any provider-specific uncovered failure before changing code. If implementation already satisfies a migrated assertion, report it as a preserved regression rather than inventing a failure.
- [ ] **Step 3: Address only confirmed conformance gaps.** Both checked-in and fallback profiles must admit all54 current opportunities for both tutor and judge, including the next call's output reservation and at least8,192 additional admission units. Preserve raw active work/provenance and the overflow guard. Do not inflate test-only profiles or shorten fixtures. If real OpenAI framing requires changing a provisional shared context allowance, document measured maxima/margin and update checked-in/default/docs consistently; preserve latency/output/tool/round caps. No domain policy changes to green provider tests.
- [ ] **Step 4: Verify GREEN:** full shared conformance, original corpus floors (15 actual ladder, two each of six actual diagnosis signatures), both provider admission matrices and unchanged dedicated overflow tests. Assert zero network/provider requests during admission checks. Run one full keyless suite after the final behavioral change at this checkpoint.
- [ ] **Step 5: Commit:** `test: enforce provider parity through real engine interactions`.

### Task 8: Opt-in live gates, installation and operator documentation

**Files:** Create `tests/adapters/tutor/openai/test_live.py`; update existing Anthropic `test_live.py`, `pyproject.toml`, `eval/README.md`, compatibility notes and implementation handoff documentation.

**Interfaces:** Preserve the `live` marker and default `-m 'not live'`. Add `openai` and `anthropic` provider markers only for explicit selection; no provider marker may override the default live exclusion. Exactly two collected probes per provider: cache prerequisites/read observations and a real engine-accepted current-work question. Parameterized equivalents must still collect four cases total.

- [ ] **Step 1: Write the two OpenAI probes and selection checks.** Use real configured model/settings/SDK, actual engine validation and private per-run traces. Cache assertions establish the selected model's documented cacheable-prefix prerequisites, sequential reuse and observed reads; report unmet prerequisites clearly. Do not equate a cache miss with volatile prompt leakage, or assert latency/quality thresholds from two calls. Each probe checks only its own key and constructs only its own provider client.
- [ ] **Step 2: Verify without spend:** `.venv/bin/python -m pytest -o addopts='' -m live --collect-only -q` must collect four cases. Explicitly selected live tests with both keys removed skip all four. With dummy keys present, use collection-only to prove default selection excludes all four; never execute live bodies with dummy keys.
- [ ] **Step 3: Document installation, configuration and migration.** Base Anthropic installation remains; OpenAI extra installs its verified pin; dev installs both SDKs for offline transport suites. Show how to activate config examples and choose the independent judge route, run a subset/no-smoke, rejudge saved responses with only judge credentials, compare controlled tutor changes and interpret incomplete provider-aware costs. Explain v1 read-only adaptation/v2 output, client ownership, local continuation/store=false limits, current buffering and unexecuted live/human-calibration gates. All artifacts remain ignored/private; no arbitrary traces or credentials are committed.
- [ ] **Step 4: Final verification:** one full keyless suite after final implementation/config changes, explicit four-live-case collection, import-boundary and both provider corpus-admission tests. Record measured results and SDK/model/source snapshot; do not claim an unexecuted paid gate passed. Build/check the package offline if packaging/extras changed; request dependency/network permissions only during authorized implementation when actually needed.
- [ ] **Step 5: Commit:** `test: gate live provider checks and document mixed evaluations`.

## Plan self-review and handoff

This plan was checked against spec sections1–11: Tasks1/4 cover route/role/composition boundaries; Tasks2/3 cover observations/accounting/legacy versions/comparison; Tasks5/6 cover Responses and mixed roles; Task7 covers real engine parity/default admission; Task8 covers live gates and operator guidance. Every Review Focus item has explicit owning tests above.

The two providers are one extension with sequential interface dependencies; separate independent product projects would leave half-migrated shared wiring. Review Task4's Anthropic-only checkpoint before OpenAI integration. Preserve existing public domain contracts and saved packet class identities throughout; internal vendor-specific constructor APIs may migrate with their callers/tests.

The SDK/model/version and commercial price snapshot are intentionally implementation decisions verified against current official sources, as delegated by the approved spec; the plan does not invent them. Execution should use the supplied exact shared interfaces, keeping provider-only private helpers flexible. This is planning evidence, not implementation or live acceptance.

The user previously preferred subagent-driven execution; preserve that preference if they authorize implementing this plan. Before execution, request their review of this concrete plan. During execution use its own SDD ledger/workspace, never resume the completed Plan2A task sequence. No automatic PR publication, integration, live spend or old-worktree cleanup follows plan creation.
