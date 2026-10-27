# OpenAI provider implementation handoff — 2026-10-27

## Current result and review boundary

The provider-neutral evaluation/OpenAI extension is implementation complete on
local branch `plan-openai-provider`, based on the merged Plan 2A baseline
`40d2559`. All eight tasks are implemented and scoped reviewed. The whole-branch
review of `e072588` found one Important outbound judge-scope gap and one Minor
nonfinite elapsed-timing gap. One final fix wave implements both; **scoped
re-review of this fix wave is still pending**. This handoff does not claim merge
approval. No push, merge, publication or paid model call ran.

The shared SDK-free `scoped_context` helper now filters the outbound judge moment,
history and transcript just as it filters tutor context. The original immutable
JudgePacket, exact accepted candidate/current work, saved packet bytes and source
hashes stay intact. Both foreign-student and foreign-session records are excluded.
Foreign duplicate IDs cannot replace permitted current metadata in either insertion
order. A transcript has no independent student/session scope: when a permitted and
foreign record share its ID, the ambiguous transcript fallback is omitted and the
permitted canonical history/current interaction remains authoritative. This may
omit duplicate fallback prose; it does not discard canonical active work. Legacy
contexts with no history scope and transcript entries without stored records retain
existing compatibility. No domain policy, budget, route default or corpus changed.

Saved request timing now uses the existing typed decoder's finite-number check,
rejecting JSON exponent overflow and huge integers that overflow float conversion,
as well as negative/bool timings. None, zero and finite nonnegative timings remain
valid. Tests mutate isolated decoder input; the frozen v1 fixture is unchanged.

## Keyless verification and packaging

All commands below removed both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` with
`env -u`; scripted native SDK transports use fictional credentials only in offline
tests. No real or dummy credential was used in a live test body.

- Behavioral TDD: before source changes, **26 failed, 7 passed, 36 deselected**
  (7.31s): 24 native SDK saved-rejudge scope cases exposed foreign wire text;
  exponent-overflow and huge-integer timings were accepted. After fixes,
  **33 passed, 36 deselected** (6.87s).
- Context/judge/both SDK/mixed-provider/artifact/admission/composition/domain/import
  checks: **234 passed in 20.62s**.
- Final `.venv/bin/python -m pytest` after the last source/test change:
  **1581 passed, 4 deselected in 86.02s**, exit 0, no warnings or unexpected skips.
- `.venv/bin/python -m pytest -o addopts='' -m live --collect-only -q`:
  **4/1585 tests collected (1581 deselected)**, two per provider.
- The same explicit live selection without collection and with both keys removed:
  **4 skipped, 1581 deselected**, exit 0. No paid probe ran.
- Existing Hatchling 1.32.4 rebuilt the wheel offline with
  `pip wheel . --no-deps --no-build-isolation --no-index --no-cache-dir`.
  Base metadata includes Anthropic/SymPy/PyYAML; `openai` and `dev` extras include
  `openai==3.39.0`; dev retains native `httpx2` and offline test dependencies.
  Both judges and changed source files match packaged bytes. Tests/private artifacts
  are excluded. Offline target install, SDK-free import/registry and CLI help pass.
- Wheel: `/tmp/learnai-final-fix-wheel/learnai-0.1.0-py3-none-any.whl`, **164887 bytes**;
  SHA256 `82953c169110f9a3de0e5215c46a37277cb4c218553afc43871db52e49f7e3aa`.
- `git diff --check` passes; `AGENTS.md`, all original fixtures and frozen v1 bytes
  are unchanged from `e072588`.

The full command/output and self-review evidence is in
`.superpowers/sdd/2026-10-26-provider-neutral-evaluation-openai/final-fix-report.md`;
the whole-branch findings remain in `final-review.md` in that workspace. Those are
private workflow records, not packaged runtime artifacts. This tracked handoff
retains the result and every ledger decision if scratch records are later removed.

## Installation, operator links and resume

From Python 3.12+, install base support with `.venv/bin/python -m pip install -e .`,
OpenAI support with `.venv/bin/python -m pip install -e '.[openai]'`, or both SDKs and
offline tools with `.venv/bin/python -m pip install -e '.[dev]'`. These are operator
instructions, not additional installs performed by this fix wave. Defaults remain
Anthropic; the `tutor_openai` and `rubric_judge_openai` named examples need explicit
activation. Real commercial model identifiers remain in YAML. Both installed SDKs
use native `httpx2` (verified at 2.16.0).

Read the [operator guide](../../../eval/README.md) for installation, explicit route
activation, per-job tutor selection, independent `--judge-route`, subset/no-smoke,
judge-only rejudge credentials, v1 read-only migration/v2 output, private artifact
handling and live selection. Read the [compatibility snapshot](2026-10-26-openai-provider-compatibility.md),
[approved design](../specs/2026-10-26-provider-neutral-evaluation-openai-design.md),
[implementation plan](../plans/2026-10-26-provider-neutral-evaluation-openai.md) and
[earlier Plan 2A handoff](2026-10-26-plan2a-implementation-handoff.md) for contracts
and historical evidence. Runtime source/tests are authoritative about implementation;
unexecuted checklist text in the historical plan is not evidence of missing tasks.

Resume with scoped re-review of this final fix against `e072588`; preserve the
whole-branch Important/Minor triage and independently check the new behavior and
evidence. Record that review separately before changing review approval status.
Do not repeat completed task implementation. The worktree and recovery ledger stay
available; cleanup and branch integration need their own explicit direction.

## Limitations and unexecuted gates

No paid OpenAI/Anthropic compatibility probe, paid corpus evaluation, observed
cache reuse, endpoint/account/model-option validation, production latency sample,
reviewed live reference summary or human judge calibration has run. Scripted
protocol/schema/engine acceptance does not establish teaching quality. The selected
OpenAI settings-dependent minimum cache prefix remains unestablished. Current
pricing supplies no OpenAI rate snapshot, so OpenAI estimates retain known subtotals
with explicit incompleteness; they are not invoices. No new prices were invented or
remote compatibility snapshot refreshed during this fix wave.

Buffered engine-validated delivery remains the boundary. Durable persistence,
authentication/UI, cross-session service access, strict synchronous socket/CAS
preemption and concurrent-worker CAS isolation remain deferred. None of those
limitations waives the implemented outbound history-scope boundary. No automatic
fallback, ensemble, dynamic provider discovery or hosted agent framework was added.

## Ordered decision appendix — complete verbatim provider ledger

The following is the entire workspace `rulings.md`, in its original order,
including contextual lines, rationale and stated cost if wrong. These are
implementation rulings, not live acceptance evidence.

```text
Ruling: Execute the approved eight-task plan continuously — current user authorization supersedes historical planning-only/status language in the documents — cost if wrong is reversible branch work; paid calls and publication remain excluded.

