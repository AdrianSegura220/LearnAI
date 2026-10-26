"""Fictional provider ports with semantic scripts and explicit provider identity."""
from pathlib import Path
from uuid import uuid4

from learnai.adapters.tutor.configuration import PreparedRequest, ResolvedRoleConfig
from learnai.adapters.tutor.fake_tutor import FakeTutor
from learnai.adapters.tutor.observations import JudgeTrace, ProviderAttempt, UsageObservation, UsageStatus
from learnai.adapters.tutor.prompts import TutorPrompt
from learnai.adapters.tutor.runtime import TurnTrace
from learnai.eval.judge import JudgeScores


class RecordingFactory:
    api_family = 'fictional-api'
    sdk_distribution = 'pytest'
    sdk_module = 'pytest'
    usage_mapper_id = 'fictional@1'
    schema_ids = {'tutor': 'fictional-turn@1', 'judge': 'fictional-scores@1'}
    role_dependencies = {'tutor': ('pytest',), 'judge': ('pytest',)}

    def __init__(self, provider: str):
        self.provider = provider
        self.credential_env = provider.upper() + '_KEY'
        self.clients_created = self.clients_closed = 0
        self.requests = []
        self.prepared = []
        self.sinks = []
        self.fail_creation = False
        self.tutor_script = []
        self.scores = JudgeScores(2, 2, 2, 2, ('scripted assessment',))

    def validate_route(self, route, *, role):
        if route.adapter != self.provider or role not in ('tutor', 'judge'):
            raise ValueError('invalid fictional role/provider')

    def resolve_config(self, route, *, role, profiles, prompts_root):
        from importlib.metadata import version
        self.validate_route(route, role=role)
        return ResolvedRoleConfig(self.provider, self.api_family, role, route, profiles[route.budget_profile],
            TutorPrompt('fictional', 1, Path('fictional.md'), 'fictional policy'),
            {'model': route.model, 'default_control': 'resolved'},
            {'final_output': 'final-hash', 'canonical_read_tools': 'canonical-hash', 'wire_read_tools': 'wire-hash'},
            {'pytest': version('pytest')}, self.usage_mapper_id, 'fictional-counter@1')

    def prepare_tutor(self, config, *, context, dependencies):
        self.prepared.append(('tutor', context))
        return PreparedRequest({'model': config.route.model}, 1, 1, True)

    def prepare_judge(self, config, *, packet):
        self.prepared.append(('judge', packet))
        return PreparedRequest({'candidate': packet.turn.message}, 1, 1, True)

    def create_client(self, *, api_key):
        if self.fail_creation:
            raise RuntimeError('scripted client construction failed')
        self.clients_created += 1
        factory = self
        class Client:
            def close(self):
                factory.clients_closed += 1
        return Client()

    def create_tutor(self, *, config, client, dependencies, trace_sink):
        factory = self
        self.sinks.append(trace_sink)
        class Tutor(FakeTutor):
            def begin_turn(self, context):
                base = super().begin_turn(context)
                trace = TurnTrace(str(uuid4()), None, None, None, context.item.id, None,
                    (config.prompt.id,), config.route.model, dict(config.effective_settings),
                    provider=config.provider, api_family=config.api_family, route_name=config.route.name)
                original = base.respond
                def respond(*, feedback=None):
                    factory.requests.append(('tutor', config.route.name, context, feedback))
                    _attempt(trace)
                    return original(feedback=feedback)
                def finish(*, accepted, reason):
                    trace.accepted = accepted
                    trace_sink(trace)
                base.respond, base.finish = respond, finish
                return base
        return Tutor(factory.tutor_script)

    def create_judge(self, *, config, client, trace_sink):
        factory = self
        self.sinks.append(trace_sink)
        class Judge:
            def evaluate(self, packet):
                factory.requests.append(('judge', config.route.name, packet))
                trace = JudgeTrace(str(uuid4()), (config.prompt.id,), config.route.model,
                    dict(config.effective_settings), provider=config.provider,
                    api_family=config.api_family, route_name=config.route.name)
                _attempt(trace)
                trace_sink(trace)
                return factory.scores
        return Judge()


def _attempt(trace):
    trace.provider_requests.append({'model': trace.model})
    trace.attempts.append(ProviderAttempt(len(trace.provider_requests) - 1,
        normalized_usage=UsageObservation({}, UsageStatus.MISSING), usage_status=UsageStatus.MISSING))


def anthropic_override(create):
    """Explicit provider override for the existing real-SDK transport tests."""
    from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
    class Factory(AnthropicFactory):
        def create_client(self, *, api_key):
            return create(api_key=api_key, max_retries=0)
    return {'anthropic': Factory()}
