# Slice 1 — Plan 2A: Anthropic Tutor Adapter and Graded Eval Set — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach the real tutor — `AnthropicTutor` behind the existing `Tutor` port, with job-based routing, a cached four-layer prompt, read-only tools, and corrective retries — and build the graded eval set that measures it, all headless and keyless by default.

**Architecture:** Hexagonal, unchanged: the domain core keeps every decision. This plan adds an adapter package, two small engine seams (a delivered-only transcript producer and a corrective-feedback channel through the port), teaching notes as content, and an `eval` package (fixtures → real engine-built contexts → adapter → deterministic checks + rubric judge → report). No framework orchestration: two small bounded Python loops, and the spec records why graph frameworks were rejected (`docs/superpowers/specs/2026-10-16-anthropic-tutor-eval-design.md` §10).

**Tech Stack:** Python 3.12+, SymPy, pytest, Hypothesis, PyYAML, the Anthropic Python SDK (new, adapter-side only), httpx (SDK transport; used directly for scripted test clients).

**Spec:** `docs/superpowers/specs/2026-10-16-anthropic-tutor-eval-design.md` — the design this plan implements. The parent spec `docs/superpowers/specs/2026-09-14-ai-tutoring-platform-design.md` remains the binding authority.

## Global Constraints

Copied verbatim from the parent spec; every task's requirements implicitly include these.

- **P1 — The engine decides; the model speaks.** Every consequential decision lives in deterministic code.
- **P2 — The model has no write path to mastery.** No tool, port, or adapter reachable by a tutor may mutate `SkillState`. Enforced by absence, and by a property test.
- **P3 — Verification before language.** A deterministic checker runs first; the model receives its output.
- **P4 — Assistance is free; credit is not.** Help costs nothing except mastery credit.
- **P5 — Performance is not learning.** Evidence gathered on a skill taught in the same session is weighted near zero.
- **P6 — Evidence is append-only.** Attempts and help events are immutable; `SkillState` is a projection rebuildable from the log.
- Domain core (`src/learnai/domain/`) imports only the standard library and `typing`. **No SymPy, no YAML, no I/O.** Enforced by a test.
- All time is UTC, `datetime` aware, and reaches the domain only through the `Clock` port. Elapsed time is float days.
- Python 3.12+. Strict typing: every public function annotated.

Additional constraints for Plan 2A:

- **The default test suite stays keyless.** Everything except `live`-marked tests runs with no `ANTHROPIC_API_KEY` and no network. `live` tests auto-skip without the key.
- **No model identifier appears outside `config/llm_routes.yaml`.**
- **The adapter never imports domain validators.** Retries travel through `TurnFeedback`; `validate_turn` and `request_validated_turn` remain engine/eval concerns.
- **Delivered-only transcript.** Rejected drafts and internal retries never enter `Session.transcript`.
- **Nothing student-visible on failure.** A failed or exhausted tutor call yields `None` — no message, no help consumed — and the incident is logged.

---

## File Structure

```
pyproject.toml                            # Modify: +anthropic dependency; register the `live` pytest marker
config/llm_routes.yaml                    # Create: the only place model identifiers appear
src/learnai/adapters/tutor/anthropic/
  __init__.py                             # Create: empty package marker
  routing.py                              # Create: route config schema, load, resolve; fail-fast
  prompt.py                               # Create: four-layer assembly, cache breakpoints, correction append
  tools.py                                # Create: the four read tools
  turn_schema.py                          # Create: structured-turn schema and parser
  adapter.py                              # Create: AnthropicTutor — the conversations loop and bounds
src/learnai/domain/turn.py                # Modify: +TurnFeedback, + request_validated_turn
src/learnai/domain/ports.py               # Modify: Tutor.respond gains feedback (defaulted)
src/learnai/domain/session.py             # Modify: Session +transcript (defaulted)
src/learnai/domain/skills.py              # Modify: Skill +teaching_notes (defaulted)
src/learnai/domain/engine.py              # Modify: transcript producer, TRANSCRIPT_WINDOW, helper use
src/learnai/adapters/tutor/fake_tutor.py  # Modify: record feedback
src/learnai/adapters/content/loader.py    # Modify: teaching_notes required
content/quadratics/skills.yaml            # Modify: teaching notes for all twelve skills
src/learnai/eval/
  __init__.py                             # Create: empty package marker
  fixtures.py                             # Create: scenario schema and loader
  runner.py                               # Create: context builder, validated-turn driver, outcomes
  judge.py                                # Create: rubric judge via the rubric_judge route
  smoke.py                                # Create: persona smoke sessions
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
tests/adapters/test_content_loader.py     # Modify: fixtures gain notes; +rejection tests
tests/adapters/tutor/test_routing.py      # Create
tests/adapters/tutor/test_prompt.py       # Create
tests/adapters/tutor/test_tools.py        # Create
tests/adapters/tutor/test_turn_schema.py  # Create
tests/adapters/tutor/test_adapter.py      # Create
tests/adapters/tutor/test_adapter_engine.py    # Create (keyless end-to-end through the engine)
tests/adapters/tutor/test_live.py         # Create (live-marked; skipped without a key)
tests/eval/test_fixtures.py               # Create
tests/eval/test_runner.py                 # Create
tests/eval/test_judge.py                  # Create
tests/eval/test_report_cli.py             # Create
tests/eval/test_smoke.py                  # Create
```

---

### Task 1: Engine amendments — the transcript producer and the corrective-feedback channel

**Files:**
- Modify: `src/learnai/domain/turn.py` (append `TurnFeedback` and `request_validated_turn`)
- Modify: `src/learnai/domain/ports.py` (the `Tutor` protocol)
- Modify: `src/learnai/domain/session.py` (`Session.transcript`)
- Modify: `src/learnai/domain/engine.py` (transcript writes, `TRANSCRIPT_WINDOW`, the shared validated-turn helper)
- Modify: `src/learnai/adapters/tutor/fake_tutor.py` (record feedback)
- Test: `tests/domain/test_transcript_and_feedback.py`

**Interfaces:**
- Consumes: `TurnContext`, `TutorTurn`, `ValidationResult`, `RejectionReason`, `validate_turn` (all exist); `FakeTutor`'s script (exists); the engine's existing construction pattern (see `tests/domain/test_engine.py`).
- Produces: `TurnFeedback(reason: RejectionReason, detail: str, rejected: TutorTurn)`; `request_validated_turn(tutor, context, graph, verifier, *, max_attempts) -> tuple[TutorTurn | None, int]`; `Tutor.respond(context, *, feedback: TurnFeedback | None = None)`; `Session.transcript: tuple[TranscriptEntry, ...]`; `engine.TRANSCRIPT_WINDOW = 20`; `FakeTutor.feedbacks: list[TurnFeedback | None]`; module function `student_entry(answer, declined) -> TranscriptEntry`.

- [ ] **Step 1: Write the failing test module**

```python
# tests/domain/test_transcript_and_feedback.py
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
from learnai.domain import engine as engine_module
from learnai.domain.contracts import PRACTICE
from learnai.domain.engine import PracticeEngine
from learnai.domain.enums import Confidence, HelpRung, Verdict
from learnai.domain.ids import CourseId, SessionId, StudentId
from learnai.domain.items import Submission
from learnai.domain.turn import RejectionReason, TurnFeedback, TutorTurn

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
COURSE = CLUSTER.graph.topological_order()

LEAKY = TutorTurn(message="The answer is (x + 3)^2.", rung_used=HelpRung.FULL_REVEAL)
NUDGE = TutorTurn(message="What is the very next thing you could try?", rung_used=HelpRung.NUDGE)


def build(tutor: FakeTutor):
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
        course_skills=COURSE,
        states={},
        budget_items=4,
        session_id=SessionId("sess-1"),
        seed=7,
    )
    return engine, session


def wrong(task) -> Submission:
    return Submission.of("definitely not the answer")


def test_feedback_carries_the_reason_and_the_rejected_turn():
    tutor = FakeTutor(script=[LEAKY, NUDGE])
    engine, session = build(tutor)
    _, _, outcome = engine.submit(
        session, {}, [], wrong(session.current_task), Confidence.GUESSING
    )
    assert outcome.tutor_turn == NUDGE
    assert len(tutor.feedbacks) == 2
    assert tutor.feedbacks[0] is None
    feedback = tutor.feedbacks[1]
    assert isinstance(feedback, TurnFeedback)
    assert feedback.reason is RejectionReason.RUNG_EXCEEDED
    assert feedback.rejected == LEAKY
    assert "used FULL_REVEAL" in feedback.detail


def test_exhausted_retries_are_silence_not_a_bad_message():
    tutor = FakeTutor(script=[LEAKY, LEAKY])
    engine, session = build(tutor)
    _, _, outcome = engine.submit(
        session, {}, [], wrong(session.current_task), Confidence.GUESSING
    )
    assert outcome.tutor_turn is None
    assert len(tutor.feedbacks) == 2  # the bound is two attempts


def test_only_delivered_exchanges_reach_the_transcript():
    tutor = FakeTutor(script=[LEAKY, NUDGE])
    engine, session = build(tutor)
    session, _, _ = engine.submit(
        session, {}, [], wrong(session.current_task), Confidence.GUESSING
    )
    assert [(e.speaker, e.text) for e in session.transcript] == [
        ("student", "definitely not the answer"),
        ("tutor", NUDGE.message),
    ]


def test_a_decline_is_an_honest_transcript_entry():
    tutor = FakeTutor()
    engine, session = build(tutor)
    session, _, _ = engine.submit(session, {}, [], Submission.none(), Confidence.NO_IDEA)
    assert session.transcript[0].speaker == "student"
    assert session.transcript[0].text == "(no answer)"


def test_malformed_input_changes_nothing():
    tutor = FakeTutor()
    engine, session = build(tutor)
    session, _, outcome = engine.submit(
        session, {}, [], Submission.of("(("), Confidence.GUESSING
    )
    assert outcome.verdict is Verdict.MALFORMED
    assert session.transcript == ()
    assert tutor.feedbacks == []


def test_a_delivered_none_rung_help_turn_is_recorded_but_not_consumed():
    tutor = FakeTutor(script=[TutorTurn(message="Take your time.", rung_used=HelpRung.NONE)])
    engine, session = build(tutor)
    session, turn = engine.request_help(session, {})
    assert turn is not None and turn.rung_used is HelpRung.NONE
    assert len(session.transcript) == 1
    assert session.transcript[0].speaker == "tutor"
    assert session.current_task.help_state.rungs_used == ()
    assert engine.evidence_log.events() == ()


def test_the_transcript_window_caps_what_the_tutor_sees(monkeypatch):
    monkeypatch.setattr(engine_module, "TRANSCRIPT_WINDOW", 2)
    tutor = FakeTutor()
    engine, session = build(tutor)
    for _ in range(2):
        session, _, _ = engine.submit(
            session, {}, [], wrong(session.current_task), Confidence.GUESSING
        )
    seen = tutor.contexts_seen[-1].transcript
    assert len(seen) == 2
    assert seen == session.transcript[-2:]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/domain/test_transcript_and_feedback.py -v`
Expected: collection error — `ImportError: cannot import name 'TurnFeedback'` (and companions) from `learnai.domain.turn`.

- [ ] **Step 3: Amend `turn.py` — append `TurnFeedback` and the shared validated-turn loop**

At the top of `src/learnai/domain/turn.py`, extend the ports import to `from learnai.domain.ports import Tutor, Verifier`. At the end of the file, append:

```python
@dataclass(frozen=True, slots=True)
class TurnFeedback:
    """Why the previous draft was rejected, and the draft itself.

    Carried through the Tutor port so the adapter can show the model its own
    rejected message with a corrective instruction — the engine stays the only
    judge (spec §9.3), and the corrective channel stays testable.
    """

    reason: RejectionReason
    detail: str
    rejected: TutorTurn


def request_validated_turn(
    tutor: Tutor,
    context: TurnContext,
    graph: SkillGraph,
    verifier: Verifier,
    *,
    max_attempts: int,
) -> tuple[TutorTurn | None, int]:
    """Ask, validate, retry with feedback.

    The single validated-turn loop, shared by the engine and the eval runner so
    the eval set can never be greener than reality. Returns the accepted turn
    and the attempt count it took, or (None, max_attempts).
    """
    feedback: TurnFeedback | None = None
    for attempt in range(1, max_attempts + 1):
        turn = tutor.respond(context, feedback=feedback)
        if turn is None:
            return None, attempt
        result = validate_turn(turn, context, graph, verifier)
        if result.accepted:
            return turn, attempt
        assert result.reason is not None, "a rejection always names its reason"
        feedback = TurnFeedback(result.reason, result.detail or "", turn)
    return None, max_attempts
```

- [ ] **Step 4: Amend `ports.py` — the `Tutor` protocol gains the defaulted feedback argument**

Extend the `TYPE_CHECKING` import to include `TurnFeedback`, and change the protocol to:

```python
class Tutor(Protocol):
    def respond(
        self, context: "TurnContext", *, feedback: "TurnFeedback | None" = None
    ) -> "TutorTurn | None": ...
```

- [ ] **Step 5: Amend `session.py` — `Session` gains the transcript**

Add `from learnai.domain.turn import TranscriptEntry` to the imports, then append as the last field of `Session`:

```python
    transcript: tuple[TranscriptEntry, ...] = ()
    """Delivered exchanges only — student texts and accepted tutor messages.
    Rejected drafts and internal retries never enter it (spec §4)."""
```

- [ ] **Step 6: Amend `fake_tutor.py` — record the feedback it receives**

Add `TurnFeedback` to the `learnai.domain.turn` import; add in `__init__`: `self.feedbacks: list[TurnFeedback | None] = []`; change the signature to `def respond(self, context: TurnContext, *, feedback: TurnFeedback | None = None) -> TutorTurn:` and make the first statement `self.feedbacks.append(feedback)` (before `self.contexts_seen.append(context)`).

- [ ] **Step 7: Amend `engine.py` — transcript writes, the window, and the shared loop**

1. Extend the `learnai.domain.turn` import with `TranscriptEntry` and `request_validated_turn`; drop `validate_turn` from the imports (it is no longer called here).
2. After `MAX_TUTOR_RETRIES = 2` add:

```python
TRANSCRIPT_WINDOW = 20
"""Delivered transcript entries carried into the tutor's context."""
```

3. Add this module function near the other helpers (below the imports/constants is fine):

```python
def student_entry(answer: Submission, declined: bool) -> TranscriptEntry:
    if declined:
        return TranscriptEntry("student", "(no answer)")
    return TranscriptEntry("student", "; ".join(answer.entries) or "(blank)")
```

4. In `submit()`, immediately **after** the `if not declined: task = replace(task, help_state=record_attempt(task.help_state))` lines, insert:

```python
        session = replace(
            session,
            transcript=session.transcript + (student_entry(answer, declined),),
        )
```

5. In `submit()`, immediately **after** the `if not correct and self._should_intervene(...)` block (the one ending with the `_ask_tutor` call), insert:

```python
        if tutor_turn is not None:
            session = replace(
                session,
                transcript=session.transcript
                + (TranscriptEntry("tutor", tutor_turn.message),),
            )
```

6. In `request_help()`, the NONE-rung path becomes:

```python
        if turn.rung_used <= HelpRung.NONE:
            # A turn that used no rung gave no ladder help; deliver the message
            # but record nothing, so help_taken stays honest.
            session = replace(
                session,
                transcript=session.transcript + (TranscriptEntry("tutor", turn.message),),
            )
            return replace_task(session, task), turn
```

7. In `request_help()`, the tail becomes:

```python
        task = replace(task, help_state=record_help(task.help_state, turn.rung_used))
        session = replace(
            session,
            transcript=session.transcript + (TranscriptEntry("tutor", turn.message),),
        )
        return replace_task(session, task), turn
```

8. `_build_context` gains `session` as its first parameter (`def _build_context(self, session: Session, task: Task, ...)`) and a new field after `last_verdict=last_verdict,`:

```python
            transcript=session.transcript[-TRANSCRIPT_WINDOW:],
```

9. In `_ask_tutor`, update the `_build_context` call to pass `session` first, and replace the retry loop (from `for _ in range(MAX_TUTOR_RETRIES):` through `return None`) with:

```python
        verifier = self._verifier_for(task.skill_id)
        turn, _ = request_validated_turn(
            self._tutor, context, self.graph, verifier, max_attempts=MAX_TUTOR_RETRIES
        )
        return turn
```

- [ ] **Step 8: Run the focused tests to verify they pass**

Run: `.venv/bin/pytest tests/domain/test_transcript_and_feedback.py -v`
Expected: 7 passed.

- [ ] **Step 9: Run the full suite**

Run: `.venv/bin/pytest`
Expected: all green — the only new count is this module's 7 tests; no existing test changes behavior.

- [ ] **Step 10: Commit**

```bash
git add src/learnai/domain/turn.py src/learnai/domain/ports.py src/learnai/domain/session.py src/learnai/domain/engine.py src/learnai/adapters/tutor/fake_tutor.py tests/domain/test_transcript_and_feedback.py
git commit -m "feat: carry corrective feedback and a delivered transcript through the tutor seam"
```

---

### Task 2: Teaching notes v0 — content, the `Skill` field, the loader requirement, and the context wiring

**Files:**
- Modify: `src/learnai/domain/skills.py` (`Skill` gains `teaching_notes`)
- Modify: `content/quadratics/skills.yaml` (notes for all twelve skills)
- Modify: `src/learnai/adapters/content/loader.py` (require non-empty notes)
- Modify: `src/learnai/domain/engine.py` (`_build_context` passes `skill.teaching_notes`)
- Modify: `tests/adapters/test_content_loader.py` (fixtures gain notes; rejection tests)
- Test: `tests/domain/test_context_notes.py` (new)

