# tests/simulation/personas.py
"""Synthetic students. Each decides what to submit and whether to ask for help."""
import pathlib
from dataclasses import dataclass, field, replace

import sympy as sp

from learnai.adapters.cas.misconception_rules import SympyMisconceptionRules
from learnai.adapters.cas.parse import parse_math, write_math
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.clock import FakeClock
from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
from learnai.adapters.content.loader import load_cluster
from learnai.adapters.content.registry import GeneratorRegistry
from learnai.adapters.cas.vocabulary import CAS_SYMBOLIC
from learnai.adapters.persistence.in_memory import InMemoryEvidenceLog
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.contracts import PRACTICE
from learnai.domain.engine import PracticeEngine
from learnai.domain.enums import Confidence
from learnai.domain.ids import CourseId, SessionId, SkillId, StudentId
from learnai.domain.items import Formula, Submission
from learnai.domain.mastery import SkillState
from learnai.domain.session import Task, TaskState, advance, replace_task

CLUSTER = load_cluster(
    pathlib.Path(__file__).parent.parent.parent / "content" / "quadratics" / "skills.yaml"
)
COURSE = CLUSTER.graph.topological_order()
_KEYS = SympyVerifier()  # turns an answer key into what a student would enter


class Persona:
    name = "base"
    asks_for_help = False
    confidence = Confidence.FAIRLY_SURE

    def answer(self, task: Task) -> Submission:
        return _KEYS.key_submission(task.item.answer_spec)


class Diligent(Persona):
    name = "diligent"


class HintAbuser(Persona):
    """Climbs the whole ladder on every task, then answers correctly."""

    name = "hint_abuser"
    asks_for_help = True
    confidence = Confidence.CERTAIN


class MisconceptionCarrier(Persona):
    """Believes (a + b)^2 == a^2 + b^2 and gets everything else right."""

    name = "misconception_carrier"
    confidence = Confidence.CERTAIN

    def answer(self, task: Task) -> Submission:
        if task.skill_id != SkillId("quad.expand.square"):
            return _KEYS.key_submission(task.item.answer_spec)
        return Submission.of(self._believed_expansion(task))

    def _believed_expansion(self, task: Task) -> str:
        correct = parse_math(task.item.answer_spec.expression)
        x = sp.Symbol("x")
        poly = sp.Poly(correct, x)
        constant = poly.coeff_monomial(1)
        return write_math(x**2 + constant)

    def steps(self, task: Task) -> list[str]:
        if task.skill_id != SkillId("quad.expand.square"):
            return []
        prompt = next(block.source for block in task.item.statement if isinstance(block, Formula))
        return [prompt, self._believed_expansion(task)]


class Overconfident(Persona):
    """Always certain, always wrong."""

    name = "overconfident"
    confidence = Confidence.CERTAIN

    def answer(self, task: Task) -> Submission:
        return Submission.of("0")


@dataclass
class TermResult:
    states: dict[SkillId, SkillState] = field(default_factory=dict)
    sessions_run: int = 0
    log: InMemoryEvidenceLog = field(default_factory=InMemoryEvidenceLog)
    clock: FakeClock = field(default_factory=FakeClock)


def run_term(
    persona: Persona,
    *,
    days: int = 84,
    days_between_sessions: float = 2.0,
    items_per_session: int = 6,
) -> TermResult:
    result = TermResult()
    verifier = SympyVerifier()
    engine = PracticeEngine(
        graph=CLUSTER.graph,
        misconceptions=CLUSTER.misconceptions,
        item_source=GeneratorRegistry(QUADRATICS_TEMPLATES),
        verifiers={CAS_SYMBOLIC: verifier},
        tutor=FakeTutor(),
        matcher=SympyMisconceptionRules(),
        evidence_log=result.log,
        clock=result.clock,
        contract=PRACTICE,
    )

    elapsed = 0.0
    while elapsed < days:
        session = engine.start_session(
            student_id=StudentId(persona.name),
            course_id=CourseId("quadratics"),
            course_skills=COURSE,
            states=result.states,
            budget_items=items_per_session,
            session_id=SessionId(f"{persona.name}-{result.sessions_run}"),
            seed=result.sessions_run + 1,
        )
        result.sessions_run += 1
        while not session.is_finished:
            task = session.current_task
            if persona.asks_for_help:
                for _ in range(3):
                    session, _ = engine.request_help(session, result.states)
            steps = getattr(persona, "steps", lambda _t: [])(task)
            session, result.states, outcome = engine.submit(
                session,
                result.states,
                steps=steps,
                answer=persona.answer(task),
                confidence=persona.confidence,
            )
            if not outcome.task_completed:
                session = _abandon(session)
            result.clock.advance(0.01)
        result.clock.advance(days_between_sessions)
        elapsed += days_between_sessions
    return result


def _abandon(session):
    """The harness's skip: mark the task abandoned and move the cursor on.

    The engine itself never advances past a wrong task — the product's exit is
    the full reveal (Task 17). A simulated persona cannot adapt to a reveal, so
    the driver skips instead; the task state records what happened.
    """
    return advance(
        replace_task(session, replace(session.current_task, state=TaskState.ABANDONED))
    )