Ruling: Verify existing venv instead of installing with Poetry — pyproject uses Hatchling and the existing Python 3.12 environment is configured — cost if wrong is a local setup correction.

Ruling: Keep Task 3 compatibility import gate staged as specified — Task 4 owns transitive SDK freedom — cost if wrong is an intermediate commit requiring Task 4 before release.

Ruling: Anthropic service_tier auto/omitted stays unknown; standard_only request can establish standard, returned usage wins. inference_geo missing stays unknown due workspace defaults. Documented speed standard default may apply only with complete actual request settings proving fast opt-in absent — official service-tiers, data-residency and fast-mode docs verified — cost if wrong is incomplete pricing correction; never snapshot-derived default. Unknown aggregate cache duration remains PARTIAL; preserve raw fixture evidence rather than enriching it to manufacture completeness.

Ruling: manifest optional identities uses role->route_name->role_identity; role_dependencies uses role->distribution->version|null; Task4 fills actual selected values, absent evidence unknown — preserves independent role comparisons and fixed judge dependency map during provider switch — cost if wrong is seam migration before Task4. No blanket identity exemptions; compare declared permitted fields only.

Ruling: role schema_hashes keys final_output/canonical_read_tools/wire_read_tools (judge final_output); tutor treatment permits only final_output/wire_read_tools encoding differences; shared canonical_read_tools must stay fixed, unknown schema key changes block eligibility — preserves distinction between changed provider strict encoding and changed tool semantics — cost if wrong is narrow map-key migration at Task4/5.

Ruling: build_manifest optional pricing_snapshots JSON mapping captures canonical actual PriceBook before execution; CLI supplies loaded snapshots, writer does not mutate fingerprint later — actual rate snapshot must participate in material inputs even if supplied outside captured config — cost if wrong is neutral serialization seam adjustment. Task4 preserves argument.

Ruling: expose Task6 OpenAIProviderFactory as public name with identity-preserving OpenAIFactory compatibility alias — Task5 introduced shorter name and Task6 brief names descriptive type; one implementation preserves callers — cost if wrong is trivial alias/API correction.

Ruling: narrowly classify known effective wire paths for declared tutor generation treatment and schema/API identities, retain unknown nested fields and same-provider invariant edits; source/prompt/budget/judge stay fixed — actualSDK comparison acceptance requires handling resolved settings, synthetic tests lacked them — cost if wrong is conservative comparison correction. Avoid SDK imports/shared provider validation or whole-map exemption; application pure helper permitted if needed.

