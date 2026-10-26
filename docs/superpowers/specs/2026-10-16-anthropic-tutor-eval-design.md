# Plan 2A — Anthropic Tutor Adapter and Graded Eval Set: design

**Date:** 2026-10-16
**Status:** original design and review refinements approved in session through 2026-10-25 and recorded below. Implementation, live compatibility and human calibration remain unverified.
**Parent spec:** `2026-09-14-ai-tutoring-platform-design.md` — the binding authority. This document adds the implementation-level detail the parent deferred (§5.2 orchestration, §9.2–9.3 mechanics, §10 routing and caching specifics, §14 D4) and records this phase's scope cuts. Where this document and the parent spec could conflict, the parent's principles (P1–P7) and decisions bind.

## Where this sits

The parent spec builds Slice 1 as two plans split at the hexagonal boundary (§13). The first is merged: the headless engine — domain core plus CAS and content adapters, driven by `FakeTutor` and `FakeClock`, 496 tests. The second attaches the I/O; it is decomposed here into three sub-plans, each with its own spec → plan → build cycle:

- **2A (this document): the real tutor and the instrument that measures it.** `AnthropicTutor` behind the existing `Tutor` port, plus the graded eval set. Headless: no database, no HTTP, no UI.
- **2B (later): the durable service.** PostgreSQL persistence (append-only log + projection, tested rebuild-from-log), FastAPI endpoints, minimal auth (D5), the CAS time budget (D17), proposal *acting* and the session lifecycle.
- **2C (later): the session UI.** React, the math-input spike (D1), step entry (D2), locale (D6), `readings(text)` and session metrics (D3).

2A front-loads risk deliberately: the model is the one component that cannot be proven by construction, so it is wired and measured before any pipe is built around it.

## 1. Scope

**In 2A:**

1. `AnthropicTutor` behind the `Tutor` port: a manual conversation loop (see §10), structured outgoing turns, corrective retries, bounded tool use.
2. Job-based routing from configuration (parent §10): the resolution mechanism plus the `tutor_dialogue`, `error_diagnosis`, and `rubric_judge` routes.
3. The four-layer prompt with cache breakpoints (parent §10.1) — asserted keyless, proven live.
4. The five read tools (parent §9.2): `check_expression`, `get_worked_example`, `lookup_misconception`, `get_student_summary`, `get_session_history` — wired read-only to the engine's verifier, content, and catalogue. Nothing in the surface touches mastery (P2, enforced by absence).
5. Engine amendments: revisioned student interactions, delivered assistance accounting, provenance-bearing history, and a request-scoped corrective-feedback exchange (§4).
6. Teaching notes v0 for the twelve quadratics skills; the loader requires them.
7. The graded eval set: ≥50 committed scenarios, deterministic checks, an LLM-judge rubric, persona smoke sessions, a report — run on demand with a key (parent §12 Layer 4, §13 deliverable 10).
8. Test doubles: a scripted fake Anthropic client so everything except two marked checks runs keyless.
9. The validation-layer policy in §2, recorded so the boundary between "enforced" and "measured" is a decision rather than a drift.

**Deliberately not in 2A, with activation points:**

| Thing | Goes to | Why not now |
|---|---|---|
| Streaming mechanics (parent §9.4) | 2B/2C | No transport to serve; the adapter stays streamable-friendly (§5). |
| Acting on proposals | 2B | Proposal validation exists and is exercised here; acting is session-lifecycle behavior. |
| CAS time budget (D17) | 2B | Needs the request boundary to enforce against. |
| Persistence, HTTP, auth, durable cross-session retrieval | 2B | 2A exposes an in-memory current-session reader and reconstruction traces. |
| UI, input spike, locale, `readings` (D1/D2/D3/D6) | 2C | Deliberately deferred to mockups and a phone-tested spike. |
| ContentPipeline batch generation (parent §5.1) | later | Notes are hand-drafted v0 here. |

## 2. What validation can and cannot guarantee

The engine's validation (parent §9.3) is the floor, not the measure of quality. No enumerable checker can express "acceptable tutoring"; pretending otherwise would either reject good turns or wave through bad ones. The design resolves this in three layers, and the boundary between them is intentional:

- **Enforced — narrow on purpose.** The gates define a small list of *never acceptable*: help above the permitted rung, the answer given away, an illegal proposal, an empty message. Each is mechanically checkable precisely because each is narrow. The list does not attempt to describe good tutoring.
- **Measured — not enforced.** General quality (correct mathematics, helpfulness, right diagnosis, tone) is scored over a sample by the eval set (§7): a statistical property watched and compared across settings, not a per-response gate.
- **Shaped — upstream.** The strongest quality levers are the prompt policy, the teaching notes, and the tools — `check_expression` in particular removes arithmetic errors, the most common way a model embarrasses itself in front of a student (parent §9.2).

