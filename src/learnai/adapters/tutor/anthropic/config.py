"""SDK-free validation and request controls for Anthropic routes."""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

from learnai.adapters.tutor.configuration import ResolvedRoleConfig, schema_hash
from learnai.adapters.tutor.routing import BudgetProfile, Route

ROLE_DEPENDENCIES = {'tutor': ('anthropic', 'httpx2'), 'judge': ('anthropic', 'httpx2')}
USAGE_MAPPER_ID = 'anthropic-messages@1'
TOKEN_COUNTER_ID = 'utf8-bytes-plus-256@1'


def validate_route(route: Route, *, role: str) -> None:
    """Validate a selected role without constraining other providers' routes."""
    if role not in ("tutor", "judge"):
        raise ValueError(f"unsupported role: {role!r}")
    if route.adapter != "anthropic":
        raise ValueError(f"unsupported Anthropic adapter: {route.adapter}")
    if route.effort is not None and route.effort not in ("low", "medium", "high", "xhigh", "max"):
        raise ValueError(f"unknown effort: {route.effort}")
    if route.thinking is not None and route.thinking != "adaptive":
        raise ValueError(f"unsupported thinking: {route.thinking}")
    if route.temperature is not None:
        raise ValueError(f"{role} routes must omit temperature")
    if route.provider_options:
        raise ValueError(f"unsupported Anthropic provider_options: {', '.join(sorted(route.provider_options))}")
    if route.prompt is None:
        raise ValueError(f"{role} route {route.name} requires an explicit prompt")


def request_settings(route: Route) -> dict[str, object]:
    """Encode shared request controls; each role adds its own wire schema."""
    result: dict[str, object] = {
        "model": route.model, "max_tokens": route.max_tokens, "stream": route.stream,
    }
    if route.effort is not None:
        result["output_config"] = {"effort": route.effort}
    if route.thinking is not None:
        result["thinking"] = {"type": route.thinking}
    return result


def final_settings(route: Route, schema: dict) -> dict:
    from copy import deepcopy
    result = request_settings(route)
    result.setdefault('output_config', {})['format'] = {
        'type': 'json_schema', 'schema': deepcopy(schema)}
    return result


def resolve_config(route: Route, *, role: str,
                   profiles: Mapping[str, BudgetProfile], prompts_root: Path) -> ResolvedRoleConfig:
    """Resolve actual encoding inputs once; distribution lookup never imports SDKs."""
    from dataclasses import asdict
    from importlib.metadata import PackageNotFoundError, version

    from learnai.adapters.tutor.prompts import load_prompt
    from learnai.adapters.tutor.tools import tool_definitions
    from learnai.adapters.tutor.anthropic.tool_schema import encode_tools
    from learnai.adapters.tutor.anthropic.turn_schema import TURN_SCHEMA
    from learnai.eval.judge import SCORE_SCHEMA

    validate_route(route, role=role)
    if route.budget_profile not in profiles:
        raise ValueError(f'unknown budget profile: {route.budget_profile}')
    schema = TURN_SCHEMA if role == 'tutor' else SCORE_SCHEMA
    hashes = {'final_output': schema_hash(schema)}
    if role == 'tutor':
        definitions = tool_definitions()
        hashes.update(canonical_read_tools=schema_hash([asdict(tool) for tool in definitions]),
                      wire_read_tools=schema_hash(encode_tools(definitions)))
    dependencies = {}
    for distribution in ROLE_DEPENDENCIES[role]:
        try:
            dependencies[distribution] = version(distribution)
        except PackageNotFoundError:
            dependencies[distribution] = None
    return ResolvedRoleConfig('anthropic', 'messages', cast(Literal['tutor', 'judge'], role), route,
        profiles[route.budget_profile], load_prompt(route.prompt, root=prompts_root),
        final_settings(route, schema), hashes, dependencies,
        USAGE_MAPPER_ID, TOKEN_COUNTER_ID)
