# Current OpenAI model migration handoff — 2026-10-27

The current Luna tutor and latest Sol judge/optional tutor are implemented as
unselected examples in [route configuration](../../../config/llm_routes.yaml).
`tutor_openai` uses low effort and local `api_profile: current`;
`rubric_judge_openai` and `tutor_openai_sol` use low and `reasoning`. All resolve to
implicit `30m` caching and standard service tier. Anthropic job bindings, engine
policies, budgets, frozen artifacts, and the SDK pin remain unchanged.

Profiles and `openai-responses@2` accounting were implemented in the preceding
commit. Current profiles default to low, allow max, and support `12h`; only
`current` allows none. Legacy remains the omitted profile and keeps its old
none/retention behavior. Local profile metadata is stripped before SDK calls.
Current requests missing returned write evidence retain known reads/output while
leaving writes/uncached input unknown. Returned zero or complete valid duration
counters establish write totals; requested TTL never fills missing counters.
Native complete-cost fixtures now explicitly return zero writes.

Task 2 changes **14 tracked files**: route YAML; the usage mapper; live helper and
its offline regressions; usage/routing/composition/mixed-provider/admission tests;
two shared test helpers; eval README; compatibility note; and this handoff.
The implementation changes **19 tracked paths** across its implementation commits,
including the final helper fix below. Adding the two planning documents gives
**21 tracked paths** for the whole branch. The final fix uses existing files;
ignored execution reports are excluded from these counts.

The installed `openai==3.39.0` / native `httpx2` serialization accepts the selected
request fields and preserves nested write usage; no dependency upgrade or install
was needed. After the final helper fix, keyless full verification passed
**1,670 tests, 4 deselected** in 94.32s. Final focused verification passed
412 tests (2 live deselected). Both corpus
admission suites passed 7 tests, retaining 71 fixtures and 54 actual opportunities.
For both checked-in and fallback budgets, current OpenAI maximum request plus
next-output reservation is 30,776 (tutor) and 31,732 (judge); minimum remaining
margins are 9,224 and 16,268 units. Anthropic remains 30,957/9,043 and
31,546/16,454. All margins exceed the extra 8,192-unit requirement after reserving
the next 2,048 output tokens. These byte-based measurements use actual factory
preparation with fictional labels and do not measure billable/cacheable tokens.

Exactly two OpenAI and two Anthropic live cases collect; explicit no-key live
execution skips all four. No paid calls ran. The cache probe records the documented
1,024-visible-input-token minimum, excluding hidden system tokens; positive
provider-reported repeat reads remain the eligibility gate. No padding was added.
Live account/model behavior, latency, teaching quality, and commercial cost
coverage remain unverified. No OpenAI price snapshot was invented: base/read
rates, returned tier and geography must have applicable evidence before complete
costs can be reported. Documented write multipliers alone (30m: 1.25×; 12h: 2.5×)
do not establish that coverage.

Whole-branch review found one Important issue in the live protocol helper: exact
comparison with the configured output ceiling rejected a valid accepted exchange
whose final request allowance had shrunk with the shared budget. The final fix
excludes only dynamic `max_output_tokens` from invariant settings comparisons and
retains the positive, route-bounded cap assertion. A native SDK/real-engine
regression uses three distinct tool turns reporting 1,900 output tokens each and
verifies request caps `[2048, 2048, 2048, 1468]` before invoking the helper. Existing
legacy/current/reasoning retry and correction coverage remains. Runtime encoding,
budgets, models, dependencies, domain policy and frozen fixtures are unchanged.
The regression failed at `1468 == 2048` before the helper fix and passed afterward.
Final focused verification passed **412 tests, 2 deselected** in 19.70s; exactly
four live cases collected and all four skipped without keys. No paid bodies ran.
Independent scoped re-review of `2692397` closed the finding with no new
breakage or out-of-scope observations. Both task reviews, the whole-branch review
and the final fix review are complete; no Critical or Important finding remains
open. The final acceptance update changes documentation only. Work is committed
locally on `feat-openai-current-models`; no push, PR or paid call has run.

Reproduce offline verification from the repository root with both keys unset:

```sh
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m pytest --tb=short
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m pytest -o addopts='' -m live --collect-only -q
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m pytest -o addopts='' -m live -q -rs
```

For installation, independent route activation, rejudge, and controlled comparison
commands see [eval README](../../../eval/README.md). For current/legacy settings
and evidence limits see [compatibility note](2026-10-26-openai-provider-compatibility.md).

## Decision appendix

The following ordered rulings preserve implementation decisions, rationale, and
cost if wrong from the execution workspace.

Ruling: Execute the user-requested bounded migration using the established OpenAI boundary and prior subagent preference — user approved newest Luna/Sol plus compatibility update from preceding discussion, routine implementation choices need no extra approval — cost if wrong is reversible local branch work.

Ruling: Luna low owns OpenAI tutor/smoke route; Sol low owns judge and optional tutor baseline; Anthropic job defaults stay fixed — matches cheaper smoke and stronger quality comparison discussed — cost if wrong is changing selected route configuration.

Ruling: Explicit local api_profile metadata selects capabilities without model-string inference; legacy/current/reasoning profiles retain old behavior and reject unsupported new settings — real model identifiers belong only in YAML and Sol disallows none — cost if wrong is a small provider configuration surface to revise.

Ruling: No new commercial price snapshot in this migration; normalize writes and verify generic costs with synthetic rates — billing geography/rate evidence remains incomplete and user requested model compatibility, not fabricated invoice coverage — cost if wrong is a separately verified pricing snapshot later.

Ruling: complete valid duration counters establish total writes without redundant aggregate; present aggregate must agree before uncached input known. Preserve valid independently bounded bucket counts on incomplete/conflicting evidence, suppress impossible combined writes and uncertain input — disjoint normalized observations must not fabricate totals/zeros — cost if wrong is a narrow mapper correction with explicit incomplete-cost provenance.

Ruling: known currentcache request with absent write counters must remain PARTIAL withuncachedinputunknown; no-currentrequestevidence retainslegacy compatibility — controllerprobe currentoptions+input100/read20/output5 returnedCOMPLETEinput80, incorrectly treating absentcurrentwriteevidence aszero — cost if wrong is conservative incompleteusage until actualreturnedcounters establishzero. AddRED/nativefixturesexplicitzeros.