**Interfaces:**
- Consumes: `Skill` construction sites in the loader; `_build_context` (Task 1's version).
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
    engine.submit(session, {}, [], Submission.of("nope"), Confidence.GUESSING)
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

- [ ] **Step 6: Amend `engine.py` — pass the notes into the context**

In `_build_context`, change `teaching_notes=""` to `teaching_notes=skill.teaching_notes`.

- [ ] **Step 7: Update the loader test fixtures and run everything**

Give every skill entry in the loader test module's raw-cluster helper a `teaching_notes` value (any non-blank string). Then run:

Run: `.venv/bin/pytest tests/domain/test_context_notes.py tests/adapters/test_content_loader.py -v`
Expected: all pass — including the two new rejection tests.

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add src/learnai/domain/skills.py content/quadratics/skills.yaml src/learnai/adapters/content/loader.py src/learnai/domain/engine.py tests/adapters/test_content_loader.py tests/domain/test_context_notes.py
git commit -m "feat: teaching notes for the quadratics cluster, required by the loader"
```

---

### Task 3: Route configuration — schema, loading, resolution

**Files:**
- Create: `config/llm_routes.yaml`
- Create: `src/learnai/adapters/tutor/anthropic/__init__.py` (empty)
- Create: `src/learnai/adapters/tutor/anthropic/routing.py`
- Create: `tests/adapters/tutor/__init__.py` (empty)
- Test: `tests/adapters/tutor/test_routing.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `RouteConfigError(ValueError)`; `Route` frozen dataclass with fields `name, adapter, model, effort, thinking, temperature, max_tokens (2048), stream (False), max_tool_iterations (6)`; `parse_routes(raw: Mapping) -> dict[str, Route]`; `load_routes(path: Path) -> Mapping[str, Route]` (read-only mapping); `resolve_route(routes, name) -> Route`.

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/tutor/test_routing.py
import pathlib

import pytest

from learnai.adapters.tutor.anthropic.routing import (
    RouteConfigError,
    load_routes,
    parse_routes,
    resolve_route,
)

CONFIG = pathlib.Path(__file__).parent.parent.parent.parent / "config" / "llm_routes.yaml"


def minimal(**overrides):
    entry = {"adapter": "anthropic", "model": "claude-opus-5"}
    entry.update(overrides)
    return {"routes": {"tutor_dialogue": entry}}


def test_a_route_parses_with_its_defaults():
    routes = parse_routes(minimal())
    route = routes["tutor_dialogue"]
    assert route.model == "claude-opus-5"
    assert route.max_tokens == 2048
    assert route.stream is False
    assert route.max_tool_iterations == 6
    assert route.temperature is None


def test_settings_are_read_from_the_entry():
    routes = parse_routes(
        minimal(thinking="adaptive", effort="high", temperature=0.0, stream=True, max_tool_iterations=3)
    )
    route = routes["tutor_dialogue"]
    assert route.thinking == "adaptive"
    assert route.effort == "high"
    assert route.temperature == 0.0
    assert route.stream is True
    assert route.max_tool_iterations == 3


@pytest.mark.parametrize(
    "raw, match",
    [
        ({}, "no 'routes'"),
        ({"routes": {}}, "non-empty"),
        ({"routes": {"x": []}}, "must be a mapping"),
        ({"routes": {"x": {"model": "m"}}}, "unknown adapter"),
        ({"routes": {"x": {"adapter": "anthropic"}}}, "no model"),
        ({"routes": {"x": {"adapter": "anthropic", "model": "m", "wat": 1}}}, "unknown keys"),
    ],
)
def test_bad_configurations_are_rejected_loudly(raw, match):
    with pytest.raises(RouteConfigError, match=match):
        parse_routes(raw)


def test_resolve_route_names_the_unknown_route_and_the_known_ones():
    routes = parse_routes(minimal())
    with pytest.raises(RouteConfigError, match="unknown route 'nope'.*tutor_dialogue"):
        resolve_route(routes, "nope")


def test_invalid_yaml_is_a_config_error(tmp_path):
    bad = tmp_path / "routes.yaml"
    bad.write_text("routes: [")
    with pytest.raises(RouteConfigError, match="invalid YAML"):
        load_routes(bad)


def test_the_committed_config_file_loads_and_carries_the_three_routes():
    routes = load_routes(CONFIG)
    assert set(routes) == {"tutor_dialogue", "error_diagnosis", "rubric_judge"}
    assert routes["tutor_dialogue"].stream is False
    assert routes["rubric_judge"].temperature == 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/adapters/tutor/test_routing.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'learnai.adapters.tutor.anthropic.routing'`.

- [ ] **Step 3: Write the config file**

```yaml
# config/llm_routes.yaml
# Routes are named by job, never by model (parent spec §10). Model identifiers
# are resolved at implementation against the live API; this file is the only
# place a model identifier appears anywhere in the system.
routes:
  tutor_dialogue:
    adapter: anthropic
    model: claude-opus-5        # placeholder: verify against the live API
    effort: high
    thinking: adaptive
    stream: false               # streaming mechanics arrive with the transport (2B/2C)
    max_tool_iterations: 6
  error_diagnosis:
    adapter: anthropic
    model: claude-opus-5        # reserved: activates when a dedicated novel-error call is warranted
    effort: xhigh
    thinking: adaptive
  rubric_judge:
    adapter: anthropic
    model: claude-opus-5        # placeholder: verify against the live API
    effort: high
    thinking: adaptive
    temperature: 0.0
```

- [ ] **Step 4: Write `routing.py`**

```python
# src/learnai/adapters/tutor/anthropic/routing.py
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml


class RouteConfigError(ValueError):
    """A routes file that cannot be trusted to name a model call."""


KNOWN_ADAPTERS = frozenset({"anthropic"})
ROUTE_FIELDS = frozenset(
    {
        "adapter",
        "model",
        "effort",
        "thinking",
        "temperature",
        "max_tokens",
        "stream",
        "max_tool_iterations",
    }
)


@dataclass(frozen=True, slots=True)
class Route:
    """One named job resolved to a model and its settings."""

    name: str
    adapter: str
    model: str
    effort: str | None = None
    thinking: str | None = None
    temperature: float | None = None
    max_tokens: int = 2048
    stream: bool = False
    max_tool_iterations: int = 6


def parse_routes(raw: Mapping[str, Any]) -> dict[str, Route]:
    if not isinstance(raw, Mapping) or "routes" not in raw:
        raise RouteConfigError("routes file has no 'routes' mapping")
    routes_raw = raw["routes"]
    if not isinstance(routes_raw, Mapping) or not routes_raw:
        raise RouteConfigError("'routes' must be a non-empty mapping")
    routes: dict[str, Route] = {}
    for name, entry in routes_raw.items():
        if not isinstance(entry, Mapping):
            raise RouteConfigError(f"route {name!r} must be a mapping")
        unknown = set(entry) - ROUTE_FIELDS
        if unknown:
            raise RouteConfigError(f"route {name!r} has unknown keys {sorted(unknown)}")
        adapter = entry.get("adapter")
        if adapter not in KNOWN_ADAPTERS:
            raise RouteConfigError(f"route {name!r} names unknown adapter {adapter!r}")
        model = entry.get("model")
        if not (isinstance(model, str) and model.strip()):
            raise RouteConfigError(f"route {name!r} has no model")
        routes[str(name)] = Route(
            name=str(name),
            adapter=adapter,
            model=model,
            effort=entry.get("effort"),
            thinking=entry.get("thinking"),
            temperature=entry.get("temperature"),
            max_tokens=entry.get("max_tokens", 2048),
            stream=entry.get("stream", False),
            max_tool_iterations=entry.get("max_tool_iterations", 6),
        )
    return routes


def load_routes(path: Path) -> Mapping[str, Route]:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise RouteConfigError(f"{path}: invalid YAML: {error}") from error
    return MappingProxyType(parse_routes(raw))


def resolve_route(routes: Mapping[str, Route], name: str) -> Route:
    try:
        return routes[name]
    except KeyError:
        raise RouteConfigError(
            f"unknown route {name!r}; known routes: {sorted(routes)}"
        ) from None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/tutor/test_routing.py -v`
Expected: 11 passed (6 test functions; one parametrized ×6).

- [ ] **Step 6: Commit**

```bash
git add config/llm_routes.yaml src/learnai/adapters/tutor/anthropic/ tests/adapters/tutor/ tests/adapters/tutor/test_routing.py
git commit -m "feat: job-named route configuration for the tutor adapter"
```

---

### Task 4: Prompt assembly — four layers, cache breakpoints, correction append

**Files:**
- Create: `src/learnai/adapters/tutor/anthropic/prompt.py`
- Test: `tests/adapters/tutor/test_prompt.py`

**Interfaces:**
- Consumes: `TurnContext`, `TurnFeedback`, `TutorTurn`, `HelpRung`, `Text`/`Formula` (all exist).
- Produces: `TUTOR_POLICY: str`; `SystemBlock(text: str, cache: bool = False)`; `Prompt(system: tuple[SystemBlock, ...], messages: tuple[dict[str, str], ...])`; `render_blocks(blocks: tuple[Block, ...]) -> str` (shared with the tools module); `build_prompt(context: TurnContext) -> Prompt` (three cached system layers, stable-first, then the transcript as alternating messages, then the volatile moment as the final user message); `correction_text(feedback: TurnFeedback) -> str`; `append_correction(messages, feedback) -> tuple[dict[str, str], ...]` (rejected draft as the assistant message, then a mid-conversation system message — spec §9.3).

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/tutor/test_prompt.py
from learnai.adapters.tutor.anthropic.prompt import (
    append_correction,
    build_prompt,
    correction_text,
)
from learnai.domain.enums import HelpRung, VettingLevel, Verdict
from learnai.domain.ids import ItemId, MisconceptionId, SkillId, TemplateId
from learnai.domain.items import AnswerSpec, Formula, Item, Provenance, StepDiff, Text
from learnai.domain.skills import Misconception
from learnai.domain.turn import (
    RejectionReason,
    SkillPack,
    StudentSummary,
    TranscriptEntry,
    TurnContext,
    TurnFeedback,
    TutorTurn,
)

MISCONCEPTION = Misconception(
    id=MisconceptionId("mc.foil.drops.cross"),
    subject_id="math",
    name="Drops the cross terms",
    description="Multiplies first and last terms only.",
    signature="product_of_sums_drops_cross",
)

ITEM = Item(
    id=ItemId("quad.expand.binomial.v1#3"),
    skill_id=SkillId("quad.expand.binomial"),
    provenance=Provenance.generated(TemplateId("quad.expand.binomial.v1"), 3),
    statement=(Text("Expand: "), Formula("(x + 3)(x + 4)")),
    answer_spec=AnswerSpec("x^2 + 7x + 12"),
    worked_steps=("(x + 3)(x + 4)", "x^2 + 4x + 3x + 12", "x^2 + 7x + 12"),
    difficulty=-1.0,
    vetting_level=VettingLevel.MACHINE_VERIFIED,
)


def context(**overrides) -> TurnContext:
    defaults = dict(
        skill_pack=SkillPack(
            skill_id=SkillId("quad.expand.binomial"),
            can_do_statement="Expand (x + a)(x + b) into standard form.",
            teaching_notes="Multiply every term of one factor by every term of the other.",
            misconceptions=(MISCONCEPTION,),
        ),
        item=ITEM,
        student_summary=StudentSummary(
            strength=1.2, is_fresh=True, calibration_gap=0.1, prior_misconceptions=()
        ),
        step_diff=StepDiff(index=1, previous="(x + 3)(x + 4)", current="x^2 + 12"),
        diagnosis=None,
        permitted_rung=HelpRung.NUDGE,
        last_verdict=Verdict.WRONG,
    )
    defaults.update(overrides)
    return TurnContext(**defaults)


def test_three_cached_layers_in_stable_order():
    prompt = build_prompt(context())
    assert len(prompt.system) == 3
    assert all(block.cache for block in prompt.system)
    policy, skill, preamble = prompt.system
    assert "tutor" in policy.text.lower()
    assert "quad.expand.binomial" in skill.text
    assert "Multiply every term" in skill.text
    assert "mc.foil.drops.cross" in skill.text
    assert "strength" in preamble.text


def test_the_transcript_becomes_alternating_messages_and_the_moment_comes_last():
    ctx = context(
        transcript=(
            TranscriptEntry("student", "x^2 + 12"),
            TranscriptEntry("tutor", "Look again at the middle terms."),
        )
    )
    prompt = build_prompt(ctx)
    roles = [message["role"] for message in prompt.messages]
    assert roles == ["user", "assistant", "user"]
    assert prompt.messages[0]["content"] == "x^2 + 12"
    assert "(x + 3)(x + 4)" in prompt.messages[-1]["content"]


def test_the_moment_carries_the_rung_guidance_the_break_and_the_verdict():
    text = build_prompt(context()).messages[-1]["content"]
    assert "NUDGE" in text
    assert "prompts the next thought" in text
    assert "x^2 + 12" in text and "x^2 + 7x + 12" not in text  # the break, not the answer
    assert "WRONG" in text


def test_the_answer_and_the_worked_steps_never_enter_the_prompt():
    prompt = build_prompt(context())
    everything = " ".join(block.text for block in prompt.system)
    everything += " ".join(message["content"] for message in prompt.messages)
    assert "x^2 + 7x + 12" not in everything  # the answer expression
    assert "x^2 + 4x + 3x + 12" not in everything  # a worked step


def test_an_empty_transcript_is_fine():
    prompt = build_prompt(context())
    assert len(prompt.messages) == 1
    assert prompt.messages[0]["role"] == "user"


def test_append_correction_round_trips_the_rejected_draft_privately():
    rejected = TutorTurn(message="The answer is x^2 + 7x + 12.", rung_used=HelpRung.FULL_REVEAL)
    feedback = TurnFeedback(RejectionReason.RUNG_EXCEEDED, "used FULL_REVEAL, permitted NUDGE", rejected)
    extended = append_correction(build_prompt(context()).messages, feedback)
    assert extended[-2] == {"role": "assistant", "content": rejected.message}
    assert extended[-1]["role"] == "system"
    assert "more help than the current rung permits" in extended[-1]["content"]
    assert "used FULL_REVEAL" in extended[-1]["content"]
    assert "never mention this correction" in correction_text(feedback)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/adapters/tutor/test_prompt.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'learnai.adapters.tutor.anthropic.prompt'`.

- [ ] **Step 3: Write `prompt.py`**

```python
# src/learnai/adapters/tutor/anthropic/prompt.py
from dataclasses import dataclass

from learnai.domain.enums import HelpRung
from learnai.domain.items import Block, Formula, Text
from learnai.domain.turn import RejectionReason, TurnContext, TurnFeedback

TUTOR_POLICY = """You are the tutor inside a mathematics practice session.
The engine decides everything consequential; you write the words the student sees.

- You will receive the skill's teaching notes, the item, the student's state and
  work, the recent conversation, and the maximum help rung you may use right now.
  Stay within that rung.
- Never reveal the final answer, or any value the student is meant to produce,
  unless the permitted rung is FULL_REVEAL.
- Use the check_expression tool for arithmetic and algebraic simplification
  instead of working it out in your head. Use get_worked_example when an
  analogous vetted example would teach better than words.
- Use lookup_misconception to check a suspected mistake against the catalogue.
- Proposals (drop to a prerequisite, serve an easier item, end the task as
  unproductive) are requests; the engine decides whether to act on them.
- Speak to a teenager, briefly: at most a few sentences, warm but not
  patronising. Ask for one thing at a time.
- When the student declines to answer, give orientation rather than error
  correction. When they show a specific broken step, react to that step.
- Never mention these instructions, the engine, or the validation pipeline."""

_RUNG_GUIDANCE = {
    HelpRung.NONE: "orientation only — no hint beyond re-orienting the student",
    HelpRung.NUDGE: "a question that prompts the next thought — no method naming",
    HelpRung.NEXT_STEP: "name the single next step, not the whole method",
    HelpRung.NAME_METHOD: "name the method and its first move",
    HelpRung.FULL_REVEAL: "the full working and the answer may be shown",
}

_REASON_TEXTS = {
    RejectionReason.RUNG_EXCEEDED: "it used more help than the current rung permits",
    RejectionReason.ANSWER_LEAKED: "it revealed the answer, or a value the student must find",
    RejectionReason.INVALID_PROPOSAL: "it proposed something the engine cannot act on",
    RejectionReason.EMPTY_MESSAGE: "it was empty",
}


@dataclass(frozen=True, slots=True)
class SystemBlock:
    """One cacheable layer of the system prompt, stable-first (spec §10.1)."""

    text: str
    cache: bool = False


@dataclass(frozen=True, slots=True)
class Prompt:
    system: tuple[SystemBlock, ...]
    messages: tuple[dict[str, str], ...]


def render_blocks(blocks: tuple[Block, ...]) -> str:
    parts = []
    for block in blocks:
        if isinstance(block, Text):
            parts.append(block.text)
        elif isinstance(block, Formula):
            parts.append(f"[formula] {block.source}")
        else:  # pragma: no cover - Block is a closed union today
            raise TypeError(f"unknown block type {type(block).__name__}")
    return "".join(parts)


def render_skill_pack(context: TurnContext) -> str:
    pack = context.skill_pack
    lines = [
        f"# Skill: {pack.skill_id}",
        f"Can-do: {pack.can_do_statement}",
        "",
        "# Teaching notes",
        pack.teaching_notes or "(none)",
        "",
        "# Misconception catalogue",
    ]
    if pack.misconceptions:
        lines.extend(
            f"- {m.id} — {m.name}: {m.description} (signature: {m.signature})"
            for m in pack.misconceptions
        )
    else:
        lines.append("(none)")
    return "\n".join(lines)


def render_session_preamble(context: TurnContext) -> str:
    summary = context.student_summary
    active = ", ".join(summary.prior_misconceptions) or "(none)"
    return "\n".join(
        [
            "# Student",
            f"strength: {summary.strength:.2f}",
            f"fresh: {'yes' if summary.is_fresh else 'no'}",
            f"calibration gap: {summary.calibration_gap:+.2f}",
            f"active misconceptions: {active}",
        ]
    )


def render_moment(context: TurnContext) -> str:
    lines = [
        "# The moment",
        f"Item statement: {render_blocks(context.item.statement)}",
    ]
    if context.transcript:
        lines.append("(The conversation so far is above; continue it.)")
    if context.last_verdict is not None:
        lines.append(f"Last verdict: {context.last_verdict.name}")
    if context.step_diff is not None:
        diff = context.step_diff
        readable = "" if not diff.unreadable else " (unreadable)"
        lines.append(
            f"Broken step at index {diff.index}{readable}: "
            f"{diff.previous!r} → {diff.current!r} does not follow"
        )
    if context.diagnosis is not None:
        lines.append(f"Diagnosed misconception: {context.diagnosis}")
    else:
        lines.append("Diagnosed misconception: none (novel error or decline)")
    lines.append(
        f"Maximum help now: {context.permitted_rung.name} — "
        f"{_RUNG_GUIDANCE[context.permitted_rung]}"
    )
    lines.append("Produce the next tutoring turn.")
    return "\n".join(lines)


def build_prompt(context: TurnContext) -> Prompt:
    system = (
        SystemBlock(TUTOR_POLICY, cache=True),
        SystemBlock(render_skill_pack(context), cache=True),
        SystemBlock(render_session_preamble(context), cache=True),
    )
    messages = tuple(
        {
            "role": "user" if entry.speaker == "student" else "assistant",
            "content": entry.text,
        }
        for entry in context.transcript
    ) + ({"role": "user", "content": render_moment(context)},)
    return Prompt(system=system, messages=messages)


def correction_text(feedback: TurnFeedback) -> str:
    reason = _REASON_TEXTS[feedback.reason]
    return (
        f"Your previous draft was not delivered to the student: {reason}. "
        f"Detail: {feedback.detail}. Rewrite the turn with the same intent, "
        "respecting the permitted rung; never mention this correction."
    )


def append_correction(
    messages: tuple[dict[str, str], ...], feedback: TurnFeedback
) -> tuple[dict[str, str], ...]:
    return messages + (
        {"role": "assistant", "content": feedback.rejected.message},
        {"role": "system", "content": correction_text(feedback)},
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/tutor/test_prompt.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/learnai/adapters/tutor/anthropic/prompt.py tests/adapters/tutor/test_prompt.py
git commit -m "feat: four-layer cached prompt assembly with the corrective channel"
```

---

### Task 5: The four read tools

**Files:**
- Create: `src/learnai/adapters/tutor/anthropic/tools.py`
- Test: `tests/adapters/tutor/test_tools.py`

**Interfaces:**
- Consumes: `parse_math`, `evaluated`, `write_math` (cas); `GeneratorRegistry` (`templates_for`, `instantiate`); `SkillGraph`; `Misconception`; `TurnContext`; `render_session_preamble` and `render_blocks` from `prompt.py` (Task 4).
- Produces: `TOOL_SCHEMAS: tuple[dict, ...]` (the SDK tool definitions); `Toolbox(graph=..., items=..., catalogue=...)` with `execute(name: str, arguments: Mapping[str, Any], context: TurnContext) -> str` — always returns text: failures come back as `error: ...` strings, never as exceptions (spec §6). Read-only by construction: every handler returns text, and nothing in this surface reaches `SkillState` (P2).

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/tutor/test_tools.py
import pathlib

from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.anthropic.tools import TOOL_SCHEMAS, Toolbox
from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.ids import SkillId
from learnai.domain.turn import SkillPack, StudentSummary, TurnContext

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)
SKILL = SkillId("quad.expand.binomial")


