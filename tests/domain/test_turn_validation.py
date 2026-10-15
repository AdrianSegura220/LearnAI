# tests/domain/test_turn_validation.py
from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.domain.enums import HelpRung, PrereqStrength, VettingLevel
from learnai.domain.graph import SkillGraph
from learnai.domain.ids import ItemId, SkillId, VerificationKind
from learnai.domain.items import AnswerSpec, Formula, Item, Provenance, Text
from learnai.domain.skills import PrereqEdge, Skill
from learnai.domain.turn import (
    Proposal,
    ProposalKind,
    RejectionReason,
    SkillPack,
    StudentSummary,
    TurnContext,
    TutorTurn,
    validate_turn,
)

VERIFIER = SympyVerifier()


def _skill(sid: str) -> Skill:
    return Skill(SkillId(sid), "math", sid, f"can {sid}", VerificationKind("cas_symbolic"), (), ())


GRAPH = SkillGraph.build(
    [_skill("quad.expand.binomial"), _skill("quad.factor.monic"), _skill("unrelated")],
    [PrereqEdge(SkillId("quad.expand.binomial"), SkillId("quad.factor.monic"), PrereqStrength.HARD)],
)

ITEM = Item(
    id=ItemId("i1"),
    skill_id=SkillId("quad.factor.monic"),
    provenance=Provenance.authored(),
    statement=(Text("Factor "), Formula("x^2 + 3x + 2")),
    answer_spec=AnswerSpec("(x + 1)*(x + 2)"),
    worked_steps=(),
    difficulty=0.0,
    vetting_level=VettingLevel.MACHINE_VERIFIED,
)


def context(permitted: HelpRung = HelpRung.NUDGE) -> TurnContext:
    return TurnContext(
        skill_pack=SkillPack(SkillId("quad.factor.monic"), "can factor", "notes", ()),
        item=ITEM,
        student_summary=StudentSummary(0.0, True, 0.0, ()),
        step_diff=None,
        diagnosis=None,
        permitted_rung=permitted,
    )


def test_a_clean_nudge_is_accepted():
    turn = TutorTurn("What multiplies to 2 and adds to 3?", HelpRung.NUDGE)
    assert validate_turn(turn, context(), GRAPH, VERIFIER).accepted


def test_a_turn_above_the_permitted_rung_is_rejected():
    turn = TutorTurn("Here is the method in full.", HelpRung.NAME_METHOD)
    result = validate_turn(turn, context(HelpRung.NUDGE), GRAPH, VERIFIER)
    assert not result.accepted and result.reason is RejectionReason.RUNG_EXCEEDED


def test_a_leaking_turn_is_rejected_even_at_a_permitted_rung():
    turn = TutorTurn("Just write (x+1)(x+2).", HelpRung.NUDGE)
    result = validate_turn(turn, context(HelpRung.NUDGE), GRAPH, VERIFIER)
    assert not result.accepted and result.reason is RejectionReason.ANSWER_LEAKED


def test_the_same_turn_is_fine_once_a_reveal_is_permitted():
    turn = TutorTurn("Just write (x+1)(x+2).", HelpRung.FULL_REVEAL)
    assert validate_turn(turn, context(HelpRung.FULL_REVEAL), GRAPH, VERIFIER).accepted


def test_a_valid_prerequisite_proposal_is_accepted():
    turn = TutorTurn(
        "Let us go back a step.",
        HelpRung.NUDGE,
        proposals=(Proposal(ProposalKind.DROP_TO_PREREQUISITE, SkillId("quad.expand.binomial")),),
    )
    assert validate_turn(turn, context(), GRAPH, VERIFIER).accepted


def test_a_proposal_to_an_unrelated_skill_is_rejected():
    turn = TutorTurn(
        "Let us try something else.",
        HelpRung.NUDGE,
        proposals=(Proposal(ProposalKind.DROP_TO_PREREQUISITE, SkillId("unrelated")),),
    )
    result = validate_turn(turn, context(), GRAPH, VERIFIER)
    assert not result.accepted and result.reason is RejectionReason.INVALID_PROPOSAL


def test_a_prerequisite_proposal_with_no_target_is_rejected():
    turn = TutorTurn(
        "Back a step.", HelpRung.NUDGE, proposals=(Proposal(ProposalKind.DROP_TO_PREREQUISITE),)
    )
    assert not validate_turn(turn, context(), GRAPH, VERIFIER).accepted


def test_an_empty_message_is_rejected():
    result = validate_turn(TutorTurn("   ", HelpRung.NUDGE), context(), GRAPH, VERIFIER)
    assert not result.accepted and result.reason is RejectionReason.EMPTY_MESSAGE
