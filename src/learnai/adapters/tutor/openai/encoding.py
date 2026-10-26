"""SDK-free strict schemas, context selection, and stateless Responses payloads."""
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import json

from learnai.adapters.tutor.configuration import PreparedRequest, ResolvedRoleConfig
from learnai.adapters.tutor.context import ContextLimitError, render_context, select_context
from learnai.adapters.tutor.rendering import render_session_preamble, render_skill_pack
from learnai.adapters.tutor.tools import ToolDefinition, tool_definitions
from learnai.domain.enums import HelpRung
from learnai.domain.turn import ProposalKind, TurnContext, TurnFeedback

TURN_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'properties': {'message': {'type': 'string'},
        'rung_used': {'type': 'string', 'enum': [r.name for r in HelpRung]},
        'diagnosis': {'type': ['string', 'null']},
        'proposals': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
            'properties': {'kind': {'type': 'string', 'enum': [k.name for k in ProposalKind]},
                'target_skill_id': {'type': ['string', 'null']}},
            'required': ['kind', 'target_skill_id']}}},
    'required': ['message', 'rung_used', 'diagnosis', 'proposals']}


def strict_schema(schema: Mapping[str, object]) -> dict:
    """Encode optional canonical fields as required nullable fields recursively."""
    result = deepcopy(dict(schema))
    result.pop('default', None)
    if result.get('type') == 'object':
        required = set(result.get('required', []))
        properties = {}
        for name, definition in result.get('properties', {}).items():
            child = strict_schema(definition)
            if name not in required:
                kind = child['type']
                child['type'] = list(dict.fromkeys((kind if isinstance(kind, list) else [kind]) + ['null']))
                if 'enum' in child and None not in child['enum']:
                    child['enum'].append(None)
            properties[name] = child
        result.update(properties=properties, required=list(properties), additionalProperties=False)
    if 'items' in result:
        result['items'] = strict_schema(result['items'])
    return result


def encode_tools(definitions: Sequence[ToolDefinition]) -> list[dict]:
    return [{'type': 'function', 'name': tool.name, 'description': tool.description,
             'parameters': strict_schema(tool.parameters), 'strict': True} for tool in definitions]


def normalize_tool_arguments(name: str, arguments: object) -> object:
    """Remove only nulls introduced for declared optional canonical arguments."""
    if not isinstance(arguments, Mapping):
        return arguments
    definition = next((tool for tool in tool_definitions() if tool.name == name), None)
    if definition is None:
        return dict(arguments)
    optional = definition.parameters['properties'].keys() - set(definition.parameters['required'])
    return {key: value for key, value in arguments.items() if not (key in optional and value is None)}


def require_config(config: ResolvedRoleConfig, *, role: str) -> None:
    if config.provider != 'openai' or config.api_family != 'responses' or config.role != role:
        raise ValueError(f'expected OpenAI Responses {role} configuration')


def tutor_payload(config: ResolvedRoleConfig, *, instructions: str, inputs: list[dict],
                  tools: list[dict], explore: bool, remaining_output: int) -> dict:
    available = remaining_output - (config.profile.finalization_reserve_tokens if explore else 0)
    return {**deepcopy(dict(config.effective_settings)), 'instructions': instructions,
        'input': deepcopy(inputs), 'tools': deepcopy(tools), 'tool_choice': 'auto' if explore else 'none',
        'max_output_tokens': min(config.route.max_tokens, available)}


def prepare_tutor(config: ResolvedRoleConfig, *, context: TurnContext,
                  count_tokens: Callable[[str], int]) -> PreparedRequest:
    require_config(config, role='tutor')
    instructions = '\n\n'.join(filter(None, (config.prompt.text, render_skill_pack(context),
                                               render_session_preamble(context))))
    tools = encode_tools(tool_definitions())
    explore = config.profile.max_round_trips > 1
    def payload(text):
        return tutor_payload(config, instructions=instructions,
            inputs=[{'role': 'user', 'content': text}], tools=tools, explore=explore,
            remaining_output=config.profile.max_output_tokens)
    def counter(text):
        return count_tokens(json.dumps(payload(text), ensure_ascii=False, separators=(',', ':')))
    reservation = payload('')['max_output_tokens']
    try:
        view = select_context(context, input_budget=max(0, config.profile.context_input_tokens - reservation),
                              count_tokens=counter)
        admitted = True
    except ContextLimitError as exc:
        view, admitted = exc.context_view, False
    body = payload(render_context(context, view))
    units = count_tokens(json.dumps(body, ensure_ascii=False, separators=(',', ':')))
    return PreparedRequest(body, units, reservation,
        admitted and units + reservation <= config.profile.context_input_tokens, view)


def correction_item(feedback: TurnFeedback | str) -> dict:
    text = feedback if isinstance(feedback, str) else json.dumps(
        {'reason': feedback.reason.name, 'detail': feedback.detail}, ensure_ascii=False, separators=(',', ':'))
    return {'role': 'developer', 'content': 'Correct the tutor response using this private feedback: ' + text}