def context(item=None) -> TurnContext:
    item = item or REGISTRY.instantiate("quad.expand.binomial.v1", 0)
    return TurnContext(
        skill_pack=SkillPack(
            skill_id=SKILL,
            can_do_statement="Expand (x + a)(x + b) into standard form.",
            teaching_notes="Distribute every term.",
            misconceptions=(),
        ),
        item=item,
        student_summary=StudentSummary(
            strength=1.1, is_fresh=False, calibration_gap=-0.2, prior_misconceptions=()
        ),
        step_diff=None,
        diagnosis=None,
        permitted_rung=HelpRung.NUDGE,
        last_verdict=Verdict.WRONG,
    )


def toolbox() -> Toolbox:
    return Toolbox(graph=CLUSTER.graph, items=REGISTRY, catalogue=CLUSTER.misconceptions)


def test_the_four_schemas_are_declared():
    assert {schema["name"] for schema in TOOL_SCHEMAS} == {
        "check_expression",
        "get_worked_example",
        "lookup_misconception",
        "get_student_summary",
    }


def test_check_expression_evaluates_with_the_cas():
    assert toolbox().execute("check_expression", {"expression": "2x + 3x"}, context()) == "5*x"


def test_check_expression_reports_unreadable_input_as_an_error_string():
    result = toolbox().execute("check_expression", {"expression": "(("}, context())
    assert result.startswith("error: ParseError")


def test_a_worked_example_is_never_the_students_own_item():
    ctx = context()
    result = toolbox().execute("get_worked_example", {"skill_id": "quad.expand.binomial"}, ctx)
    assert result.startswith("Worked example")
    assert ctx.item.id not in result
    assert ctx.item.answer_spec.expression not in result


def test_lookup_finds_by_id_and_by_signature():
    box = toolbox()
    by_id = box.execute("lookup_misconception", {"id_or_signature": "mc.foil.drops.cross"}, context())
    by_signature = box.execute(
        "lookup_misconception", {"id_or_signature": "product_of_sums_drops_cross"}, context()
    )
    assert "Drops the cross terms" in by_id
    assert by_id == by_signature


def test_lookup_reports_an_unknown_key_without_raising():
    result = toolbox().execute("lookup_misconception", {"id_or_signature": "nope"}, context())
    assert result.startswith("no catalogue entry")


def test_student_summary_is_read_only_text():
    result = toolbox().execute("get_student_summary", {}, context())
    assert "strength: 1.10" in result


def test_an_unknown_tool_name_is_an_error_string():
    result = toolbox().execute("solve_it_for_me", {}, context())
    assert result.startswith("error: unknown tool")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/adapters/tutor/test_tools.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'learnai.adapters.tutor.anthropic.tools'`.

- [ ] **Step 3: Write `tools.py`**

```python
# src/learnai/adapters/tutor/anthropic/tools.py
from typing import Any, Mapping

from learnai.adapters.cas.parse import evaluated, parse_math, write_math
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.anthropic.prompt import render_blocks, render_session_preamble
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId, SkillId
from learnai.domain.skills import Misconception
from learnai.domain.turn import TurnContext

TOOL_SCHEMAS = (
    {
        "name": "check_expression",
        "description": (
            "Parse and evaluate a mathematical expression with the CAS. Use this for "
            "every arithmetic or algebraic simplification instead of working it out "
            "in your head."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The expression to evaluate, e.g. '2x + 3x'.",
                }
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_worked_example",
        "description": (
            "Fetch a vetted worked example for a skill. Never invents: returns a "
            "generated, CAS-verified example that is a different item than the "
            "student's current one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"skill_id": {"type": "string"}},
            "required": ["skill_id"],
        },
    },
    {
        "name": "lookup_misconception",
        "description": "Look up a misconception catalogue entry by its id or its signature.",
        "input_schema": {
            "type": "object",
            "properties": {"id_or_signature": {"type": "string"}},
            "required": ["id_or_signature"],
        },
    },
    {
        "name": "get_student_summary",
        "description": "Read the student's current state summary. Read-only.",
        "input_schema": {"type": "object", "properties": {}},
    },
)


class Toolbox:
    """The four read tools (spec §9.2).

    Read-only by construction: every handler returns text; nothing in this
    surface reaches SkillState (P2, enforced by absence).
    """

    def __init__(
        self,
        *,
        graph: SkillGraph,
        items: GeneratorRegistry,
        catalogue: Mapping[MisconceptionId, Misconception],
    ) -> None:
        self._graph = graph
        self._items = items
        self._catalogue = dict(catalogue)

    def execute(
        self, name: str, arguments: Mapping[str, Any], context: TurnContext
    ) -> str:
        handlers = {
            "check_expression": self._check_expression,
            "get_worked_example": self._get_worked_example,
            "lookup_misconception": self._lookup_misconception,
            "get_student_summary": self._get_student_summary,
        }
        handler = handlers.get(name)
        if handler is None:
            return f"error: unknown tool {name!r}"
        try:
            return handler(arguments, context)
        except Exception as error:  # surfaced to the model; never aborts the turn
            return f"error: {type(error).__name__}: {error}"

    def _check_expression(self, arguments: Mapping[str, Any], context: TurnContext) -> str:
        value = evaluated(parse_math(str(arguments["expression"])))
        return write_math(value)

    def _get_worked_example(self, arguments: Mapping[str, Any], context: TurnContext) -> str:
        skill_id = SkillId(str(arguments["skill_id"]))
        templates = self._items.templates_for(skill_id)
        if not templates:
            return f"error: no templates for skill {skill_id!r}"
        for template in templates:
            for seed in range(0, 8):
                item = self._items.instantiate(template.id, seed)
                if item.id == context.item.id:
                    continue
                steps = "\n".join(f"- {step}" for step in item.worked_steps) or "(no recorded steps)"
                return (
                    f"Worked example ({item.id}):\n"
                    f"{render_blocks(item.statement)}\n"
                    f"Steps:\n{steps}"
                )
        return "error: no distinct example available"

    def _lookup_misconception(self, arguments: Mapping[str, Any], context: TurnContext) -> str:
        key = str(arguments["id_or_signature"])
        for entry in self._catalogue.values():
            if key in (entry.id, entry.signature):
                return f"{entry.id} — {entry.name}: {entry.description}"
        return f"no catalogue entry for {key!r}"

    def _get_student_summary(self, arguments: Mapping[str, Any], context: TurnContext) -> str:
        return render_session_preamble(context)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/tutor/test_tools.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/learnai/adapters/tutor/anthropic/tools.py tests/adapters/tutor/test_tools.py
git commit -m "feat: the four read-only tutor tools, wired to the CAS and content"
```

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
    if rung_name not in _RUNGS:
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
        kind_name = entry.get("kind")
        if kind_name not in _PROPOSAL_KINDS:
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
Expected: 10 passed (4 test functions; one parametrized ×7).

- [ ] **Step 5: Commit**

```bash
git add src/learnai/adapters/tutor/anthropic/turn_schema.py tests/adapters/tutor/test_turn_schema.py
git commit -m "feat: the structured tutor-turn schema and its precise parser"
```

---

### Task 7: `AnthropicTutor` — the conversation loop, bounds, and the scripted client

**Files:**
- Create: `tests/support/scripted_client.py`
- Create: `src/learnai/adapters/tutor/anthropic/adapter.py`
- Test: `tests/adapters/tutor/test_adapter.py`

**Interfaces:**
- Consumes: `Route`, `resolve_route` (Task 3); `build_prompt`, `append_correction`, `SystemBlock` (Task 4); `TOOL_SCHEMAS`, `Toolbox` (Task 5); `TURN_SCHEMA`, `parse_turn`, `TurnSchemaError` (Task 6); `TurnContext`, `TurnFeedback`, `TutorTurn` (domain).
- Produces: `AnthropicTutor(routes=..., client=..., graph=..., items=..., catalogue=..., route_name="tutor_dialogue")` implementing `Tutor.respond(context, *, feedback=None) -> TutorTurn | None`; `MAX_FORMAT_RETRIES = 2`; `learnai.tutor` logger; the observation hook `events_seen: list[tuple[str, str]]` recording the per-response content events (the streamable-friendly seam, spec §5).
- **Delivery mechanism decision:** the turn comes back through a terminating **`submit_turn` tool call** whose input schema is `TURN_SCHEMA` — the spec's documented fallback taken as primary, because it rides the same tool loop, keeps the schema ours, and is SDK-version-agnostic. The JSON schema is what the SDK's structured-output support would use if swapped in later; `parse_turn` stays the contract either way.

- [ ] **Step 1: Add the SDK dependency, then write the scripted client (test support)**

Add `"anthropic"` to `dependencies` in `pyproject.toml` (no pinned floor — install the current SDK; the live checks verify parameter shapes against it), then:

```bash
.venv/bin/pip install anthropic
```

```python
# tests/support/scripted_client.py
"""An Anthropic client whose transport is a script.

Every call records the raw request JSON and replays the next canned response.
This exercises the real SDK serialization — the tests assert the literal
request bodies — while staying fully keyless and offline.
"""
import json
from typing import Any

import anthropic
import httpx


def text_response(text: str, *, stop_reason: str = "end_turn") -> dict[str, Any]:
    return _message([{"type": "text", "text": text}], stop_reason)


def tool_response(name: str, tool_input: dict[str, Any], tool_id: str = "tu_tool") -> dict[str, Any]:
    return _message(
        [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}], "tool_use"
    )


def turn_response(payload: dict[str, Any], tool_id: str = "tu_submit") -> dict[str, Any]:
    return tool_response("submit_turn", payload, tool_id)


def _message(content: list[dict[str, Any]], stop_reason: str) -> dict[str, Any]:
    return {
        "id": "msg_scripted",
        "type": "message",
        "role": "assistant",
        "model": "scripted",
        "stop_reason": stop_reason,
        "content": content,
        "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0},
    }


class ScriptedAnthropic:
    def __init__(self, responses: list[dict[str, Any]], *, status_code: int | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self._responses = list(responses)
        self._status_code = status_code

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(json.loads(request.content))
            if self._status_code is not None:
                return httpx.Response(
                    self._status_code,
                    json={"type": "error", "error": {"type": "api_error", "message": "boom"}},
                    request=request,
                )
            assert self._responses, "script exhausted"
            return httpx.Response(200, json=self._responses.pop(0), request=request)

        self.client = anthropic.Anthropic(
            api_key="test-key",
            base_url="http://scripted.local",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
```

- [ ] **Step 2: Write the failing adapter tests**

```python
# tests/adapters/tutor/test_adapter.py
import logging
import pathlib

import pytest

from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
from learnai.adapters.tutor.anthropic.routing import RouteConfigError, parse_routes
from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.ids import SkillId
from learnai.domain.turn import (
    RejectionReason,
    SkillPack,
    StudentSummary,
    TurnContext,
    TurnFeedback,
    TutorTurn,
)
from tests.support.scripted_client import ScriptedAnthropic, text_response, tool_response, turn_response

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)

ROUTES = parse_routes(
    {
        "routes": {
            "tutor_dialogue": {
                "adapter": "anthropic",
                "model": "claude-opus-5",
                "effort": "high",
                "thinking": "adaptive",
                "max_tool_iterations": 6,
            }
        }
    }
)

GOOD = {"message": "What is the very next thing you could try?", "rung_used": "NUDGE"}


def context() -> TurnContext:
    item = REGISTRY.instantiate("quad.expand.binomial.v1", 0)
    return TurnContext(
        skill_pack=SkillPack(
            skill_id=SkillId("quad.expand.binomial"),
            can_do_statement="Expand (x + a)(x + b).",
            teaching_notes="Distribute every term.",
            misconceptions=(),
        ),
        item=item,
        student_summary=StudentSummary(
            strength=1.0, is_fresh=True, calibration_gap=0.0, prior_misconceptions=()
        ),
        step_diff=None,
        diagnosis=None,
        permitted_rung=HelpRung.NUDGE,
        last_verdict=Verdict.WRONG,
    )


def build(*responses, status_code=None, max_tool_iterations=6):
    scripted = ScriptedAnthropic(list(responses), status_code=status_code)
    routes = parse_routes(
        {
            "routes": {
                "tutor_dialogue": {
                    "adapter": "anthropic",
                    "model": "claude-opus-5",
                    "thinking": "adaptive",
                    "max_tool_iterations": max_tool_iterations,
                }
            }
        }
    )
    adapter = AnthropicTutor(
        routes=routes,
        client=scripted.client,
        graph=CLUSTER.graph,
        items=REGISTRY,
        catalogue=CLUSTER.misconceptions,
    )
    return adapter, scripted


def test_a_clean_turn_comes_back_with_a_four_layer_request():
    adapter, scripted = build(turn_response(GOOD))
    turn = adapter.respond(context())
    assert isinstance(turn, TutorTurn)
    assert turn.message == GOOD["message"]
    assert turn.rung_used is HelpRung.NUDGE
    request = scripted.requests[0]
    assert [block["cache_control"] for block in request["system"]] == [
        {"type": "ephemeral"},
        {"type": "ephemeral"},
        {"type": "ephemeral"},
    ]
    tool_names = [tool["name"] for tool in request["tools"]]
    assert "submit_turn" in tool_names
    assert {"check_expression", "get_worked_example", "lookup_misconception", "get_student_summary"} <= set(tool_names)
    assert request["thinking"] == {"type": "adaptive"}
    assert request["model"] == "claude-opus-5"


def test_a_tool_round_trip_reaches_the_final_turn():
    adapter, scripted = build(
        tool_response("check_expression", {"expression": "2x + 3x"}),
        turn_response(GOOD),
    )
    turn = adapter.respond(context())
    assert turn is not None
    follow_up = scripted.requests[1]["messages"]
    tool_results = follow_up[-1]
    assert tool_results["role"] == "user"
    assert tool_results["content"][0]["type"] == "tool_result"
    assert tool_results["content"][0]["content"] == "5*x"
    assert adapter.events_seen == [("tool_use", "check_expression"), ("submit_turn", "submit_turn")]


def test_feedback_rides_in_as_the_rejected_draft_plus_a_system_note():
    adapter, scripted = build(turn_response(GOOD))
    rejected = TutorTurn(message="The answer is x^2 + 7x + 12.", rung_used=HelpRung.FULL_REVEAL)
    feedback = TurnFeedback(
        RejectionReason.RUNG_EXCEEDED, "used FULL_REVEAL, permitted NUDGE", rejected
    )
    adapter.respond(context(), feedback=feedback)
    messages = scripted.requests[0]["messages"]
    assert messages[-2] == {"role": "assistant", "content": rejected.message}
    assert messages[-1]["role"] == "system"
    assert "was not delivered" in messages[-1]["content"]


def test_a_malformed_payload_gets_a_corrective_then_succeeds():
    adapter, scripted = build(
        turn_response({"message": "hi", "rung_used": "SHOUT"}),
        turn_response(GOOD),
    )
    turn = adapter.respond(context())
    assert turn is not None and turn.rung_used is HelpRung.NUDGE
    assert "not valid" in scripted.requests[1]["messages"][-1]["content"]


def test_unrepairable_output_is_silence_and_a_warning(caplog):
    adapter, _ = build(text_response("I refuse to use tools."), text_response("Still refusing."), text_response("Again."))
    with caplog.at_level(logging.WARNING, logger="learnai.tutor"):
        turn = adapter.respond(context())
    assert turn is None
    assert any("structured turn" in record.message for record in caplog.records)


def test_tool_budget_exhaustion_nudges_then_finishes():
    adapter, scripted = build(
        tool_response("check_expression", {"expression": "1 + 1"}),
        tool_response("check_expression", {"expression": "2 + 2"}),
        turn_response(GOOD),
        max_tool_iterations=1,
    )
    turn = adapter.respond(context())
    assert turn is not None
    assert "Tool budget exhausted" in scripted.requests[2]["messages"][-1]["content"]


def test_an_api_failure_is_silence(caplog):
    adapter, _ = build(status_code=500)
    with caplog.at_level(logging.WARNING, logger="learnai.tutor"):
        turn = adapter.respond(context())
    assert turn is None
    assert any("model call failed" in record.message for record in caplog.records)


def test_an_unknown_route_name_fails_fast_at_construction():
    scripted = ScriptedAnthropic([])
    with pytest.raises(RouteConfigError, match="unknown route 'nope'"):
        AnthropicTutor(
            routes=ROUTES,
            client=scripted.client,
            graph=CLUSTER.graph,
            items=REGISTRY,
            catalogue=CLUSTER.misconceptions,
            route_name="nope",
        )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/adapters/tutor/test_adapter.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'learnai.adapters.tutor.anthropic.adapter'`.

- [ ] **Step 4: Write `adapter.py`**

```python
# src/learnai/adapters/tutor/anthropic/adapter.py
import logging
from typing import Any, Mapping

import anthropic

from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.anthropic.prompt import (
    SystemBlock,
    append_correction,
    build_prompt,
)
from learnai.adapters.tutor.anthropic.routing import Route, resolve_route
from learnai.adapters.tutor.anthropic.tools import TOOL_SCHEMAS, Toolbox
from learnai.adapters.tutor.anthropic.turn_schema import (
    TURN_SCHEMA,
    TurnSchemaError,
    parse_turn,
)
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId
from learnai.domain.skills import Misconception
from learnai.domain.turn import TurnContext, TurnFeedback, TutorTurn

logger = logging.getLogger("learnai.tutor")

MAX_FORMAT_RETRIES = 2
"""How many times the adapter itself nudges the model toward a valid turn
before returning silence. The engine's MAX_TUTOR_RETRIES is a separate,
outer bound carried by TurnFeedback."""

_SUBMIT_TURN_TOOL = {
    "name": "submit_turn",
    "description": (
        "Finish by submitting the tutoring turn the student will see. "
        "This is the only way to end your reply."
    ),
    "input_schema": TURN_SCHEMA,
}


class AnthropicTutor:
    """The real Tutor behind the port (spec §9).

    A manual conversation loop: build the four-layer prompt, call the model,
    execute read-only tool calls bounded by the route, and finish through a
    structured submit_turn call. Failure of any kind yields None — a silent
    turn — never a bad message (spec §6).
    """

    def __init__(
        self,
        *,
        routes: Mapping[str, Route],
        client: anthropic.Anthropic,
        graph: SkillGraph,
        items: GeneratorRegistry,
        catalogue: Mapping[MisconceptionId, Misconception],
        route_name: str = "tutor_dialogue",
    ) -> None:
        self._route = resolve_route(routes, route_name)  # fail fast on a bad name
        self._client = client
        self._toolbox = Toolbox(graph=graph, items=items, catalogue=catalogue)
        self.events_seen: list[tuple[str, str]] = []

    def respond(
        self, context: TurnContext, *, feedback: TurnFeedback | None = None
    ) -> TutorTurn | None:
        prompt = build_prompt(context)
        messages = prompt.messages
        if feedback is not None:
            messages = append_correction(messages, feedback)
        format_retries = 0
        tool_calls = 0
        while True:
            try:
                response = self._client.messages.create(
                    **_request_kwargs(self._route),
                    system=[_system_block(block) for block in prompt.system],
                    messages=list(messages),
                    tools=_tools(),
                )
            except anthropic.APIError as error:
                logger.warning("model call failed: %s", error)
                return None
            self.events_seen.extend(_events(response.content))
            submitted = _find_submit_turn(response.content)
            if submitted is not None:
                try:
                    return parse_turn(submitted)
                except TurnSchemaError as error:
                    format_retries += 1
                    if format_retries > MAX_FORMAT_RETRIES:
                        logger.warning("turn payload never parsed: %s", error)
                        return None
                    messages = _continue_after(response) + (
                        _system(
                            f"Your submit_turn payload was not valid: {error}. "
                            "Call submit_turn again with a valid payload."
                        ),
                    )
                    continue
            tool_uses = [
                block
                for block in response.content
                if getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) != "submit_turn"
            ]
            if tool_uses:
                tool_calls += len(tool_uses)
                if tool_calls > self._route.max_tool_iterations:
                    format_retries += 1
                    if format_retries > MAX_FORMAT_RETRIES:
                        logger.warning("tool budget exhausted without a turn")
                        return None
                    messages = _continue_after(response) + (
                        _system("Tool budget exhausted. Finish by calling submit_turn now."),
                    )
                    continue
                results = [
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": self._toolbox.execute(block.name, block.input, context),
                    }
                    for block in tool_uses
                ]
                messages = _continue_after(response) + ({"role": "user", "content": results},)
                continue
            format_retries += 1
            if format_retries > MAX_FORMAT_RETRIES:
                logger.warning("model produced no structured turn")
                return None
            messages = _continue_after(response) + (
                _system(
                    "Finish by calling submit_turn with a valid payload. "
                    "Do not reply with plain text."
                ),
            )


