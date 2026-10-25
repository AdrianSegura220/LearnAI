from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from learnai.adapters.tutor.anthropic.routing import (
    load_budget_profiles,
    load_routes,
    parse_routes,
    resolve_route,
    resolve_tutor_route,
)
from learnai.domain.interaction import ResponseJob


@pytest.fixture
def raw() -> dict:
    return {
        "budget_profiles": {
            "normal": {
                "soft_seconds": 8,
                "hard_seconds": 15,
                "max_round_trips": 8,
                "max_tool_calls": 16,
                "max_output_tokens": 8192,
                "context_input_tokens": 16000,
                "finalization_reserve_tokens": 1024,
            },
        },
        "routes": {
            "tutor_dialogue": {
                "adapter": "anthropic",
                "model": "scripted",
                "prompt": "tutor_math@1",
            },
        },
    }


def write_config(tmp_path: Path, raw: dict) -> Path:
    path = tmp_path / "routes.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_profile_counts_calls_and_round_trips_separately(tmp_path, raw):
    profiles = load_budget_profiles(write_config(tmp_path, raw))
    assert profiles["normal"].max_round_trips == 8
    assert profiles["normal"].max_tool_calls == 16


@pytest.mark.parametrize("field", [
    "soft_seconds", "hard_seconds", "max_round_trips", "max_tool_calls",
    "max_output_tokens", "context_input_tokens", "finalization_reserve_tokens",
])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1, True])
def test_invalid_budget_values_fail_fast(raw, field, value):
    raw["budget_profiles"]["normal"][field] = value
    with pytest.raises(ValueError):
        parse_routes(raw)


@pytest.mark.parametrize("field,value", [
    ("soft_seconds", 15), ("soft_seconds", 16),
    ("finalization_reserve_tokens", 8192),
    ("finalization_reserve_tokens", 8193),
    ("max_round_trips", 1.5), ("max_tool_calls", "16"),
])
def test_invalid_budget_boundaries_fail_fast(raw, field, value):
    raw["budget_profiles"]["normal"][field] = value
    with pytest.raises(ValueError):
        parse_routes(raw)


@pytest.mark.parametrize("job,name,profile", [
    (ResponseJob.BRIEF, "tutor_brief", "brief"),
    (ResponseJob.NORMAL, "tutor_dialogue", "normal"),
    (ResponseJob.SUBSTANTIAL, "tutor_explanation", "substantial"),
    (ResponseJob.COMPLEX, "tutor_complex", "complex"),
])
def test_route_resolves_job_profile(raw, job, name, profile):
    raw["budget_profiles"][profile] = deepcopy(raw["budget_profiles"]["normal"])
    raw["routes"][name] = {
        "adapter": "anthropic", "model": "scripted",
        "budget_profile": profile, "prompt": "tutor_math@1",
    }
    route = resolve_tutor_route(parse_routes(raw), job)
    assert (route.name, route.budget_profile) == (name, profile)


def test_complex_requires_an_explicit_route(raw):
    with pytest.raises(ValueError, match="tutor_complex"):
        resolve_tutor_route(parse_routes(raw), ResponseJob.COMPLEX)


@pytest.mark.parametrize("field,value", [
    ("budget_profile", "absent"), ("max_tool_iterations", 3),
    ("adapter", "unknown"), ("model", ""), ("model", None),
    ("max_tokens", True), ("max_tokens", 0), ("max_tokens", 1.5),
    ("stream", "false"), ("effort", "urgent"), ("thinking", "magic"),
    ("temperature", True), ("temperature", float("nan")),
    ("temperature", -1), ("temperature", 2),
    ("prompt", "../tutor_math@1"), ("prompt", "tutor_math@0"),
])
def test_unknown_profile_and_old_iteration_key_fail(raw, field, value):
    raw["routes"]["tutor_dialogue"][field] = value
    with pytest.raises(ValueError):
        parse_routes(raw)


def test_missing_model_fails(raw):
    del raw["routes"]["tutor_dialogue"]["model"]
    with pytest.raises(ValueError, match="model"):
        parse_routes(raw)


def test_unknown_route_fails(raw):
    with pytest.raises(ValueError, match="missing"):
        resolve_route(parse_routes(raw), "missing")


@pytest.mark.parametrize("section", ["root", "profile", "route"])
def test_unknown_fields_fail(raw, section):
    target = {"root": raw, "profile": raw["budget_profiles"]["normal"],
              "route": raw["routes"]["tutor_dialogue"]}[section]
    target["typo"] = 1
    with pytest.raises(ValueError):
        parse_routes(raw)


@pytest.mark.parametrize("document", [None, [], {"routes": {}},
    {"budget_profiles": [], "routes": {}},
    {"budget_profiles": {"normal": []}, "routes": {}},
    {"budget_profiles": {}, "routes": []},
    {"budget_profiles": {}, "routes": {"broken": []}},
])
def test_malformed_schema_fails(document):
    with pytest.raises(ValueError):
        parse_routes(document)


@pytest.mark.parametrize("loader", [load_routes, load_budget_profiles])
def test_invalid_yaml_fails_as_configuration_error(tmp_path, loader):
    path = tmp_path / "broken.yaml"
    path.write_text("routes: [", encoding="utf-8")
    with pytest.raises(ValueError):
        loader(path)


def test_load_routes_keeps_provider_settings_without_loading_prompts(tmp_path, raw):
    raw["routes"]["tutor_dialogue"].update(
        effort="medium", thinking="adaptive", max_tokens=3072, stream=True,
    )
    route = load_routes(write_config(tmp_path, raw))["tutor_dialogue"]
    assert (route.effort, route.thinking, route.temperature) == ("medium", "adaptive", None)
    assert (route.max_tokens, route.stream, route.budget_profile) == (3072, True, "normal")


def test_reserved_route_can_omit_prompt(raw):
    raw["routes"]["error_diagnosis"] = {"adapter": "anthropic", "model": "scripted"}
    assert parse_routes(raw)["error_diagnosis"].prompt is None


def test_initial_configuration_loads_job_budgets():
    path = Path(__file__).resolve().parents[3] / "config" / "llm_routes.yaml"
    routes = load_routes(path)
    profiles = load_budget_profiles(path)
    assert set(routes) == {
        "tutor_dialogue", "tutor_brief", "tutor_explanation", "error_diagnosis", "rubric_judge",
    }
    assert set(profiles) == {"brief", "normal", "substantial", "complex"}
    for job, expected in [
        (ResponseJob.BRIEF, (3, 8, 4, 8, 4096, 16000, 512)),
        (ResponseJob.NORMAL, (8, 15, 8, 16, 8192, 16000, 1024)),
        (ResponseJob.SUBSTANTIAL, (20, 30, 12, 24, 16384, 24000, 1024)),
    ]:
        profile = profiles[resolve_tutor_route(routes, job).budget_profile]
        assert (
            profile.soft_seconds, profile.hard_seconds, profile.max_round_trips,
            profile.max_tool_calls, profile.max_output_tokens, profile.context_input_tokens,
            profile.finalization_reserve_tokens,
        ) == expected
    complex_profile = profiles["complex"]
    assert (complex_profile.soft_seconds, complex_profile.hard_seconds,
            complex_profile.max_round_trips, complex_profile.max_tool_calls,
            complex_profile.max_output_tokens, complex_profile.context_input_tokens,
            complex_profile.finalization_reserve_tokens) == (30, 60, 20, 40, 32768, 32000, 2048)
