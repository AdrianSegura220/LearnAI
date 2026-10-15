# tests/adapters/test_fake_tutor.py
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.enums import HelpRung, VettingLevel
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import ItemId, SkillId, VerificationKind
from learnai.domain.items import AnswerSpec, Formula, Item, Provenance, Text
from learnai.domain.skills import Skill
from learnai.domain.turn import SkillPack, StudentSummary, TurnContext, TutorTurn, validate_turn

GRAPH = SkillGraph.build(
    [Skill(SkillId("s"), "math", "s", "can s", VerificationKind("cas_symbolic"), (), ())], []
)
ITEM = Item(
    ItemId("i"), SkillId("s"), Provenance.authored(), (Text("Factor "), Formula("x^2 + 3x + 2")),
    AnswerSpec("(x + 1)*(x + 2)"), (), 0.0, VettingLevel.MACHINE_VERIFIED,
)


def ctx(permitted=HelpRung.NUDGE) -> TurnContext:
    return TurnContext(
        SkillPack(SkillId("s"), "can s", "", ()),
        ITEM,
        StudentSummary(0.0, True, 0.0, ()),
        None,
        None,
        permitted,
    )


def test_the_default_response_always_passes_validation():
    tutor = FakeTutor()
    verifier = SympyVerifier()
    for _ in range(5):
        turn = tutor.respond(ctx())
        assert validate_turn(turn, ctx(), GRAPH, verifier).accepted


def test_a_none_permitted_context_yields_a_none_rung_turn_that_is_accepted():
    tutor = FakeTutor()
    context = ctx(HelpRung.NONE)
    turn = tutor.respond(context)
    assert turn.rung_used is HelpRung.NONE
    assert validate_turn(turn, context, GRAPH, SympyVerifier()).accepted


def test_the_script_is_played_in_order_then_falls_back():
    scripted = TutorTurn("scripted", HelpRung.NUDGE)
    tutor = FakeTutor([scripted])
    assert tutor.respond(ctx()) is scripted
    assert tutor.respond(ctx()).message != "scripted"


def test_contexts_are_recorded_for_assertions():
    tutor = FakeTutor()
    tutor.respond(ctx(HelpRung.NEXT_STEP))
    assert tutor.contexts_seen[0].permitted_rung is HelpRung.NEXT_STEP


def test_a_scripted_leak_is_caught_by_validation():
    tutor = FakeTutor([TutorTurn("It is (x+1)(x+2).", HelpRung.NUDGE)])
    result = validate_turn(tutor.respond(ctx()), ctx(), GRAPH, SympyVerifier())
    assert not result.accepted