**Why no judge in the hot path.** A model checking every message before it is shown doubles latency and cost, puts one model in the critical path of another, and adds no bright-line semantics the deterministic floor lacks. Not worth it for the classes the floor misses.

**The floor grows from evidence.** Every failure observed — in eval or in real sessions — becomes a committed fixture; the mechanically checkable ones become new deterministic checks. Coverage accumulates where reality actually bit, instead of guessing up front.

**Blast radius is small by construction.** The engine never parses the model's prose to make consequential decisions (P1). A weak message costs polish, never correctness: it cannot corrupt mastery, evidence, help accounting, or sequencing. That is the architectural reason a measured ceiling is acceptable next to an enforced floor.

**Escalation ladder, in order:** tighten the prompt or notes → add a fixture and, if checkable, a gate → add a cheap classifier check on the reserved `intent_classify` route. The first two are data changes; the third is a deliberate design step with its own evidence.

## 3. Components and files

```
config/llm_routes.yaml                    # job -> model + settings; the only place a model name appears
src/learnai/adapters/tutor/anthropic/
  __init__.py
  adapter.py          # AnthropicTutor: respond(), conversation loop, corrective handling, bounds
  routing.py          # route config load and resolve; fail-fast on missing or invalid
  prompt.py           # four-layer assembly and cache breakpoints
  # Shared read tools live at adapters/tutor/tools.py; provider encoding is tool_schema.py.
  turn_schema.py      # structured-turn schema <-> TutorTurn mapping
src/learnai/domain/interaction.py # current work, verification scope, task progress
src/learnai/domain/history.py     # immutable interaction/history records and scoped reader
src/learnai/domain/turn.py      # + current interaction, TurnFeedback, shared exchange driver
src/learnai/adapters/tutor/context.py # token-budgeted context selection
src/learnai/adapters/tutor/runtime.py # response budgets and private trace records
src/learnai/domain/ports.py     # TutorExchange + begin_turn; one-shot respond retained
src/learnai/domain/session.py   # Session transcript/history and task work revision
src/learnai/domain/engine.py    # ask_question, interaction/progress/history and assistance recording
content/quadratics/skills.yaml  # + teaching_notes for all twelve skills
src/learnai/adapters/content/loader.py   # requires non-empty teaching_notes
src/learnai/eval/
  __init__.py
  fixtures.py       # scenario schema and loader
  runner.py         # builds real contexts from scenarios; drives adapter; collects outcomes
  judge.py          # rubric judge via the rubric_judge route
  report.py         # JSON + readable summary writer
  __main__.py       # CLI: python -m learnai.eval run
eval/fixtures/*.yaml                      # >=50 committed scenarios, grouped by family
tests/support/scripted_client.py          # records requests, replays canned responses
tests/adapters/tutor/anthropic/...        # keyless unit suites
```

One clear responsibility per file, matching the repo's existing layout. The adapter package holds no globals: `AnthropicTutor` is constructed with the route configuration, an Anthropic client (real or scripted), and the same engine instances the rest of the system uses — the verifier registry, the generator registry, the graph, and the misconception catalogue.

## 4. Interfaces and amendments

**A private exchange belongs to one engine response request.** `Tutor.begin_turn(context)`
opens a `TutorExchange`; the shared engine/eval driver calls `exchange.respond(feedback=...)`
on that same exchange through validation retries, then closes it. It owns the provider messages,
one runtime budget and a private trace. A one-shot `Tutor.respond(context, feedback=None)` wrapper
remains for direct callers and test compatibility; the engine uses the exchange driver. No
mutable last-conversation field may be shared between students or simultaneous requests. A
`None` result means no delivered message; it is logged, not assessment evidence. The engine
remains the only validation authority; the adapter never imports `validate_turn`.

`TurnFeedback(reason, detail, rejected)` remains the private engine-authored rejection record.
Corrections continue the actual accumulated provider exchange, including previous tool results
and required provider content blocks; they do not rebuild a conversation containing only the
rejected prose. Every tool invocation that is continued receives a matching result or error,
including rejected `submit_turn` calls and calls declined at budget exhaustion.

### 4.1 Current student interaction and assistance

`TurnContext` gains an immutable current interaction: task/item reference, work revision,
ordered raw steps, structured `Submission`, draft/submitted/revised status, exact question and
optional zero-based referenced-step index. An engine-authored verification snapshot identifies
what was checked and its revision. Unchecked, unreadable, no-answer and incorrect are distinct;
old findings stay associated with the old revision after a student edits their work. Same task/work revision requires identical raw steps and structured answer; changed work requires a newer work revision. Question-only changes may keep that work revision but get distinct interaction record ids. Equal-revision conflicts fail before side effects. Existing
`step_diff`, `diagnosis` and `last_verdict` fields mirror current-revision findings only.

