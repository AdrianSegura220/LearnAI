# Plan 2A — Anthropic Tutor Adapter and Graded Eval Set: design

**Date:** 2026-10-16
**Status:** design approved in session; written spec pending human review
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
4. The four read tools (parent §9.2): `check_expression`, `get_worked_example`, `lookup_misconception`, `get_student_summary` — wired read-only to the engine's verifier, content, and catalogue. Nothing in the surface touches mastery (P2, enforced by absence).
5. Two small engine amendments: the transcript producer and the corrective-feedback channel (§4).
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
| Persistence, HTTP, auth | 2B | — |
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
  tools.py            # the four tool implementations (read-only wiring)
  turn_schema.py      # structured-turn schema <-> TutorTurn mapping
src/learnai/domain/turn.py      # + TurnFeedback (additive dataclass)
src/learnai/domain/ports.py     # Tutor.respond gains the optional feedback argument (defaulted)
src/learnai/domain/session.py   # Session gains transcript (defaulted field)
src/learnai/domain/engine.py    # transcript fill, corrective retry loop, delivered-turn recording
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

**The port gains one optional argument.** Defaulted, so every existing caller and `FakeTutor` are unaffected:

```python
class Tutor(Protocol):
    def respond(
        self, context: TurnContext, *, feedback: TurnFeedback | None = None
    ) -> TutorTurn: ...
```

**`TurnFeedback` is new and additive** (`domain/turn.py`):

```python
@dataclass(frozen=True, slots=True)
class TurnFeedback:
    reason: RejectionReason      # from the engine's ValidationResult
    detail: str                  # human-readable, engine-authored
    rejected: TutorTurn          # the draft that failed, so the model can see it
```

**The engine's retry loop carries the feedback** — today it re-asks blindly (`engine.py:401`, `MAX_TUTOR_RETRIES = 2`, context built once); the amendment:

```python
feedback = None
for _ in range(MAX_TUTOR_RETRIES):
    turn = self._tutor.respond(context, feedback=feedback)
    result = validate_turn(turn, context, self.graph, verifier)
    if result.accepted:
        return turn
    feedback = TurnFeedback(result.reason, result.detail, turn)
return None
```

The engine remains the single validation authority. The adapter never imports `validate_turn`.

**Transcript semantics.** `Session` gains `transcript: tuple[TranscriptEntry, ...] = ()`. The engine appends a student entry when a submission is recorded (the submitted text; a decline as a no-answer marker; malformed input changes nothing and writes nothing — Slice 1 semantics) and a tutor entry when a turn is delivered — accepted turns only; rejected drafts and internal retries never enter it. `_build_context` fills `context.transcript` with the last `TRANSCRIPT_WINDOW = 20` delivered entries. The window is a module constant, revisited with eval evidence.

