# Slice 1 — Plan 2A: Anthropic Tutor Adapter and Graded Eval Set — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach the real tutor — `AnthropicTutor` behind the existing `Tutor` port, with job-based routing, a cached four-layer prompt, read-only tools, and corrective retries — and build the graded eval set that measures it, all headless and keyless by default.

**Architecture:** Hexagonal, unchanged: the domain core keeps every decision. This plan adds an adapter package, revisioned student interactions, delivered assistance accounting, scoped history and a request-scoped corrective exchange, teaching notes as content, and an `eval` package (fixtures → real engine-built contexts → adapter → deterministic checks + rubric judge → report). No framework orchestration: two small bounded Python loops, and the spec records why graph frameworks were rejected (`docs/superpowers/specs/2026-10-16-anthropic-tutor-eval-design.md` §10).

**Tech Stack:** Python 3.12+, SymPy, pytest, Hypothesis, PyYAML, the Anthropic Python SDK (new, adapter-side only), httpx (SDK transport; used directly for scripted test clients).

**Spec:** `docs/superpowers/specs/2026-10-16-anthropic-tutor-eval-design.md` — the design this plan implements. The parent spec `docs/superpowers/specs/2026-09-14-ai-tutoring-platform-design.md` remains the binding authority.

**Revision 2026-10-25:** Records the agreed history, current-interaction, assistance, retrieval, response-budget, judge-packet, corpus-validity and run-provenance/accounting decisions. The five discussed review issues are recorded; implementation and live calibration remain unverified.

**Current implementation status — 2026-10-26:** Tasks 1–14 are implemented and reviewed.
Task 15's keyless implementation is pending independent review. See [eval/README.md](../../../eval/README.md)
and the execution ledger for current behavior and verification limits. The dated review-only
notes below describe the earlier planning scope; paid live acceptance and human calibration remain unverified.

## Global Constraints

Project constraints from the parent spec, clarified for runtime versus study time; every task includes these.

- **P1 — The engine decides; the model speaks.** Every consequential decision lives in deterministic code.
- **P2 — The model has no write path to mastery.** No tool, port, or adapter reachable by a tutor may mutate `SkillState`. Enforced by absence, and by a property test.
- **P3 — Verification before language.** A deterministic checker runs first; the model receives its output.
- **P4 — Assistance is free; credit is not.** Help costs nothing except mastery credit.
- **P5 — Performance is not learning.** Evidence gathered on a skill taught in the same session is weighted near zero.
- **P6 — Evidence is append-only.** Attempts and help events are immutable; `SkillState` is a projection rebuildable from the log.
- Domain core (`src/learnai/domain/`) imports only the standard library and `typing`. **No SymPy, no YAML, no I/O.** Enforced by a test.
- All pedagogical time is UTC, `datetime` aware, and reaches the domain only through the `Clock` port. Elapsed study time is float days; adapter execution deadlines use a separate injected monotonic clock.
- Python 3.12+. Strict typing: every public function annotated.

Additional constraints for Plan 2A:

- **The default test suite stays keyless.** Everything except `live`-marked tests runs with no `ANTHROPIC_API_KEY` and no network. `live` tests auto-skip without the key.
- **No model identifier appears outside `config/llm_routes.yaml`.**
- **The adapter never imports domain validators.** Retries travel through `TurnFeedback`; `validate_turn` and `request_validated_turn` remain engine/eval concerns.
- **Prose is data, not code.** Tutor- and judge-facing policy text lives in `prompts/` as versioned files (`name@version`); adapters compose prompts but never author them. Every eval report records the prompt ids it ran — prompt ids are required provenance; run comparability follows the captured manifest and evaluator rules in Task 13.
- **Provider-neutral machinery lives at `adapters/tutor/`.** Rendering and prompt loading hold no provider specifics; provider mechanics (cache layout, message roles, tool-schema encoding) live under `adapters/tutor/anthropic/`. The first toolbox contains math-specific CAS handlers; a subject-generic tool registry remains a separate design question.
- **Delivered-only tutor transcript.** Student interaction snapshots carry provenance; rejected drafts, internal tools and operator messages remain in a separate private trace.
- **One response, one budget.** API, formatting, tool and validation retries share a request-scoped exchange and allowance.
- **Current work is explicit.** Draft/questions are not implicit submissions; current engine state is authoritative.
- **History is selected by tokens and exercise boundaries.** Protect active working; retrieve older records through a bound read scope.
- **Nothing student-visible on failure.** A failed or exhausted tutor call yields `None` — no message, no help consumed — and the incident is logged.

---

## File Structure

```
pyproject.toml                            # Modify: +anthropic dependency; register the `live` pytest marker
config/llm_routes.yaml                    # Create: the only place model identifiers and prompt references appear
prompts/tutor_math/v1.md                  # Create: the tutor policy text (versioned; iterated against the eval)
prompts/rubric_judge/v1.md                # Create: the judge rubric (versioned; calibration is tied to it)
src/learnai/adapters/tutor/rendering.py   # Create: render_* — domain objects to model-facing text (provider-neutral)
src/learnai/adapters/tutor/prompts.py     # Create: TutorPrompt + load_prompt (provider-neutral)
src/learnai/adapters/tutor/tools.py       # Create: the Tool table + Toolbox (provider-neutral)
src/learnai/adapters/tutor/anthropic/
  __init__.py                             # Create: empty package marker
  routing.py                              # Create: routes + response-job budgets; fail-fast
  prompt.py                               # Create: four-layer assembly, cache breakpoints, correction append
  tool_schema.py                          # Create: the Tool table encoded into Anthropic tool payloads
  turn_schema.py                          # Create: structured-turn schema and parser
  adapter.py                              # Create: AnthropicTutor — the conversations loop and bounds
src/learnai/domain/turn.py                # Modify: +TurnFeedback, + request_validated_turn
src/learnai/domain/ports.py               # Modify: TutorExchange + begin_turn; one-shot respond retained
src/learnai/domain/session.py             # Modify: Session +transcript/history; Task +work revision
src/learnai/domain/skills.py              # Modify: Skill +teaching_notes (defaulted)
src/learnai/domain/engine.py              # Modify: ask_question, work/progress/history and shared driver
src/learnai/domain/interaction.py         # Create: work/verification snapshots and task progress
src/learnai/domain/history.py             # Create: records, scope/query/page and reader port
src/learnai/domain/{help,events}.py        # Modify: independence separate from hint progression
src/learnai/adapters/tutor/context.py     # Create: protected token-budgeted context selection
src/learnai/adapters/tutor/runtime.py     # Create: monotonic budgets and private traces
src/learnai/adapters/persistence/in_memory_history.py # Create: scoped current-session reader
src/learnai/adapters/tutor/fake_tutor.py  # Modify: record feedback
src/learnai/adapters/content/loader.py    # Modify: teaching_notes required
content/quadratics/skills.yaml            # Modify: teaching notes for all twelve skills
src/learnai/eval/
  __init__.py                             # Create: empty package marker
  fixtures.py                             # Create: scenario schema, loader and keyless corpus preflight
  runner.py                               # Create: context builder, validated-turn driver, outcomes
  judge.py                                # Create: rubric judge via the rubric_judge route
  smoke.py                                # Create: persona smoke sessions
  manifest.py                             # Create: captured inputs and configuration fingerprint
  accounting.py                           # Create: shared request ledger and dated price estimates
  report.py                               # Create: JSON + summary writers
  __main__.py                             # Create: CLI (python -m learnai.eval run)
eval/fixtures/
  ladder.yaml                             # Create: >=12 scenarios
  diagnosis.yaml                          # Create: >=12 scenarios
  leak_bait.yaml                          # Create: >=12 scenarios
  decline.yaml                            # Create: >=8 scenarios
  extra.yaml                              # Create: >=6 scenarios
eval/README.md                            # Create: run instructions, report policy, calibration record
tests/support/scripted_client.py          # Create: recording/replaying Anthropic client (MockTransport)
tests/domain/test_transcript_and_feedback.py   # Create
tests/domain/test_context_notes.py        # Create
tests/domain/{test_interaction,test_assistance,test_history}.py # Create
tests/adapters/tutor/{test_context,test_runtime}.py # Create
tests/adapters/test_in_memory_history.py  # Create
tests/adapters/test_content_loader.py     # Modify: fixtures gain notes; +rejection tests
tests/adapters/tutor/test_routing.py      # Create
tests/adapters/tutor/test_prompts.py      # Create
tests/adapters/tutor/test_rendering.py    # Create
tests/adapters/tutor/test_prompt.py       # Create (assembly + corrective channel)
tests/adapters/tutor/test_tools.py        # Create (the table, the handlers, the encoding)
tests/adapters/tutor/test_turn_schema.py  # Create
tests/adapters/tutor/test_adapter.py      # Create
tests/adapters/tutor/test_adapter_engine.py    # Create (keyless end-to-end through the engine)
tests/adapters/tutor/test_live.py         # Create (live-marked; skipped without a key)
tests/eval/test_fixture_corpus.py         # Create: coherent scenarios, exact expectations and coverage
tests/eval/test_fixtures.py               # Create
tests/eval/test_runner.py                 # Create
tests/eval/test_judge.py                  # Create
tests/eval/test_manifest.py               # Create
tests/eval/test_accounting.py             # Create
tests/eval/test_report_cli.py             # Create
tests/eval/test_smoke.py                  # Create
```

---

### Task 1: Current interactions, assistance, session history and corrective exchanges

**Files:**
- Create: `src/learnai/domain/interaction.py`, `src/learnai/domain/history.py`
- Modify: `src/learnai/domain/{turn,ports,session,engine,help,events}.py`
- Modify: `src/learnai/adapters/tutor/fake_tutor.py`
- Test: `tests/domain/test_transcript_and_feedback.py`, `tests/domain/test_interaction.py`, `tests/domain/test_assistance.py`, `tests/domain/test_history.py`

