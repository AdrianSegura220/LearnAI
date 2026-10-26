"""Validated provider routes and request-scoped execution allowances."""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from math import isfinite
from pathlib import Path
from typing import Any

import yaml

from learnai.adapters.tutor.prompts import _parse_reference
from learnai.domain.interaction import ResponseJob


def _positive_limit(value: Any, name: str, *, integer: bool = True) -> None:
    expected = (int,) if integer else (int, float)
    if (isinstance(value, bool) or not isinstance(value, expected)
            or value <= 0 or not isfinite(value)):
        raise ValueError(f"{name} must be a positive finite {'integer' if integer else 'number'}")


def _nonempty_string(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


@dataclass(frozen=True, slots=True)
class BudgetProfile:
    """One response allowance, shared by all retries and model/tool rounds.

    Round trips count model calls; tool calls count individual reads, excluding
    submit_turn. Output tokens include thinking and retries. The input allowance
    covers protected and selected context; finalization reserves output tokens.
    """

    soft_seconds: float
    hard_seconds: float
    max_round_trips: int
    max_tool_calls: int
    max_output_tokens: int
    context_input_tokens: int
    finalization_reserve_tokens: int

    def __post_init__(self) -> None:
        for field in fields(self):
            _positive_limit(getattr(self, field.name), field.name,
                            integer=field.name not in {"soft_seconds", "hard_seconds"})
        if self.soft_seconds >= self.hard_seconds:
            raise ValueError("soft_seconds must be less than hard_seconds")
        if self.finalization_reserve_tokens >= self.max_output_tokens:
            raise ValueError("finalization reserve must be less than output token allowance")


@dataclass(frozen=True, slots=True)
class Route:
    name: str
    adapter: str
    model: str
    effort: str | None = None
    thinking: str | None = None
    temperature: float | None = None
    max_tokens: int = 2048
    stream: bool = False
    prompt: str | None = None
    budget_profile: str = "normal"

    def __post_init__(self) -> None:
        for name in ("name", "adapter", "model", "budget_profile"):
            _nonempty_string(getattr(self, name), name)
        if self.adapter != "anthropic":
            raise ValueError(f"unknown adapter: {self.adapter}")
        if self.effort is not None and self.effort not in ("low", "medium", "high", "xhigh", "max"):
            raise ValueError(f"unknown effort: {self.effort}")
        if self.thinking is not None and self.thinking != "adaptive":
            raise ValueError(f"unsupported thinking: {self.thinking}")
        if self.temperature is not None:
            if (isinstance(self.temperature, bool)
                    or not isinstance(self.temperature, (int, float))
                    or not isfinite(self.temperature) or not 0 <= self.temperature <= 1):
                raise ValueError("temperature must be finite and between zero and one")
        _positive_limit(self.max_tokens, "max_tokens")
        if not isinstance(self.stream, bool):
            raise ValueError("stream must be boolean")
        if self.prompt is not None:
            _parse_reference(self.prompt)


def _mapping(value: Any, name: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def _reject_unknown(raw: Mapping, allowed: set[str], name: str) -> None:
    if unknown := raw.keys() - allowed:
        raise ValueError(f"unknown {name} fields: {', '.join(sorted(map(str, unknown)))}")


def _parse_config(raw: Mapping) -> tuple[dict[str, Route], dict[str, BudgetProfile]]:
    raw = _mapping(raw, "configuration")
    _reject_unknown(raw, {"budget_profiles", "routes", "pricing"}, "configuration")
    profile_entries = _mapping(raw.get("budget_profiles"), "budget_profiles")
    route_entries = _mapping(raw.get("routes"), "routes")
    profiles: dict[str, BudgetProfile] = {}
    profile_fields = {field.name for field in fields(BudgetProfile)}
    for name, entry in profile_entries.items():
        _nonempty_string(name, "profile name")
        entry = _mapping(entry, f"profile {name}")
        _reject_unknown(entry, profile_fields, f"profile {name}")
        if missing := profile_fields - entry.keys():
            raise ValueError(f"profile {name} missing fields: {', '.join(sorted(missing))}")
        profiles[name] = BudgetProfile(**entry)
    routes: dict[str, Route] = {}
    route_fields = {field.name for field in fields(Route)} - {"name"}
    for name, entry in route_entries.items():
        _nonempty_string(name, "route name")
        entry = _mapping(entry, f"route {name}")
        _reject_unknown(entry, route_fields, f"route {name}")
        if missing := {"adapter", "model"} - entry.keys():
            raise ValueError(f"route {name} missing fields: {', '.join(sorted(missing))}")
        route = Route(name=name, **entry)
        if route.budget_profile not in profiles:
            raise ValueError(f"route {name} references unknown profile: {route.budget_profile}")
        routes[name] = route
    return routes, profiles


def parse_routes(raw: Mapping) -> dict[str, Route]:
    """Validate routes and profiles without accessing prompt files."""
    return _parse_config(raw)[0]


def _load_config(path: Path) -> tuple[dict[str, Route], dict[str, BudgetProfile]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load route configuration {path}: {exc}") from exc
    return _parse_config(raw)


def load_routes(path: Path) -> Mapping[str, Route]:
    return _load_config(path)[0]


def load_budget_profiles(path: Path) -> Mapping[str, BudgetProfile]:
    return _load_config(path)[1]


def resolve_route(routes: Mapping[str, Route], name: str) -> Route:
    try:
        return routes[name]
    except KeyError as exc:
        raise ValueError(f"unknown route: {name}") from exc


def resolve_tutor_route(routes: Mapping[str, Route], job: ResponseJob) -> Route:
    """Resolve explicitly selected work; complex jobs need their own route."""
    names = {
        ResponseJob.BRIEF: "tutor_brief",
        ResponseJob.NORMAL: "tutor_dialogue",
        ResponseJob.SUBSTANTIAL: "tutor_explanation",
        ResponseJob.COMPLEX: "tutor_complex",
    }
    if not isinstance(job, ResponseJob):
        raise ValueError(f"unknown response job: {job!r}")
    return resolve_route(routes, names[job])