**Route configuration** (sample; model identifiers are placeholders per parent §10 and are resolved at implementation, since the parent spec's names are illustrative):

```yaml
routes:
  tutor_dialogue:  {adapter: anthropic, model: claude-opus-5, effort: high,  thinking: adaptive, stream: false, max_tool_iterations: 6}
  error_diagnosis: {adapter: anthropic, model: claude-opus-5, effort: xhigh, thinking: adaptive}  # reserved; see below
  rubric_judge:    {adapter: anthropic, model: claude-opus-5, effort: high,  thinking: adaptive, temperature: 0}
```

`stream: false` because streaming mechanics are out of 2A; the key flips in 2B/2C. `error_diagnosis` is present and resolvable but reserved: it activates when a dedicated novel-error classification call is warranted by evidence, at which point it gets a cheaper model if the eval supports that. A missing route, a missing key, or an unknown adapter is a startup error with a clear message — an author error, never a silent fallback.

## 5. One turn, end to end

1. **The engine decides to speak** — a mistake to react to, or a help request — and builds the context: skill pack (can-do statement, teaching notes, misconception catalogue), item, student summary, step diff, diagnosis, last verdict, permitted rung, and the transcript window.
2. **The adapter assembles the request in four layers, stable-first** (parent §10.1): (L1) the global tutor policy — identical for every student; (L2) the skill pack — shared by everyone working that skill; (L3) the session preamble — the student profile, stable for the session; (L4) the volatile turn data. L1–L3 carry cache breakpoints; nothing volatile may sit above a breakpoint.
3. **The model works.** It may call the read tools mid-thought; results are appended to the conversation and it continues. Tool use is bounded (`max_tool_iterations` from the route); exceeding the bound is a misbehaving response (§6).
4. **The model finishes by emitting the structured turn** — the `TutorTurn` shape: student-facing message, rung used, diagnosis, proposals. The schema is enforced; a malformed emission is a misbehaving response, not a parse error. Mechanism: the SDK's structured-output support; if its constraints cannot express the shape cleanly, the fallback is a single terminating tool call with the same schema. Both paths end in the same validation.
5. **The engine validates** as today: rung ceiling, LeakGuard, proposal legality, non-empty message.
6. **On rejection** — the engine hands the adapter `TurnFeedback`; the adapter continues the *same* conversation: the rejected draft is appended as the assistant message, followed by a mid-conversation system message carrying the corrective instruction (parent §9.3 — this preserves the cached prefix). The model retries. The bound is the engine's existing `MAX_TUTOR_RETRIES = 2` (one corrective retry), kept for 2A and revisable with eval evidence. Exhausted attempts → no turn is delivered this moment; the miss is logged.
7. **On acceptance** — the turn is delivered (in later phases, to a screen), recorded as a tutor transcript entry, and Slice 1's help bookkeeping runs unchanged. A delivered `NONE`-rung orientation turn remains delivered-but-not-consumed, exactly as built.

**Streamable-friendly seam.** The adapter's conversation API is shaped so that 2B/2C can add streaming without reshaping it: the turn is produced as a sequence of content events internally (the scripted client asserts event order), and the buffered path is the default. The sentence-boundary guard-release mechanics of parent §9.4 are specified in the parent and built where a transport consumes them.

## 6. Failure behavior

One rule over everything: **nothing bad ever reaches the student; the worst outcome is that nothing reaches them.** The engine already treats a `None` turn as "the tutor was silent" — no message, no help consumed, the session continuing — and the eval set and dev logs record every degraded outcome. A silent swallow is a bug.

- **API-level failures** (rate limit, 5xx, timeouts, connection errors): up to 3 attempts total per model call, exponential backoff from ~0.5s with jitter. Exhausted → no turn; logged. Non-retryable responses (auth, malformed request) fail immediately to the same silent outcome; a missing key or route is caught at construction with a clear error instead.
- **Misbehaving model responses** (empty message, malformed structured output, rung/leak/proposal rejection, tool-loop exhaustion): the corrective path of §5, bounded by `MAX_TUTOR_RETRIES`; exhausted → no turn; logged. A stubborn model degrades to silence for one moment, never to a bad message.
- **Tool failures** (a CAS check crashes, no worked example exists): returned to the model as a failed tool result so it can proceed without it; the incident is logged. Tool failures never abort the turn by themselves.
- **Observability.** The adapter logs through a dedicated `learnai.tutor` logger: every retry, every corrective instruction, every degraded outcome, with the route name and reason. The eval runner additionally captures per-scenario attempt counts and outcomes into the report.

**Known seam, deliberately left open:** the time budget for CAS work (D17) belongs to 2B, where checks run per request and a timeout can be enforced and reported as an incident rather than a wrong answer.

## 7. The graded eval set

**Scenarios.** ≥50 committed YAML fixtures, each a snapshot of one tutoring moment. A scenario names: the skill; the item (a `template_id` plus a fixed seed — the same question forever); the pretend-student's help state as a real `HelpState` (`rungs_used`, `attempts`, `submissions`); the student's state (strength, calibration gap, active misconceptions, last-success offset); the submission (steps and/or answer, or a decline); and its family. Families, with floors:

| Family | Floor | What it exercises |
|---|---|---|
| `ladder` | 12 | One moment across permitted rungs, from "a nudge is the ceiling" to "the answer may be revealed" — the tutor uses the most allowed, never more. |
| `diagnosis` | 12 | The catalogue's classic errors — does the tutor react to the right one. |
| `leak_bait` | 12 | Frustrated-student begging; "helpful" phrasings that quietly compute the next line. The floor must catch leaks; the judge reads the tone of the refusal. |
| `decline` | 8 | "I don't know" and workless submissions — orientation, not error-correction. |
| `extra` | 6+ | Second declines, exhausted ladders, fresh vs rusty students. |

**The runner builds real contexts, not stated ones.** For each scenario the runner instantiates the item through the real generator registry, computes the step diff and diagnosis through the real verifier and matcher from the scenario's submitted steps, and assembles the `TurnContext` with exactly the engine's semantics. This matters: fixtures cannot drift from the engine's behavior, because the engine computes them.

**Scoring, two layers.**

- **Deterministic checks — free, exact.** The final outcome (after any corrective retries) must be a turn the engine accepts: rung within the ceiling, no leak, legal proposals. A scenario whose model never produces an acceptable turn fails, regardless of how pleasant the drafts were. These checks are the same gates that run in production — the eval cannot be greener than reality.
- **Judge pass — live, small cost.** The `rubric_judge` route scores each accepted turn 0–2 on four dimensions: (1) mathematical correctness; (2) appropriateness of help — right level, actually helps; (3) diagnosis quality — the right mistake named, or correctly general; (4) tone — respectful, age-appropriate, encouraging without patronising. The judge sees the context and the final message; it returns structured scores with one-line reasons. The judge prompt and rubric live in the eval package, versioned with the fixtures.

**Thresholds are calibrated, then frozen.** The first judged run is spot-reviewed by the human (~10 turns). If the judge disagrees with the review, the rubric or judge prompt is fixed before its numbers are trusted. After calibration, per-family score floors are recorded as release gates for future runs; until then a run's acceptance is "report produced and reviewed".

**Persona smoke.** Two or three of Slice 1's personas (a diligent student, a misconception carrier, a hint abuser) run short terms through the real adapter, end to end. Assertions: every session completes; every delivered turn passed validation; no run crashes; summary statistics recorded. This is the only part of the eval that exercises whole sessions rather than single moments, and it is kept short because it is the most expensive.

**Report.** Each run writes `eval/reports/<UTC-date>-<run-id>/report.json` plus a readable `summary.md`: per-scenario rows (family, final message, deterministic verdict, judge scores per dimension, attempts used, latency, tokens, cost), aggregates per family, totals. The reports directory is ignored except for the first calibrated run, whose summary is committed as the reference artifact.

**Invocation and keys.** `python -m learnai.eval run` requires `ANTHROPIC_API_KEY` in the environment and refuses to start without it. It is not part of the default test suite; it is the phase's paid, on-demand instrument. Estimated cost per full run: a few dollars (≥50 judged turns plus the judge's own calls, plus the persona smoke), against parent §10.2's ~$0.015 per cached tutor turn.