**Interfaces:**
- `interaction.py`: frozen `StudentInteraction(task_id: TaskId, revision: int, kind: InteractionKind, status: WorkStatus, steps: tuple[str, ...], answer: Submission, question: str | None = None, referenced_step: int | None = None)`. `InteractionKind` has SUBMISSION, TASK_QUESTION, HELP_REQUEST; `WorkStatus` has DRAFT, SUBMITTED, REVISED. The revision fields here identify student work (`work_revision`), not document versions. Revision is nonnegative; a referenced step is zero-based and must exist. Same task/revision requires identical raw steps and structured answer (including claims_none); changed work requires a greater revision. A question-only change may retain the work revision but gets its own interaction record id. First work may use revision 0. Reject conflicting equal revisions before side effects; submit assigns the next revision automatically when work changes. Interface-only guidance stays a predefined application response, outside this free-form port.
- Frozen `VerificationSnapshot(revision: int, answer_checked: bool, steps_checked: bool, verdict: Verdict | None, step_diff: StepDiff | None, diagnosis: MisconceptionId | None, failed_constraints: tuple[FormConstraint, ...] = ())`. No final verdict when `answer_checked=False`; a wrong *step* does not fabricate a wrong final answer. Old findings stay attached to their revision.
- Frozen `TaskProgress(submissions: int, genuine_attempts: int, declines: int, delivered_rungs: tuple[HelpRung, ...], independence_spent: bool, last_checked_revision: int | None)`. Derive counts from engine state/records, never model text.
- `history.py`: frozen `HistoryRecord(id: str, at: datetime, student_id: StudentId, session_id: SessionId, task_id: TaskId, item_id: ItemId, skill_id: SkillId, revision: int, kind: HistoryKind, interaction: StudentInteraction | None = None, message: str | None = None, verdict: Verdict | None = None, evidence_class: EvidenceClass | None = None, rung: HelpRung | None = None, related_record_ids: tuple[str, ...] = ())`. Preserve typed metadata and related-record links alongside raw interaction content; skill is one optional retrieval filter, not an access boundary. `HistoryKind`: STUDENT_QUESTION, SUBMISSION, TUTOR_DELIVERED, HELP_DELIVERED. SUBMISSION may include NO_ANSWER; unreadable submissions retain existing no-evidence semantics. Generate ids from session id plus monotonic record sequence, and timestamps from the UTC domain Clock.
- Frozen `HistoryScope(student_id: StudentId, session_id: SessionId)`, `HistoryQuery(task_id: TaskId | None = None, skill_id: SkillId | None = None, before_id: str | None = None, limit: int = 10, item_id: ItemId | None = None, kind: HistoryKind | None = None, after: datetime | None = None, before: datetime | None = None)`, `HistoryPage(records: tuple[HistoryRecord, ...], next_before_id: str | None)`. Read scope is bound by application code; query has no student/session override. The scoped reader implementation is Task 5.
- `TurnContext` gains defaulted `interaction: StudentInteraction | None = None`, `verification: VerificationSnapshot | None = None`, `task_progress: TaskProgress | None = None`, `history_scope: HistoryScope | None = None`, `history: tuple[HistoryRecord, ...] = ()`, `current_interaction_id: str | None = None`, `response_job: ResponseJob = ResponseJob.NORMAL`. `ResponseJob` is defined in domain/interaction.py as a domain enum (BRIEF, NORMAL, SUBSTANTIAL, COMPLEX) for engine-controlled request classification, not a model choice. Keep existing fields; `last_verdict`, `step_diff`, `diagnosis` mirror current-revision findings only. Defaults support old isolated fixtures, but engine-created contexts always fill the new fields.
- `Task` gains defaulted `work_revision: int = 0` and `current_interaction: StudentInteraction | None = None`; `Session` gains defaulted `transcript: tuple[TranscriptEntry, ...] = ()` and `history: tuple[HistoryRecord, ...] = ()`. Extend `TranscriptEntry` with optional `record_id`, `task_id`, `revision`, `at` fields after existing positional speaker/text. Engine-produced entries fill provenance; legacy direct constructions remain valid.
- `PracticeEngine.ask_question(session: Session, states: dict[SkillId, SkillState], interaction: StudentInteraction, *, response_job: ResponseJob = ResponseJob.NORMAL) -> tuple[Session, TutorTurn | None]`. Validate current task/revision and shape and allowed response job first; no attempt, reveal effort or mastery update. Timed contracts reject task questions. `submit` and `request_help` retain their existing public signatures and construct current snapshots internally. `submit` advances revision when new submitted working differs; help uses the latest snapshot without inventing a submission.
- `HelpState` gains `assistance_received: bool = False`; `help_taken` includes that flag. Record delivered task assistance independently from ladder progression: append HelpTaken for accepted task replies, set the flag, and call `record_help` only for rung > NONE. This applies to questions, requested help and unsolicited feedback. A NONE-rung task reply can spend independence without consuming a ladder rung. Silence/rejected drafts do neither. Prior evidence events are unchanged. Existing NONE-rung tests must distinguish these two effects.
- `TutorExchange` protocol: `respond(*, feedback: TurnFeedback | None = None) -> TutorTurn | None`, `expired() -> bool`, `record_validation(result: ValidationResult) -> None`, read-only `stop_reason: str | None`, `finish(*, accepted: TutorTurn | None, reason: str) -> None`. `Tutor.begin_turn(context: TurnContext) -> TutorExchange` creates one private exchange for the whole validation loop. `Tutor.respond(context, *, feedback=None)` remains a one-shot convenience. FakeTutor implements begin_turn via a wrapper delegating to its scripted respond and recording feedback; it never expires.
- `request_validated_turn(tutor, context, graph, verifier, *, max_attempts: int) -> tuple[TutorTurn | None, int]`: create exactly one exchange, request/validate/retry on it, record validation, check expiry before and after validation, finish in `finally`. Reject nonpositive max_attempts before opening an exchange. Return accepted turn + actual attempt count, or None + actual count; preserve an existing operational stop_reason rather than overwriting api_error/context_limit with generic silence. No model draft is delivered after deadline. Reasons: accepted, silent, validation_exhausted, deadline, context_limit, tool_limit, token_limit, format_exhausted, api_error. The adapter supplies operational reasons to its trace; the driver supplies validation outcomes. `TurnFeedback` remains reason/detail/rejected.

- [ ] **Step 1: Write failing domain tests with these assertions.**

| Test | Required assertions |
|---|---|
| `test_question_keeps_raw_work_and_reference_without_submission` | Draft `(x+3)(x+4) -> x^2+4x+3x+12`, blank answer, question “Do I add 4x and 3x?”, referenced_step=1 all survive into context; zero AttemptRecorded and zero genuine attempts. |
| `test_invalid_or_stale_work_is_rejected_before_side_effects` | Wrong task, negative revision, missing referenced step, or revision older than Task.work_revision, or changed steps/answer at the same revision raises ValueError; evidence/history/help unchanged. |
| `test_question_only_change_keeps_work_revision` | New question with identical steps/answer retains work revision but receives a distinct interaction id; changed work at a newer revision clears current answer findings. |
| `test_old_verdict_is_not_attached_to_revised_work` | Old wrong submission remains in history; revised draft has no final verdict until explicitly checked; old check retains old revision. |
| `test_delivered_task_reply_spends_independence_even_at_none_rung` | Accepted task reply at NONE sets help_taken, records HelpTaken, leaves rungs_used unchanged; later correct answer has ASSISTED and zero strength contribution. |
| `test_silent_question_preserves_independence` | None/rejected-only exchange records the student's explicit question but no HelpTaken or AttemptRecorded; subsequent first independent submission can be cold. |
| `test_predefined_interface_guidance_is_not_task_tutoring` | Interface guidance bypasses the Tutor entirely and records no help/attempt; free-form assessed-terminology questions use the task-question path. |
| `test_assistance_does_not_rewrite_a_cold_failure` | Cold wrong submission event stays byte-for-byte equivalent after help and correction; later answer ASSISTED; replay yields the same assessment state. |
| `test_question_does_not_unlock_reveal` | Repeated questions and draft edits leave genuine-attempt count unchanged; timed contract rejects task questions without calling Tutor. |
| `test_decline_and_no_solutions_are_distinct` | Use blank Submission.of("") for SINGLE_VALUE decline, not Submission.none(); no-solutions is an explicit claim only where shape allows it. |
| `test_transcript_has_only_delivered_tutor_messages` | Students' questions/submissions and accepted tutor text only; no rejected drafts, tools or correction instructions. Current interaction id is available for prompt deduplication. |
| `test_one_exchange_survives_corrective_validation` | begin_turn once; rejected FULL_REVEAL followed by accepted NUDGE receives TurnFeedback on the same exchange; finish once; two attempts. |
| `test_expiry_after_validation_prevents_delivery` | Expiry becomes true during verification; returned turn None, no delivery or help consumption. |

Use the existing real engine construction from `tests/domain/test_engine.py`. Wrong answers must be readable and verified WRONG for the selected item. For transcript assertions capture the pre-reply context, rather than comparing it to a transcript containing a later tutor reply. Keep the original malformed-submission no-state-change regression.

- [ ] **Step 2: Run `.venv/bin/pytest tests/domain/test_interaction.py tests/domain/test_assistance.py tests/domain/test_history.py tests/domain/test_transcript_and_feedback.py -v`.** Expected: fail because new types/operations do not exist.
- [ ] **Step 3: Implement the interfaces and engine wiring above.** Extract a shared engine context builder consumed by Task 11; define `build_turn_context(*, session: Session, task: Task, states: dict[SkillId, SkillState], interaction: StudentInteraction, verification: VerificationSnapshot, graph: SkillGraph, catalogue: Mapping[MisconceptionId, Misconception], now: datetime, permitted_rung: HelpRung, parameters: MasteryParameters, response_job: ResponseJob = ResponseJob.NORMAL) -> TurnContext` in `domain/turn.py` (TYPE_CHECKING imports for session types). Initially read notes with getattr(skill, "teaching_notes", ""); Task 2 then supplies the declared field. Resolve parameter_overrides per skill before passing parameters to this builder so live and eval contexts do not silently use the global defaults. Separate delivered assistance from rung progression, preserve old evidence, and bind each history record to its task/revision. Domain code imports no runtime/tokenizer/provider code.
  Add `prepare_verification(interaction: StudentInteraction, *, item: Item, verifier: Verifier,
  catalogue: Sequence[Misconception], matcher: MisconceptionMatcher, check_answer: bool,
  check_steps: bool) -> VerificationSnapshot` in `domain/interaction.py`, with TYPE_CHECKING
  imports where needed to avoid cycles. Extract the existing engine's checks/diagnosis fallback
  into it, preserving submission behavior: blank -> NO_ANSWER; malformed -> no evidence/tutor;
  correct final submission -> completion without unsolicited tutoring; wrong readable work ->
  actual step diff plus the existing final-transition form-diagnosis fallback when diff is None.
  Preserve failed_constraints from CheckResult; never turn a valid but incomplete factorization
  into a broken equivalence. For final submissions preserve the existing check_steps policy
  (wrong, non-declined work only); explicit draft questions may request scoped step checks without
  checking the final answer. Engine and eval call this helper before the shared context builder.
  Add parity regressions for partial factoring, wrong algebra, correct final submissions and
  questions about correct draft work. This reuses Slice 1 behavior; it is not a new grading policy.
- [ ] **Step 4: Run focused tests, existing engine/help/projection tests and `tests/test_domain_purity.py`, then the full keyless suite.** Expected: all pass; explicitly update the previous NONE-rung expectation for independent contamination versus ladder progress.
- [ ] **Step 5: Commit only the files listed above.** Suggested subject: `feat: model current student interactions and preserve private tutor exchanges`.

---

### Task 2: Teaching notes v0 — content, the `Skill` field, the loader requirement, and the context wiring

**Files:**
- Modify: `src/learnai/domain/skills.py` (`Skill` gains `teaching_notes`)
- Modify: `content/quadratics/skills.yaml` (notes for all twelve skills)
- Modify: `src/learnai/adapters/content/loader.py` (require non-empty notes)
- Modify: `src/learnai/domain/turn.py` (shared `build_turn_context` passes `skill.teaching_notes`)
- Modify: `tests/adapters/test_content_loader.py` (fixtures gain notes; rejection tests)
- Test: `tests/domain/test_context_notes.py` (new)