Ruling: Task7 profilefamily=checkedin vs fallback sets; admission uses each actual engine responsejob/configured mapping and selected rubric judge profile, not every long context forced through BRIEF/disabledCOMPLEX — preserves actual workload/routing semantics and original admission scope — cost if wrong is additional representative routed-profile test, not changed budget policy. Report actual job distribution.

Ruling: fix scoped-history filtering minimally in shared context selection/render metadata when HistoryScope present; retain legacy unscoped compatibility, no domainpolicy edits. Keep new failing wire/sourceIDs test instead of deleting — global historyscope/provenance and confirmed conformance-gap requirement apply equally to initial input — cost if wrong is narrow contextfilter compatibility correction, no external authorization needed. Exclude foreign same-ID metadata override as well.

Ruling: OpenAI admission uses explicit fictional provider model label with same configured names/job/profile/limits and supported equivalent settings — do not send/claim Anthropic commercial label as OpenAI; real IDs only YAML — cost if wrong is tiny framinglength difference, remeasure final values. Model/account livecompatibility remains separate.

Ruling: Task8 unselected named tutor_openai/rubric_judge_openai YAML routes replace initiallycommentedexamples; defaults/bindings remainAnthropic and unusedSDK/keyirrelevant — realIDsonlyYAML enables clear operatoractivation/liveprobe reuse — costifwrong reversibleoptionalconfig.

Ruling: narrow pytestcollection guard preserves configured notlive default even CLI provider-only-m override; explicitpaidselection documented as -o addopts=empty -m live/provider. Plan says provider markers must not override exclusion — prevents accidentalspend from pytest last-m behavior — costifwrong explicitinvocation convenience, no real/dummykeyliveexecutionauthorized.

Task8 officialcacheguide currentmodel-dependent min notuniversal1024: probe validates stablecache-relevantprefix/settings and positive observed repeatcache read; zero clear unmetprerequisite/readfailure, never leakagediagnosis. Ruling: no inventedminimum/promptpadding or latencyclaim; docuncertainty/unexecutedlivegate — costifwrong latermodel-specificcachegate refinement with authorizedliveevidence.

Task8 offlinewheel initiallyblocked missingHatchling buildbackend. Ruling: install already-declared buildrequirement in worktreevenv/temporarytarget via authorized dependencysetup/networkescalation ifcacheunavailable, then offlinewheel — packagingacceptance needs actualwheel, no knownpreinstalledpath — costifwrong reversibledevtoolinstall, no runtime dependency/modelcalls.

Ruling: implicitlegacyconstructor ignores unselectedforeignroutes but validateactualchosenroute at begin_turn, explicitforeignselection rejects; fix customAnthropic-onlytestconfigs to removeoptionalexamples without weakening unknownprovider parsing. Also fix liveprotocolhelper to use ProviderAttempt.request_index with offline regression — confirmed configactivation/retryattribution bugs — costifwrong narrow compatibility rework, rerunfull afterbehaviorchanges.

Task8 secondfull1546passed1failed4deselected81.41s: oldTask1test assumes implicitforeign-onlyconstructorfails immediately. Ruling: bind that invalidselectiontest explicitly to route.name, preserve allinvalidsettings/no-requestassertions; newimplicitrouteandbegin_turntests own revisedboundary — aligns approvedunusedforeignroutecontract — testonlychange, wheelcurrent. Finalfullrerunrequired.

Ruling: Fix bothfinalreviewfindings in singlewave, including previouslydeferredMinorfiniteelapsedguard — judgeisolation is load-bearing and timingguard small truthfulJSONcontract correction — costifwrong narrowserialization/scope rework.

Ruling: Finalreviewdeclinedliveaccount/cache, teachingquality/calibration/latency, invoices/rates, servicepersistence/auth/UI/CAS, redundanttests andfreshremotedocsnapshotclaims remain explicitunexecuted/outofscope — approvedspec and no-paid authorization boundary — costifwrong laterseparatelyauthorized gates, no safetyguarantee asserted.

Ruling: when permitted andforeignrecords share anID, omitambiguous transcriptfallbackbut retain permittedcanonicalhistory/currentmetadata andexactcurrentinteraction — transcript hasno independentstudent/session provenance andcanonicalrecord is authoritative — costifwrong lostduplicatefallbackprose, no legitimatecanonicalactivework. Add insertionorderregressions bothprovideroutboundpaths.
```