The engine also supplies current task progress: readable submissions, genuine attempts,
declines, delivered help rungs, whether independence is spent, and last checked revision. These
are authoritative; the model never counts retrieved events to calculate permissions. Exercise
instructions and answer constraints are always present alongside the student's work. Include
the current question/submission exactly once, not once in history and again as a new message.

A headless `ask_question` operation accepts an explicit work snapshot without submitting a final
answer. It records a relevant interaction snapshot, but no AttemptRecorded, no reveal effort and
no fabricated final verdict. Draft checks may inform the tutor privately. Free-form task replies
are conservatively treated as assistance on delivery, including replies labelled rung NONE;
that label cannot opt out of accounting. Track independence separately from hint-ladder progress.
Interface-only guidance is engine-owned/predefined and does not invoke free-form tutoring in 2A.
Timed exam contracts do not allow task questions. UI editing/chatting remains 2C; Learn mode is
still Slice 3.

First readable unaided submissions retain cold evidence, correct or incorrect. Delivered
step confirmation, error localization, content clarification or hints make subsequent answers
assisted (weight 0). Earlier cold evidence is immutable. A question with no delivered reply,
rejected draft or timeout does not consume independence. No fractional credit by hint rung.
The existing post-instruction weight remains 0.1, including same-session fresh variants after
teaching; stronger evidence comes from later independent work.

### 4.2 Three histories and context selection

- **Assessment evidence:** append-only AttemptRecorded and HelpTaken facts used in projection.
- **Interaction history:** explicit question/work snapshots, submissions, outcomes and delivered
  tutor replies, with ids, UTC timestamps and session/task/item/revision references. Do not log
  every keystroke. Unreadable submissions still change no assessment state; an explicitly asked
  question about unreadable draft work is a separate interaction.
- **Private response trace:** exact selected context, actual provider requests/responses and tool
  results, prompt versions/settings, validation results, budget usage and termination reason.
  Never expose rejected drafts or private traces through delivered history or tutor history tools.

Keep all three linked, not conflated. `Session.transcript` is the delivered exchange view;
`Session.history` holds the richer immutable interaction records. Current-session retrieval reads
bounded pages of evidence and interaction records through a scope bound by application code to
the current student/session. A model cannot supply a different student identity. Previous
exercises and other skills in that session are available; durable previous-session retrieval is 2B.
Records preserve typed skill/item/task/time/kind/revision metadata, related-record links and raw
content. Retrieval optionally filters task, skill, item, kind and time with bounded pagination;
no filter means session-wide browsing, not a restriction to the active skill. Student/session is
the access boundary. Each exchange binds a reader to the full immutable context.history snapshot;
rendered context selection does not remove records from retrieval. Semantic search is deferred.

Replace the fixed twenty-entry window with adapter-side token-budgeted selection: protect the
current exercise/work and complete active-exercise exchanges, reserve generation headroom,
then include relevant earlier history and compact summaries. In 2A, summaries are deterministic
views of earlier exercise outcomes, with source event ids/timestamps, not a new summarizer agent.
Preserve errors followed by corrections as a sequence, rather than a permanent student label.
Original records remain retrievable. If protected content does not fit, return a traced
context-limit outcome; never truncate student working silently. No compaction splits pending
tool calls from results. Current engine state and permissions remain outside historical summaries.

**Initial approaches considered.** Full-history replay accumulates irrelevant tool output;
a fixed message window can remove the exercise that makes a question meaningful. The agreed
starting approach protects active work, uses token budgets and deterministic older-history
summaries, and retrieves details on demand. Model-written summaries and separate memory agents
are deferred until measured traces justify their extra latency and complexity.

