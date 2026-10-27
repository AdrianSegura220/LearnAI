"""Select one configured tutor at the start of an engine-owned exchange."""
from collections.abc import Callable, Mapping

from learnai.adapters.tutor.routing import Route
from learnai.domain.interaction import ResponseJob
from learnai.domain.ports import Tutor, TutorExchange
from learnai.domain.turn import TurnContext, TurnFeedback, TutorTurn


class TutorRouter:
    def __init__(self, routes: Mapping[ResponseJob, Route], create: Callable[[Route, TurnContext], Tutor]):
        self._routes = dict(routes)
        self._create = create

    def begin_turn(self, context: TurnContext) -> TutorExchange:
        try:
            route = self._routes[context.response_job]
        except KeyError as exc:
            raise ValueError(f'job was not selected for this operation: {context.response_job}') from exc
        return self._create(route, context).begin_turn(context)

    def respond(self, context: TurnContext, *, feedback: TurnFeedback | None = None) -> TutorTurn | None:
        exchange = self.begin_turn(context)
        turn = None
        try:
            turn = exchange.respond(feedback=feedback)
            if exchange.expired():
                turn = None
            return turn
        finally:
            exchange.finish(accepted=turn, reason=exchange.stop_reason or 'completed')