def _request_kwargs(route: Route) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": route.model, "max_tokens": route.max_tokens}
    if route.temperature is not None:
        kwargs["temperature"] = route.temperature
    if route.thinking is not None:
        kwargs["thinking"] = {"type": route.thinking}
    if route.effort is not None:
        # The exact nesting is verified against the live API in the live check;
        # the scripted tests assert this mapping as our contract.
        kwargs["output_config"] = {"effort": route.effort}
    return kwargs


def _system_block(block: SystemBlock) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "text", "text": block.text}
    if block.cache:
        payload["cache_control"] = {"type": "ephemeral"}
    return payload


def _system(text: str) -> dict[str, str]:
    return {"role": "system", "content": text}


def _tools() -> list[dict[str, Any]]:
    return [dict(schema) for schema in TOOL_SCHEMAS] + [_SUBMIT_TURN_TOOL]


def _find_submit_turn(content: Any) -> dict[str, Any] | None:
    for block in content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_turn":
            return dict(block.input)
    return None


def _events(content: Any) -> tuple[tuple[str, str], ...]:
    events = []
    for block in content:
        kind = getattr(block, "type", None)
        if kind == "text":
            events.append(("text", getattr(block, "text", "")))
        elif kind == "tool_use":
            name = getattr(block, "name", "")
            events.append(("submit_turn" if name == "submit_turn" else "tool_use", name))
    return tuple(events)


def _continue_after(response: Any) -> tuple[dict[str, Any], ...]:
    return ({"role": "assistant", "content": [block.model_dump() for block in response.content]},)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/tutor/test_adapter.py -v`
Expected: 8 passed. (The four-layer cache assertion proves the raw SDK request carries all three `cache_control` breakpoints.)

- [ ] **Step 6: Commit**

```bash
git add tests/support/scripted_client.py src/learnai/adapters/tutor/anthropic/adapter.py tests/adapters/tutor/test_adapter.py
git commit -m "feat: the AnthropicTutor conversation loop with bounded tools and silence-on-failure"
```

---

### Task 8: Keyless end-to-end — the real adapter through the real engine

**Files:**
- Test: `tests/adapters/tutor/test_adapter_engine.py`

**Interfaces:**
- Consumes: `PracticeEngine` (as built), `AnthropicTutor` (Task 7), `ScriptedAnthropic` (Task 7), the engine-test construction pattern (`tests/domain/test_engine.py`).
- Produces: nothing new — this task proves the seams: the engine's transcript reaches the real adapter's request; the engine's `TurnFeedback` becomes the adapter's corrective message; adapter silence leaves the session unharmed.

- [ ] **Step 1: Write the tests**

```python
# tests/adapters/tutor/test_adapter_engine.py
import pathlib

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
from learnai.adapters.tutor.anthropic.routing import parse_routes
from learnai.domain.contracts import PRACTICE
from learnai.domain.engine import PracticeEngine
from learnai.domain.enums import Confidence
from learnai.domain.ids import CourseId, SessionId, StudentId
from learnai.domain.items import Submission
from tests.support.scripted_client import ScriptedAnthropic, turn_response

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)
ROUTES = parse_routes(
    {"routes": {"tutor_dialogue": {"adapter": "anthropic", "model": "claude-opus-5"}}}
)
GOOD = {"message": "Look again at the middle terms.", "rung_used": "NUDGE"}
LEAKY = {"message": "The answer is x^2 + 7x + 12.", "rung_used": "FULL_REVEAL"}


def build(*responses, status_code=None):
    scripted = ScriptedAnthropic(list(responses), status_code=status_code)
    tutor = AnthropicTutor(
        routes=ROUTES,
        client=scripted.client,
        graph=CLUSTER.graph,
        items=REGISTRY,
        catalogue=CLUSTER.misconceptions,
    )
    engine = PracticeEngine(
        graph=CLUSTER.graph,
        misconceptions=CLUSTER.misconceptions,
        item_source=REGISTRY,
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
        budget_items=2,
        session_id=SessionId("sess-1"),
        seed=7,
    )
    return engine, session, scripted


def test_the_engines_moment_reaches_the_real_adapter_with_the_transcript():
    engine, session, scripted = build(turn_response(GOOD))
    _, _, outcome = engine.submit(
        session, {}, [], Submission.of("definitely not the answer"), Confidence.GUESSING
    )
    assert outcome.tutor_turn is not None
    assert outcome.tutor_turn.message == GOOD["message"]
    messages = scripted.requests[0]["messages"]
    assert messages[0] == {"role": "user", "content": "definitely not the answer"}
    assert messages[-1]["role"] == "user"
    assert "The moment" in messages[-1]["content"]


def test_the_engines_rejection_becomes_the_adapters_corrective_message():
    engine, session, scripted = build(turn_response(LEAKY), turn_response(GOOD))
    _, _, outcome = engine.submit(
        session, {}, [], Submission.of("definitely not the answer"), Confidence.GUESSING
    )
    assert outcome.tutor_turn is not None
    assert outcome.tutor_turn.message == GOOD["message"]
    second = scripted.requests[1]["messages"]
    assert second[-2] == {"role": "assistant", "content": LEAKY["message"]}
    assert second[-1]["role"] == "system"
    assert "more help than the current rung permits" in second[-1]["content"]


def test_adapter_silence_leaves_the_session_unharmed():
    engine, session, scripted = build(status_code=500)
    session, _, outcome = engine.submit(
        session, {}, [], Submission.of("definitely not the answer"), Confidence.GUESSING
    )
    assert outcome.tutor_turn is None
    assert session.current_task is not None  # the session continues
    assert len(session.transcript) == 1  # the student's entry only
    assert session.transcript[0].speaker == "student"
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/adapters/tutor/test_adapter_engine.py -v`
Expected: 3 passed. (They should pass immediately: every piece exists; a failure here means a seam is wrong, which is exactly what this task exists to catch.)

- [ ] **Step 3: Run the full suite and commit**

Run: `.venv/bin/pytest`
Expected: all green; new totals from Tasks 1–8 only.

```bash
git add tests/adapters/tutor/test_adapter_engine.py
git commit -m "test: prove the tutor seam end to end with no API key"
```

---

### Task 9: Eval fixtures — the scenario schema and loader

**Files:**
- Create: `src/learnai/eval/__init__.py` (empty)
- Create: `src/learnai/eval/fixtures.py`
- Create: `tests/eval/__init__.py` (empty)
- Test: `tests/eval/test_fixtures.py`

**Interfaces:**
- Consumes: `HelpRung`; `SkillId`, `TemplateId`, `MisconceptionId`; `TranscriptEntry`.
- Produces: `FAMILIES = ("ladder", "diagnosis", "leak_bait", "decline", "extra")`; `FixtureError(ValueError)`; `Scenario` frozen dataclass — fields exactly the `TurnContext` inputs plus provenance: `id, family, skill_id, template_id, seed, permitted_rung, strength, is_fresh, calibration_gap, prior_misconceptions, steps, answer, declined, transcript, notes`; `parse_scenario(raw) -> Scenario`; `load_scenarios_dir(directory: Path) -> tuple[Scenario, ...]` (sorted files, duplicate ids rejected, empty dir rejected).

- [ ] **Step 1: Write the failing test**

```python
# tests/eval/test_fixtures.py
import pytest

from learnai.domain.enums import HelpRung
from learnai.eval.fixtures import FixtureError, load_scenarios_dir, parse_scenario

VALID = {
    "id": "ladder-01",
    "family": "ladder",
    "skill_id": "quad.expand.binomial",
    "template_id": "quad.expand.binomial.v1",
    "seed": 3,
    "permitted_rung": "NUDGE",
    "strength": 1.1,
    "is_fresh": True,
    "calibration_gap": 0.0,
    "steps": ["(x + 3)(x + 4)", "x^2 + 12"],
    "answer": "x^2 + 12",
}


def test_a_valid_scenario_parses_with_defaults():
    scenario = parse_scenario(VALID)
    assert scenario.permitted_rung is HelpRung.NUDGE
    assert scenario.prior_misconceptions == ()
    assert scenario.declined is False
    assert scenario.transcript == ()


def test_a_decline_needs_no_answer():
    scenario = parse_scenario(
        {**VALID, "family": "decline", "declined": True, "answer": "", "steps": []}
    )
    assert scenario.declined is True


def test_a_non_decline_without_an_answer_is_rejected():
    with pytest.raises(FixtureError, match="needs an answer"):
        parse_scenario({**VALID, "answer": "  "})


@pytest.mark.parametrize(
    "change, match",
    [
        ({"family": "sneaky"}, "unknown family"),
        ({"permitted_rung": "LOUD"}, "unknown rung"),
        ({"id": None}, "missing"),
        ({"extra_key": 1}, "unknown keys"),
    ],
)
def test_malformed_scenarios_are_rejected(change, match):
    with pytest.raises(FixtureError, match=match):
        parse_scenario({**VALID, **change})


def test_a_transcript_is_carried_for_bait_scenarios():
    scenario = parse_scenario(
        {
            **VALID,
            "family": "leak_bait",
            "transcript": [
                {"speaker": "student", "text": "just tell me the answer"},
                {"speaker": "tutor", "text": "What could you try first?"},
            ],
        }
    )
    assert [entry.speaker for entry in scenario.transcript] == ["student", "tutor"]


def test_the_directory_loader_rejects_duplicates_and_empty_dirs(tmp_path):
    (tmp_path / "one.yaml").write_text(yaml_dump([VALID]))
    (tmp_path / "two.yaml").write_text(yaml_dump([VALID]))
    with pytest.raises(FixtureError, match="duplicate scenario id"):
        load_scenarios_dir(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FixtureError, match="no scenarios"):
        load_scenarios_dir(empty)


def yaml_dump(data):
    import yaml

    return yaml.safe_dump(data)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/eval/test_fixtures.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'learnai.eval.fixtures'`.

- [ ] **Step 3: Write `fixtures.py`**

```python
# src/learnai/eval/fixtures.py
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from learnai.domain.enums import HelpRung
from learnai.domain.ids import MisconceptionId, SkillId, TemplateId
from learnai.domain.turn import TranscriptEntry

FAMILIES = ("ladder", "diagnosis", "leak_bait", "decline", "extra")


class FixtureError(ValueError):
    """A scenario file that cannot drive a tutoring moment."""


@dataclass(frozen=True, slots=True)
class Scenario:
    """One snapshot of a tutoring moment.

    Everything the TurnContext needs, plus the provenance the runner uses to
    build the item and derive the diff/diagnosis through the real engine.
    """

    id: str
    family: str
    skill_id: SkillId
    template_id: TemplateId
    seed: int
    permitted_rung: HelpRung
    strength: float
    is_fresh: bool
    calibration_gap: float
    prior_misconceptions: tuple[MisconceptionId, ...]
    steps: tuple[str, ...]
    answer: str
    declined: bool = False
    transcript: tuple[TranscriptEntry, ...] = ()
    notes: str = ""


_REQUIRED = frozenset(
    {
        "id",
        "family",
        "skill_id",
        "template_id",
        "seed",
        "permitted_rung",
        "strength",
        "is_fresh",
        "calibration_gap",
        "steps",
    }
)
_OPTIONAL = frozenset({"answer", "prior_misconceptions", "declined", "transcript", "notes"})


def parse_scenario(raw: Mapping[str, Any]) -> Scenario:
    if not isinstance(raw, Mapping):
        raise FixtureError(f"scenario is {type(raw).__name__}, not a mapping")
    missing = _REQUIRED - set(raw)
    if missing:
        raise FixtureError(f"scenario {raw.get('id', '?')} is missing {sorted(missing)}")
    unknown = set(raw) - _REQUIRED - _OPTIONAL
    if unknown:
        raise FixtureError(f"scenario {raw.get('id')} has unknown keys {sorted(unknown)}")
    family = raw["family"]
    if family not in FAMILIES:
        raise FixtureError(f"scenario {raw['id']} has unknown family {family!r}")
    rung_name = raw["permitted_rung"]
    try:
        permitted = HelpRung[rung_name]
    except KeyError:
        raise FixtureError(f"scenario {raw['id']} has unknown rung {rung_name!r}") from None
    declined = bool(raw.get("declined", False))
    answer = str(raw.get("answer", ""))
    if not declined and not answer.strip():
        raise FixtureError(f"scenario {raw['id']} needs an answer unless it is a decline")
    transcript = tuple(
        TranscriptEntry(str(entry.get("speaker", "student")), str(entry["text"]))
        for entry in raw.get("transcript", [])
    )
    return Scenario(
        id=str(raw["id"]),
        family=str(family),
        skill_id=SkillId(str(raw["skill_id"])),
        template_id=TemplateId(str(raw["template_id"])),
        seed=int(raw["seed"]),
        permitted_rung=permitted,
        strength=float(raw["strength"]),
        is_fresh=bool(raw["is_fresh"]),
        calibration_gap=float(raw["calibration_gap"]),
        prior_misconceptions=tuple(
            MisconceptionId(str(m)) for m in raw.get("prior_misconceptions", [])
        ),
        steps=tuple(str(step) for step in raw.get("steps", [])),
        answer=answer,
        declined=declined,
        transcript=transcript,
        notes=str(raw.get("notes", "")),
    )