**Route configuration** (sample; model identifiers are placeholders per parent §10 and are resolved at implementation, since the parent spec's names are illustrative):

```yaml
routes:
  tutor_dialogue:  {adapter: anthropic, model: claude-opus-5, effort: high,  thinking: adaptive, prompt: tutor_math@1, stream: false, budget_profile: normal}
  tutor_brief:    {adapter: anthropic, model: claude-opus-5, effort: high, thinking: adaptive, prompt: tutor_math@1, budget_profile: brief}
  tutor_explanation: {adapter: anthropic, model: claude-opus-5, effort: high, thinking: adaptive, prompt: tutor_math@1, budget_profile: substantial}
  error_diagnosis: {adapter: anthropic, model: claude-opus-5, effort: xhigh, thinking: adaptive}  # reserved; see below
  rubric_judge:    {adapter: anthropic, model: claude-opus-5, effort: high,  thinking: adaptive, prompt: rubric_judge@1, temperature: 0, budget_profile: substantial}
```

`stream: false` because streaming mechanics are out of 2A; the key flips in 2B/2C. `error_diagnosis` is present and resolvable but reserved: it activates when a dedicated novel-error classification call is warranted by evidence, at which point it gets a cheaper model if the eval supports that. A missing route, a missing key, or an unknown adapter is a startup error with a clear message — an author error, never a silent fallback.

**Prompts are versioned data.** A route also names the prompt file it runs: `prompt: tutor_math@1` resolves to `prompts/tutor_math/v1.md`, loaded fail-fast (a malformed reference, a missing file, or an empty file all raise at load). The adapter composes prompts; it never authors them. Iterating wording means a new version file plus a route bump — the old file stays for reproducing old runs — and every eval report records the prompt ids it ran, so prompt provenance is available; the captured manifest and comparison rules in §7 establish the remaining provenance requirements. The same mechanism carries the judge's rubric (`prompts/rubric_judge/v1.md`), which is why calibration binds to a rubric version.

**Live response-job selection.** Engine context carries ResponseJob. Automatic feedback/help uses
NORMAL; explicit questions may designate BRIEF or SUBSTANTIAL through application metadata.
COMPLEX is disabled unless explicitly enabled and configured. Resolve normal/brief/substantial/
complex to tutor_dialogue/tutor_brief/tutor_explanation/tutor_complex respectively, selecting model,
effort and budget together. No length heuristic or LLM classifier. Trace and manifest record the
actual job/route/profile; missing enabled routes fail before calls. The default config adds brief
and explanation routes to the original three; complex is optional. This does not relax help rules.

## 5. One turn, end to end

1. **The engine decides to speak** — a mistake to react to, or a help request — and builds the context: skill pack (can-do statement, teaching notes, misconception catalogue), item, student summary, step diff, diagnosis, last verdict, permitted rung, the current interaction and verification revisions, task progress, and selected history.
2. **The adapter assembles the request in four layers, stable-first** (parent §10.1): (L1) the global tutor policy — identical for every student, a versioned file under `prompts/` named by the route; (L2) the skill pack — shared by everyone working that skill; (L3) the session preamble — stable session identity/profile metadata; evolving student state belongs in L4; (L4) the volatile turn data. Cache stable L1–L3 only; if no stable profile exists omit L3, and put evolving student state in L4. Nothing volatile may sit above a breakpoint.
3. **The model works.** It may call the read tools mid-thought; results are appended to the conversation and it continues. All calls append to the same private exchange. Configurable per-job budgets govern elapsed time, round trips, tool calls and tokens (§6.1); exhaustion is an operational outcome, not student failure.
4. **The model finishes by emitting the structured turn** — the `TutorTurn` shape: student-facing message, rung used, diagnosis, proposals. The schema is enforced; a malformed emission is a misbehaving response, not a parse error. Mechanism: the SDK's structured-output support; if its constraints cannot express the shape cleanly, the fallback is a single terminating tool call with the same schema. Both paths end in the same validation.
5. **The engine validates** as today: rung ceiling, LeakGuard, proposal legality, non-empty message.
6. **On rejection** — the engine hands the adapter `TurnFeedback`; the adapter continues the *same* conversation: the terminating tool call receives a matching rejection result, and a provider-supported operator message carries the corrective instruction in the retained exchange (parent §9.3 — this preserves the cached prefix). The model retries. The bound is the engine's existing `MAX_TUTOR_RETRIES = 2` (one corrective retry), kept for 2A and revisable with eval evidence. Exhausted attempts → no turn is delivered this moment; the miss is logged.
7. **On acceptance** — the turn is delivered (in later phases, to a screen), recorded as a tutor transcript entry, and the engine records any task-related assistance. A delivered NONE-rung task reply spends independence conservatively without advancing the hint ladder; engine-owned interface guidance remains exempt.

**Streamable-friendly seam.** The adapter's conversation API is shaped so that 2B/2C can add streaming without reshaping it: the turn is produced as a sequence of content events internally (the scripted client asserts event order), and the buffered path is the default. The sentence-boundary guard-release mechanics of parent §9.4 are specified in the parent and built where a transport consumes them.

## 6. Failure behavior

One rule over everything: **nothing bad ever reaches the student; the worst outcome is that nothing reaches them.** The engine already treats a `None` turn as "the tutor was silent" — no message, no help consumed, the session continuing — and the eval set and dev logs record every degraded outcome. A silent swallow is a bug.

- **API-level failures** (rate limit, 5xx, timeouts, connection errors): up to 3 attempts total per model call, exponential backoff from ~0.5s with jitter. Exhausted → no turn; logged. Non-retryable responses (auth, malformed request) fail immediately to the same silent outcome; a missing key or route is caught at construction with a clear error instead.
- **Misbehaving model responses** (empty message, malformed structured output, rung/leak/proposal rejection, tool-loop exhaustion): the corrective path of §5, bounded by `MAX_TUTOR_RETRIES` and the same response budget; exhausted → no turn; logged. A stubborn model degrades to silence for one moment, never to a bad message.
- **Tool failures** (a CAS check crashes, no worked example exists): returned as paired failed tool results, with the incident logged. A hard response budget still stops the exchange; a tool error never becomes an incorrect student verdict.
- **Observability.** The adapter logs through a dedicated `learnai.tutor` logger: every retry, every corrective instruction, every degraded outcome, with the route name and reason. The eval runner additionally captures per-scenario attempt counts and outcomes into the report.

**Known seam, deliberately left open:** the time budget for CAS work (D17) belongs to 2B, where checks run per request and a timeout can be enforced and reported as an incident rather than a wrong answer.

### 6.1 Latency targets, budgets and observability (agreed 2026-10-24)

Parent §10.3 defines the initial targets: brief replies 1–3 s, normal hints 3–8 s, substantial
explanations 8–20 s, exceptional complex work 20–30 s with up to 60 s when justified. These are
tuning targets, not guarantees or vendor benchmarks. Classify the response job, not exercise
length alone; “is this correct?” may refer to extensive working. Thirty seconds is a review point
for substantial work, not the default allowance for a short clarification.

Use a configurable soft threshold and hard ceiling per response job, plus generous emergency
round-trip, tool-call and token ceilings. Count round trips and individual calls separately.
At soft exhaustion, settle outstanding calls, disable further exploratory tools and reserve one
final generation opportunity using the terminating tool. At hard exhaustion, stop with a typed
reason and no unchecked student message. Count API/backoff, formatting and validation retries
against the same allowance; a corrective retry never starts a fresh budget.

Use an injected monotonic runtime clock separate from the domain's UTC Clock. 2A clamps network
request timeouts and backoff to the remaining allowance and checks deadlines before/after tools
and validation. It cannot interrupt an in-process SymPy call: hard isolation and strict request
wall-clock enforcement remain D17 in 2B. The buffered metric is time to accepted delivery; 2B/2C
adds truthful progress, cancellation and time to first validated chunk, never raw unvalidated text.
Report median/p95 by job, exhaustion/silence, tool round trips and retry counts alongside quality.

Trace replay reconstructs recorded inputs, tools, checks and delivered output. Evidence replay
rebuilds student state under a recorded rules/parameters version. Regenerating an LLM response
is a new run, not a guarantee of identical text. In-memory traces and eval artifacts land in 2A;
durable history/trace storage and cross-session access land in 2B.

## 7. The graded eval set

**Scenarios.** ≥50 committed YAML fixtures, each a snapshot of one tutoring moment. A scenario names: the skill; the item (a `template_id` plus a fixed seed — the same question forever); the context fields exactly as `TurnContext` carries them (`permitted_rung` — the ceiling the engine would pass for this moment — and the student summary: strength, freshness, calibration gap, prior misconceptions); the interaction (current working, structured answer, question, status and revision), plus relevant history; submissions are checked through shared engine pieces, while draft questions carry no fabricated final verdict; and its family. Families, with floors:

| Family | Floor | What it exercises |
|---|---|---|
| `ladder` | 12 | One moment across permitted rungs, from "a nudge is the ceiling" to "the answer may be revealed" — the tutor gives useful help within the ceiling, without needing to use the maximum. |
| `diagnosis` | 12 | The catalogue's classic errors — does the tutor react to the right one. |
| `leak_bait` | 12 | Frustrated-student begging; "helpful" phrasings that quietly compute the next line. The floor must catch leaks; the judge reads the tone of the refusal. |
| `decline` | 8 | "I don't know" and workless submissions — orientation, not error-correction. |
| `extra` | 6+ | Second declines, exhausted ladders, fresh vs rusty students. |

**Corpus validity (approved issue 4, 2026-10-25).** Each scenario pins its actual generated
statement, answer shape and constraints. Student working must correspond to that exercise;
copying errors explicitly name the discrepancy and are evaluated separately from transformation
errors. Structured fields follow the real AnswerKind. Explicit no-solutions is not a decline.

Fixtures declare expected final verdict (including correct, malformed, decline and unchecked),
exact diagnosis id or explicit absence, checked scope/revision, failed form constraints and any expected broken transition. Form failures need not break equivalence: partial factoring is algebraically valid. Reuse Slice 1's existing final-transition diagnosis fallback through shared verification preparation, rather than duplicating it in eval code.
The corpus includes correct work, alternative methods and conceptual/draft questions alongside
errors. No-diagnosis cases distinguish unsupported errors from valid work. Expected findings
remain evaluator-only; the engine computes actual findings independently.

Historical events and accepted historical replies determine transcript, assistance and progress
through engine transitions; expectations assert those results rather than setting engine state.
Prior task assistance spends independence even at rung NONE; silence/rejection does not.
Keyless preflight validates coherent fixtures before any paid calls. Full-corpus tests enforce
family floors and balanced coverage; selected CLI subsets need individual validity only.
Local checks cannot prove every word-problem interpretation, so authored anchors and intended
mistakes also require human review. Do not alter generator output or weaken checks to fit an
invalid fixture. Unreachable signatures get direct matcher tests rather than invented exercises.

**The runner builds real contexts, not stated ones.** It instantiates the item through the real
registry, replays history and computes findings through shared engine pieces. Correct final submissions preserve completion without unsolicited tutoring or step diagnosis; evaluate questions about correct work as explicit draft questions with scoped checks. Expected malformed
final submissions exercise the keyless no-tutoring path separately; questions about malformed
drafts remain valid tutoring cases. Reports distinguish expected non-tutored operations from
operational failures. Scripted CLI tests supply all tutor responses before judge responses and
assert each judge packet is paired with the corresponding accepted student moment.

**Scoring, two layers.**

- **Deterministic checks — free, exact.** The final outcome (after any corrective retries) must be a turn the engine accepts: rung within the ceiling, no leak, legal proposals. A scenario whose model never produces an acceptable turn fails, regardless of how pleasant the drafts were. These checks are the same gates that run in production — the eval cannot be greener than reality.
- **Judge pass — live, small cost.** The `rubric_judge` route scores each accepted turn 0–2 on four dimensions: (1) mathematical correctness; (2) appropriateness of help — right level, actually helps; (3) diagnosis quality — the right mistake named, or correctly general; (4) tone — respectful, age-appropriate, encouraging without patronising. The judge sees the context and the final message; it returns structured scores with one-line reasons. The judge prompt is itself a versioned file (`prompts/rubric_judge/v1.md`, named by the route), so calibration is tied to a rubric version by construction.

**Judge review packet (approved issue 3, 2026-10-24).** Capture the exact student moment
used for the accepted response: exercise/constraints, raw working and answer, question, status
and revision, relevant delivered conversation, known learner level, assistance ceiling/progress,
and verification results with checked scope/revision. Keep evaluator-only verified answers,
reference reasoning with provenance, teaching notes, misconception explanations and scenario
criteria in a separate labeled section. Never send those private references to the tutor.
References support alternative valid methods; missing information is explicit rather than
invented. Evaluate the delivered response, not hidden reasoning or rejected drafts.

The help rung is a ceiling, not a target: a smaller helpful intervention can earn full marks.
No diagnosis is appropriate when the evidence does not justify one; unverified work is not
incorrect work. Judge usefulness in relation to the student's actual question and prior hints.
If evidence cannot support a full assessment, return `insufficient_evidence` with missing fields
and reasons, with null scores rather than guessed numbers. Operational judge failures remain
separate errors. Reports retain the packet, report scoring coverage/abstentions/errors, and
exclude abstentions from score averages without hiding them. Deterministic acceptance remains
separate; this judge never enters the student response path. Human calibration includes
context-sensitive paired hints, repetition, conceptual questions, alternative methods and gaps.

**Thresholds are calibrated, then frozen.** The first judged run is spot-reviewed by the human (~10 turns). If the judge disagrees with the review, the rubric moves to a new version before its numbers are trusted. After calibration, per-family score floors are recorded as release gates for future runs; until then a run's acceptance is "report produced and reviewed".

**Persona smoke.** Two or three of Slice 1's personas (a diligent student, a misconception carrier, a hint abuser) run short terms through the real adapter, end to end. Assertions: every session completes; every delivered turn passed validation; no run crashes; summary statistics recorded. This is the only part of the eval that exercises whole sessions rather than single moments, and it is kept short because it is the most expensive.

**Run provenance and comparison (approved issue 5, 2026-10-25).** A unique run id identifies
one execution. A configuration fingerprint hashes captured material inputs/setup, excluding
execution timestamps and outputs. Save the readable manifest and actual input artifacts, not
hashes alone: resolved model/settings/budgets, tutor/judge prompts and rubric, fixtures/references,
selected ids/order/seeds, content/generator source, code revision plus relevant dirty/untracked
changes, Python/dependencies. Record requested and provider-returned model ids when available;
an unchanged alias/fingerprint does not prove the backend stayed unchanged. No secrets in artifacts.

Direct tutor comparisons keep scenario/reference material and evaluator settings/rubric fixed;
report changes and overlapping cases before score differences. Rejudge saved responses from both
runs under the same new evaluator when changing the judge, without regenerating tutor replies.
Reviewing artifacts is read-only; rerunning generation and rejudging invoke models explicitly.
Identical captured setup does not guarantee identical regenerated wording. Repeated runs are
optional when small differences would affect a decision.

**Cost accounting.** One request ledger includes every actual tutor, judge and smoke API attempt,
including rejected drafts/retries/failures; phase totals do not double count trace summaries.
Preserve raw usage and normalize uncached input, cache reads/writes and output according to
current provider semantics verified at implementation. Apply a dated, model-specific pricing
snapshot with source and billing conditions. Missing usage/rates yield an incomplete estimate,
known subtotal and unknown entries, never zero or an invented upper bound. Estimated cost is
separate from an actual bill. Include failed runs and report quality, acceptance/judge coverage,
latency/sample counts, costs by phase and cost per accepted response with explicit denominators.

**Report.** Each unique `eval/reports/<UTC-date>-<run-id>/` contains manifest.json, requests.jsonl,
report.json, summary.md and referenced input/response/judge artifacts. Store exact accepted
student moments and responses; save partial results on later failures. Reports distinguish
scored, abstained, judge-error, operational tutor failure and expected non-tutored outcomes.
Artifacts are ignored except the approved first calibrated summary; no automatic publication
of private traces. Full interfaces and keyless tests are in Task 13.

**Invocation and keys.** `python -m learnai.eval run` requires `ANTHROPIC_API_KEY` in the environment and refuses to start without it. It is not part of the default test suite; it is the phase's paid, on-demand instrument. Full-run cost is measured from the shared request ledger and dated price snapshot; earlier planning estimates are not a verified budget or upper bound.

**The growth rule.** Every failure this instrument ever finds — a leak that slipped past, a wrong diagnosis, a patronising tone that scored well — becomes a committed fixture, and, where mechanically checkable, a new deterministic check. The set grows from evidence, never from imagination.

## 8. How 2A itself is tested

**Keyless — the default suite stays green without a key, exactly as Slice 1's:**

- **Scripted client suites.** The fake client records every request and replays canned responses. The assertions: stable policy/skill/profile layers have cache breakpoints with no volatile content above them; the corrective instruction follows a paired rejection result using a provider-supported operator encoding, without dropping the accumulated private exchange; tool calls dispatch to the right engine pieces in order; the complete history survives multiple tools and validation retries; tool pairing and shared-budget exhaustion are checked; malformed structured output, empty messages, and each rejection class route into the corrective path; retryable error classes back off, non-retryable do not; exhausted bounds yield `None`.
- **Tool suites.** `check_expression` against the real verifier; `get_worked_example` returns a vetted generator item with worked steps for the same skill (fixed seed selection); `lookup_misconception` against the loaded catalogue; `get_student_summary` returns the context's summary unchanged; `get_session_history` provides scoped bounded pages with source references and excludes private traces. All deterministic.
- **Engine amendment suites.** Transcript: student entries on submission, tutor entries on delivery only, active exercise protected by the token budget, current work/question/revision intact, rejected drafts absent, and assistance recorded only on delivery. Feedback: `FakeTutor` records the `TurnFeedback` it receives on a retry and tests assert reason, detail, and the rejected turn carried. Exhaustion: two rejected drafts yield `None`, and the session continues.
- **Content suites.** The loader requires non-empty `teaching_notes` for every skill; the twelve notes are reviewed by the human as content.

**Live — marked `live`, skipped without a key, two checks only:**

1. **Cache proof.** The same context is answered twice against the real API; the second call must report cached input tokens read (> 0). Interpret a zero after checking model support, minimum cacheable length and TTL as well as volatile-prefix changes (parent §10.1).
2. **One real turn, end to end.** A real context answered by the real model produces a structured turn that the real engine accepts.

## 9. Acceptance criteria — what "done" means

1. A real tutor turn flows engine → adapter → validated `TutorTurn`, proven by the live end-to-end check.
2. The four-layer cache layout is asserted keyless and proven live; it cannot break silently.
3. Corrective retries work: a rejected draft receives a private corrective note and the retried draft is what counts; exhaustion degrades to silence; both proven by tests.
4. The tutor sees the current work/question and revision, scoped verification, authoritative progress, protected active history and retrievable earlier-exercise events within the current session (cross-session retrieval in 2B); private drafts remain excluded.
5. All twelve skills carry reviewed teaching notes; the loader enforces them.
6. The eval set: ≥50 scenarios across the families, deterministic checks green, judged report written, first report spot-reviewed by the human, persona smoke sessions passing end to end.
7. The eval reports measured usage and dated cost estimates with completeness, phase breakdowns and explicit denominators. Earlier estimates are planning context, not a cost acceptance threshold; establish a measured baseline before setting one.
8. The whole phase is headless and terminal-runnable: no database, no HTTP, no UI — and the default suite remains keyless.

## 10. Decisions recorded in this phase

- **Orchestration: a manual conversation loop**, resolving D4 for this phase. Rationale: the parent §5.2 reserves the choice to implementation; the design depends on explicit cache-breakpoint placement, adaptive thinking and effort control, provider-supported corrective messages, and structured outputs — all of which a hand-written loop keeps visible and testable. No provider-neutral client beneath the adapter (parent §5.2).
- **No graph-framework orchestration — considered and rejected** (LangGraph-style graphs; generic open-ended agent harnesses à la coding agents with skill systems). With a graph, behaviour changes imply structural changes: every tweak reshapes the wiring, and the graph becomes the place behaviour lives. And a generic harness's open-ended degrees of freedom — the model planning and choosing its own sequences — would give back exactly what P1 (the engine decides) and P2 (no write path) exist to remove. Here, behaviour changes land in data (prompt policy, teaching notes, routes) or engine policy code; the loop's structure stays fixed. The plug points are task-level: the adapter behind the `Tutor` port, plus tools, prompt blocks, notes, and routes. A genuine agent harness may earn its place later in offline authoring and the ContentPipeline, where the task space is open — not in the tutoring hot path, where constraint is the feature.
- **Corrective feedback travels through the port**, not through the adapter importing domain validators: one validation authority, a testable channel (`FakeTutor` records it), and the spec's mid-conversation mechanics live inside the adapter where the conversation does.
- **Retry bounds kept conservative**: `MAX_TUTOR_RETRIES = 2` (one corrective retry) as built; API attempts 3 with backoff; per-job response budgets shared across all retry layers, with separate round-trip and individual-call counters. All revisable with eval evidence.
- **Context is selected by tokens and exercise boundaries**, protecting active work; earlier records stay retrievable. Private exchanges retain tools and corrective history across retries.
- **Structured output**: the SDK's structured-output support with a `TutorTurn` schema; a terminating tool call is the documented fallback if SDK constraints demand it.
- **Model identifiers resolve at implementation**: route config carries the parent spec's illustrative names as placeholders; the only place a real model identifier appears is the config file.
- **Keys: opt-in live runs.** `ANTHROPIC_API_KEY` from the environment; `live`-marked tests auto-skip without it; the eval CLI refuses without it. The default suite never needs a key.
- **Eval thresholds are calibrated on the first judged run** (human spot-review of ~10 turns), then frozen as per-family floors.
- **Reports**: `eval/reports/` ignored except the first calibrated run's summary, committed as the reference artifact.


## 11. Review status and implementation mapping — 2026-10-25

The conversation approved the history/interaction, conservative assistance, retrieval and latency
policies above. This revision records those decisions; it does not implement them. The matching
plan tasks 1, 3–5 and 7–15 carry the affected work. Cross-session persistence and retrieval
remain 2B; draft/chat UI and progress display remain 2C. Issue 4 corpus/test refinements are recorded in §7 and Tasks 9–13. Issue 5 provenance, comparisons and accounting are approved above and mapped to Task 13. Issue 3 is now approved and recorded in §7 and Tasks 12–13;
all five discussed review issues are recorded; implementation, live compatibility and human calibration are not yet established.

Final review refinements also record work-revision identity, metadata-rich cross-skill session
retrieval, per-exchange reader wiring, live response-job routing, reuse of existing form-diagnosis
behavior and stricter malformed-output parsing. Task-local checks no longer depend on later tasks.

Engineering choices made while writing this revision (not empirical findings): a request-scoped
TutorExchange owns provider history and one budget; deterministic earlier-exercise summaries avoid
an extra LLM call; initial budget profiles and token limits in the plan are provisional configuration.

Research background used in the discussion (not product guarantees):
- [OpenAI compaction](https://developers.openai.com/api/docs/guides/compaction).
- [Claude Agent SDK loop and budgets](https://code.claude.com/docs/en/agent-sdk/agent-loop).
- [Anthropic context engineering cookbook, March 2026](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools).
- [The Complexity Trap, revised October 2025](https://arxiv.org/abs/2508.21433).
- [LLMs Get Lost in Multi-Turn Conversation, May 2025](https://arxiv.org/abs/2505.06120).
- [Shared Selective Persistent Memory, revised September 2026](https://arxiv.org/abs/2607.09493).