**Interfaces:**
- Consumes: `Skill` construction sites in the loader; `build_turn_context` (Task 1's shared version).
- Produces: `Skill.teaching_notes: str = ""` (last field, defaulted); the loader's `ContentError` when a skill has no non-blank `teaching_notes`; `TurnContext.skill_pack.teaching_notes` carries the skill's notes.

- [ ] **Step 1: Write the failing tests**

```python
# tests/domain/test_context_notes.py
import pathlib

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.contracts import PRACTICE
from learnai.domain.engine import PracticeEngine
from learnai.domain.enums import Confidence
from learnai.domain.ids import CourseId, SessionId, StudentId
from learnai.domain.items import Submission

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)


def test_the_tutor_context_carries_the_skills_teaching_notes():
    tutor = FakeTutor()
    engine = PracticeEngine(
        graph=CLUSTER.graph,
        misconceptions=CLUSTER.misconceptions,
        item_source=GeneratorRegistry(QUADRATICS_TEMPLATES),
        verifiers={CAS_SYMBOLIC: SympyVerifier()},
        tutor=tutor,
        matcher=SympyMisconceptionRules(),
        evidence_log=InMemoryEvidenceLog(),
        clock=FakeClock(),
        contract=PRACTICE,
    )
    session = engine.start_session(
        student_id=StudentId("stu"),
        course_id=CourseId("quadratics"),
        course_skills=CLUSTER.graph.topological_order(),
        states={},
        budget_items=1,
        session_id=SessionId("sess-1"),
        seed=7,
    )
    skill_id = session.current_task.skill_id
    engine.request_help(session, {})
    seen = tutor.contexts_seen[-1]
    assert seen.skill_pack.teaching_notes
    assert seen.skill_pack.teaching_notes == CLUSTER.graph.skills[skill_id].teaching_notes


def test_every_skill_in_the_cluster_has_notes():
    for skill in CLUSTER.graph.skills.values():
        assert skill.teaching_notes.strip(), f"{skill.id} has no teaching notes"
```

Add to `tests/adapters/test_content_loader.py` these two tests. First extend that module's constants: `SKILL_A` gains `"teaching_notes": "notes for A"` (line ~61) and `SKILL_B` gains `"teaching_notes": "notes for B"`; the module's `cluster(**overrides)` helper then needs no change.

```python
def test_a_skill_without_teaching_notes_is_rejected():
    raw = cluster(
        skills=[{key: value for key, value in SKILL_A.items() if key != "teaching_notes"}]
    )
    with pytest.raises(ContentError, match="teaching_notes"):
        parse_cluster(raw)


def test_blank_teaching_notes_are_rejected():
    raw = cluster(skills=[SKILL_A | {"teaching_notes": "   "}])
    with pytest.raises(ContentError, match="teaching_notes"):
        parse_cluster(raw)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/domain/test_context_notes.py tests/adapters/test_content_loader.py -v`
Expected: FAIL — notes are empty (engine test), and `parse_cluster` accepts missing/blank notes (loader tests).

- [ ] **Step 3: Amend `skills.py` — add the field**

Append to `Skill`, as the last field, defaulted:

```python
    teaching_notes: str = ""
    """How to teach this skill — the tutor's cached skill-pack content.
    The loader requires it non-empty; the domain default keeps the field
    additive for direct constructions in tests."""
```

- [ ] **Step 4: Author the notes — amend `content/quadratics/skills.yaml`**

Add a `teaching_notes: |` block to each skill entry (same indent as `can_do:`), verbatim these twelve texts:

`quad.expand.binomial`: "Expand (x + a)(x + b) by distributing — each term of the first binomial times each term of the second — then collect like terms. First move: multiply the two 'first' terms, then the two cross products, then the two 'last' terms. The classic slip is dropping the cross terms: a student who writes only x² + ab has the Foil-drops-cross belief — help them see the two inner and outer products explicitly. Check work by substituting a small value of x into both forms."

`quad.expand.square`: "(x + a)² means (x + a)(x + a), never x² + a². The middle term 2ax is always present. First move: write the square as an explicit product. If the student squared each term separately (the square-distributes belief), show a numeric example — (3 + 4)² — that makes the missing 24 visible, then redo the algebra. Check by expanding one cross term at a time."

`quad.factor.common`: "Nearly every factoring starts by pulling out the greatest common monomial: 12x² + 18x = 6x(2x + 3). First move: look at the coefficients and each variable's smallest power. The classic error is partial extraction — pulling 2x instead of 6x — which leaves a common factor inside the bracket; ask 'is there anything still common inside?'. Check by expanding back."

`quad.factor.monic`: "For x² + bx + c, find two numbers whose product is c and whose sum is b, then write (x + p)(x + q). First move: list factor pairs of c. Sign logic: c > 0 and b < 0 means both numbers are negative; c < 0 means the numbers have opposite signs. The classic error is a sign slip (right magnitudes, wrong signs) — have the student re-check the SUM, not just the product. Check by expanding."

`quad.factor.diffsquares`: "a² − b² = (a − b)(a + b), for any squares: 4x² − 9 = (2x − 3)(2x + 3). First move: write both terms as squares (what is squared to give 4x²?). The telling slip is treating a² + b² the same way — sums of squares do not factor over the reals, so the student must notice the minus before choosing the pattern. Check by expanding."

`quad.factor.nonmonic`: "For ax² + bx + c with a ≠ 1: use the ac-method — find two numbers with product a·c and sum b, split the middle term, then factor in pairs — or trial-and-error with factor pairs of a and c. First move: compute a·c; the pair of numbers does the work. The classic error is factoring as though a were 1, which leaves the expansion short by the leading factor. Check by expanding; the leading term must come out right."

`quad.solve.factoring`: "Solving by factoring has a strict order: move everything to one side so the right side is exactly 0, factor, then set EACH factor to zero (the zero-product property applies only to a zero product). First move: get the 0 first. Two classic errors: applying zero-product to a non-zero right side, and dividing by the variable (which throws a root away). Check by substituting each root back."

`quad.completesquare`: "Rewrite x² + bx by taking half of b, squaring it, and adding AND subtracting it: x² + bx + (b/2)² − (b/2)², then collapse to (x + b/2)² − (b/2)². First move: half of b — it drives everything. The classic error adds the square without subtracting it, changing the expression's value; remind the student that adding zero keeps things equal. Check by expanding back to the original."

`quad.formula.apply`: "Get the equation into standard form first, then identify a, b, c with their signs, and substitute into x = (−b ± √(b² − 4ac)) / 2a. First move: write a, b, c on a line before touching the formula. The classic error drops the negation of b — the numerator starts with −b, the whole b including its sign flipped. Check: substitute the roots back, or sanity-check the discriminant's sign."

`quad.discriminant`: "The discriminant b² − 4ac decides the count: positive — two real roots; zero — one repeated root; negative — no real roots. First move: compute b² − 4ac carefully (mind the signs of b and c). The classic error is reversed cases — reading a negative discriminant as two real roots. Check: evaluate the quadratic at its vertex, or sketch — a negative discriminant means the parabola misses the x-axis."

`quad.vertex`: "Two shapes, two methods. In vertex form y = a(x − h)² + k the vertex is (h, k) — the sign inside the bracket flips when read out. In standard form, x = −b/(2a) gives the axis of symmetry, then substitute to get y. First move: identify which form the equation is in. The classic error is the sign flip reading (x − h) as (−h). Check by substituting the vertex's x back."

`quad.word.area`: "Model area problems explicitly: name the unknown (width = w), express the other dimension through it (length = w + 3), write area = product, expand to a quadratic, solve, then interpret. First move: write the 'let' statement. The classic error keeps a negative root as a valid length — dimensions must be positive; reject it and say why. Check by substituting back into the problem's words, not just the equation."

- [ ] **Step 5: Amend `loader.py` — require the notes**

In the loop that builds each `Skill(...)`, before the construction:

```python
        notes = entry.get("teaching_notes")
        if not (isinstance(notes, str) and notes.strip()):
            raise ContentError(f"skill {sid} has no teaching_notes")
```

and add `teaching_notes=notes,` to the `Skill(...)` construction arguments.

- [ ] **Step 6: Amend the shared context builder — pass the notes into the context**

In Task 1's shared `build_turn_context` in `domain/turn.py`, replace the temporary getattr fallback with `teaching_notes=skill.teaching_notes`; the engine and eval both consume it.

- [ ] **Step 7: Update the loader test fixtures and run everything**

Give every skill entry in the loader test module's raw-cluster helper a `teaching_notes` value (any non-blank string). Then run:

Run: `.venv/bin/pytest tests/domain/test_context_notes.py tests/adapters/test_content_loader.py -v`
Expected: all pass — including the two new rejection tests.

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add src/learnai/domain/skills.py content/quadratics/skills.yaml src/learnai/adapters/content/loader.py src/learnai/domain/turn.py tests/adapters/test_content_loader.py tests/domain/test_context_notes.py
git commit -m "feat: teaching notes for the quadratics cluster, required by the loader"
```

---

### Task 3: Route configuration, response budgets and versioned prompt loading

**Files:**
- Create: `config/llm_routes.yaml`, `src/learnai/adapters/tutor/anthropic/{__init__,routing}.py`, `src/learnai/adapters/tutor/prompts.py`
- Test: `tests/adapters/tutor/test_routing.py`, `tests/adapters/tutor/test_prompts.py`

**Interfaces:**
- `Route(name, adapter, model, effort=None, thinking=None, temperature=None, max_tokens=2048, stream=False, prompt=None, budget_profile="normal")`, frozen. Do not retain the ambiguous `max_tool_iterations` setting.
- Frozen `BudgetProfile(soft_seconds: float, hard_seconds: float, max_round_trips: int, max_tool_calls: int, max_output_tokens: int, context_input_tokens: int, finalization_reserve_tokens: int)`. Round trips count model calls; tool calls count individual read calls, not submit_turn. max_output_tokens is cumulative generated tokens, including thinking and retries; route.max_tokens remains the per-call upper bound.
- `parse_routes(raw: Mapping) -> dict[str, Route]`, `load_routes(path: Path) -> Mapping[str, Route]`, `resolve_route(routes, name) -> Route`, `load_budget_profiles(path: Path) -> Mapping[str, BudgetProfile]`. A route references a profile in the same file. Reject unknown fields/adapters/profiles, booleans as numeric limits, nonpositive/nonfinite limits, soft >= hard, or reserve >= token allowance. Reserved error_diagnosis may omit a prompt; live tutor/judge constructors require one.
- `PromptError(ValueError)`, `PROMPTS_ROOT`, `TutorPrompt(name: str, version: int, path: Path, text: str)` with id `name@version`; `load_prompt(reference: str, *, root: Path = PROMPTS_ROOT) -> TutorPrompt`. Exact reference grammar `[a-z][a-z0-9_]*@[1-9][0-9]*`; resolve to `root/name/vN.md`, reject traversal, missing/empty text.

**Initial configuration values are engineering starting points, not measured latency guarantees.** Keep all values editable in YAML. Response-job profiles:

| Profile | Soft/hard seconds | Max model round trips | Max individual read calls | Total output tokens | Protected+selected input budget | Finalization token reserve |
|---|---|---|---|---|---|---|
| brief | 3 / 8 | 4 | 8 | 4096 | 16000 | 512 |
| normal | 8 / 15 | 8 | 16 | 8192 | 16000 | 1024 |
| substantial | 20 / 30 | 12 | 24 | 16384 | 24000 | 1024 |
| complex | 30 / 60 | 20 | 40 | 32768 | 32000 | 2048 |

These ceilings are emergency controls; soft deadlines should normally end exploration sooner.
Select the job deterministically from the operation and explicit request metadata; use normal
for ordinary Practice hints/questions, substantial for explicitly requested detailed explanation,
and complex only for an explicitly enabled complex-analysis job. Brief is for designated brief
clarifications, not all short strings; a short question may refer to long working. Use route
configuration to choose model/effort per job; do not add an LLM classifier call. The shared context carries the selected ResponseJob into begin_turn. Engine submit feedback and
request_help use NORMAL; ask_question accepts explicitly designated jobs, default NORMAL. The
application enables COMPLEX explicitly; it is disabled by default and rejected before a call
when not enabled. Tests may enable it; no LLM classifier or question-length heuristic is used.
Use `resolve_tutor_route(routes, job: ResponseJob) -> Route`: NORMAL -> tutor_dialogue,
BRIEF -> tutor_brief, SUBSTANTIAL -> tutor_explanation, COMPLEX -> tutor_complex (required only
when enabled). Declare tutor_brief with brief and tutor_explanation with substantial profiles
alongside tutor_dialogue; prompt tutor_math@1 remains shared. Each route controls its own model/
effort and profile; the chosen job/route/profile is recorded in traces and manifests. The engine
constructor gains `enabled_response_jobs: frozenset[ResponseJob]` defaulting to BRIEF/NORMAL/
SUBSTANTIAL. This slice does not implement Learn mode.
Budgets never relax rung permissions or make a full solution legal in Practice.

- [ ] **Step 1: Write failing tests.** `test_profile_counts_calls_and_round_trips_separately` asserts both limits survive parsing; `test_invalid_budget_values_fail_fast` parametrizes NaN, infinity, zero, negative, bool and inverted soft/hard; `test_route_resolves_job_profile` proves brief/normal/substantial receive their mapped routes/profiles; enabled complex resolves its configured route and disabled/missing complex fails before calls; `test_unknown_profile_and_old_iteration_key_fail` rejects missing profile/max_tool_iterations. Preserve tests for unknown routes, missing model, invalid YAML and prompt references, missing/empty prompt files. Use `model="scripted"` in fixtures; actual vendor ids live only in config.
- [ ] **Step 2: Run `.venv/bin/pytest tests/adapters/tutor/test_routing.py tests/adapters/tutor/test_prompts.py -v`.** Expected: missing modules/types.
- [ ] **Step 3: Implement schema, loaders and config.** YAML has top-level `budget_profiles` and `routes`; commit the four profiles above plus tutor_dialogue (normal, tutor_math@1), tutor_brief (brief, tutor_math@1), tutor_explanation (substantial, tutor_math@1), error_diagnosis (reserved) and rubric_judge (substantial, rubric_judge@1). Resolve actual vendor ids/settings at implementation using current official API docs; no placeholder is a verified API contract. Cache layouts and budgets are independent.
- [ ] **Step 4: Run focused tests and full keyless suite.** Expected: pass without key/network; config loads all five initial routes and all four profiles; enabled complex jobs require an explicit tutor_complex route.
- [ ] **Step 5: Commit the listed files.** Suggested subject: `feat: configure tutor jobs, execution budgets and versioned prompts`.

---

### Task 4: Render the current interaction and select context by tokens and exercise boundaries

**Files:**
- Create: `prompts/tutor_math/v1.md`
- Create: `src/learnai/adapters/tutor/{rendering,context}.py`, `src/learnai/adapters/tutor/anthropic/prompt.py`
- Test: `tests/adapters/tutor/{test_rendering,test_context,test_prompt}.py`

**Interfaces:**
- Rendering functions remain `render_blocks(blocks: tuple[Block, ...]) -> str`, `render_skill_pack(context: TurnContext) -> str`, `render_session_preamble(context: TurnContext) -> str`, `render_moment(context: TurnContext) -> str`. Add `render_interaction(interaction: StudentInteraction, verification: VerificationSnapshot | None) -> str` and `render_history(records: tuple[HistoryRecord, ...]) -> str`.
- `ContextView(active: tuple[TranscriptEntry, ...], earlier: tuple[TranscriptEntry, ...], summary: str, source_ids: tuple[str, ...], input_tokens: int)`; `select_context(context: TurnContext, *, input_budget: int, count_tokens: Callable[[str], int]) -> ContextView`. Raise `ContextLimitError` when protected content alone exceeds the allowance. Model window minus reserved generation/tool headroom can further reduce input_budget. Task 7 injects provider-appropriate counting; tests inject a deterministic counter.
- Protect exercise instructions/constraints, full current working/question/status/reference, authoritative progress, current-revision findings and complete active-task delivered exchanges. Exclude the current record_id from historical messages so it is rendered once as the current moment. Keep earlier exercises by relevance/recency within the remainder; summarize omitted exercises deterministically using engine-authored outcomes, timestamps and source ids. Never label a corrected mistake permanently unresolved. No extra LLM summarizer, no twenty-message cutoff, no truncating raw active work.
- `SystemBlock(text: str, cache: bool = False)`, `Prompt(system: tuple[SystemBlock, ...], messages: tuple[dict[str, Any], ...], context_view: ContextView)`; `build_prompt(context: TurnContext, policy: str, *, input_budget: int, count_tokens: Callable[[str], int]) -> Prompt`; `correction_text(feedback: TurnFeedback) -> str`. Task 7 appends corrective tool results/operator messages to the retained provider exchange, not a rebuilt prompt.
- Four layers: L1 policy cached, L2 skill pack cached, L3 stable session identity/profile metadata cached, L4 current student state/progress/interaction/history volatile. Strength, freshness, misconception state and calibration must not be treated as session-stable. If no stable profile metadata exists in 2A, omit L3 instead of caching evolving state. Prefix-cache tests assert stable layers and volatile separation rather than exactly three cached blocks.

- [ ] **Step 1: Write failing tests.**

| Test | Required assertions |
|---|---|
| `test_render_current_work_and_question_without_grading_a_draft` | Exact steps, answer fields, DRAFT, revision and question reference appear; unchecked final answer labelled not checked, never WRONG. |
| `test_old_check_is_identified_as_old` | Revision 1 WRONG cannot appear as verdict on revision 2; its source remains historical. |
| `test_context_keeps_active_exercise_beyond_twenty_entries` | 24 short active exchanges fit a supplied token budget and all remain; no count-based eviction. |
| `test_budget_excludes_older_exercises_before_active_work` | Earlier raw messages are replaced by deterministic source-linked outcome summaries; active work byte-for-byte unchanged. |
| `test_earlier_mistake_then_correction_stays_ordered` | Summary includes both outcome sources/times, not an unqualified permanent misconception. |
| `test_current_interaction_is_included_once` | Current question/submission id excluded from historical messages; appears once in current moment. |
| `test_protected_overflow_is_explicit` | ContextLimitError before API generation, no partial working sent. |
| `test_volatile_state_is_outside_cached_prefix` | Changing strength, permissions or revision leaves stable cached blocks equal and changes L4. |
| `test_history_is_data_not_operator_instructions` | Student text containing role-like strings remains user data; rejected drafts never become delivered transcript. |

Preserve Text/Formula ordering and fail on unknown block types. Do not inject reference answers or generator worked solutions into the tutor prompt merely because they exist in Item; students' own identical expressions remain valid input and must not be filtered out.

- [ ] **Step 2: Run `.venv/bin/pytest tests/adapters/tutor/test_rendering.py tests/adapters/tutor/test_context.py tests/adapters/tutor/test_prompt.py -v`.** Expected: missing modules/functions.
- [ ] **Step 3: Implement renderers, selector, prompt assembly and policy file.** Policy directs the model to distinguish drafts from submissions, respect checker scope/revision, treat current engine state as authoritative, respond to the referenced work, use tools for checking, respect the permitted rung, and retrieve missing older details. Keep one pedagogical request per reply. The policy may address teenage quadratics students in this slice; age adaptation remains separate future work. Provider mechanics belong only in anthropic/.
- [ ] **Step 4: Run focused tests and full keyless suite.** Expected: pass; changing an old-summary selection never changes evidence or permissions.
- [ ] **Step 5: Commit listed files.** Suggested subject: `feat: render revisioned student work with bounded relevant context`.

---

### Task 5: Read tools and scoped current-session history retrieval

**Files:**
- Create: `src/learnai/adapters/tutor/tools.py`, `src/learnai/adapters/tutor/anthropic/tool_schema.py`
- Create: `src/learnai/adapters/persistence/in_memory_history.py`
- Test: `tests/adapters/tutor/test_tools.py`, `tests/adapters/test_in_memory_history.py`

**Interfaces:**
- Frozen `Tool(name: str, description: str, parameters: Mapping[str, Any], handler: Callable[[Mapping[str, Any], TurnContext], str])`; one table drives implementations and provider schemas.
- `HistoryReader` port in domain/history.py: `read(scope: HistoryScope, query: HistoryQuery) -> HistoryPage`. `InMemoryHistoryReader(records: tuple[HistoryRecord, ...])` implements it without an engine/state write reference; build it from the request's immutable session snapshot. Read skill/item/kind/time metadata directly from HistoryRecord; all optional filters are intersected with bound scope first. Empty filters browse all skills in the permitted session. Require aware UTC time bounds (exclusive after/before, after < before); reject invalid types or unknown filters. No semantic/text search service in 2A; preserve raw questions/content for bounded browsing and later retrieval improvements. Newest-first stable record order; before_id is exclusive; limit 1–20, default 10. Unknown or out-of-scope cursor returns a typed lookup error, never leaks a record. Pagination has no duplicates/skips.
- `Toolbox(items: GeneratorRegistry, catalogue: Mapping[MisconceptionId, Misconception], history: HistoryReader | None = None)`; `tools() -> tuple[Tool, ...]`, `execute(name, arguments, context) -> str`. History defaults to an empty scoped reader for isolated legacy tests, never to unrestricted access.
- Tools: check_expression, get_worked_example, lookup_misconception, get_student_summary, **get_session_history**. History accepts only task_id, skill_id, item_id, kind, after, before, before_id, limit. All are optional; no implicit current-skill restriction. Scope comes from TurnContext.history_scope; absent scope is an explicit tool error. Return ids, UTC times, task/item/skill/revision, related_record_ids, event kinds, relevant work/question/delivered text/verdict and next cursor. Exclude private traces, rejected drafts and operator instructions. Never advertise previous-session retrieval before 2B implements it.
- `encode_tools(tools: tuple[Tool, ...]) -> tuple[dict[str, Any], ...]` in provider tool_schema.py. Runtime emits failures as `tool_result` with `is_error=True`; keep tool call/result pairing.

- [ ] **Step 1: Write failing tests.** Assert the five advertised tools each execute; expression check returns deterministic checked output; example is a distinct vetted item; catalogue lookup/summary preserve original semantics. `test_history_is_bound_to_student_and_session` loads two students and two sessions and asserts only current scope appears, even with a guessed foreign task/cursor. `test_history_filters_are_optional_and_composable` covers cross-skill browsing, prior-skill filtering, kind/item/time filters and related-record metadata; `test_history_pages_previous_exercises_with_provenance` reads 25 records as 10/10/5 with no overlap. `test_history_excludes_private_drafts_and_operators` asserts those records are unavailable. `test_tool_reads_cannot_change_evidence_or_mastery` snapshots log/state before all five calls and compares after. Invalid/oversized limit fails; no silent unlimited query.
- [ ] **Step 2: Run `.venv/bin/pytest tests/adapters/tutor/test_tools.py tests/adapters/test_in_memory_history.py -v`.** Expected: missing modules/types.
- [ ] **Step 3: Implement table, scoped reader and provider encoding.** Initial math check remains backed by the existing CAS adapter; descriptions must accurately call it math-specific. Provider-neutral encoding does not make CAS subject-neutral. A generic subject-tool registry remains a later design discussion; do not introduce one here. At each begin_turn construct InMemoryHistoryReader(context.history), then a fresh Toolbox using it. context.history is the full immutable session-record snapshot; ContextView selects only what is rendered, never prunes retrieval records. The adapter constructor accepts no mutable global current-student history; no extra task-to-skill mapping is needed.
- [ ] **Step 4: Run focused tests and full keyless suite.** Expected: pass without network or storage service.
- [ ] **Step 5: Commit listed files.** Suggested subject: `feat: expose bounded read-only session history to the tutor`.

---

### Task 6: The structured turn — schema and parser

**Files:**
- Create: `src/learnai/adapters/tutor/anthropic/turn_schema.py`
- Test: `tests/adapters/tutor/test_turn_schema.py`

**Interfaces:**
- Consumes: `HelpRung`, `Proposal`, `ProposalKind`, `TutorTurn`, `SkillId`, `MisconceptionId` (all exist).
- Produces: `TurnSchemaError(ValueError)`; `TURN_SCHEMA: dict` (the JSON schema handed to the SDK's structured-output mechanism — enum values are the member *names*); `parse_turn(payload: Mapping[str, Any]) -> TutorTurn` (raises `TurnSchemaError` with a specific message for every malformed shape).

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/tutor/test_turn_schema.py
import pytest

from learnai.adapters.tutor.anthropic.turn_schema import TURN_SCHEMA, TurnSchemaError, parse_turn
from learnai.domain.enums import HelpRung
from learnai.domain.turn import ProposalKind


def test_a_full_payload_round_trips():
    turn = parse_turn(
        {
            "message": "Try factoring out the common term first.",
            "rung_used": "NEXT_STEP",
            "diagnosis": "mc.gcf.partial",
            "proposals": [{"kind": "DROP_TO_PREREQUISITE", "target_skill_id": "quad.factor.common"}],
        }
    )
    assert turn.rung_used is HelpRung.NEXT_STEP
    assert turn.diagnosis == "mc.gcf.partial"
    assert turn.proposals[0].kind is ProposalKind.DROP_TO_PREREQUISITE
    assert turn.proposals[0].target_skill_id == "quad.factor.common"


def test_a_minimal_payload_defaults_the_rest():
    turn = parse_turn({"message": "What is the next thing you could try?", "rung_used": "NUDGE"})
    assert turn.diagnosis is None
    assert turn.proposals == ()


@pytest.mark.parametrize(
    "payload, match",
    [
        ("not an object", "not an object"),
        ({}, "'message'"),
        ({"message": "hi", "rung_used": "SHOUT"}, "'rung_used'"),
        ({"message": "hi", "rung_used": []}, "'rung_used'"),
        ({"message": "hi", "rung_used": "NUDGE", "proposals": [{"kind": {}}]}, "proposal kind"),
        ({"message": "hi", "rung_used": "NUDGE", "proposals": [{"kind": "SERVE_EASIER_ITEM", "extra": 1}]}, "unknown proposal fields"),
        ({"message": "hi", "rung_used": "NUDGE", "diagnosis": 3}, "'diagnosis'"),
        ({"message": "hi", "rung_used": "NUDGE", "proposals": {}}, "'proposals'"),
        (
            {"message": "hi", "rung_used": "NUDGE", "proposals": [{"kind": "TELEPORT"}]},
            "proposal kind",
        ),
        ({"message": "hi", "rung_used": "NUDGE", "extra": 1}, "unknown fields"),
    ],
)
def test_malformed_payloads_are_named_precisely(payload, match):
    with pytest.raises(TurnSchemaError, match=match):
        parse_turn(payload)


def test_the_schema_uses_member_names_as_enums():
    assert TURN_SCHEMA["properties"]["rung_used"]["enum"] == [
        "NONE",
        "NUDGE",
        "NEXT_STEP",
        "NAME_METHOD",
        "FULL_REVEAL",
    ]
    assert TURN_SCHEMA["required"] == ["message", "rung_used"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/adapters/tutor/test_turn_schema.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'learnai.adapters.tutor.anthropic.turn_schema'`.

- [ ] **Step 3: Write `turn_schema.py`**

```python
# src/learnai/adapters/tutor/anthropic/turn_schema.py
from typing import Any, Mapping

from learnai.domain.enums import HelpRung
from learnai.domain.ids import MisconceptionId, SkillId
from learnai.domain.turn import Proposal, ProposalKind, TutorTurn


class TurnSchemaError(ValueError):
    """A model payload that does not carry a valid tutor turn."""


TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "rung_used": {
            "type": "string",
            "enum": ["NONE", "NUDGE", "NEXT_STEP", "NAME_METHOD", "FULL_REVEAL"],
        },
        "diagnosis": {"type": ["string", "null"]},
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "DROP_TO_PREREQUISITE",
                            "SERVE_EASIER_ITEM",
                            "END_TASK_UNPRODUCTIVE",
                        ],
                    },
                    "target_skill_id": {"type": ["string", "null"]},
                },
                "required": ["kind"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["message", "rung_used"],
    "additionalProperties": False,
}

_RUNGS = {rung.name: rung for rung in HelpRung}
_PROPOSAL_KINDS = {kind.name: kind for kind in ProposalKind}
_TURN_FIELDS = frozenset({"message", "rung_used", "diagnosis", "proposals"})


def parse_turn(payload: Mapping[str, Any]) -> TutorTurn:
    if not isinstance(payload, Mapping):
        raise TurnSchemaError(f"payload is {type(payload).__name__}, not an object")
    unknown = set(payload) - _TURN_FIELDS
    if unknown:
        raise TurnSchemaError(f"unknown fields {sorted(unknown)}")
    message = payload.get("message")
    if not isinstance(message, str):
        raise TurnSchemaError("'message' must be a string")
    rung_name = payload.get("rung_used")
    if not isinstance(rung_name, str) or rung_name not in _RUNGS:
        raise TurnSchemaError(
            f"'rung_used' must be one of {sorted(_RUNGS)}, got {rung_name!r}"
        )
    diagnosis = payload.get("diagnosis")
    if diagnosis is not None and not isinstance(diagnosis, str):
        raise TurnSchemaError("'diagnosis' must be a string or null")
    proposals_raw = payload.get("proposals", [])
    if not isinstance(proposals_raw, list):
        raise TurnSchemaError("'proposals' must be an array")
    proposals = []
    for entry in proposals_raw:
        if not isinstance(entry, Mapping):
            raise TurnSchemaError("each proposal must be an object")
        unknown = set(entry) - {"kind", "target_skill_id"}
        if unknown:
            raise TurnSchemaError(f"unknown proposal fields {sorted(unknown)}")
        kind_name = entry.get("kind")
        if not isinstance(kind_name, str) or kind_name not in _PROPOSAL_KINDS:
            raise TurnSchemaError(
                f"proposal kind must be one of {sorted(_PROPOSAL_KINDS)}, got {kind_name!r}"
            )
        target = entry.get("target_skill_id")
        if target is not None and not isinstance(target, str):
            raise TurnSchemaError("'target_skill_id' must be a string or null")
        proposals.append(
            Proposal(
                kind=_PROPOSAL_KINDS[kind_name],
                target_skill_id=SkillId(target) if target else None,
            )
        )
    return TutorTurn(
        message=message,
        rung_used=_RUNGS[rung_name],
        diagnosis=MisconceptionId(diagnosis) if diagnosis else None,
        proposals=tuple(proposals),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/tutor/test_turn_schema.py -v`
Expected: 13 passed (4 test functions; one parametrized ×10).

- [ ] **Step 5: Commit**

```bash
git add src/learnai/adapters/tutor/anthropic/turn_schema.py tests/adapters/tutor/test_turn_schema.py
git commit -m "feat: the structured tutor-turn schema and its precise parser"
```

---

### Task 7: Request-scoped Anthropic exchange, complete tool history, shared budgets and private traces

**Files:**
- Modify: `pyproject.toml` (+Anthropic SDK and scripted transport dev dependency)
- Create: `src/learnai/adapters/tutor/runtime.py`, `src/learnai/adapters/tutor/anthropic/adapter.py`
- Create: `tests/support/scripted_client.py`
- Test: `tests/adapters/tutor/test_adapter.py`, `tests/adapters/tutor/test_runtime.py`

**Interfaces:**
- `AnthropicTutor(routes: Mapping[str, Route], client: anthropic.Anthropic, items: GeneratorRegistry, catalogue: Mapping[MisconceptionId, Misconception], *, budget_profiles: Mapping[str, BudgetProfile] | None = None, route_name: str | None = None, prompts_root: Path = PROMPTS_ROOT, monotonic: Callable[[], float] = time.monotonic, count_tokens: Callable[[str], int] | None = None, trace_sink: Callable[[TurnTrace], None] | None = None)`. If budget_profiles is omitted use the exact provisional defaults of Task 3, allowing old minimal fixtures; production loads them from YAML. With route_name=None resolve context.response_job via Task 3. An explicit route_name is a direct-call/test override; engine/eval production paths use job resolution. Per exchange bind the scoped history reader and Toolbox as Task 5 specifies. Token counting has an injectable deterministic test implementation and a conservative model-appropriate runtime implementation.
- `begin_turn(context: TurnContext) -> TutorExchange` owns fresh messages, usage, budget and trace; one-shot `respond(context, *, feedback=None)` opens/closes an independent exchange. Engine/eval always use request_validated_turn, retaining the same exchange across rejection retries. Keep existing adapter `events_seen` and `usages` readouts for Tasks 11/13/15; traces are request-scoped and emitted to trace_sink on finish.
- `ResponseBudget(profile: BudgetProfile, *, monotonic: Callable[[], float])`: `remaining_seconds() -> float`, `expired() -> bool`, `can_explore() -> bool`, `record_model_call(output_tokens: int) -> None`, `record_tool_calls(count: int) -> None`. Reserve finalization tokens and one model call from the emergency ceilings before allowing exploration. Begin timestamp/deadline are created once at begin_turn; API, format and validation retries share the object.
- `TurnTrace` carries request id, student/session/task/item/revision refs, selected ContextView and source ids, exact rendered initial context, prompt ids and actual model/settings, ordered provider request/response blocks, tool results, validation results, elapsed time, model/tool/retry counts, usage and termination reason. Store provider-returned blocks needed for replay, not invented/extracted hidden reasoning. Never return private trace content via get_session_history. In-memory trace sink and eval JSON serialization only in 2A.
- Preserve `_request_kwargs(route)`, `_system_block(block)`, event extraction and schema parsing, adjusted to current official SDK/API shape. MAX_FORMAT_RETRIES remains 2 but is subordinate to the shared budget. API attempts at most 3 with backoff, bounded by remaining time; disable SDK-hidden retries and implement this once so two retry layers cannot multiply allowances. Network timeouts are clamped to remaining time. Check budget before/after tools and validation; D17 worker isolation remains 2B.

- [ ] **Step 1: Add SDK/dev transport dependencies and scripted transport.** ScriptedAnthropic records full request JSON, returns unique message/tool ids, supports text/tool/submit responses, API errors and injected fake elapsed-time changes. Configure max_retries=0. Its protocol validator rejects missing/reordered tool results and continuations without original history; it must not accept malformed request sequences merely because a canned response exists.
- [ ] **Step 2: Write failing tests with these assertions.**

| Test | Required assertions |
|---|---|
| `test_two_tool_round_trips_preserve_original_history_and_results` | Request 3 includes original student context, both assistant tool calls and both matching results in order, including first result. |
| `test_validation_retry_keeps_the_same_tool_exchange` | After checked tool -> rejected submit_turn -> feedback, retry still contains original context and checked result; rejected submit has paired error result before correction. begin_turn once. |
| `test_format_and_budget_errors_settle_pending_tool_calls` | Malformed submit and budget-denied read calls each receive matching error results before finalization; no orphan calls or altered thinking/signature blocks. |
| `test_soft_threshold_reserves_final_response` | Fake time crosses profile soft_seconds; exploratory tools removed, submit_turn retained, reserved call/tokens remain and accepted response can finish. |
| `test_hard_budget_is_shared_across_all_retry_layers` | Fake elapsed time 7 then validation retry under hard=8 permits at most 1 remaining second; no new budget, timeout/backoff never exceeds remaining allowance, expired output not delivered. |
| `test_parallel_calls_are_distinct_from_model_round_trips` | One response with 3 read calls records 3 calls and 1 round trip; individual and round-trip ceilings enforced separately. |
| `test_total_token_reserve_includes_thinking_and_retries` | Accumulate API output_tokens across responses; before reserve is consumed exploration stops; no final call larger than remaining tokens. |
| `test_concurrent_exchange_history_is_isolated` | Interleave two exchange objects for different contexts; no cross-student messages, usage budget or history retrieval. |
| `test_context_overflow_never_sends_truncated_work` | Protected-overflow trace reason context_limit, zero model calls, None returned. |
| `test_trace_reconstructs_inputs_and_final_delivery` | Exact context revision, source ids, raw tool results, both validation outcomes and accepted text recoverable; rejected drafts absent from delivered history. |
| `test_failures_degrade_without_student_evidence` | Exhausted network/format/validation budgets yield None with one typed trace outcome and warning; silence consumes no help. |

Preserve happy-path schema/tool dispatch, route/prompt fail-fast, stable caching prefix and usage tests. The test clock is monotonic and does not advance the student's domain Clock; domain UTC timestamps remain aware.

- [ ] **Step 3: Run `.venv/bin/pytest tests/adapters/tutor/test_runtime.py tests/adapters/tutor/test_adapter.py -v`.** Expected: missing modules/interfaces.
- [ ] **Step 4: Implement the runtime and provider exchange.** On each continuation append to messages; never replace history with just the last assistant response. Keep provider content blocks unchanged. Recount the full accumulated request before every model call, reserving generation headroom; context overflow becomes a typed context_limit outcome rather than an API crash or silent removal of active work. On rejection, retain the actual terminating tool call and supply a matching error result plus provider-supported operator correction. Check the current official API's role/feature support before using mid-conversation system messages; use a supported correction encoding rather than pinning an unsupported role in tests. If submit_turn and reads appear together, reject/settle all outstanding calls and request a single final submit; do not silently drop calls. At soft exhaustion finalize; at hard exhaustion return None with operational reason. No adapter-side domain validation.
- [ ] **Step 5: Run focused tests and full keyless suite.** Expected: all pass without key, network or sleeping. These prove protocol construction; live compatibility is checked early in Task 15, not inferred from the fake.
- [ ] **Step 6: Commit listed files.** Suggested subject: `feat: preserve tutor tool history under shared response budgets`.

---

### Task 8: Keyless engine-to-adapter integration with drafts, assistance and history

**Files:** Test: `tests/adapters/tutor/test_adapter_engine.py`.
**Interfaces:** Consume Tasks 1–7 and the existing engine construction pattern. No new product API.

- [ ] **Step 1: Write integration tests.** A draft question carries full working/answer/status/revision and selected-step reference into the real adapter request, without AttemptRecorded. Tool -> rejected submit -> corrected submit preserves original history and same deadline. Accepted task reply sets independence spent and subsequent correct answer is ASSISTED; its help rung is recorded as delivered. API/format/validation/deadline silence leaves independence unchanged. History tool retrieves an earlier exercise from the same session and excludes another student's records. A later revised draft does not inherit an old final verdict. Two engine questions designated BRIEF and SUBSTANTIAL resolve different configured model/settings/profiles and trace the actual selection; disabled COMPLEX calls no provider. Filter earlier-exercise history by another skill as well as browsing without a skill filter. Use blank shape-correct declines and generator-compatible readable wrong submissions.
- [ ] **Step 2: Run `.venv/bin/pytest tests/adapters/tutor/test_adapter_engine.py -v`.** Expected: pass if the seams are wired; otherwise fix the owning task. Compare requests to the actual pre-response context, not a transcript after a later reply.
- [ ] **Step 3: Run full keyless suite, then commit the test file.** Suggested subject: `test: verify draft tutoring and retained history through the real adapter`.

---

### Task 9: Eval scenario schema includes the current interaction and history

**Files:** Create `src/learnai/eval/{__init__,fixtures}.py`; test `tests/eval/test_fixtures.py`.

**Interfaces:** Preserve `Scenario(id, family, skill_id, template_id, seed, permitted_rung, strength, is_fresh, calibration_gap, prior_misconceptions, steps, answer, declined=False, transcript=(), notes="")` and `FixtureError`, `parse_scenario(raw: Mapping[str, Any]) -> Scenario`, `load_scenarios_dir(directory: Path) -> tuple[Scenario, ...]`. Add defaulted question=None, referenced_step=None, work_status=SUBMITTED, work_revision=0, interaction_kind=SUBMISSION and response_job=ResponseJob.NORMAL; parse the enum names/values explicitly and pass the selected job to the shared builder, never discard it. `answer` accepts a legacy single string or list of field strings; normalize into structured Submission before building context, preserving VALUE_SET/no-solutions semantics. No-solutions is an explicit claims_none field; blank/decline is not that claim. Add optional current-session history records and current_interaction_id with Task 1 types. FAMILIES stays ladder/diagnosis/leak_bait/decline/extra.

**Issue 4 schema refinement (2026-10-25).** Committed corpus entries require evaluator-only
`expected_statement: str`, `work_origin: Literal["exercise", "copy_error", "none"]`,
`exercise_anchor: str | None`, `copy_error_description: str | None`,
`expected_verdict: Literal["CORRECT", "WRONG", "MALFORMED", "NO_ANSWER", "UNCHECKED"]`,
`expected_diagnosis: MisconceptionId | None` (explicit null required when absent),
`expected_broken_transition: tuple[str, str] | None`, `expected_step_check: bool`,
`expected_error_kinds: tuple[Literal["equivalence", "form_constraint", "copy_error", "unreadable"], ...]` (empty for valid work; multiple defects may coexist),
`expected_failed_constraints: tuple[FormConstraint, ...]`,
`coverage_tags: tuple[str, ...]`, and `expected_progress: TaskProgress`. Optional reviewed
`reference_reasoning: tuple[str, ...]` and `evaluation_criteria: tuple[str, ...]` feed Task 12.
These are assertions about independently computed results, never injected findings. Legacy
minimal loader tests may omit expectations; corpus preflight requires them. Copy-error metadata
is mandatory for that origin and forbidden otherwise; work_origin=none permits workless questions
and declines. Exact diagnosis and final-verdict expectations remain separate.

Historical events are the canonical source. Reuse Task 1's typed records and scripted historical
engine transitions; mark rejected/silent drafts separately from delivered history. If legacy
transcript is supplied alongside events it must agree, or the fixture is rejected. The runner
passes history to the shared context builder; it never accepts fixture-specified engine counts
as authoritative. `expected_progress` is only a replay assertion. Add loader tests for every
new field/type, missing required corpus expectations and contradictory history.

- [ ] **Step 1: Write failing tests.** Legacy minimal schema fixtures still load; committed corpus entries must pass Task 10 preflight. Draft question with blank answer is valid without declined=True; an explicit submission requires an answer or explicit decline/no-solutions claim. Reject negative revisions, invalid referenced steps, unknown fields/status/kind/job, duplicate ids, absent template/skill and malformed history provenance. Tests distinguish final-answer unchecked from WRONG and current work from an earlier revision. History records can name prior exercises but cannot override current bound student identity or engine counts.
- [ ] **Step 2: Run `.venv/bin/pytest tests/eval/test_fixtures.py -v`.** Expected: missing module/types.
- [ ] **Step 3: Implement loader and normalized scenario fields.** Construct deterministic fixtures for user-visible history, never provider-private operator/tool traces. Preserve deterministic seed ids. Validate field types rather than coercing strings such as "false" into truthy booleans.
- [ ] **Step 4: Run focused tests and full keyless suite.** Expected: pass.
- [ ] **Step 5: Commit listed files.** Suggested subject: `feat: describe revisioned student questions in tutor eval scenarios`.

---

### Task 10: Author and validate a balanced, coherent eval corpus

**Files:** Create `eval/fixtures/{ladder,diagnosis,leak_bait,decline,extra}.yaml`;
test `tests/eval/test_fixture_corpus.py`.

**Approved issue 4 — 2026-10-25.** This task replaces the earlier handwritten YAML and
wrong-only tests. Those examples mismatched generated questions, answer shapes and history.
Do not copy them from older revisions. Author fixtures against actual generated items.

**Interfaces:** Consume Task 9 scenarios/expectations, the real registry, verifier, matcher,
shared context builder and Task 1 history/progress semantics. Produce at least 50 validated
scenarios with family floors ladder=12, diagnosis=12, leak_bait=12, decline=8, extra=6.
Add balanced cases beyond those floors; no fixed total of 52 is required. Expectations and
reference reasoning are evaluator-only; never insert expected findings into the tutor context.

- [ ] **Step 1: Write failing corpus validity tests.**
  - `test_generated_item_matches_pinned_exercise`: instantiate template/seed, check skill and
    exact `expected_statement` snapshot, preserving constraints and answer kind. Never overwrite
    a snapshot automatically after generator changes. For `work_origin=exercise`, require the
    declared first mathematical line to match an approved equivalent of the generated starting
    expression/equation. Use the actual generator's initial worked line when available; for word
    problems or generators without one, author a reviewed `exercise_anchor` and compare it with
    the pinned statement during fixture review. Nonalgebraic linking is human-reviewed, not
    falsely certified by local adjacent-step checks.
  - `test_copy_errors_are_explicit`: `work_origin=copy_error` requires a reviewed
    `exercise_anchor`, the copied first line, and evaluator-only `copy_error_description` naming
    the discrepancy. A copying error is evaluated separately from a subsequent transformation
    error; neither is silently substituted for the other.
  - `test_submission_shape_matches_item`: normalize Task 9 fields and run
    `Submission.check_shape(item.answer_spec.kind)`. VALUE_SET uses separate value strings;
    x-coordinate questions use one scalar. Blank decline differs from explicit no-solutions.
    Shape-invalid payloads are loader/contract negative tests, not student mistakes in paid evals.
  - `test_verdict_matches_explicit_expectation`: assert CORRECT/WRONG/MALFORMED/NO_ANSWER
    against the actual checked verdict; UNCHECKED means the current draft has no final-answer
    verification. No global requirement that answers be wrong or readable. A correct final submission preserves existing engine behavior: complete without an unsolicited
    tutor call or step diagnosis. To evaluate feedback on questionable intermediate work despite
    a correct answer, use an explicit draft question with step checks and no final submission.
  - `test_diagnosis_matches_exact_expected_id`: for checked submitted work, compare actual
    `diagnose(...)` to `expected_diagnosis` (including explicit null), not merely non-None.
    Use Task 1's prepare_verification rather than directly diagnosing only diff_steps. Assert
    expected_error_kinds and failed constraints independently from the diagnosis. Equivalence
    errors have a broken transition; form-constraint failures can have none. Incomplete common
    factoring must be WRONG with failed constraints, no equivalence break, and the exact diagnosis
    from Slice 1's final-transition fallback. Deferred signatures prove their intended defect
    (equivalence or form) and absence of a catalogue diagnosis. Valid work has neither a broken
    transition nor failed constraints. Copying errors name the exercise mismatch separately
    from any subsequent calculation/form defect. Draft questions may
    have scoped step checks without any final verdict; record their scope explicitly.
  - `test_history_and_progress_share_one_source`: replay fixture history through engine
    transitions with scripted accepted historical replies; derive transcript, rung history,
    attempts, declines and independence from those transitions. Compare explicit expected
    progress to the result. An accepted task reply at rung NONE spends independence without
    advancing the ladder; rejected/silent replies do neither. Reject snapshots whose redundant
    transcript/progress contradict the replay or whose revisions/identities do not match.
  - `test_coverage_floors_and_balanced_cases`: assert family floors and named coverage tags
    below, so scenario count cannot conceal missing correct-work or copying-error coverage.

- [ ] **Step 2: Run `.venv/bin/pytest tests/eval/test_fixture_corpus.py -v`.**
  Expected: missing corpus/expectations or assertion failures until fixtures are authored.

- [ ] **Step 3: Author fixtures from inspected generator output and reviewed expectations.**
  For each template/seed, inspect the statement, constraints, answer kind/key and available worked
  steps before constructing student work. Set expectations independently, then confirm them with
  real checks; never derive an expected result by simply copying observed output. Unsupported
  scenario types require suitable authored content in a later scope, not a fake generator seed.
  In particular, a difference-of-squares generator cannot supply a sum-of-squares exercise;
  use an explicit copying-error case or exercise its matcher directly in adapter unit tests.

  Preserve two examples per implemented signature in the diagnosis family **where supported by
  coherent generated exercises**. Current signatures: product_of_sums_drops_cross,
  square_distributes_over_sum, incomplete_common_factor, factor_sign_flip,
  sum_of_squares_factored, zero_product_without_zero. If one cannot be reached coherently,
  cover it directly in matcher tests and use another coherent diagnosis case to meet the family
  floor; do not manufacture an exercise or change production diagnosis behavior to satisfy counts.
  Deferred signatures belong in extra only when their intended mathematical error is present.

  Required named coverage tags (cases may carry multiple tags): correct submission, valid
  alternative method, wrong submission, explicit decline, no-solutions claim, conceptual question,
  unfinished draft, copying error, supported diagnosis, unsupported error, valid-work no-diagnosis,
  draft question with incorrect intermediate work and a correct proposed answer, and malformed draft question. Include
  edited draft after an earlier wrong answer, mistake followed by correction, help before first
  submission, previous-exercise retrieval and an active conversation beyond twenty entries.
  Correct work must not trigger invented correction. The help ceiling remains a maximum.

- [ ] **Step 4: Separate corpus defects from operational tests.** An explicit MALFORMED
  final submission exercises the engine's no-evidence/no-tutor behavior in keyless integration
  tests; it is excluded from paid accepted-turn judging and reported as an expected non-tutored
  operation. A question about malformed draft work is a valid paid tutoring moment. Timeouts,
  context overflow and forced silence remain scripted runtime tests, not cases requiring an
  accepted paid reply. No silent removal of invalid fixtures from denominators.

- [ ] **Step 5: Gate paid execution on keyless preflight.** Expose
  `validate_corpus(scenarios, *, graph, items, catalogue, verifier, matcher) -> None` in
  `src/learnai/eval/fixtures.py`, raising `FixtureError` with scenario id and discrepancy for
  violated expectations. Share these checks with corpus tests. It also validates the required
  historical replay through the shared builder. Family/coverage floors apply to the complete
  committed corpus; CLI `--only` subsets need per-scenario validity, not all-family floors.
  Task 13 calls preflight before constructing a client or making tutor/judge/smoke calls;
  invalid selected fixtures exit 2 without network or spend. Test this with a client factory
  that fails if constructed. Fix an incorrect expectation when review establishes it is wrong;
  never weaken a valid check merely to make the corpus green.

- [ ] **Step 6: Run focused tests and the full keyless suite, then commit when implemented.**
  `.venv/bin/pytest tests/eval/test_fixtures.py tests/eval/test_fixture_corpus.py -v`
  then `.venv/bin/pytest`. Expected: pass. Human review must still confirm scenario coherence;
  these checks do not establish real tutor quality. Suggested commit:
  `feat: validate coherent balanced tutor evaluation scenarios`.

---

### Task 11: Eval runner shares engine context semantics and captures reconstruction traces

**Files:** Create `src/learnai/eval/runner.py`; test `tests/eval/test_runner.py`. At Task 11 run corpus/runner parity tests; at Task 13 run CLI integration tests. Task 10 does not collect tests from tasks not yet implemented.

**Issue 4 integration:** use Task 10's shared keyless preflight and history replay; retain
`context: TurnContext` on ScenarioOutcome for Task 12. Expected non-tutored malformed submissions
are labeled separately from operational tutor failures and are not sent to the judge. A correct final submission is an expected non-tutored completion; a conceptual question or
question about correct draft work remains eligible under engine delivery semantics.
Never force a tutor call merely to satisfy a fixture expectation.

**Interfaces:**
- Preserve `build_context(scenario, *, graph, items, catalogue, matcher, verifier) -> TurnContext`, `run_scenario(scenario, *, tutor, graph, items, catalogue, verifiers, matcher) -> ScenarioOutcome`, `run_scenarios(scenarios, *, tutor, graph, items, catalogue, verifiers, matcher) -> tuple[ScenarioOutcome, ...]`.
- `ScenarioOutcome(scenario, item, turn, attempts, usage, error=None, trace=None)`; trace is optional TurnTrace from Task 7. `AnthropicTutor.usages` stays a cumulative per-call readout compatible with Tasks 13/15. Record input_tokens, output_tokens and cache_read_input_tokens as before; trace additionally stores complete vendor-returned usage. Task 13 records complete usage and costs across all phases through one shared ledger.
- Instantiate real item and normalized structured Submission, current interaction and the full immutable scoped session history (rendering remains bounded); compute scope-correct findings through Task 1 prepare_verification, including existing form-constraint diagnosis fallback. Call Task 1's shared `build_turn_context`, not a copied diagnosis/context algorithm. A draft is not automatically declined; its final verdict is unchecked. Explicit unreadable submission remains the existing no-evidence/no-tutoring operation; a question *about* unreadable draft working is allowed.
- Construct deterministic session/task/state fixtures for the shared builder, using recorded prior events for TaskProgress. Preserve question exactly once. Drive the same `request_validated_turn` helper with the adapter's one shared exchange/budget. A typed operational exhaustion becomes an outcome with trace, not a student failure.

- [ ] **Step 1: Write failing tests.** Engine and eval contexts for the same interaction have equal working, question, revision, findings (including form failures/fallback), job, progress and history refs. Correct final submissions complete without a tutor call; explicit questions about correct draft work are tutored with scoped findings. Draft question has no fabricated NO_ANSWER/WRONG verdict. Explicit decline has NO_ANSWER and no fictitious steps. VALUE_SET inputs retain shape. Accepted, corrected and silent runs report actual attempts and usage deltas; same trace includes all tools/rejections and the accepted text. A fake clock deadline is measured without advancing domain study time. Any fake/silent Tutor must implement begin_turn, not just respond.
- [ ] **Step 2: Run `.venv/bin/pytest tests/eval/test_runner.py tests/adapters/tutor/test_adapter.py -v`.** Expected: missing runner/new outcome fields.
- [ ] **Step 3: Implement runner and trace collection.** Allow a request-local trace sink; match traces to outcomes by request id, not adapter-wide "last response" state. Add build_context parity assertions against engine-generated contexts rather than asserting only a non-None diagnosis.
- [ ] **Step 4: Run focused tests and full keyless suite.** Expected: pass. This does not establish live tutor quality or judge calibration.
- [ ] **Step 5: Commit listed files.** Suggested subject: `feat: evaluate real interaction contexts with reconstruction traces`.

---

### Task 12: The rubric judge

**Files:**
- Create: `prompts/rubric_judge/v1.md`
- Create: `src/learnai/eval/judge.py`
- Test: `tests/eval/test_judge.py`

**Approved review refinement — 2026-10-24.** Judge usefulness for the specific student
moment using a structured review packet, with evaluator-only references separated from the
student-facing situation. This is an offline instrument; never add it to delivery latency.

**Interfaces (engineering choices for the approved design):**
- Consumes: Task 11's exact captured `TurnContext` and accepted `TutorTurn`, not a later
  reconstruction of mutable state; Task 3 routing/prompt loading; Task 7 scripted client.
- `JudgeReference(answer: Submission | None, reasoning: tuple[str, ...],
  provenance: str, teaching_notes: str, misconception_explanations: tuple[str, ...],
  criteria: tuple[str, ...])` is frozen evaluator-only data. The answer comes from the
  generated item; reference reasoning is curated/versioned for the template and instantiated
  parameters. Do not invent an explanation by trusting the tutor output being evaluated.
- `JudgePacket(context: TurnContext, turn: TutorTurn, reference: JudgeReference,
  learner_level: str | None, missing_information: tuple[str, ...])` preserves available
  information and explicitly marks gaps. Unknown learner level is not an inferred age.
- `build_judge_messages(packet: JudgePacket) -> tuple[dict, ...]` serializes two labeled
  sections: `student_situation` and `evaluator_reference`, with the candidate response separate.
  Include exact instructions/constraints, current raw working/answer/question/status/revision,
  relevant delivered conversation and provenance, permissions/task progress, verifier scope and
  revision, checked results, teaching notes, references and scenario-specific criteria.
- `JudgeScores(mathematics, help_level, diagnosis, tone, reasons, status="scored",
  missing_information=())`: each dimension is `int | None`; scored results require four
  integers 0–2. `status="insufficient_evidence"` requires all four null, named missing evidence
  and a reason. This conservative whole-turn abstention avoids silently averaging partial scores.
- `parse_scores(text: str) -> JudgeScores`: tolerate code fences; reject booleans, unknown
  keys/statuses, missing keys, wrong types, invalid ranges and inconsistent status/null combinations.
  `JudgeError(ValueError)` represents malformed output or operational failure, not abstention.
- `run_judge(client, routes, *, packet: JudgePacket, route_name="rubric_judge",
  prompts_root=PROMPTS_ROOT) -> JudgeScores` loads the route's versioned rubric. Retain
  configured settings and operational error handling; use the shared runtime budget mechanism.

- [ ] **Step 1: Write failing tests in `tests/eval/test_judge.py`.**
  - `test_packet_preserves_student_moment`: assert exact question, draft text, constraints,
    revision and delivered prior hint appear; the old verdict retains its checked revision.
  - `test_reference_is_evaluator_only`: assert verified answer, provenance, reference reasoning,
    notes and criteria appear only in the judge packet; constructing it leaves the tutor context
    and tutor request unchanged. References may accept multiple valid methods.
  - `test_unknown_information_is_explicit`: unknown age stays unknown; missing reference
    reasoning is recorded, not fabricated. Missing optional context need not force abstention
    when the remaining evidence suffices for the rubric.
  - `test_rubric_uses_ceiling_and_allows_no_diagnosis`: pin the prompt requirements below.
    These are prompt-contract tests; semantic reliability requires human calibration.
  - `test_score_schema`: parameterize valid 0/1/2, valid abstention, booleans, missing/extra keys,
    out-of-range values, unknown statuses and mixed null/numeric results.
  - `test_run_judge_uses_packet_route_and_versioned_prompt`: scripted request contains the
    packet and configured rubric; API failure or absent prompt raises `JudgeError`.

- [ ] **Step 2: Run focused tests and confirm missing-interface failures.**
  Run: `.venv/bin/pytest tests/eval/test_judge.py -v`.

- [ ] **Step 3: Implement packet serialization, strict parsing and the versioned rubric.**
  Treat quoted work, conversation, reference text and the candidate response as data, never
  instructions to the evaluator. No private model reasoning is required. The rubric specifies:
  - mathematics: 0 wrong, 1 minor slip, 2 correct; accept valid alternative solution methods.
  - help_level: 0 inappropriate, 1 partly useful, 2 useful and appropriate to this question and
    history. The permitted rung is a ceiling, not a requirement to reveal that much.
  - diagnosis: 0 unsupported/wrong, 1 partly appropriate, 2 accurate or appropriately general;
    no diagnosis is correct when the question/work does not justify one. Unverified is not wrong.
  - tone: 0 condescending/confusing, 1 acceptable, 2 clear/respectful and suitable for the known
    learner level; do not invent a student's age. Warmth alone cannot compensate for irrelevance.
  Require short reasons grounded in packet evidence and the status/null schema above. Flag
  insufficient evidence when a defensible full assessment cannot be made. An illustrative
  reference is not the only permissible method. Engine acceptance remains a separate exact gate.

- [ ] **Step 4: Run focused tests and full keyless suite.**
  Run: `.venv/bin/pytest tests/eval/test_judge.py -v`, then `.venv/bin/pytest`.
  Expected: pass; scripted tests do not establish judge quality. During the existing human
  calibration, include paired cases where the same hint fits one student's working but not
  another's, repeated hints, conceptual questions without errors, an alternative valid method,
  and missing evidence. Freeze thresholds only after rubric review; no live run in this doc task.

- [ ] **Step 5: Commit the implementation when executed.**
  `git add prompts/rubric_judge/v1.md src/learnai/eval/judge.py tests/eval/test_judge.py`
  then commit with `feat: evaluate tutoring against the student moment and references`.

---

### Task 13: Reproducible evaluation artifacts, request accounting and CLI

**Approved issue 5 — 2026-10-25.** A unique run id identifies an execution; a configuration
fingerprint identifies its captured inputs/setup. Neither promises identical regenerated text.
This task replaces the older report/CLI implementation and illustrative flat pricing constant.

**Files:** Create `src/learnai/eval/{manifest,accounting,report,__main__}.py`;
test `tests/eval/{test_manifest,test_accounting,test_report_cli}.py`.

**Interfaces (engineering choices implementing the approved direction):**
- `RunManifest`: schema version, unique run id, UTC start/end, phase/status, selected scenario ids
  and order, seeds, captured fixture/reference/content/generator inputs, rendered tutor/judge
  prompts, requested models/resolved settings/budgets, code revision and dirty flag, Python and
  dependency versions. Include content hashes and local artifact paths for actual inputs;
  capture changed/untracked relevant code via a patch/source snapshot, excluding keys and
  irrelevant private files. A dirty flag alone cannot reconstruct uncommitted behavior.
- `build_manifest(...) -> RunManifest`, `configuration_fingerprint(manifest) -> str` in
  manifest.py: SHA-256 of canonical UTF-8 JSON (sorted object keys, preserved array order,
  nonfinite numbers forbidden). Hash versioned material inputs and execution settings;
  exclude execution id/time, outputs, usage and observed latency. Requested model aliases are
  configuration inputs; provider-returned model identifiers are recorded per call and compared
  separately, since alias resolution may change. Save captured inputs, not hashes alone.
- `RequestRecord`: unique request/attempt id, logical exchange id, phase (tutor/judge/smoke),
  scenario/session refs, requested/returned model id, settings, provider request id when available,
  timestamps/elapsed time, outcome, raw provider usage and normalized token categories.
  Include rejected outputs, validation/format/API retries and calls without usable responses.
  Record provider blocks needed for reconstruction; do not extract hidden reasoning.
- `RequestLedger.record(record)`: shared by adapter, judge and smoke, one entry per actual API
  attempt. Update the same entry when usage arrives; never double count it via both trace and
  scenario aggregates. Missing usage is unknown, not zero; a response with explicit zero is known.
- `PriceSnapshot`: dated/versioned rates, currency/unit, model and applicable billing conditions,
  source URL and retrieval date. `estimate_cost(ledger, prices) -> CostSummary` uses Decimal
  arithmetic, rounding for display only. Distinguish uncached input, cache reads, cache creation
  (including supported durations) and output using current official provider semantics verified
  at implementation. Preserve raw counters; avoid double counting aggregate and nested usage.
  Unknown models/categories/rates or usage yield an incomplete total with known subtotal and
  reasons, never a fabricated zero or claimed upper bound. Estimated API cost is not an invoice.
- `write_report(directory, *, manifest, outcomes, scores, judge_packets, ledger, prices,
  persona_smoke) -> Path`: writes manifest.json, requests.jsonl, report.json, summary.md and
  referenced input/response/packet artifacts. Unique run directories must not overwrite earlier
  runs. Preserve partial artifacts on failures; update completion status in finally/exception
  handling without hiding the original error. Completed requests survive later phase failures.
- CLI `main(argv, *, client_factory=None) -> int` retains run/--fixtures/--routes/--out/--only/
  --no-smoke, key refusal and unknown-id exit 2. Load/select/validate fixtures before client
  creation or any paid call. Create SDK clients with max_retries=0; Task 7 owns bounded retries.
  Run all tutor scenarios before judging accepted eligible responses, then optional smoke.
  Use captured ScenarioOutcome.context, not a later rebuilt context. Build Task 12 references
  from versioned generated/scenario material, never feed them to tutor inputs. One ledger spans
  all phases; smoke's tutor calls use phase=smoke rather than appearing in both phase totals.
- `compare_runs(left, right)`: report changed input hashes/settings, judge/rubric/reference
  differences, selected-case overlap and provider-returned model differences before numerical
  differences. Direct tutor comparisons hold scenarios/references/judge fixed. A configuration
  fingerprint is not an automatic quality/comparability verdict.
- `rejudge` CLI operation reads saved candidate responses and student-moment packets, retains
  their source run ids/hashes, and evaluates them with one chosen judge/rubric. It creates a
  new linked run with its own ledger; zero tutor-generation calls. Check artifact completeness
  before client creation. Reviewing existing artifacts is read-only and never invokes a model;
  rerunning generation or rejudging is an explicit paid operation. Repeated generation runs are
  optional for close decisions, not mandatory for routine development.

- [ ] **Step 1: Write failing manifest and accounting tests.** Fingerprints are stable across
  JSON key ordering and execution timestamps, but change with prompts, fixtures, references,
  selected-case ordering, model/settings, budgets and relevant dirty source. Capture effective
  defaults explicitly. Verify dirty/untracked relevant changes can be reconstructed, no keys
  enter artifacts, and missing snapshot material is reported. A provider alias returning a new
  model is visible even with the same configuration fingerprint.
  Use synthetic prices (not current commercial rates): per-million rates input=2, cache-read=1,
  cache-write=3, output=4 with disjoint counts 100/200/300/400 must total Decimal('0.0029').
  Include two write-duration categories, retry and rejected-response usage, absent usage,
  unknown prices/models, provider nested/aggregate counters and duplicate-record prevention.
  Unknown entries produce incomplete totals while preserving the known subtotal.

- [ ] **Step 2: Write report and CLI integration tests.**
  - Capture accepted-after-rejection and timeout traces, exact inputs, revisions, delivered text,
    judge packets and full provider usage; serialize and read them back.
  - Score averages include numeric scored results only; report accepted/eligible/judged/scored/
    abstained/judge-error counts and coverage with explicit denominators. Expected non-tutored
    operations, failed/silent tutor calls and judge failures remain separate visible outcomes.
  - Report per-job buffered accepted-response median/p95 with sample counts; show failure and
    exhaustion rates alongside latency so faster failures cannot masquerade as improvements.
  - Ledger totals reconcile with phase subtotals (tutor/judge/smoke); retry cost is an overlapping
    breakdown, not added again. Show total estimate/completeness, known subtotal, unknown entries,
    and scenario tutor cost per accepted response; if none accepted use null. Full evaluation
    cost per accepted response is labeled separately and includes judge/smoke overhead.
  - Script the two-scenario CLI as tutor A, tutor B, judge A, judge B. Assert request prompt/phase
    order and each judge's matching candidate/context, not just final counts. Use Task 12's schema.
  - Invalid fixtures/unknown ids/missing keys fail before client construction; --only subsets
    do not need full family floors. --no-smoke skips smoke calls. Judge failure in a later case
    preserves earlier results and ledger records with explicit incomplete/error status.
  - Rejudge saved responses from two tutor runs with the same evaluator; no tutor call occurs.
    Report evaluator/input changes rather than presenting incompatible scores as direct gains.
  - Two runs with identical setup get distinct directories/run ids and the same fingerprint;
    artifact review makes no calls. Interrupt/error handling leaves readable partial artifacts.

- [ ] **Step 3: Run focused tests and confirm missing-interface failures.**
  `.venv/bin/pytest tests/eval/test_manifest.py tests/eval/test_accounting.py tests/eval/test_report_cli.py -v`.

- [ ] **Step 4: Implement the interfaces and artifacts above.** Extend Task 7 adapter and
  Task 12 judge with the same injectable ledger sink; emit exactly one attempt entry even on
  provider failure. Task 11 retains exact input context and complete usage; Task 14 shares sink
  and phase tags. Keep vendor billing normalization in adapters/accounting, outside the domain.
  Verify current provider pricing/usage documentation before populating the dated snapshot;
  no live call or current-price claim is authorized by this documentation task.

- [ ] **Step 5: Run focused tests and full keyless suite.** Expected: pass without key,
  network or spend. Then commit listed implementation files when executed, with subject
  `feat: record reproducible eval runs and complete request costs`.

---

### Task 14: Persona smoke with assistance and silent-response accounting

**Files:** Create `src/learnai/eval/smoke.py`; test `tests/eval/test_smoke.py`.

**Interfaces:** Preserve `run_persona_smoke(*, tutor, graph, misconceptions, items, verifiers, matcher, clock=None, contract=PRACTICE, sessions=2, items_per_session=3, seed=11) -> dict[str, dict[str, float]]`. Existing engine/session/clock doubles supply the rest. Fake/silent tutors implement the request-scoped exchange protocol.

- [ ] **Step 1: Write failing tests.** Diligent persona makes one readable wrong cold submission then corrects; term completes, prior cold evidence remains. Help-seeking persona asks a draft question before submitting the verifier key; when substantive help was delivered every answer is ASSISTED and strength_total=0. A silent tutor does not contaminate the item: first correct independent submissions can earn strength, and no help event is recorded. Assert attempts/declines/rungs separately. Both personas complete under silent/error responses, with degraded counts surfaced rather than claiming zero-credit help for help never received.
- [ ] **Step 2: Run `.venv/bin/pytest tests/eval/test_smoke.py -v`.** Expected: missing module.
- [ ] **Step 3: Implement short deterministic terms.** Use real engine ask_question, submit and key_submission, revisioned working, scoped session history and bounded task abandonment as in the existing simulator. Do not intentionally submit a wrong cold answer for the help-seeker: that tests a different behavior and masks the no-delivery case. Collect sessions_run/items_completed/tutor_turns/strength_total plus operational silence/exhaustion counts from traces. No LLM student simulator.
- [ ] **Step 4: Run focused tests and full keyless suite.** Expected: pass; live delivery rate is measured, not assumed.
- [ ] **Step 5: Commit listed files.** Suggested subject: `test: exercise help delivery and silence through short tutor sessions`.

---

### Task 15: Early live compatibility, latency measurements and run documentation

**Files:** Modify `pyproject.toml`, `.gitignore`; create `tests/adapters/tutor/test_live.py`, `eval/README.md`.

**Interfaces:** Two live tests only: cache proof and a real accepted engine-to-adapter turn. Register `live` marker and set default pytest selection to exclude it: append `-m 'not live'` to existing quiet addopts. `pytest -o addopts='' -m live` explicitly opts in; tests additionally skip when ANTHROPIC_API_KEY is absent. A key in the environment alone must not make ordinary pytest spend money.

- [ ] **Step 1: Write the two live tests and marker config.** Repeated stable-prefix calls record cache-read tokens; end-to-end draft question or readable submission yields an engine-accepted turn. Assert provider protocol, actual model/settings, history continuity and runtime trace. Do not fail a quality check merely because a provisional latency target was missed: record elapsed delivery time and job, and classify exhaustion explicitly. Make cache prerequisites (vendor minimum cacheable tokens and supported model/settings) explicit so a cache miss is not automatically diagnosed as volatile-prefix leakage.
- [ ] **Step 2: Run the live compatibility tests as soon as Task 8 exists, before spending on the full corpus.** `.venv/bin/pytest -o addopts='' -m live tests/adapters/tutor/test_live.py -v`. Requires the explicit live-run authorization/key used for the paid eval; otherwise document skipped, never claim verified live. Test defaults remain keyless.
- [ ] **Step 3: Write eval/README.md.** Document CLI run/--only/--no-smoke, prompt versioning, current-session retrieval versus deferred cross-session storage, trace privacy, evidence replay versus interaction reconstruction, and parent §10.3 latency targets. Describe provisional YAML profile values as engineering choices. Explain buffered time-to-accepted-turn, per-job median/p95 and silence/exhaustion reporting; progress/validated streaming arrive in 2B/2C. Human calibration of the judge remains required. Document the manifest/fingerprint versus run id, captured inputs, evaluator-controlled comparisons, read-only artifact review versus paid rerun/rejudge, and incomplete cost estimates from Task 13. Matching prompt ids alone never proves comparability.
- [ ] **Step 4: Ignore eval/reports/; retain the reviewed reference summary with an explicit force-add when approved.** Never commit keys or arbitrary private interaction traces.
- [ ] **Step 5: Run `.venv/bin/pytest`, then `.venv/bin/pytest -o addopts='' -m live --collect-only -q`.** Expected: default excludes live even with a key; explicit collection lists exactly two live tests. Paid execution is separate. Run full eval only when implementation and paid execution are authorized; record measured latency/quality and review slow simple replies individually.
- [ ] **Step 6: Commit listed documentation/config/tests.** Suggested subject: `test: make live tutor checks opt-in and document response budgets`.

---

## Done means (acceptance criteria)

1. Real tutor turn flows engine → request-scoped adapter exchange → engine-validated TutorTurn; keyless protocol tests and explicit live checks establish different evidence.
2. Current exercise/work/question/status/revision and checker scope are explicit; drafts are not graded final answers. Engine and eval use the same context builder.
3. Tools and corrective retries retain accumulated provider history with correct call/result pairing and one shared budget; exhaustion yields traced silence without consumed assistance.
4. Delivered task assistance makes subsequent answers ASSISTED (0 weight) even if no hint rung advances; prior cold evidence is unchanged. Engine-owned interface guidance remains exempt.
5. Protected active context is selected by tokens/exercise boundaries; scoped current-session history is retrievable. Rejected drafts and private traces never enter delivered history.
6. Twelve skills carry reviewed teaching notes. The default suite stays keyless and excludes paid live checks even when a key exists.
7. At least fifty core scenarios plus the agreed interaction/history cases run; trace artifacts reconstruct inputs/checks/delivered replies and report per-job latency distributions and exhaustion with quality.
8. Issues 3–4 are recorded in Tasks 9–13: judge packet completeness and coherent corpus expectations. Task 13 records issue 5 manifest/fingerprint, comparison and full request accounting requirements; implementation and live calibration remain to be verified.
9. No database/HTTP/UI, durable cross-session retrieval or strict CAS worker timeout is claimed in 2A. Those arrive in 2B/2C as specified.

## Review Focus

- A student edits working after an old wrong answer: keep revisions distinct and show no fabricated verdict (Tasks 1, 4, 8, 11).
- A NONE-rung task response still supplies help: preserve strict assistance accounting without falsely advancing the ladder (Tasks 1, 8, 14).
- Several tools and a validation retry: preserve original history, paired results and the same deadline (Tasks 7–8).
- History retrieval crosses an exercise boundary: keep provenance, bound scope and corrected misconceptions intact (Tasks 4–5, 8, 10).
- A slow reply exceeds a budget or active work cannot fit: report a typed outcome, preserve cold credit if no help arrived, and never deliver a truncated/unchecked guess (Tasks 4, 7–8, 13–15).

## Historical execution notes and review status — 2026-10-24

This is a documentation revision of the existing plan, not an implementation. Affected inline
implementations were replaced with explicit interfaces, behaviors and verification tasks so stale
algorithms are not left as competing instructions. At that review, execution was to start at Task 1; Task 13 could test the CLI with --no-smoke; Task 14 would add full smoke integration, so task order stayed sequential. Perform Task 15's small live compatibility checks after Task 8
when paid live execution is authorized; the larger eval remains an explicitly authorized implementation validation step.

Engineering starting values (Task 3 profiles, context budgets and reserves) are provisional and
must be evaluated with real traces. The approved product targets are parent §10.3; emergency
ceilings are not latency promises. D17 still requires 2B isolation to enforce synchronous CAS time.

Scope of this review edit: coherent balanced corpus expectations, history retention, current interactions, conservative assistance,
scoped retrieval, reconstruction traces, response budgets and the offline judge packet/rubric. The five discussed review issues are recorded, including issue 5 provenance and cost accounting in Task 13. This does not establish implementation correctness or live readiness. No implementation execution method is selected
by this documentation-only task, and nothing is committed automatically.

Final review refinements (2026-10-25) are recorded in Tasks 1, 3, 5–11: work-revision
identity, richer scoped history metadata and per-exchange binding, live response-job routing,
shared existing verification/form-diagnosis behavior, strict malformed-turn parsing and task-local
verification commands. At that review these were planned work, not implemented features;
the current implementation status and eval guide above supersede that historical status.