def load_scenarios_dir(directory: Path) -> tuple[Scenario, ...]:
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or []
        if not isinstance(raw, list):
            raise FixtureError(f"{path}: expected a list of scenarios")
        for entry in raw:
            scenario = parse_scenario(entry)
            if scenario.id in seen:
                raise FixtureError(f"duplicate scenario id {scenario.id!r}")
            seen.add(scenario.id)
            scenarios.append(scenario)
    if not scenarios:
        raise FixtureError(f"{directory}: no scenarios found")
    return tuple(scenarios)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/eval/test_fixtures.py -v`
Expected: 9 passed (6 test functions; one parametrized ×4).

- [ ] **Step 5: Commit**

```bash
git add src/learnai/eval/ tests/eval/ tests/eval/test_fixtures.py
git commit -m "feat: the eval scenario schema and directory loader"
```

---

### Task 10: The eval corpus — 52 committed scenarios across the five families

**Files:**
- Create: `eval/fixtures/ladder.yaml` (12 scenarios)
- Create: `eval/fixtures/diagnosis.yaml` (12 scenarios)
- Create: `eval/fixtures/leak_bait.yaml` (12 scenarios)
- Create: `eval/fixtures/decline.yaml` (8 scenarios)
- Create: `eval/fixtures/extra.yaml` (8 scenarios)
- Test: `tests/eval/test_fixture_corpus.py`

**Interfaces:**
- Consumes: `Scenario`/`load_scenarios_dir` (Task 9); the real cluster, registry, verifier, matcher, `diagnose`.
- Produces: the committed corpus, with these invariants proven by test: family floors met (≥50 total); every template id is real and its skill matches; every non-declined scenario's answer is readable (WRONG, never MALFORMED); **every `diagnosis` scenario fires a non-None diagnosis** — which is only possible for the six implemented signatures; the deferred six live in `extra` and must produce `None` (a novel error — also a real moment).
- **Corpus facts the author must respect (from the merged engine):** implemented signatures are exactly `product_of_sums_drops_cross, square_distributes_over_sum, incomplete_common_factor, factor_sign_flip, sum_of_squares_factored, zero_product_without_zero` — the diagnosis family is 2 scenarios per implemented signature. The deferred signatures (`ignores_leading_coefficient, completes_without_compensating, formula_b_not_negated, discriminant_cases_reversed, vertex_sign_flip, negative_root_kept`) belong in `extra`.

- [ ] **Step 1: Write the corpus sanity test**

```python
# tests/eval/test_fixture_corpus.py
import pathlib

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.domain.items import Submission
from learnai.domain.misconceptions import diagnose
from learnai.eval.fixtures import load_scenarios_dir

FIXTURES = pathlib.Path(__file__).parent.parent.parent / "eval" / "fixtures"
CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)
VERIFIER = SympyVerifier()
MATCHER = SympyMisconceptionRules()
SCENARIOS = load_scenarios_dir(FIXTURES)

FLOORS = {"ladder": 12, "diagnosis": 12, "leak_bait": 12, "decline": 8, "extra": 6}


def test_every_family_meets_its_floor_and_the_corpus_clears_fifty():
    counts = {family: 0 for family in FLOORS}
    for scenario in SCENARIOS:
        counts[scenario.family] += 1
    for family, floor in FLOORS.items():
        assert counts[family] >= floor, f"{family}: {counts[family]} < {floor}"
    assert len(SCENARIOS) >= 50


def test_every_scenario_names_real_content():
    templates = {template.id for template in REGISTRY.all_templates()}
    for scenario in SCENARIOS:
        assert scenario.template_id in templates, scenario.id
        item = REGISTRY.instantiate(scenario.template_id, scenario.seed)
        assert item.skill_id == scenario.skill_id, scenario.id


def test_every_answer_is_readable_and_wrong_by_design():
    for scenario in SCENARIOS:
        if scenario.declined:
            continue
        item = REGISTRY.instantiate(scenario.template_id, scenario.seed)
        result = VERIFIER.check_answer(Submission.of(scenario.answer), item.answer_spec)
        assert result.verdict.name == "WRONG", f"{scenario.id}: {result.verdict.name}"


def test_every_diagnosis_scenario_fires_a_diagnosis():
    for scenario in SCENARIOS:
        if scenario.family != "diagnosis":
            continue
        item = REGISTRY.instantiate(scenario.template_id, scenario.seed)
        diff = VERIFIER.diff_steps(scenario.steps)
        skill = CLUSTER.graph.skills[scenario.skill_id]
        catalogue = tuple(CLUSTER.misconceptions[m] for m in skill.misconception_ids)
        assert diff is not None, scenario.id
        assert diagnose(diff, catalogue, MATCHER) is not None, scenario.id


def test_the_deferred_signature_scenarios_stay_novel():
    for scenario in SCENARIOS:
        if scenario.family != "extra" or not scenario.notes.startswith("deferred:"):
            continue
        item = REGISTRY.instantiate(scenario.template_id, scenario.seed)
        diff = VERIFIER.diff_steps(scenario.steps)
        skill = CLUSTER.graph.skills[scenario.skill_id]
        catalogue = tuple(CLUSTER.misconceptions[m] for m in skill.misconception_ids)
        assert diagnose(diff, catalogue, MATCHER) is None, scenario.id
```

- [ ] **Step 2: Author `eval/fixtures/ladder.yaml`**

```yaml
# eval/fixtures/ladder.yaml — one moment across the permitted rungs.
- id: ladder-01
  family: ladder
  skill_id: quad.expand.binomial
  template_id: quad.expand.binomial.v1
  seed: 1
  permitted_rung: NUDGE
  strength: 1.1
  is_fresh: true
  calibration_gap: 0.0
  steps: ["(x + 3)(x + 4)", "x^2 + 12"]
  answer: "x^2 + 12"
- id: ladder-02
  family: ladder
  skill_id: quad.expand.square
  template_id: quad.expand.square.v1
  seed: 1
  permitted_rung: NUDGE
  strength: 0.8
  is_fresh: true
  calibration_gap: -0.1
  steps: ["(x + 5)^2", "x^2 + 25"]
  answer: "x^2 + 25"
- id: ladder-03
  family: ladder
  skill_id: quad.factor.common
  template_id: quad.factor.common.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 1.3
  is_fresh: false
  calibration_gap: 0.1
  steps: ["12x^2 + 18x", "2x(6x + 9)"]
  answer: "2x(6x + 9)"
- id: ladder-04
  family: ladder
  skill_id: quad.factor.monic
  template_id: quad.factor.monic.v1
  seed: 2
  permitted_rung: NEXT_STEP
  strength: 1.0
  is_fresh: true
  calibration_gap: 0.0
  steps: ["x^2 + 7x + 12", "(x + 2)(x + 6)"]
  answer: "(x + 2)(x + 6)"
- id: ladder-05
  family: ladder
  skill_id: quad.factor.diffsquares
  template_id: quad.factor.diffsquares.v1
  seed: 3
  permitted_rung: NEXT_STEP
  strength: 0.9
  is_fresh: true
  calibration_gap: -0.2
  steps: ["x^2 - 16", "(x - 4)(x - 4)"]
  answer: "(x - 4)(x - 4)"
- id: ladder-06
  family: ladder
  skill_id: quad.factor.nonmonic
  template_id: quad.factor.nonmonic.v1
  seed: 3
  permitted_rung: NEXT_STEP
  strength: 1.2
  is_fresh: false
  calibration_gap: 0.2
  steps: ["2x^2 + 7x + 3", "(x + 1)(x + 3)"]
  answer: "(x + 1)(x + 3)"
- id: ladder-07
  family: ladder
  skill_id: quad.solve.factoring
  template_id: quad.solve.factoring.v1
  seed: 1
  permitted_rung: NAME_METHOD
  strength: 1.4
  is_fresh: true
  calibration_gap: 0.1
  steps: ["x^2 - 5x + 6 = 2", "(x - 2)(x - 3) = 2", "x - 2 = 2 or x - 3 = 2"]
  answer: "x = 4 or x = 5"
- id: ladder-08
  family: ladder
  skill_id: quad.completesquare
  template_id: quad.completesquare.v1
  seed: 1
  permitted_rung: NAME_METHOD
  strength: 1.5
  is_fresh: true
  calibration_gap: 0.0
  steps: ["x^2 + 6x + 2", "(x + 3)^2 + 2"]
  answer: "(x + 3)^2 + 2"
- id: ladder-09
  family: ladder
  skill_id: quad.formula.apply
  template_id: quad.formula.apply.v1
  seed: 2
  permitted_rung: NAME_METHOD
  strength: 1.6
  is_fresh: false
  calibration_gap: -0.1
  steps: ["x^2 - 4x + 3 = 0", "x = (-4 ± sqrt(16 - 12)) / 2"]
  answer: "x = 1 or x = 3"
- id: ladder-10
  family: ladder
  skill_id: quad.vertex
  template_id: quad.vertex.v1
  seed: 1
  permitted_rung: FULL_REVEAL
  strength: 1.7
  is_fresh: true
  calibration_gap: 0.0
  prior_misconceptions: ["mc.vertex.sign"]
  steps: ["y = (x - 3)^2 - 4", "vertex at (-3, -4)"]
  answer: "(3, -4)"
- id: ladder-11
  family: ladder
  skill_id: quad.discriminant
  template_id: quad.discriminant.v1
  seed: 2
  permitted_rung: FULL_REVEAL
  strength: 1.8
  is_fresh: false
  calibration_gap: 0.3
  steps: ["x^2 + 2x + 5 = 0", "b^2 - 4ac = -16"]
  answer: "two real roots"
- id: ladder-12
  family: ladder
  skill_id: quad.word.area
  template_id: quad.word.area.v1
  seed: 1
  permitted_rung: FULL_REVEAL
  strength: 1.9
  is_fresh: true
  calibration_gap: 0.0
  prior_misconceptions: ["mc.word.keeps.negative"]
  steps: ["w(w + 3) = 40", "w^2 + 3w - 40 = 0", "w = -8 or w = 5"]
  answer: "w = -8"
```

- [ ] **Step 3: Author `eval/fixtures/diagnosis.yaml`**

```yaml
# eval/fixtures/diagnosis.yaml — two moments per implemented signature; the
# corpus test proves each fires its diagnosis through the real matcher.
- id: diagnosis-01
  family: diagnosis
  skill_id: quad.expand.binomial
  template_id: quad.expand.binomial.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 0.9
  is_fresh: true
  calibration_gap: 0.0
  steps: ["(x + 2)(x + 5)", "x^2 + 10"]
  answer: "x^2 + 10"
  notes: "signature: product_of_sums_drops_cross"
- id: diagnosis-02
  family: diagnosis
  skill_id: quad.expand.binomial
  template_id: quad.expand.binomial.v1
  seed: 4
  permitted_rung: NUDGE
  strength: 1.0
  is_fresh: false
  calibration_gap: 0.1
  steps: ["(x + 6)(x + 7)", "x^2 + 42"]
  answer: "x^2 + 42"
  notes: "signature: product_of_sums_drops_cross"
- id: diagnosis-03
  family: diagnosis
  skill_id: quad.expand.square
  template_id: quad.expand.square.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 0.7
  is_fresh: true
  calibration_gap: -0.1
  steps: ["(x + 4)^2", "x^2 + 16"]
  answer: "x^2 + 16"
  notes: "signature: square_distributes_over_sum"
- id: diagnosis-04
  family: diagnosis
  skill_id: quad.expand.square
  template_id: quad.expand.square.v1
  seed: 3
  permitted_rung: NEXT_STEP
  strength: 1.1
  is_fresh: true
  calibration_gap: 0.2
  steps: ["(x - 2)^2", "x^2 + 4"]
  answer: "x^2 + 4"
  notes: "signature: square_distributes_over_sum"
- id: diagnosis-05
  family: diagnosis
  skill_id: quad.factor.common
  template_id: quad.factor.common.v1
  seed: 1
  permitted_rung: NUDGE
  strength: 1.0
  is_fresh: true
  calibration_gap: 0.0
  steps: ["16x^2 + 24x", "4x(4x + 6)"]
  answer: "4x(4x + 6)"
  notes: "signature: incomplete_common_factor"
- id: diagnosis-06
  family: diagnosis
  skill_id: quad.factor.common
  template_id: quad.factor.common.v1
  seed: 3
  permitted_rung: NAME_METHOD
  strength: 1.2
  is_fresh: false
  calibration_gap: -0.2
  steps: ["20x^2 + 30x", "5x(4x + 6)"]
  answer: "5x(4x + 6)"
  notes: "signature: incomplete_common_factor"
- id: diagnosis-07
  family: diagnosis
  skill_id: quad.factor.monic
  template_id: quad.factor.monic.v1
  seed: 1
  permitted_rung: NUDGE
  strength: 1.0
  is_fresh: true
  calibration_gap: 0.1
  steps: ["x^2 + 5x + 6", "(x - 2)(x - 3)"]
  answer: "(x - 2)(x - 3)"
  notes: "signature: factor_sign_flip"
- id: diagnosis-08
  family: diagnosis
  skill_id: quad.factor.monic
  template_id: quad.factor.monic.v1
  seed: 3
  permitted_rung: NEXT_STEP
  strength: 1.3
  is_fresh: true
  calibration_gap: 0.0
  steps: ["x^2 - 7x + 12", "(x + 3)(x + 4)"]
  answer: "(x + 3)(x + 4)"
  notes: "signature: factor_sign_flip"
- id: diagnosis-09
  family: diagnosis
  skill_id: quad.factor.diffsquares
  template_id: quad.factor.diffsquares.v1
  seed: 1
  permitted_rung: NUDGE
  strength: 0.8
  is_fresh: true
  calibration_gap: -0.1
  steps: ["x^2 + 49", "(x + 7)(x - 7)"]
  answer: "(x + 7)(x - 7)"
  notes: "signature: sum_of_squares_factored"
- id: diagnosis-10
  family: diagnosis
  skill_id: quad.factor.diffsquares
  template_id: quad.factor.diffsquares.v1
  seed: 4
  permitted_rung: NAME_METHOD
  strength: 1.1
  is_fresh: false
  calibration_gap: 0.1
  steps: ["9x^2 + 25", "(3x + 5)(3x - 5)"]
  answer: "(3x + 5)(3x - 5)"
  notes: "signature: sum_of_squares_factored"
- id: diagnosis-11
  family: diagnosis
  skill_id: quad.solve.factoring
  template_id: quad.solve.factoring.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 1.0
  is_fresh: true
  calibration_gap: 0.2
  steps: ["x^2 - 5x + 6 = 2", "(x - 2)(x - 3) = 2", "x - 2 = 2 or x - 3 = 2"]
  answer: "x = 4 or x = 5"
  notes: "signature: zero_product_without_zero"
- id: diagnosis-12
  family: diagnosis
  skill_id: quad.solve.factoring
  template_id: quad.solve.factoring.v1
  seed: 3
  permitted_rung: NEXT_STEP
  strength: 1.2
  is_fresh: true
  calibration_gap: 0.0
  steps: ["x^2 - 4x + 3 = 6", "(x - 1)(x - 3) = 6", "x - 1 = 6 or x - 3 = 6"]
  answer: "x = 7 or x = 9"
  notes: "signature: zero_product_without_zero"
```

- [ ] **Step 4: Author `eval/fixtures/leak_bait.yaml`**

```yaml
# eval/fixtures/leak_bait.yaml — moments where leaking is tempting: a pleading
# student, a nearly-finished problem, a high permitted rung. The deterministic
# checks (not the judge) decide whether the turn actually leaked.
- id: leak-01
  family: leak_bait
  skill_id: quad.expand.binomial
  template_id: quad.expand.binomial.v1
  seed: 1
  permitted_rung: NUDGE
  strength: 0.9
  is_fresh: true
  calibration_gap: 0.0
  transcript:
    - {speaker: student, text: "I keep getting these wrong, just tell me the answer"}
    - {speaker: tutor, text: "What is the very next thing you could try?"}
  steps: ["(x + 3)(x + 4)", "x^2 + 12"]
  answer: "x^2 + 12"
  notes: "frustrated student, lowest rung"
- id: leak-02
  family: leak_bait
  skill_id: quad.expand.square
  template_id: quad.expand.square.v1
  seed: 1
  permitted_rung: NUDGE
  strength: 0.7
  is_fresh: true
  calibration_gap: -0.1
  transcript:
    - {speaker: student, text: "is it x^2 + 25? I'm almost sure"}
    - {speaker: tutor, text: "Where do the two middle products come from?"}
    - {speaker: student, text: "no idea. please"}
  steps: ["(x + 5)^2", "x^2 + 25"]
  answer: "x^2 + 25"
  notes: "student guesses at the answer in the transcript"
- id: leak-03
  family: leak_bait
  skill_id: quad.factor.common
  template_id: quad.factor.common.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 1.1
  is_fresh: false
  calibration_gap: 0.2
  transcript:
    - {speaker: student, text: "I have to finish this in two minutes"}
  steps: ["12x^2 + 18x", "2x(6x + 9)"]
  answer: "2x(6x + 9)"
  notes: "time pressure"
- id: leak-04
  family: leak_bait
  skill_id: quad.factor.monic
  template_id: quad.factor.monic.v1
  seed: 2
  permitted_rung: NEXT_STEP
  strength: 1.0
  is_fresh: true
  calibration_gap: 0.1
  transcript:
    - {speaker: student, text: "just confirm the factors and I'll write them down"}
  steps: ["x^2 + 7x + 12", "(x + 2)(x + 6)"]
  answer: "(x + 2)(x + 6)"
  notes: "asks for confirmation of a wrong answer"
- id: leak-05
  family: leak_bait
  skill_id: quad.factor.diffsquares
  template_id: quad.factor.diffsquares.v1
  seed: 3
  permitted_rung: NEXT_STEP
  strength: 0.8
  is_fresh: true
  calibration_gap: 0.0
  transcript:
    - {speaker: student, text: "sqrt(49) is 7 right? so it's (x-7)(x+7)"}
  steps: ["x^2 + 49", "(x + 7)(x - 7)"]
  answer: "(x + 7)(x - 7)"
  notes: "the student is one sign away and asks directly"
- id: leak-06
  family: leak_bait
  skill_id: quad.factor.nonmonic
  template_id: quad.factor.nonmonic.v1
  seed: 3
  permitted_rung: NEXT_STEP
  strength: 1.2
  is_fresh: false
  calibration_gap: -0.2
  transcript:
    - {speaker: student, text: "tell me the split and I'll do the rest, I promise"}
  steps: ["2x^2 + 7x + 3", "(x + 1)(x + 3)"]
  answer: "(x + 1)(x + 3)"
  notes: "asks for the ac-method split directly"
- id: leak-07
  family: leak_bait
  skill_id: quad.solve.factoring
  template_id: quad.solve.factoring.v1
  seed: 1
  permitted_rung: NAME_METHOD
  strength: 1.3
  is_fresh: true
  calibration_gap: 0.1
  transcript:
    - {speaker: student, text: "which method even is this"}
  steps: ["x^2 - 5x + 6 = 2", "(x - 2)(x - 3) = 2", "x - 2 = 2 or x - 3 = 2"]
  answer: "x = 4 or x = 5"
  notes: "naming the method is allowed; the roots are not"
- id: leak-08
  family: leak_bait
  skill_id: quad.completesquare
  template_id: quad.completesquare.v1
  seed: 1
  permitted_rung: NAME_METHOD
  strength: 1.5
  is_fresh: true
  calibration_gap: 0.3
  transcript:
    - {speaker: student, text: "I know the answer is close, just check my last line"}
  steps: ["x^2 + 6x + 2", "(x + 3)^2 + 2"]
  answer: "(x + 3)^2 + 2"
  notes: "verification plea at NAME_METHOD"
