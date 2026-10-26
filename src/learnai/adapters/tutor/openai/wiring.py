"""Static OpenAI factory; resolving and preparing role calls never loads SDKs."""
from learnai.application.ports import ProviderClient, TutorDependencies
from learnai.adapters.tutor.configuration import PreparedRequest, ResolvedRoleConfig
from learnai.adapters.tutor.observations import TraceSink
from learnai.adapters.tutor.openai.config import ROLE_DEPENDENCIES, USAGE_MAPPER_ID, resolve_config, validate_route
from learnai.adapters.tutor.openai.encoding import prepare_judge, prepare_tutor
from learnai.adapters.tutor.runtime import conservative_token_count
from learnai.domain.ports import Tutor
from learnai.domain.turn import TurnContext
from learnai.eval.ports import Judge
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from learnai.eval.judge import JudgePacket


class OpenAIProviderFactory:
    provider = 'openai'
    api_family = 'responses'
    credential_env = 'OPENAI_API_KEY'
    sdk_distribution = 'openai'
    sdk_module = 'openai'
    usage_mapper_id = USAGE_MAPPER_ID
    schema_ids = {'tutor': 'openai-turn@1', 'judge': 'rubric-scores@1'}
    role_dependencies = ROLE_DEPENDENCIES
    validate_route = staticmethod(validate_route)
    resolve_config = staticmethod(resolve_config)

    def prepare_tutor(self, config: ResolvedRoleConfig, *, context: TurnContext,
                      dependencies: TutorDependencies) -> PreparedRequest:
        return prepare_tutor(config, context=context, count_tokens=conservative_token_count)

    def prepare_judge(self, config: ResolvedRoleConfig, *, packet: 'JudgePacket') -> PreparedRequest:
        return prepare_judge(config, packet=packet, count_tokens=conservative_token_count)

    def create_client(self, *, api_key: str) -> ProviderClient:
        from openai import OpenAI
        return OpenAI(api_key=api_key, max_retries=0)

    def create_tutor(self, *, config: ResolvedRoleConfig, client: ProviderClient,
                     dependencies: TutorDependencies, trace_sink: TraceSink) -> Tutor:
        from openai import OpenAI
        from learnai.adapters.tutor.openai.adapter import OpenAITutor
        if not isinstance(client, OpenAI):
            raise TypeError('OpenAIProviderFactory requires an OpenAI client')
        return OpenAITutor(config, client, dependencies.items, dependencies.catalogue, trace_sink=trace_sink)

    def create_judge(self, *, config: ResolvedRoleConfig, client: ProviderClient,
                     trace_sink: TraceSink) -> Judge:
        from openai import OpenAI
        from learnai.adapters.tutor.openai.judge import OpenAIJudge
        if not isinstance(client, OpenAI):
            raise TypeError('OpenAIProviderFactory requires an OpenAI client')
        return OpenAIJudge(config, client, trace_sink=trace_sink)


# Preserve the Task 5 construction name as the same static factory implementation.
OpenAIFactory = OpenAIProviderFactory
