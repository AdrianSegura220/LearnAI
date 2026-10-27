"""Static SDK-free Anthropic factory; SDK imports occur only on selected creation."""
from typing import TYPE_CHECKING

from learnai.application.ports import ProviderClient, TutorDependencies
from learnai.adapters.tutor.configuration import PreparedRequest, ResolvedRoleConfig
from learnai.adapters.tutor.observations import TraceSink
from learnai.domain.ports import Tutor
from learnai.domain.turn import TurnContext
from learnai.eval.ports import Judge

if TYPE_CHECKING:
    from learnai.eval.judge import JudgePacket

from learnai.adapters.tutor.anthropic.config import ROLE_DEPENDENCIES, USAGE_MAPPER_ID, resolve_config, validate_route
from learnai.adapters.tutor.anthropic.prompt import prepare_judge, prepare_tutor
from learnai.adapters.tutor.runtime import conservative_token_count


class AnthropicFactory:
    provider = 'anthropic'
    api_family = 'messages'
    credential_env = 'ANTHROPIC_API_KEY'
    sdk_distribution = 'anthropic'
    sdk_module = 'anthropic'
    usage_mapper_id = USAGE_MAPPER_ID
    schema_ids = {'tutor': 'anthropic-turn@1', 'judge': 'rubric-scores@1'}
    role_dependencies = ROLE_DEPENDENCIES

    validate_route = staticmethod(validate_route)
    resolve_config = staticmethod(resolve_config)

    def prepare_tutor(self, config: ResolvedRoleConfig, *, context: TurnContext,
                      dependencies: TutorDependencies) -> PreparedRequest:
        return prepare_tutor(config, context=context, count_tokens=conservative_token_count)

    def prepare_judge(self, config: ResolvedRoleConfig, *, packet: "JudgePacket") -> PreparedRequest:
        return prepare_judge(config, packet=packet, count_tokens=conservative_token_count)

    def create_client(self, *, api_key: str) -> ProviderClient:
        import anthropic
        return anthropic.Anthropic(api_key=api_key, max_retries=0)

    def create_tutor(self, *, config: ResolvedRoleConfig, client: ProviderClient,
                     dependencies: TutorDependencies, trace_sink: TraceSink) -> Tutor:
        from anthropic import Anthropic
        from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
        if not isinstance(client, Anthropic):
            raise TypeError('AnthropicFactory requires an Anthropic client')
        return AnthropicTutor({config.route.name: config.route}, client,
            dependencies.items, dependencies.catalogue, resolved_config=config, trace_sink=trace_sink)

    def create_judge(self, *, config: ResolvedRoleConfig, client: ProviderClient,
                     trace_sink: TraceSink) -> Judge:
        from anthropic import Anthropic
        from learnai.adapters.tutor.anthropic.judge import AnthropicJudge
        if not isinstance(client, Anthropic):
            raise TypeError('AnthropicFactory requires an Anthropic client')
        return AnthropicJudge(config=config, client=client, trace_sink=trace_sink)