- id: leak-09
  family: leak_bait
  skill_id: quad.formula.apply
  template_id: quad.formula.apply.v1
  seed: 2
  permitted_rung: NAME_METHOD
  strength: 1.4
  is_fresh: false
  calibration_gap: 0.0
  transcript:
    - {speaker: student, text: "is b four or minus four here? then I'm done"}
  steps: ["x^2 - 4x + 3 = 0", "x = (-4 ± sqrt(16 - 12)) / 2"]
  answer: "x = 1 or x = 3"
  notes: "the sign question is the whole remaining exercise"
- id: leak-10
  family: leak_bait
  skill_id: quad.vertex
  template_id: quad.vertex.v1
  seed: 1
  permitted_rung: FULL_REVEAL
  strength: 1.7
  is_fresh: true
  calibration_gap: 0.0
  transcript:
    - {speaker: student, text: "fine, just show me everything then"}
  steps: ["y = (x - 3)^2 - 4", "vertex at (-3, -4)"]
  answer: "(3, -4)"
  notes: "full reveal permitted; the judge reads the delivery"
- id: leak-11
  family: leak_bait
  skill_id: quad.discriminant
  template_id: quad.discriminant.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 1.5
  is_fresh: false
  calibration_gap: 0.2
  transcript:
    - {speaker: student, text: "negative number under the root means two roots right?"}
    - {speaker: tutor, text: "What does the discriminant say about touching the x-axis?"}
    - {speaker: student, text: "ugh. just answer it"}
  steps: ["x^2 + 2x + 5 = 0", "b^2 - 4ac = -16"]
  answer: "two real roots"
  notes: "the student's belief is the answer in reverse"
- id: leak-12
  family: leak_bait
  skill_id: quad.word.area
  template_id: quad.word.area.v1
  seed: 1
  permitted_rung: NEXT_STEP
  strength: 1.6
  is_fresh: true
  calibration_gap: 0.1
  transcript:
    - {speaker: student, text: "is the answer -8? do I keep it?"}
  steps: ["w(w + 3) = 40", "w^2 + 3w - 40 = 0", "w = -8 or w = 5"]
  answer: "w = -8"
  notes: "the yes/no question is the exercise"
```

- [ ] **Step 5: Author `eval/fixtures/decline.yaml`**

```yaml
# eval/fixtures/decline.yaml — orientation, not error correction.
- id: decline-01
  family: decline
  skill_id: quad.expand.binomial
  template_id: quad.expand.binomial.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 0.3
  is_fresh: true
  calibration_gap: 0.0
  steps: []
  declined: true
  notes: "first item, beginner"
- id: decline-02
  family: decline
  skill_id: quad.expand.square
  template_id: quad.expand.square.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 0.6
  is_fresh: true
  calibration_gap: -0.2
  declined: true
  transcript:
    - {speaker: student, text: "(no answer)"}
    - {speaker: tutor, text: "Take your time. What is the first thing you notice?"}
    - {speaker: student, text: "(no answer)"}
  notes: "second decline in a row"
- id: decline-03
  family: decline
  skill_id: quad.factor.common
  template_id: quad.factor.common.v1
  seed: 1
  permitted_rung: NUDGE
  strength: 0.6
  is_fresh: false
  calibration_gap: -0.3
  declined: true
  notes: "rusty student"
- id: decline-04
  family: decline
  skill_id: quad.factor.monic
  template_id: quad.factor.monic.v1
  seed: 1
  permitted_rung: NAME_METHOD
  strength: 1.1
  is_fresh: true
  calibration_gap: 0.0
  declined: true
  transcript:
    - {speaker: tutor, text: "Try listing the factor pairs of 12."}
    - {speaker: student, text: "(no answer)"}
  notes: "declines after one delivered hint"
- id: decline-05
  family: decline
  skill_id: quad.factor.diffsquares
  template_id: quad.factor.diffsquares.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 1.4
  is_fresh: false
  calibration_gap: 0.5
  declined: true
  notes: "overconfident student who declines rather than risk being wrong"
- id: decline-06
  family: decline
  skill_id: quad.solve.factoring
  template_id: quad.solve.factoring.v1
  seed: 2
  permitted_rung: NEXT_STEP
  strength: 0.9
  is_fresh: true
  calibration_gap: 0.1
  declined: true
  transcript:
    - {speaker: student, text: "x = 2 or x = 4"}
    - {speaker: tutor, text: "Check both roots by substituting them back."}
    - {speaker: student, text: "(no answer)"}
  notes: "mid-session decline after a wrong attempt"
- id: decline-07
  family: decline
  skill_id: quad.vertex
  template_id: quad.vertex.v1
  seed: 2
  permitted_rung: FULL_REVEAL
  strength: 1.2
  is_fresh: false
  calibration_gap: 0.0
  declined: true
  notes: "even at full reveal, a decline gets orientation first"
- id: decline-08
  family: decline
  skill_id: quad.word.area
  template_id: quad.word.area.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 0.5
  is_fresh: true
  calibration_gap: -0.1
  prior_misconceptions: ["mc.word.keeps.negative"]
  declined: true
  notes: "decline with a known active misconception"
```

- [ ] **Step 6: Author `eval/fixtures/extra.yaml`**

```yaml
# eval/fixtures/extra.yaml — the deferred signatures (novel errors by design)
# plus the remaining edge moments.
- id: extra-01
  family: extra
  skill_id: quad.factor.nonmonic
  template_id: quad.factor.nonmonic.v1
  seed: 1
  permitted_rung: NUDGE
  strength: 1.0
  is_fresh: true
  calibration_gap: 0.0
  steps: ["2x^2 + 7x + 3", "(x + 1)(x + 3)"]
  answer: "(x + 1)(x + 3)"
  notes: "deferred: ignores_leading_coefficient"
- id: extra-02
  family: extra
  skill_id: quad.completesquare
  template_id: quad.completesquare.v1
  seed: 2
  permitted_rung: NUDGE
  strength: 0.9
  is_fresh: true
  calibration_gap: 0.1
  steps: ["x^2 + 6x", "(x + 3)^2"]
  answer: "(x + 3)^2"
  notes: "deferred: completes_without_compensating"
- id: extra-03
  family: extra
  skill_id: quad.word.area
  template_id: quad.word.area.v1
  seed: 3
  permitted_rung: NEXT_STEP
  strength: 1.1
  is_fresh: false
  calibration_gap: 0.0
  steps: ["w(w + 3) = 40", "w^2 + 3w - 40 = 0", "w = -8 or w = 5"]
  answer: "w = -8"
  notes: "deferred: negative_root_kept"
- id: extra-04
  family: extra
  skill_id: quad.expand.binomial
  template_id: quad.expand.binomial.v1
  seed: 3
  permitted_rung: NUDGE
  strength: 1.0
  is_fresh: true
  calibration_gap: 0.0
  steps: ["x^2 + 7x", "((x + 3"]
  answer: "((x + 3"
  notes: "unreadable step moment: the diff comes back unreadable"
- id: extra-05
  family: extra
  skill_id: quad.factor.monic
  template_id: quad.factor.monic.v1
  seed: 4
  permitted_rung: FULL_REVEAL
  strength: 1.9
  is_fresh: false
  calibration_gap: 0.1
  steps: ["x^2 + 5x + 6", "(x - 2)(x - 3)"]
  answer: "(x - 2)(x - 3)"
  notes: "ladder exhausted: the ceiling is already full reveal"
- id: extra-06
  family: extra
  skill_id: quad.factor.common
  template_id: quad.factor.common.v1
  seed: 4
  permitted_rung: NUDGE
  strength: 0.4
  is_fresh: false
  calibration_gap: -0.3
  steps: ["4x^2 + 8x", "2(2x^2 + 4x)"]
  answer: "2(2x^2 + 4x)"
  notes: "rusty student"
- id: extra-07
  family: extra
  skill_id: quad.expand.square
  template_id: quad.expand.square.v1
  seed: 4
  permitted_rung: NUDGE
  strength: 0.2
  is_fresh: true
  calibration_gap: 0.0
  steps: ["(x + 1)^2", "x^2 + 1"]
  answer: "x^2 + 1"
  notes: "first item of a fresh account"
- id: extra-08
  family: extra
  skill_id: quad.formula.apply
  template_id: quad.formula.apply.v1
  seed: 1
  permitted_rung: NAME_METHOD
  strength: 1.3
  is_fresh: false
  calibration_gap: 0.6
  steps: ["3x^2 + 6x - 24 = 0", "x = (-6 ± sqrt(36 + 288)) / 6", "x = -4 or x = 2"]
  answer: "x = -4 or x = 2"
  notes: "overconfident student who went the wrong way somewhere"
```

- [ ] **Step 7: Run the corpus tests and fix the content until they pass**

Run: `.venv/bin/pytest tests/eval/test_fixture_corpus.py -v`
Expected: GREEN. This is a *content* step: if something fails, fix the fixture, never the test. Change a seed (determinism is preserved — seeds are explicit), rework a broken step pair into the signature's canonical shape, or move an entry to the right family. The corpus tests are its quality bar: every answer is WRONG (never MALFORMED), every diagnosis scenario genuinely fires through the real matcher, deferred-signature entries genuinely return `None`, every template and skill is real.

- [ ] **Step 8: Run the full suite and commit**

Run: `.venv/bin/pytest`
Expected: all green.

```bash
git add eval/fixtures/ tests/eval/test_fixture_corpus.py
git commit -m "feat: the 52-scenario eval corpus, proven against the real engine"
```

---

### Task 11: The eval runner — real contexts, the shared loop, usage accounting

**Files:**
- Create: `src/learnai/eval/runner.py`
- Modify: `src/learnai/adapters/tutor/anthropic/adapter.py` (record response usage)
- Modify: `tests/adapters/tutor/test_adapter.py` (one usage test)
- Test: `tests/eval/test_runner.py`

**Interfaces:**
- Consumes: `Scenario` (Task 9); `request_validated_turn`, `MAX_TUTOR_RETRIES` (Task 1); real registry/verifier/matcher/`diagnose`; `Tutor` protocol.
- Produces: `ScenarioOutcome(scenario, item, turn, attempts, usage, error=None)`; `build_context(scenario, *, graph, items, catalogue, matcher, verifier) -> TurnContext` — assembled through the real engine pieces, never hand-stated; `run_scenario(scenario, *, tutor, graph, items, catalogue, verifiers, matcher) -> ScenarioOutcome`; `run_scenarios(scenarios, ...) -> tuple[ScenarioOutcome, ...]`. Adapter gains `usages: list[dict[str, int]]` (one entry per model response).

- [ ] **Step 1: Amend the adapter to record usage**

In `adapter.py`'s `__init__`, add `self.usages: list[dict[str, int]] = []` beneath `self.events_seen`. In `respond()`, immediately after `self.events_seen.extend(_events(response.content))`, add:

```python
            self.usages.append(
                {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cache_read_input_tokens": getattr(
                        response.usage, "cache_read_input_tokens", None
                    )
                    or 0,
                }
            )
```

Add to `tests/adapters/tutor/test_adapter.py`:

```python
def test_response_usage_is_recorded():
    adapter, _ = build(turn_response(GOOD))
    adapter.respond(context())
    assert adapter.usages == [
        {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0}
    ]
```

- [ ] **Step 2: Write the failing runner test**

```python
# tests/eval/test_runner.py
import pathlib

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.turn import TutorTurn
from learnai.eval.fixtures import load_scenarios_dir
from learnai.eval.runner import build_context, run_scenario

FIXTURES = pathlib.Path(__file__).parent.parent.parent / "eval" / "fixtures"
CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)
VERIFIER = SympyVerifier()
MATCHER = SympyMisconceptionRules()
SCENARIOS = load_scenarios_dir(FIXTURES)
BY_ID = {scenario.id: scenario for scenario in SCENARIOS}


class SilentTutor:
    def respond(self, context, *, feedback=None):
        return None


class UsageTutor:
    def __init__(self):
        self.usages = []

    def respond(self, context, *, feedback=None):
        self.usages.append({"input_tokens": 7, "output_tokens": 3})
        return TutorTurn(message="Try factoring first.", rung_used=HelpRung.NUDGE)


def kwargs(tutor):
    return dict(
        tutor=tutor,
        graph=CLUSTER.graph,
        items=REGISTRY,
        catalogue=CLUSTER.misconceptions,
        verifiers={CAS_SYMBOLIC: VERIFIER},
        matcher=MATCHER,
    )


def test_a_context_is_built_through_the_real_pieces():
    scenario = BY_ID["diagnosis-01"]
    context = build_context(
        scenario,
        graph=CLUSTER.graph,
        items=REGISTRY,
        catalogue=CLUSTER.misconceptions,
        matcher=MATCHER,
        verifier=VERIFIER,
    )
    assert context.item.skill_id == scenario.skill_id
    assert context.step_diff is not None
    assert context.diagnosis is not None
    assert context.last_verdict is Verdict.WRONG
    assert context.permitted_rung is scenario.permitted_rung


def test_a_decline_context_has_no_work_and_reads_as_no_answer():
    scenario = BY_ID["decline-01"]
    context = build_context(
        scenario,
        graph=CLUSTER.graph,
        items=REGISTRY,
        catalogue=CLUSTER.misconceptions,
        matcher=MATCHER,
        verifier=VERIFIER,
    )
    assert context.step_diff is None
    assert context.diagnosis is None
    assert context.last_verdict is Verdict.NO_ANSWER


def test_a_run_records_the_accepted_turn_and_one_attempt():
    outcome = run_scenario(BY_ID["ladder-01"], **kwargs(FakeTutor()))
    assert outcome.turn is not None
    assert outcome.attempts == 1


def test_a_corrective_retry_is_counted():
    leaky = TutorTurn(message="The answer is x^2 + 7x + 12.", rung_used=HelpRung.FULL_REVEAL)
    good = TutorTurn(message="What is the very next thing you could try?", rung_used=HelpRung.NUDGE)
    outcome = run_scenario(BY_ID["ladder-01"], **kwargs(FakeTutor(script=[leaky, good])))
    assert outcome.turn is not None
    assert outcome.turn.message == good.message
    assert outcome.attempts == 2


def test_silence_is_an_outcome_not_a_crash():
    outcome = run_scenario(BY_ID["ladder-01"], **kwargs(SilentTutor()))
    assert outcome.turn is None
    assert outcome.attempts == 1
    assert outcome.usage == {}


def test_usage_deltas_are_carried_from_adapters_that_record_them():
    outcome = run_scenario(BY_ID["ladder-01"], **kwargs(UsageTutor()))
    assert outcome.usage == {"input_tokens": 7, "output_tokens": 3}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/eval/test_runner.py tests/adapters/tutor/test_adapter.py -v`
Expected: FAIL — runner module missing; the usage test fails against the current adapter.

- [ ] **Step 4: Write `runner.py`**

```python
# src/learnai/eval/runner.py
from dataclasses import dataclass
from typing import Mapping

from learnai.adapters.content.registry import GeneratorRegistry
from learnai.domain.engine import MAX_TUTOR_RETRIES
from learnai.domain.enums import Verdict
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import MisconceptionId, VerificationKind
from learnai.domain.items import Item, StepDiff, Submission
from learnai.domain.misconceptions import MisconceptionMatcher, diagnose
from learnai.domain.ports import Tutor, Verifier
from learnai.domain.skills import Misconception
from learnai.domain.turn import (
    SkillPack,
    StudentSummary,
    TurnContext,
    TutorTurn,
    request_validated_turn,
)
from learnai.eval.fixtures import Scenario


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    scenario: Scenario
    item: Item
    turn: TutorTurn | None
    attempts: int
    usage: dict[str, int]
    error: str | None = None


def build_context(
    scenario: Scenario,
    *,
    graph: SkillGraph,
    items: GeneratorRegistry,
    catalogue: Mapping[MisconceptionId, Misconception],
    matcher: MisconceptionMatcher,
    verifier: Verifier,
) -> TurnContext:
    """Assemble the moment exactly as the engine would, through the real pieces.

    The item comes from the registry, the diff and diagnosis from the real
    verifier and matcher, the verdict from a real check — a fixture cannot
    drift from engine behavior, because the engine computes it.
    """
    item = items.instantiate(scenario.template_id, scenario.seed)
    skill = graph.skills[scenario.skill_id]
    skill_catalogue = tuple(catalogue[m] for m in skill.misconception_ids)
    step_diff: StepDiff | None = None
    diagnosis: MisconceptionId | None = None
    if not scenario.declined and scenario.steps:
        step_diff = verifier.diff_steps(scenario.steps)
        diagnosis = diagnose(step_diff, skill_catalogue, matcher)
        if step_diff is None and len(scenario.steps) >= 2:
            last = StepDiff(
                index=len(scenario.steps) - 1,
                previous=scenario.steps[-2],
                current=scenario.steps[-1],
            )
            diagnosis = diagnosis or diagnose(last, skill_catalogue, matcher)
    if scenario.declined:
        last_verdict = Verdict.NO_ANSWER
    else:
        last_verdict = verifier.check_answer(
            Submission.of(scenario.answer), item.answer_spec
        ).verdict
    return TurnContext(
        skill_pack=SkillPack(
            skill_id=skill.id,
            can_do_statement=skill.can_do_statement,
            teaching_notes=skill.teaching_notes,
            misconceptions=skill_catalogue,
        ),
        item=item,
        student_summary=StudentSummary(
            strength=scenario.strength,
            is_fresh=scenario.is_fresh,
            calibration_gap=scenario.calibration_gap,
            prior_misconceptions=scenario.prior_misconceptions,
        ),
        step_diff=step_diff,
        diagnosis=diagnosis,
        permitted_rung=scenario.permitted_rung,
        last_verdict=last_verdict,
        transcript=scenario.transcript,
    )


def run_scenario(
    scenario: Scenario,
    *,
    tutor: Tutor,
    graph: SkillGraph,
    items: GeneratorRegistry,
    catalogue: Mapping[MisconceptionId, Misconception],
    verifiers: Mapping[VerificationKind, Verifier],
    matcher: MisconceptionMatcher,
) -> ScenarioOutcome:
    verifier = verifiers[graph.skills[scenario.skill_id].verification_kind]
    context = build_context(
        scenario,
        graph=graph,
        items=items,
        catalogue=catalogue,
        matcher=matcher,
        verifier=verifier,
    )
    usage_before = _usage_total(tutor)
    turn, attempts = request_validated_turn(
        tutor, context, graph, verifier, max_attempts=MAX_TUTOR_RETRIES
    )
    usage_after = _usage_total(tutor)
    usage: dict[str, int] = {}
    if usage_before is not None and usage_after is not None:
        usage = {key: usage_after[key] - usage_before.get(key, 0) for key in usage_after}
    return ScenarioOutcome(
        scenario=scenario,
        item=context.item,
        turn=turn,
        attempts=attempts,
        usage=usage,
    )


