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
from learnai.domain.ids import CourseId, SessionId, StudentId

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
