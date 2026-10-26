"""SDK-free controls for the documented Responses compatibility profile."""
from collections.abc import Mapping
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from learnai.adapters.tutor.configuration import ResolvedRoleConfig, schema_hash
from learnai.adapters.tutor.prompts import load_prompt
from learnai.adapters.tutor.routing import BudgetProfile, Route
from learnai.adapters.tutor.tools import tool_definitions

ROLE_DEPENDENCIES = {'tutor': ('openai', 'httpx2'), 'judge': ('openai', 'httpx2')}
USAGE_MAPPER_ID = 'openai-responses@1'
TOKEN_COUNTER_ID = 'utf8-bytes-plus-256@1'
_OPTIONS = {'prompt_cache_key', 'prompt_cache_retention', 'service_tier'}


def validate_route(route: Route, *, role: str) -> None:
    """Reject unsupported controls locally; never silently drop selected options."""
    if role not in ('tutor', 'judge'):
        raise ValueError(f'unsupported role: {role!r}')
    if route.adapter != 'openai':
        raise ValueError('expected OpenAI route')
    if route.thinking is not None:
        raise ValueError('OpenAI routes must omit thinking')
    if route.effort is not None and route.effort not in ('none', 'low', 'medium', 'high', 'xhigh'):
        raise ValueError(f'unsupported effort: {route.effort}')
    if route.temperature is not None and (
        (route.effort or 'none') != 'none' or not 0 <= route.temperature <= 2
    ):
        raise ValueError('temperature requires effort none and range [0, 2]')
    if route.prompt is None:
        raise ValueError(f'{role} route {route.name} requires an explicit prompt')
    options = route.provider_options
    if unknown := options.keys() - _OPTIONS:
        raise ValueError(f'unsupported OpenAI provider_options: {", ".join(sorted(unknown))}')
    if 'prompt_cache_key' in options and (
        not isinstance(options['prompt_cache_key'], str) or not options['prompt_cache_key'].strip()
        or len(options['prompt_cache_key']) > 64
    ):
        raise ValueError('prompt_cache_key requires 1–64 characters')
    if 'prompt_cache_retention' in options and options['prompt_cache_retention'] not in ('in_memory', '24h'):
        raise ValueError('unsupported prompt_cache_retention')
    if 'service_tier' in options and options['service_tier'] not in ('default', 'flex', 'priority'):
        raise ValueError('service_tier must explicitly select default, flex or priority')


def request_settings(route: Route) -> dict[str, object]:
    validate_route(route, role='tutor')
    settings: dict[str, object] = {'model': route.model, 'max_output_tokens': route.max_tokens,
        'stream': route.stream, 'store': False, 'include': ['reasoning.encrypted_content'],
        'reasoning': {'effort': route.effort or 'none'}, 'truncation': 'disabled'}
    if route.temperature is not None:
        settings['temperature'] = route.temperature
    for key in _OPTIONS:
        if key in route.provider_options:
            settings[key] = route.provider_options[key]
    return settings


def final_settings(route: Route, schema: dict, *, name: str) -> dict[str, object]:
    from copy import deepcopy
    return {**request_settings(route), 'text': {'format': {'type': 'json_schema',
        'name': name, 'strict': True, 'schema': deepcopy(schema)}}}


def resolve_config(route: Route, *, role: str, profiles: Mapping[str, BudgetProfile],
                   prompts_root: Path) -> ResolvedRoleConfig:
    from learnai.adapters.tutor.openai.encoding import TURN_SCHEMA, encode_tools
    validate_route(route, role=role)
    if route.budget_profile not in profiles:
        raise ValueError(f'unknown budget profile: {route.budget_profile}')
    if role == 'tutor':
        schema, name = TURN_SCHEMA, 'tutor_turn'
        definitions = tool_definitions()
        hashes = {'final_output': schema_hash(schema),
            'canonical_read_tools': schema_hash([asdict(tool) for tool in definitions]),
            'wire_read_tools': schema_hash(encode_tools(definitions))}
    else:
        from learnai.eval.judge import SCORE_SCHEMA
        schema, name = SCORE_SCHEMA, 'rubric_scores'
        hashes = {'final_output': schema_hash(schema)}
    dependencies = {}
    for distribution in ROLE_DEPENDENCIES[role]:
        try:
            dependencies[distribution] = version(distribution)
        except PackageNotFoundError:
            dependencies[distribution] = None
    return ResolvedRoleConfig('openai', 'responses', role, route, profiles[route.budget_profile],
        load_prompt(route.prompt, root=prompts_root), final_settings(route, schema, name=name),
        hashes, dependencies, USAGE_MAPPER_ID, TOKEN_COUNTER_ID)