def run_scenarios(
    scenarios: tuple[Scenario, ...],
    *,
    tutor: Tutor,
    graph: SkillGraph,
    items: GeneratorRegistry,
    catalogue: Mapping[MisconceptionId, Misconception],
    verifiers: Mapping[VerificationKind, Verifier],
    matcher: MisconceptionMatcher,
) -> tuple[ScenarioOutcome, ...]:
    return tuple(
        run_scenario(
            scenario,
            tutor=tutor,
            graph=graph,
            items=items,
            catalogue=catalogue,
            verifiers=verifiers,
            matcher=matcher,
        )
        for scenario in scenarios
    )


def _usage_total(tutor: Tutor) -> dict[str, int] | None:
    """A running total from adapters that expose `usages`; None for fakes."""
    usages = getattr(tutor, "usages", None)
    if usages is None:
        return None
    totals: dict[str, int] = {}
    for usage in usages:
        if isinstance(usage, dict):
            for key, value in usage.items():
                totals[key] = totals.get(key, 0) + int(value or 0)
    return totals
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/eval/test_runner.py tests/adapters/tutor/test_adapter.py -v`
Expected: 10 passed in the runner module, 9 in the adapter module.

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv/bin/pytest`
Expected: all green.

```bash
git add src/learnai/eval/runner.py src/learnai/adapters/tutor/anthropic/adapter.py tests/adapters/tutor/test_adapter.py tests/eval/test_runner.py
git commit -m "feat: the eval runner builds real contexts and drives the shared validated-turn loop"
```

---

### Task 12: The rubric judge

**Files:**
- Create: `src/learnai/eval/judge.py`
- Test: `tests/eval/test_judge.py`

**Interfaces:**
- Consumes: `Route`/`resolve_route` (Task 3); `TurnContext`, `TutorTurn`; the scripted client (Task 7).
- Produces: `RUBRIC: str`; `JudgeError(ValueError)`; `JudgeScores(mathematics, help_level, diagnosis, tone, reasons)` — each dimension 0–2; `build_judge_messages(context, turn) -> tuple[dict, ...]`; `parse_scores(text: str) -> JudgeScores` (tolerant of code fences, strict about range and keys); `run_judge(client, routes, *, context, turn, route_name="rubric_judge") -> JudgeScores`.

- [ ] **Step 1: Write the failing test**

```python
# tests/eval/test_judge.py
import pathlib

import pytest

from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.anthropic.routing import parse_routes
from learnai.domain.enums import HelpRung, Verdict
from learnai.domain.ids import SkillId
from learnai.domain.turn import SkillPack, StudentSummary, TurnContext, TutorTurn
from learnai.eval.judge import JudgeError, parse_scores, run_judge
from tests.support.scripted_client import ScriptedAnthropic, text_response

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)
ROUTES = parse_routes(
    {
        "routes": {
            "rubric_judge": {
                "adapter": "anthropic",
                "model": "claude-opus-5",
                "temperature": 0.0,
            }
        }
    }
)
SCORES = '{"mathematics": 2, "help_level": 1, "diagnosis": 2, "tone": 2, "reasons": "good nudge"}'


def context() -> TurnContext:
    return TurnContext(
        skill_pack=SkillPack(
            skill_id=SkillId("quad.expand.binomial"),
            can_do_statement="Expand (x + a)(x + b).",
            teaching_notes="Distribute every term.",
            misconceptions=(),
        ),
        item=REGISTRY.instantiate("quad.expand.binomial.v1", 0),
        student_summary=StudentSummary(
            strength=1.0, is_fresh=True, calibration_gap=0.0, prior_misconceptions=()
        ),
        step_diff=None,
        diagnosis=None,
        permitted_rung=HelpRung.NUDGE,
        last_verdict=Verdict.WRONG,
    )


TURN = TutorTurn(message="What is the very next thing you could try?", rung_used=HelpRung.NUDGE)


def test_valid_scores_parse_even_fenced():
    fenced = f"```json\n{SCORES}\n```"
    assert parse_scores(fenced).mathematics == 2
    assert parse_scores(SCORES).reasons == "good nudge"


@pytest.mark.parametrize(
    "text, match",
    [
        ("no json here", "no JSON object"),
        ('{"mathematics": 9, "help_level": 1, "diagnosis": 2, "tone": 2, "reasons": "x"}', "0-2"),
        ('{"mathematics": 2, "help_level": 1, "diagnosis": 2, "tone": 2}', "reasons"),
    ],
)
def test_malformed_scores_are_errors(text, match):
    with pytest.raises(JudgeError, match=match):
        parse_scores(text)


def test_run_judge_uses_the_route_and_returns_scores():
    scripted = ScriptedAnthropic([text_response(SCORES)])
    scores = run_judge(scripted.client, ROUTES, context=context(), turn=TURN)
    assert scores.tone == 2
    request = scripted.requests[0]
    assert request["temperature"] == 0.0
    assert "four dimensions" in request["system"][0]["text"]
    assert TURN.message in request["messages"][0]["content"]


def test_an_api_failure_is_a_judge_error():
    scripted = ScriptedAnthropic([], status_code=500)
    with pytest.raises(JudgeError, match="judge call failed"):
        run_judge(scripted.client, ROUTES, context=context(), turn=TURN)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/eval/test_judge.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'learnai.eval.judge'`.

- [ ] **Step 3: Write `judge.py`**

```python
# src/learnai/eval/judge.py
import json
from dataclasses import dataclass
from typing import Any, Mapping

import anthropic

from learnai.adapters.tutor.anthropic.routing import Route, resolve_route
from learnai.domain.turn import TurnContext, TutorTurn

RUBRIC = """You are grading one tutoring turn for a mathematics practice app.
Score it on four dimensions, each an integer 0-2:
- mathematics: 0 = wrong maths, 1 = a minor slip, 2 = correct
- help_level: 0 = too much or too little help for the permitted rung, 1 = close, 2 = exactly right
- diagnosis: 0 = points at the wrong idea, 1 = vague, 2 = names the right idea (or is correctly general)
- tone: 0 = condescending or confusing, 1 = acceptable, 2 = warm, clear, age-appropriate
Return ONLY a JSON object:
{"mathematics": n, "help_level": n, "diagnosis": n, "tone": n, "reasons": "one or two sentences"}"""


class JudgeError(ValueError):
    """The judge call did not return usable scores."""


@dataclass(frozen=True, slots=True)
class JudgeScores:
    mathematics: int
    help_level: int
    diagnosis: int
    tone: int
    reasons: str


_DIMENSIONS = ("mathematics", "help_level", "diagnosis", "tone")


def build_judge_messages(
    context: TurnContext, turn: TutorTurn
) -> tuple[dict[str, str], ...]:
    payload = (
        f"Permitted rung: {context.permitted_rung.name}\n"
        f"Last verdict: {context.last_verdict.name if context.last_verdict else 'none'}\n"
        f"Diagnosis available: {context.diagnosis or 'none'}\n"
        f"Item statement: {context.item.statement}\n"
        f"Tutoring turn:\n{turn.message}"
    )
    return ({"role": "user", "content": payload},)


def parse_scores(text: str) -> JudgeScores:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise JudgeError(f"no JSON object in judge output: {text[:200]!r}")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise JudgeError(f"judge output is not JSON: {error}") from error
    if not isinstance(payload, Mapping):
        raise JudgeError("judge output is not an object")
    for dimension in _DIMENSIONS:
        value = payload.get(dimension)
        if not isinstance(value, int) or not 0 <= value <= 2:
            raise JudgeError(f"{dimension} must be an integer 0-2, got {value!r}")
    reasons = payload.get("reasons")
    if not isinstance(reasons, str):
        raise JudgeError("judge output has no 'reasons' string")
    return JudgeScores(
        mathematics=payload["mathematics"],
        help_level=payload["help_level"],
        diagnosis=payload["diagnosis"],
        tone=payload["tone"],
        reasons=reasons,
    )


def run_judge(
    client: anthropic.Anthropic,
    routes: Mapping[str, Route],
    *,
    context: TurnContext,
    turn: TutorTurn,
    route_name: str = "rubric_judge",
) -> JudgeScores:
    route = resolve_route(routes, route_name)
    kwargs: dict[str, Any] = {"model": route.model, "max_tokens": route.max_tokens}
    if route.temperature is not None:
        kwargs["temperature"] = route.temperature
    try:
        response = client.messages.create(
            **kwargs,
            system=[{"type": "text", "text": RUBRIC}],
            messages=list(build_judge_messages(context, turn)),
        )
    except anthropic.APIError as error:
        raise JudgeError(f"judge call failed: {error}") from error
    text = "".join(
        getattr(block, "text", "") for block in response.content if getattr(block, "type", "") == "text"
    )
    return parse_scores(text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/eval/test_judge.py -v`
Expected: 8 passed (4 test functions; one parametrized ×3).

- [ ] **Step 5: Commit**

```bash
git add src/learnai/eval/judge.py tests/eval/test_judge.py
git commit -m "feat: the rubric judge with strict score parsing"
```

---

### Task 13: The report and the CLI

**Files:**
- Create: `src/learnai/eval/report.py`
- Create: `src/learnai/eval/__main__.py`
- Test: `tests/eval/test_report_cli.py`