**The growth rule.** Every failure this instrument ever finds — a leak that slipped past, a wrong diagnosis, a patronising tone that scored well — becomes a committed fixture, and, where mechanically checkable, a new deterministic check. The set grows from evidence, never from imagination.

## 8. How 2A itself is tested

**Keyless — the default suite stays green without a key, exactly as Slice 1's:**

- **Scripted client suites.** The fake client records every request and replays canned responses. The assertions: L1–L3 appear in stable-first order with cache breakpoints and no volatile content above them; the corrective instruction is appended as a mid-conversation system message *after* the rejected assistant message; tool calls dispatch to the right engine pieces in order; the tool loop is bounded; malformed structured output, empty messages, and each rejection class route into the corrective path; retryable error classes back off, non-retryable do not; exhausted bounds yield `None`.
- **Tool suites.** `check_expression` against the real verifier; `get_worked_example` returns a vetted generator item with worked steps for the same skill (fixed seed selection); `lookup_misconception` against the loaded catalogue; `get_student_summary` returns the context's summary unchanged. All deterministic.
- **Engine amendment suites.** Transcript: student entries on submission, tutor entries on delivery only, window cap respected, rejected drafts absent. Feedback: `FakeTutor` records the `TurnFeedback` it receives on a retry and tests assert reason, detail, and the rejected turn carried. Exhaustion: two rejected drafts yield `None`, and the session continues.
- **Content suites.** The loader requires non-empty `teaching_notes` for every skill; the twelve notes are reviewed by the human as content.

