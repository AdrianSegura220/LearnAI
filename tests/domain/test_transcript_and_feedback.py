import pytest

from learnai.adapters.cas.sympy_verifier import SympyVerifier
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.domain.enums import HelpRung
from learnai.domain.turn import TutorTurn, request_validated_turn
from tests.domain.test_engine import build
from tests.domain.test_interaction import question


class TrackedExchange:
    def __init__(self, turns, *, stop_reason=None):
        self.turns = iter(turns)
        self.feedback = []
        self.validations = []
        self.finished = []
        self.stop_reason = stop_reason
        self.is_expired = False

    def respond(self, *, feedback=None):
        self.feedback.append(feedback)
        return next(self.turns)

    def expired(self):
        return self.is_expired

    def record_validation(self, result):
        self.validations.append(result)

    def finish(self, *, accepted, reason):
        self.finished.append((accepted, reason))


class ExchangeTutor:
    def __init__(self, exchange):
        self.exchange = exchange
        self.contexts = []

    def begin_turn(self, context):
        self.contexts.append(context)
        return self.exchange


def context():
    tutor = FakeTutor()
    engine, session, _ = build(tutor)
    engine.ask_question(session, {}, question(session.current_task))
    return engine, tutor.contexts_seen[0]


def test_one_exchange_survives_corrective_validation():
    engine, ctx = context()
    rejected = TutorTurn("Here is everything.", HelpRung.FULL_REVEAL)
    accepted = TutorTurn("Check the previous line.", HelpRung.NUDGE)
    exchange = TrackedExchange([rejected, accepted])
    tutor = ExchangeTutor(exchange)
    turn, attempts = request_validated_turn(tutor, ctx, engine.graph, SympyVerifier(), max_attempts=2)
    assert turn is accepted and attempts == 2
    assert len(tutor.contexts) == 1
    assert exchange.feedback[0] is None
    assert exchange.feedback[1].rejected is rejected
    assert exchange.feedback[1].reason.value == "rung_exceeded"
    assert [r.accepted for r in exchange.validations] == [False, True]
    assert exchange.finished == [(accepted, "accepted")]


def test_expiry_after_validation_prevents_delivery():
    engine, ctx = context()
    exchange = TrackedExchange([TutorTurn("Check the previous line.", HelpRung.NUDGE)])
    class ExpiringVerifier(SympyVerifier):
        def extract_candidate_expressions(self, text):
            exchange.is_expired = True
            return super().extract_candidate_expressions(text)
    turn, attempts = request_validated_turn(ExchangeTutor(exchange), ctx, engine.graph,
                                            ExpiringVerifier(), max_attempts=2)
    assert turn is None and attempts == 1
    assert exchange.finished == [(None, "deadline")]


@pytest.mark.parametrize("reason", ["api_error", "context_limit", "tool_limit", "token_limit", "format_exhausted"])
def test_operational_stop_reason_survives_silence(reason):
    engine, ctx = context()
    exchange = TrackedExchange([None], stop_reason=reason)
    turn, attempts = request_validated_turn(ExchangeTutor(exchange), ctx, engine.graph,
                                           SympyVerifier(), max_attempts=2)
    assert turn is None and attempts == 1
    assert exchange.finished == [(None, reason)]


def test_nonpositive_attempt_limit_rejected_before_exchange():
    engine, ctx = context()
    tutor = ExchangeTutor(TrackedExchange([]))
    with pytest.raises(ValueError):
        request_validated_turn(tutor, ctx, engine.graph, SympyVerifier(), max_attempts=0)
    assert tutor.contexts == []


def test_transcript_has_only_delivered_tutor_messages():
    rejected = TutorTurn("Here is everything.", HelpRung.FULL_REVEAL)
    accepted = TutorTurn("Check the previous line.", HelpRung.NUDGE)
    tutor = FakeTutor([rejected, accepted])
    engine, session, _ = build(tutor)
    interaction = question(session.current_task)
    session, turn = engine.ask_question(session, {}, interaction)
    assert turn is accepted
    assert [e.speaker for e in session.transcript] == ["student", "tutor"]
    assert session.transcript[0].text == "(x+3)(x+4)\nx^2+4x+3x+12\n\nDo I add 4x and 3x?"
    assert session.transcript[1].text == accepted.message
    ctx = tutor.contexts_seen[0]
    assert len(ctx.transcript) == 1
    assert ctx.current_interaction_id == ctx.transcript[0].record_id
    assert all(e.record_id and e.at and e.task_id == interaction.task_id and e.revision == 0
               for e in session.transcript)


def test_expired_engine_exchange_delivers_no_transcript_or_assistance():
    accepted = TutorTurn("Check the previous line.", HelpRung.NUDGE)
    exchange = TrackedExchange([accepted])
    tutor = ExchangeTutor(exchange)
    engine, session, _ = build(tutor)
    class ExpiringVerifier(SympyVerifier):
        def extract_candidate_expressions(self, text):
            exchange.is_expired = True
            return super().extract_candidate_expressions(text)
    engine.verifiers = {kind: ExpiringVerifier() for kind in engine.verifiers}
    session, turn = engine.ask_question(session, {}, question(session.current_task))
    assert turn is None
    assert [entry.speaker for entry in session.transcript] == ["student"]
    assert len(session.history) == 1
    assert engine.evidence_log.events() == ()
    assert not session.current_task.help_state.help_taken
    assert exchange.finished == [(None, "deadline")]


def test_expired_exchange_does_not_start_a_model_attempt():
    engine, ctx = context()
    exchange = TrackedExchange([])
    exchange.is_expired = True
    turn, attempts = request_validated_turn(ExchangeTutor(exchange), ctx, engine.graph,
                                            SympyVerifier(), max_attempts=2)
    assert turn is None and attempts == 0
    assert exchange.finished == [(None, "deadline")]


def test_rejected_only_exchange_finishes_as_validation_exhausted():
    engine, ctx = context()
    rejected = TutorTurn("Here is everything.", HelpRung.FULL_REVEAL)
    exchange = TrackedExchange([rejected, rejected])
    turn, attempts = request_validated_turn(ExchangeTutor(exchange), ctx, engine.graph,
                                            SympyVerifier(), max_attempts=2)
    assert turn is None and attempts == 2
    assert exchange.finished == [(None, "validation_exhausted")]
