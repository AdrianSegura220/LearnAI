"""SDK-free validation and request controls for Anthropic routes."""

from learnai.adapters.tutor.routing import Route


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
