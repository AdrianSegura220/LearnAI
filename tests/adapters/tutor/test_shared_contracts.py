"""Shared semantics stay reusable while selected Anthropic routes stay strict."""
from dataclasses import replace

import pytest


def test_old_routing_imports_are_identity_preserving():
    from learnai.adapters.tutor import routing
    from learnai.adapters.tutor.anthropic import routing as old

    for name in ("Route", "BudgetProfile", "parse_routes", "load_routes",
                 "load_budget_profiles", "resolve_route", "resolve_tutor_route"):
        assert getattr(old, name) is getattr(routing, name)


def test_old_turn_imports_are_identity_preserving():
    from learnai.adapters.tutor import turn_schema
    from learnai.adapters.tutor.anthropic import turn_schema as old

    assert old.parse_turn is turn_schema.parse_turn
    assert old.TurnSchemaError is turn_schema.TurnSchemaError
    assert not hasattr(turn_schema, "TURN_SCHEMA")


def test_shared_route_accepts_other_provider_values_and_copies_options():
    from learnai.adapters.tutor.routing import Route

    options = {"reasoning_summary": "detailed"}
    route = Route("tutor_other", "openai", "fictional-openai", effort="minimal",
                  thinking="provider-specific", temperature=1.5, prompt="tutor_math@1",
                  provider_options=options)
    options["reasoning_summary"] = "changed"
    assert route.provider_options == {"reasoning_summary": "detailed"}
    assert (route.effort, route.thinking, route.temperature) == ("minimal", "provider-specific", 1.5)
    first = Route("first", "fictional", "scripted")
    second = Route("second", "fictional", "scripted")
    assert first.provider_options == second.provider_options == {}
    assert first.provider_options is not second.provider_options


@pytest.mark.parametrize("changes", [
    {"adapter": ""}, {"effort": 1}, {"effort": ""}, {"thinking": True},
    {"thinking": " "}, {"temperature": True}, {"temperature": float("inf")},
    {"max_tokens": 0}, {"stream": 1}, {"prompt": "invalid"},
    {"provider_options": []}, {"provider_options": {1: "bad key"}},
])
def test_shared_route_rejects_structural_errors(changes):
    from learnai.adapters.tutor.routing import Route

    with pytest.raises(ValueError):
        Route(**(dict(name="selected", adapter="fictional", model="scripted") | changes))


@pytest.mark.parametrize("role", ["tutor", "judge"])
@pytest.mark.parametrize("changes,match", [
    ({"adapter": "openai"}, "adapter"), ({"effort": "minimal"}, "effort"),
    ({"thinking": "enabled"}, "thinking"), ({"temperature": 0}, "temperature"),
    ({"provider_options": {"reasoning_summary": "detailed"}}, "provider_options"),
    ({"prompt": None}, "prompt"),
])
def test_anthropic_validator_rejects_unsupported_selected_settings(role, changes, match):
    from learnai.adapters.tutor.anthropic.config import validate_route
    from learnai.adapters.tutor.routing import Route

    route = Route("selected", "anthropic", "scripted", prompt="tutor_math@1")
    with pytest.raises(ValueError, match=match):
        validate_route(replace(route, **changes), role=role)


@pytest.mark.parametrize("role", ["tutor", "judge"])
@pytest.mark.parametrize("effort", [None, "low", "medium", "high", "xhigh", "max"])
def test_anthropic_validator_keeps_existing_supported_settings(role, effort):
    from learnai.adapters.tutor.anthropic.config import validate_route
    from learnai.adapters.tutor.routing import Route

    validate_route(Route("selected", "anthropic", "scripted", effort=effort,
                         thinking="adaptive", prompt="tutor_math@1"), role=role)


@pytest.mark.parametrize("role", ["other", "", None])
def test_anthropic_validator_requires_an_explicit_supported_role(role):
    from learnai.adapters.tutor.anthropic.config import validate_route
    from learnai.adapters.tutor.routing import Route

    with pytest.raises(ValueError, match="role"):
        validate_route(Route("selected", "anthropic", "scripted", prompt="tutor_math@1"), role=role)


def test_anthropic_request_settings_encode_common_controls_without_a_role_schema():
    from learnai.adapters.tutor.anthropic.config import request_settings
    from learnai.adapters.tutor.routing import Route

    route = Route("selected", "anthropic", "scripted", effort="high", thinking="adaptive",
                  max_tokens=3072, stream=True, prompt="tutor_math@1")
    settings = request_settings(route)
    assert settings == {"model": "scripted", "max_tokens": 3072, "stream": True,
                        "output_config": {"effort": "high"}, "thinking": {"type": "adaptive"}}
    settings["output_config"]["effort"] = "low"
    assert request_settings(route)["output_config"]["effort"] == "high"
    assert request_settings(replace(route, effort=None, thinking=None)) == {
        "model": "scripted", "max_tokens": 3072, "stream": True,
    }


@pytest.mark.parametrize("changes", [
    {"adapter": "openai"}, {"effort": "minimal"}, {"thinking": "enabled"},
    {"provider_options": {"unknown": True}},
])
def test_anthropic_tutor_rejects_invalid_selection_before_provider_requests(changes):
    from learnai.adapters.content.registry import GeneratorRegistry
    from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
    from learnai.adapters.tutor.routing import Route
    from tests.support.scripted_client import ScriptedAnthropic

    sdk = ScriptedAnthropic([])
    route = Route("tutor_dialogue", "anthropic", "scripted", prompt="tutor_math@1")
    with pytest.raises(ValueError):
        AnthropicTutor({route.name: replace(route, **changes)}, sdk.client, GeneratorRegistry(()), {})
    assert sdk.requests == []


@pytest.mark.parametrize("changes", [
    {"adapter": "openai"}, {"effort": "minimal"}, {"thinking": "enabled"},
    {"provider_options": {"unknown": True}}, {"prompt": None},
])
def test_anthropic_judge_rejects_invalid_selection_before_provider_requests(changes):
    from learnai.adapters.tutor.anthropic.judge import request_judgment
    from learnai.adapters.tutor.prompts import load_prompt
    from learnai.adapters.tutor.routing import Route
    from tests.support.scripted_client import ScriptedAnthropic

    sdk = ScriptedAnthropic([])
    route = Route("rubric_judge", "anthropic", "scripted", prompt="rubric_judge@1")
    with pytest.raises(ValueError):
        request_judgment(sdk.client, replace(route, **changes), prompt=load_prompt("rubric_judge@1"),
                         messages=(), schema={}, parse=lambda text: text)
    assert sdk.requests == []