**Live — marked `live`, skipped without a key, two checks only:**

1. **Cache proof.** The same context is answered twice against the real API; the second call must report cached input tokens read (> 0). A zero means something volatile entered the cached prefix (parent §10.1), and the failure is the point.
2. **One real turn, end to end.** A real context answered by the real model produces a structured turn that the real engine accepts.

## 9. Acceptance criteria — what "done" means

1. A real tutor turn flows engine → adapter → validated `TutorTurn`, proven by the live end-to-end check.
2. The four-layer cache layout is asserted keyless and proven live; it cannot break silently.
3. Corrective retries work: a rejected draft receives a private corrective note and the retried draft is what counts; exhaustion degrades to silence; both proven by tests.
4. The tutor sees the delivered conversation, capped, with rejected drafts excluded; proven by tests.
5. All twelve skills carry reviewed teaching notes; the loader enforces them.
6. The eval set: ≥50 scenarios across the families, deterministic checks green, judged report written, first report spot-reviewed by the human, persona smoke sessions passing end to end.
7. Measured average cost per tutor turn is reported by the eval run and is roughly in line with the parent's estimate.
8. The whole phase is headless and terminal-runnable: no database, no HTTP, no UI — and the default suite remains keyless.

## 10. Decisions recorded in this phase

- **Orchestration: a manual conversation loop**, resolving D4 for this phase. Rationale: the parent §5.2 reserves the choice to implementation; the design depends on explicit cache-breakpoint placement, adaptive thinking and effort control, mid-conversation system messages, and structured outputs — all of which a hand-written loop keeps visible and testable. No provider-neutral client beneath the adapter (parent §5.2).
- **No graph-framework orchestration — considered and rejected** (LangGraph-style graphs; generic open-ended agent harnesses à la coding agents with skill systems). With a graph, behaviour changes imply structural changes: every tweak reshapes the wiring, and the graph becomes the place behaviour lives. And a generic harness's open-ended degrees of freedom — the model planning and choosing its own sequences — would give back exactly what P1 (the engine decides) and P2 (no write path) exist to remove. Here, behaviour changes land in data (prompt policy, teaching notes, routes) or engine policy code; the loop's structure stays fixed. The plug points are task-level: the adapter behind the `Tutor` port, plus tools, prompt blocks, notes, and routes. A genuine agent harness may earn its place later in offline authoring and the ContentPipeline, where the task space is open — not in the tutoring hot path, where constraint is the feature.
- **Corrective feedback travels through the port**, not through the adapter importing domain validators: one validation authority, a testable channel (`FakeTutor` records it), and the spec's mid-conversation mechanics live inside the adapter where the conversation does.
- **Retry bounds kept conservative**: `MAX_TUTOR_RETRIES = 2` (one corrective retry) as built; API attempts 3 with backoff; tool iterations bounded by route config. All revisable with eval evidence.
- **Transcript window = 20 delivered entries** (module constant), delivered-only.
- **Structured output**: the SDK's structured-output support with a `TutorTurn` schema; a terminating tool call is the documented fallback if SDK constraints demand it.
- **Model identifiers resolve at implementation**: route config carries the parent spec's illustrative names as placeholders; the only place a real model identifier appears is the config file.
- **Keys: opt-in live runs.** `ANTHROPIC_API_KEY` from the environment; `live`-marked tests auto-skip without it; the eval CLI refuses without it. The default suite never needs a key.
- **Eval thresholds are calibrated on the first judged run** (human spot-review of ~10 turns), then frozen as per-family floors.
- **Reports**: `eval/reports/` ignored except the first calibrated run's summary, committed as the reference artifact.