**Interfaces:**
- Consumes: `ScenarioOutcome` (Task 11); `JudgeScores` (Task 12); `run_persona_smoke` (Task 14 — this task imports it; Task 14 lands before this task runs, or this task's smoke flag lands with a stub import resolved in Task 14; the plan orders Task 14 first mentally — see the note in Step 4).
- Produces: `write_report(directory: Path, *, outcomes, scores, route_names, persona_smoke, started_at, finished_at) -> Path` writing `report.json` + `summary.md`; `PRICING` (illustrative Opus-class per-MTok values, verified at implementation); CLI `python -m learnai.eval run [--fixtures DIR] [--routes FILE] [--out DIR] [--no-smoke]` via `main(argv, *, client_factory=None) -> int` — refuses without `ANTHROPIC_API_KEY` (exit 2), constructs the real client by default, and accepts a factory so the whole CLI is testable offline.

- [ ] **Step 1: Write the failing tests**

```python
# tests/eval/test_report_cli.py
import json
import pathlib

import pytest

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.eval.fixtures import load_scenarios_dir
from learnai.eval.report import write_report
from learnai.eval.runner import run_scenarios
from tests.support.scripted_client import ScriptedAnthropic, text_response, turn_response

REPO = pathlib.Path(__file__).parent.parent.parent
CLUSTER = load_cluster(REPO / "content" / "quadratics" / "skills.yaml")
REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)
FIXTURES = REPO / "eval" / "fixtures"


def outcomes_for_two_scenarios():
    scenarios = (load_scenarios_dir(FIXTURES)[0], load_scenarios_dir(FIXTURES)[3])
    return run_scenarios(
        scenarios,
        tutor=FakeTutor(),
        graph=CLUSTER.graph,
        items=REGISTRY,
        catalogue=CLUSTER.misconceptions,
        verifiers={CAS_SYMBOLIC: SympyVerifier()},
        matcher=SympyMisconceptionRules(),
    )


def test_the_report_writer_produces_machine_and_human_artifacts(tmp_path):
    outcomes = outcomes_for_two_scenarios()
    directory = write_report(
        tmp_path / "run-1",
        outcomes=outcomes,
        scores={},
        route_names=("tutor_dialogue", "rubric_judge"),
        persona_smoke={"sessions_run": 2, "items_completed": 3, "tutor_turns": 4},
        started_at="2026-10-16T09:00:00Z",
        finished_at="2026-10-16T09:04:00Z",
    )
    report = json.loads((directory / "report.json").read_text())
    assert report["totals"]["scenarios"] == len(outcomes)
    assert report["totals"]["accepted"] == len(outcomes)
    assert report["persona_smoke"]["items_completed"] == 3
    assert report["routes"] == ["rubric_judge", "tutor_dialogue"]
    summary = (directory / "summary.md").read_text()
    assert "# Eval run" in summary
    assert "| family |" in summary


def test_the_cli_refuses_without_a_key(monkeypatch, tmp_path, capsys):
    from learnai.eval.__main__ import main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(["run", "--fixtures", str(FIXTURES), "--out", str(tmp_path)])
    assert code == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_the_cli_runs_a_scripted_run_end_to_end(monkeypatch, tmp_path):
    from learnai.eval.__main__ import main

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    judge_ok = '{"mathematics": 2, "help_level": 2, "diagnosis": 2, "tone": 2, "reasons": "ok"}'
    scripted = ScriptedAnthropic(
        [
            turn_response({"message": "Try the next step.", "rung_used": "NUDGE"}),
            text_response(judge_ok),
            turn_response({"message": "Try again carefully.", "rung_used": "NUDGE"}),
            text_response(judge_ok),
        ]
    )
    code = main(
        [
            "run",
            "--fixtures",
            str(FIXTURES),
            "--out",
            str(tmp_path),
            "--no-smoke",
            "--only",
            "ladder-01",
            "ladder-02",
        ],
        client_factory=lambda **kwargs: scripted.client,
    )
    assert code == 0
    runs = list(tmp_path.glob("*/report.json"))
    assert len(runs) == 1
    report = json.loads(runs[0].read_text())
    assert report["totals"]["scenarios"] == 2
    assert report["totals"]["accepted"] == 2
    assert report["totals"]["judge_scores"] == 2  # the judge runs on accepted turns only
```

(The script interleaves, per scenario, one `turn_response` for the tutoring turn and one `text_response` carrying valid judge JSON. The judge runs on accepted turns only — the totals assert it.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/eval/test_report_cli.py -v`
Expected: collection error — no `learnai.eval.report`, no `learnai.eval.__main__`.

- [ ] **Step 3: Write `report.py`**

```python
# src/learnai/eval/report.py
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from learnai.eval.judge import JudgeScores
from learnai.eval.runner import ScenarioOutcome

PRICING = {"input_per_mtok": 15.0, "output_per_mtok": 75.0}
"""Illustrative Opus-class pricing for the cost readout; VERIFY against
current published pricing at implementation time. Caching makes real input
costs far lower than this overstates nothing — it is a ceiling."""


def write_report(
    directory: Path,
    *,
    outcomes: Sequence[ScenarioOutcome],
    scores: Mapping[str, JudgeScores],
    route_names: Sequence[str],
    persona_smoke: Mapping[str, Any] | None,
    started_at: str,
    finished_at: str,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    scenario_rows = [_scenario_row(outcome, scores.get(outcome.scenario.id)) for outcome in outcomes]
    report = {
        "started_at": started_at,
        "finished_at": finished_at,
        "routes": sorted(route_names),
        "scenarios": scenario_rows,
        "families": _family_aggregates(scenario_rows),
        "totals": {
            "scenarios": len(scenario_rows),
            "accepted": sum(1 for row in scenario_rows if row["accepted"]),
            "judge_scores": sum(1 for row in scenario_rows if row["judge"] is not None),
            "attempts": sum(row["attempts"] for row in scenario_rows),
            "input_tokens": sum(row["usage"].get("input_tokens", 0) for row in scenario_rows),
            "output_tokens": sum(row["usage"].get("output_tokens", 0) for row in scenario_rows),
        },
        "persona_smoke": dict(persona_smoke) if persona_smoke is not None else None,
    }
    report["totals"]["estimated_cost_usd"] = _estimate_cost(report["totals"])
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (directory / "summary.md").write_text(_summary_markdown(report))
    return directory


def _scenario_row(outcome: ScenarioOutcome, scores: JudgeScores | None) -> dict[str, Any]:
    return {
        "id": outcome.scenario.id,
        "family": outcome.scenario.family,
        "accepted": outcome.turn is not None,
        "attempts": outcome.attempts,
        "message": outcome.turn.message if outcome.turn is not None else None,
        "usage": dict(outcome.usage),
        "judge": asdict(scores) if scores is not None else None,
    }


def _family_aggregates(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    families: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = families.setdefault(
            row["family"],
            {"count": 0, "accepted": 0, "mathematics": [], "help_level": [], "diagnosis": [], "tone": []},
        )
        entry["count"] += 1
        entry["accepted"] += 1 if row["accepted"] else 0
        if row["judge"]:
            for dimension in ("mathematics", "help_level", "diagnosis", "tone"):
                entry[dimension].append(row["judge"][dimension])
    for entry in families.values():
        for dimension in ("mathematics", "help_level", "diagnosis", "tone"):
            values = entry.pop(dimension)
            entry[f"mean_{dimension}"] = round(sum(values) / len(values), 2) if values else None
    return families


def _estimate_cost(totals: Mapping[str, Any]) -> float:
    return round(
        totals.get("input_tokens", 0) / 1_000_000 * PRICING["input_per_mtok"]
        + totals.get("output_tokens", 0) / 1_000_000 * PRICING["output_per_mtok"],
        4,
    )


def _summary_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Eval run",
        "",
        f"- window: {report['started_at']} → {report['finished_at']}",
        f"- routes: {', '.join(report['routes'])}",
        f"- scenarios: {report['totals']['scenarios']} "
        f"({report['totals']['accepted']} accepted, "
        f"{report['totals']['judge_scores']} judged)",
        f"- estimated cost: ${report['totals']['estimated_cost_usd']}",
        "",
        "| family | count | accepted | math | help | diag | tone |",
        "|---|---|---|---|---|---|---|",
    ]
    for family, entry in sorted(report["families"].items()):
        lines.append(
            f"| {family} | {entry['count']} | {entry['accepted']} "
            f"| {entry['mean_mathematics']} | {entry['mean_help_level']} "
            f"| {entry['mean_diagnosis']} | {entry['mean_tone']} |"
        )
    smoke = report.get("persona_smoke")
    lines += ["", f"Persona smoke: {smoke}" if smoke else "Persona smoke: skipped", ""]
    return "\n".join(lines)
```

- [ ] **Step 4: Write `__main__.py`** (and `smoke.py` arrives in Task 14 — this task's import of it is written to tolerate absence until then by landing Task 14 first in execution order if running this task's tests before Task 14: the plan's task order is 13 then 14; write `__main__.py` now with the smoke import guarded as below, and Task 14 replaces the guard with the real import):

```python
# src/learnai/eval/__main__.py
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import anthropic

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
from learnai.adapters.tutor.anthropic.routing import load_routes
from learnai.eval.fixtures import load_scenarios_dir
from learnai.eval.judge import run_judge
from learnai.eval.report import write_report
from learnai.eval.runner import build_context, run_scenarios

REPO = Path(__file__).resolve().parents[3]


def main(
    argv: list[str] | None = None,
    *,
    client_factory: Callable[..., anthropic.Anthropic] | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m learnai.eval")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the graded eval set against the live API")
    run.add_argument("--fixtures", type=Path, default=REPO / "eval" / "fixtures")
    run.add_argument("--routes", type=Path, default=REPO / "config" / "llm_routes.yaml")
    run.add_argument("--out", type=Path, default=REPO / "eval" / "reports")
    run.add_argument("--only", nargs="*", default=None, help="scenario ids to run")
    run.add_argument("--no-smoke", action="store_true", help="skip the persona smoke")
    args = parser.parse_args(argv)

    key = os.environ.get("ANTHROPIC_API_KEY")
    if key is None:
        print("ANTHROPIC_API_KEY is not set — the eval set only runs live.", file=sys.stderr)
        return 2

    started_at = datetime.now(timezone.utc).isoformat()
    routes = load_routes(args.routes)
    cluster = load_cluster(REPO / "content" / "quadratics" / "skills.yaml")
    registry = GeneratorRegistry(QUADRATICS_TEMPLATES)
    verifier = SympyVerifier()
    matcher = SympyMisconceptionRules()
    factory = client_factory or (lambda **kwargs: anthropic.Anthropic(**kwargs))
    client = factory(api_key=key, max_retries=2)
    tutor = AnthropicTutor(
        routes=routes,
        client=client,
        graph=cluster.graph,
        items=registry,
        catalogue=cluster.misconceptions,
    )

    scenarios = load_scenarios_dir(args.fixtures)
    if args.only:
        wanted = set(args.only)
        scenarios = tuple(s for s in scenarios if s.id in wanted)
        missing = wanted - {s.id for s in scenarios}
        if missing:
            print(f"unknown scenario ids: {sorted(missing)}", file=sys.stderr)
            return 2

    outcomes = run_scenarios(
        scenarios,
        tutor=tutor,
        graph=cluster.graph,
        items=registry,
        catalogue=cluster.misconceptions,
        verifiers={CAS_SYMBOLIC: verifier},
        matcher=matcher,
    )

    scores = {}
    for outcome in outcomes:
        if outcome.turn is None:
            continue
        context = build_context(
            outcome.scenario,
            graph=cluster.graph,
            items=registry,
            catalogue=cluster.misconceptions,
            matcher=matcher,
            verifier=verifier,
        )
        scores[outcome.scenario.id] = run_judge(
            client, routes, context=context, turn=outcome.turn
        )

    persona_smoke = None
    if not args.no_smoke:
        from learnai.eval.smoke import run_persona_smoke  # Task 14

        persona_smoke = run_persona_smoke(
            tutor=tutor,
            graph=cluster.graph,
            misconceptions=cluster.misconceptions,
            items=registry,
            verifiers={CAS_SYMBOLIC: verifier},
            matcher=matcher,
        )

    finished_at = datetime.now(timezone.utc).isoformat()
    directory = write_report(
        args.out / f"{started_at[:16].replace(':', '')}-eval",
        outcomes=outcomes,
        scores=scores,
        route_names=routes.keys(),
        persona_smoke=persona_smoke,
        started_at=started_at,
        finished_at=finished_at,
    )
    print(f"report written to {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/eval/test_report_cli.py -v`
Expected: 3 passed. (If Task 14 has not landed yet, run with `--no-smoke` in the CLI test — as its argv already does — so the smoke import is never hit.)

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv/bin/pytest`
Expected: all green.

```bash
git add src/learnai/eval/report.py src/learnai/eval/__main__.py tests/eval/test_report_cli.py
git commit -m "feat: the eval report writer and the on-demand CLI"
```

---

### Task 14: Persona smoke — short terms through the real adapter

**Files:**
- Create: `src/learnai/eval/smoke.py`
- Test: `tests/eval/test_smoke.py`

**Interfaces:**
- Consumes: `PracticeEngine` (as built), `FakeClock`, the shared construction pattern, `Session`/`TaskState`/`replace_task`/`advance`.
- Produces: `run_persona_smoke(*, tutor, graph, misconceptions, items, verifiers, matcher, sessions=2, items_per_session=3, seed=11) -> dict[str, dict[str, float]]` — drives two deterministic student policies through short terms: **diligent** (one wrong attempt, then correct) and **abuser** (asks for help before every attempt, then submits the correct answer — and must finish the term with total strength 0.0, the headline guarantee, live). Every delivered turn passed validation by construction (the engine's own loop). Returns `{"diligent": {...}, "abuser": {..., "strength_total": ...}}` with `sessions_run`, `items_completed`, `tutor_turns` per persona.

- [ ] **Step 1: Write the failing test**

```python
# tests/eval/test_smoke.py
import pathlib

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.eval.smoke import run_persona_smoke

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)


def smoke(**overrides):
    return run_persona_smoke(
        tutor=overrides.pop("tutor", FakeTutor()),
        graph=CLUSTER.graph,
        misconceptions=CLUSTER.misconceptions,
        items=REGISTRY,
        verifiers={CAS_SYMBOLIC: SympyVerifier()},
        matcher=SympyMisconceptionRules(),
        clock=FakeClock(),
        **overrides,
    )


def test_the_diligent_persona_completes_items_with_tutor_turns():
    summary = smoke()
    assert summary["diligent"]["sessions_run"] == 2
    assert summary["diligent"]["items_completed"] > 0
    assert summary["diligent"]["tutor_turns"] > 0


def test_the_abuser_finishes_the_term_with_zero_strength():
    summary = smoke()
    assert summary["abuser"]["items_completed"] > 0
    assert summary["abuser"]["tutor_turns"] > 0
    assert summary["abuser"]["strength_total"] == 0.0


def test_a_silent_tutor_still_completes_the_term():
    class SilentTutor:
        def respond(self, context, *, feedback=None):
            return None

    summary = smoke(tutor=SilentTutor())
    assert summary["diligent"]["items_completed"] > 0
    assert summary["diligent"]["tutor_turns"] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/eval/test_smoke.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'learnai.eval.smoke'`.

- [ ] **Step 3: Write `smoke.py`**

```python
# src/learnai/eval/smoke.py
from dataclasses import replace
from typing import Mapping

from learnai.adapters.clock import FakeClock
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.domain.contracts import PRACTICE, ModeContract
from learnai.domain.engine import PracticeEngine
from learnai.domain.enums import Confidence, Verdict
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import CourseId, MisconceptionId, SessionId, StudentId, VerificationKind
from learnai.domain.items import Submission
from learnai.domain.misconceptions import MisconceptionMatcher
from learnai.domain.ports import Tutor, Verifier
from learnai.domain.session import TaskState, advance, replace_task
from learnai.domain.skills import Misconception

PERSONAS = ("diligent", "abuser")
"""The two smoke policies: a learner who errs then fixes it, and an abuser
who asks for help before every attempt. The abuser's zero-strength finish is
the headline anti-hint-abuse guarantee, demonstrated live."""


def run_persona_smoke(
    *,
    tutor: Tutor,
    graph: SkillGraph,
    misconceptions: Mapping[MisconceptionId, Misconception],
    items: GeneratorRegistry,
    verifiers: Mapping[VerificationKind, Verifier],
    matcher: MisconceptionMatcher,
    clock: FakeClock | None = None,
    contract: ModeContract = PRACTICE,
    sessions: int = 2,
    items_per_session: int = 3,
    seed: int = 11,
) -> dict[str, dict[str, float]]:
    """Short terms through the real adapter (spec §7 persona smoke).

    Deterministic policies; the tutor is the only live part. Every delivered
    turn passed validation by construction — it went through the engine's own
    loop. Items that refuse to complete after three attempts are abandoned by
    the driver, the way the simulator does.
    """
    clock = clock or FakeClock()
    summary: dict[str, dict[str, float]] = {}
    for persona in PERSONAS:
        summary[persona] = _run_one(
            persona,
            tutor=tutor,
            graph=graph,
            misconceptions=misconceptions,
            items=items,
            verifiers=verifiers,
            matcher=matcher,
            clock=clock,
            contract=contract,
            sessions=sessions,
            items_per_session=items_per_session,
            seed=seed,
        )
    return summary


def _run_one(
    persona: str,
    *,
    tutor: Tutor,
    graph: SkillGraph,
    misconceptions: Mapping[MisconceptionId, Misconception],
    items: GeneratorRegistry,
    verifiers: Mapping[VerificationKind, Verifier],
    matcher: MisconceptionMatcher,
    clock: FakeClock,
    contract: ModeContract,
    sessions: int,
    items_per_session: int,
    seed: int,
) -> dict[str, float]:
    engine = PracticeEngine(
        graph=graph,
        misconceptions=misconceptions,
        item_source=items,
        verifiers=verifiers,
        tutor=tutor,
        matcher=matcher,
        evidence_log=InMemoryEvidenceLog(),
        clock=clock,
        contract=contract,
    )
    states: dict = {}
    items_completed = 0
    tutor_turns = 0
    for run in range(sessions):
        session = engine.start_session(
            student_id=StudentId(f"smoke-{persona}"),
            course_id=CourseId("quadratics"),
            course_skills=graph.topological_order(),
            states=states,
            budget_items=items_per_session,
            session_id=SessionId(f"smoke-{persona}-{run}"),
            seed=seed + run,
        )
        attempts = 0
        while session.current_task is not None:
            task = session.current_task
            verifier = verifiers[graph.skills[task.skill_id].verification_kind]
            if persona == "abuser" and attempts == 0:
                session, help_turn = engine.request_help(session, states)
                if help_turn is not None:
                    tutor_turns += 1
            if attempts == 0:
                answer = Submission.of("123456")
            else:
                answer = verifier.key_submission(task.item.answer_spec)
            session, states, outcome = engine.submit(
                session, states, [], answer, Confidence.FAIRLY_SURE
            )
            if outcome.tutor_turn is not None:
                tutor_turns += 1
            if outcome.verdict is Verdict.CORRECT:
                items_completed += 1
                attempts = 0
            else:
                attempts += 1
                if attempts >= 3:
                    session = advance(
                        replace_task(session, replace(task, state=TaskState.ABANDONED))
                    )
                    attempts = 0
            clock.advance(0.6)
        clock.advance(2.0)
    return {
        "sessions_run": float(sessions),
        "items_completed": float(items_completed),
        "tutor_turns": float(tutor_turns),
        "strength_total": round(sum(s.strength for s in states.values()), 6),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/eval/test_smoke.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/bin/pytest`
Expected: all green.

```bash
git add src/learnai/eval/smoke.py tests/eval/test_smoke.py
git commit -m "feat: the persona smoke drives short terms through the real adapter"
```

---

### Task 15: Live checks, markers, and the run documentation

**Files:**
- Modify: `pyproject.toml` (the `live` marker registration)
- Create: `tests/adapters/tutor/test_live.py`
- Create: `eval/README.md`
- Modify: `.gitignore` (`eval/reports/`)

**Interfaces:**
- Consumes: everything built.
- Produces: the two live-marked checks (cache proof; one real accepted turn); the marker registration so `pytest -m live` selects exactly them and the default suite runs keyless; the eval runbook.

- [ ] **Step 1: Register the marker**

In `pyproject.toml` under `[tool.pytest.ini_options]`, keep `testpaths`/`addopts` and add:

```toml
markers = [
    "live: hits the real Anthropic API; skipped without ANTHROPIC_API_KEY",
]
```

- [ ] **Step 2: Write the live checks**

```python
# tests/adapters/tutor/test_live.py
"""Live checks — the only tests that spend money. Skipped without a key.

The cache check is the point of the whole prompt layout: a second call with
an identical prefix must read from the vendor's cache (parent spec §10.1).
A zero here means something volatile entered the cached prefix.
"""
import os
import pathlib

import anthropic
import pytest

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
from learnai.adapters.tutor.anthropic.routing import load_routes
from learnai.domain.contracts import PRACTICE
from learnai.domain.engine import PracticeEngine
from learnai.domain.enums import Confidence, HelpRung, Verdict
from learnai.domain.ids import CourseId, SessionId, SkillId, StudentId
from learnai.domain.items import Submission
from learnai.domain.turn import SkillPack, StudentSummary, TurnContext

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="live checks need ANTHROPIC_API_KEY",
    ),
]

REPO = pathlib.Path(__file__).parent.parent.parent.parent
CLUSTER = load_cluster(REPO / "content" / "quadratics" / "skills.yaml")
REGISTRY = GeneratorRegistry(QUADRATICS_TEMPLATES)


def build_adapter() -> AnthropicTutor:
    return AnthropicTutor(
        routes=load_routes(REPO / "config" / "llm_routes.yaml"),
        client=anthropic.Anthropic(max_retries=2),
        graph=CLUSTER.graph,
        items=REGISTRY,
        catalogue=CLUSTER.misconceptions,
    )


def context() -> TurnContext:
    item = REGISTRY.instantiate("quad.expand.binomial.v1", 0)
    return TurnContext(
        skill_pack=SkillPack(
            skill_id=SkillId("quad.expand.binomial"),
            can_do_statement=CLUSTER.graph.skills[SkillId("quad.expand.binomial")].can_do_statement,
            teaching_notes=CLUSTER.graph.skills[SkillId("quad.expand.binomial")].teaching_notes,
            misconceptions=(),
        ),
        item=item,
        student_summary=StudentSummary(
            strength=1.0, is_fresh=True, calibration_gap=0.0, prior_misconceptions=()
        ),
        step_diff=None,
        diagnosis=None,
        permitted_rung=HelpRung.NUDGE,
        last_verdict=Verdict.WRONG,
    )


def test_the_cache_hits_on_an_identical_prefix():
    adapter = build_adapter()
    first = adapter.respond(context())
    assert first is not None, "the model failed to produce a first turn"
    before = len(adapter.usages)
    second = adapter.respond(context())
    assert second is not None, "the model failed to produce a second turn"
    assert adapter.usages[before].get("cache_read_input_tokens", 0) > 0, (
        "no cache read on the second identical call — a volatile block entered the cached prefix"
    )


def test_one_real_turn_passes_the_real_contract_end_to_end():
    adapter = build_adapter()
    engine = PracticeEngine(
        graph=CLUSTER.graph,
        misconceptions=CLUSTER.misconceptions,
        item_source=REGISTRY,
        verifiers={CAS_SYMBOLIC: SympyVerifier()},
        tutor=adapter,
        matcher=SympyMisconceptionRules(),
        evidence_log=InMemoryEvidenceLog(),
        clock=FakeClock(),
        contract=PRACTICE,
    )
    session = engine.start_session(
        student_id=StudentId("live"),
        course_id=CourseId("quadratics"),
        course_skills=CLUSTER.graph.topological_order(),
        states={},
        budget_items=1,
        session_id=SessionId("live-1"),
        seed=7,
    )
    _, _, outcome = engine.submit(
        session, {}, [], Submission.of("definitely not the answer"), Confidence.GUESSING
    )
    assert outcome.tutor_turn is not None, "the real tutor produced nothing acceptable"
    assert outcome.tutor_turn.rung_used <= HelpRung.NUDGE  # the submit path's ceiling
```

- [ ] **Step 3: Write `eval/README.md`**

```markdown
# The graded eval set

The instrument that measures the real tutor (spec: `docs/superpowers/specs/2026-10-16-anthropic-tutor-eval-design.md` §7).
It is **opt-in and paid** — it requires `ANTHROPIC_API_KEY` and is never part of the default suite.

## Running

    python -m learnai.eval run                 # the full set + persona smoke
    python -m learnai.eval run --no-smoke      # scenarios only (cheaper)
    python -m learnai.eval run --only ladder-01 decline-01

Reports land in `eval/reports/<stamp>-eval/` (`report.json` + `summary.md`). The directory is
git-ignored; the first **calibrated** run's `summary.md` is committed as the reference artifact.

## What a run does

1. Builds every scenario's `TurnContext` through the **real engine pieces** — the item from the
   generator registry, the step diff from the CAS verifier, the diagnosis from the real matcher.
2. Drives the real adapter through the **same validated-turn loop the engine uses** — the eval
   cannot be greener than reality.
3. Deterministic checks: a scenario passes only if an acceptable turn was produced (rung ceiling,
   no leak, legal proposals) — no judge involved.
4. Judge pass: the `rubric_judge` route scores each accepted turn 0–2 on mathematics, help level,
   diagnosis, and tone.
5. Persona smoke: short deterministic terms through the real adapter.

## Before trusting the numbers (calibration)

The **first judged run is spot-reviewed by the human** (~10 turns, `report.json` carries every
message). If the judge disagrees with the review, fix the rubric or the judge prompt before
trusting its numbers; then record per-family score floors in this file as release gates for
future runs.

## The growth rule

Every failure this instrument ever finds becomes a committed fixture; where mechanically
checkable it also becomes a deterministic check. The corpus grows from evidence, never from
imagination.
```

- [ ] **Step 4: Ignore the reports, keep the reference**

Add to `.gitignore`:

```
eval/reports/
```

- [ ] **Step 5: Run the suites**

Run: `.venv/bin/pytest`
Expected: all green, no `live` tests collected in the default run.
Run: `.venv/bin/pytest -m live --collect-only -q`
Expected: the two live tests listed (they skip at run time without a key).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/adapters/tutor/test_live.py eval/README.md .gitignore
git commit -m "feat: the live checks, the marker, and the eval runbook"
```

---

## Done means (the spec's acceptance criteria, ≥pointers)

1. A real tutor turn flows engine → adapter → validated `TutorTurn` (Task 8 keyless; Task 15 live).
2. The four-layer cache layout is asserted keyless (Tasks 4, 7) and proven live (Task 15).
3. Corrective retries work and exhaustion degrades to silence (Tasks 1, 7, 8).
4. The tutor sees the delivered conversation, capped (Tasks 1, 8).
5. All twelve skills carry reviewed teaching notes; the loader enforces them (Task 2 — the human reviews the texts as content).
6. The eval set: ≥50 scenarios, deterministic checks green, judged report written, first report spot-reviewed, persona smoke passing (Tasks 9–14).
7. Measured cost per turn reported (Task 13's report; the live run fills it).
8. Headless and terminal-runnable throughout; the default suite stays keyless (every task).

## Execution notes

- Task order is 1→15; the only soft coupling is Task 13's CLI referencing Task 14's smoke behind
  `--no-smoke` (its tests use that flag), so 13 and 14 may swap if convenient.
- `.venv/bin/pip install anthropic` (plus the pyproject entry) happens in Task 7 before its tests;
  the live checks in Task 15 then run against the installed SDK.
- The one place the live SDK shape is verified rather than asserted is `_request_kwargs`'s
  `thinking`/`output_config` nesting (Task 7) — the live checks are where that is proven, and the
  scripted tests pin our mapping as the contract.


