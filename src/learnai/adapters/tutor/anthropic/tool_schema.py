"""Encode the shared read-tool table for Anthropic's tool API."""
from copy import deepcopy
from typing import Any

from learnai.adapters.tutor.tools import Tool, ToolDefinition


def encode_tools(tools: tuple[Tool | ToolDefinition, ...]) -> tuple[dict[str, Any], ...]:
    return tuple({"name": tool.name, "description": tool.description,
                  "input_schema": deepcopy(dict(tool.parameters))} for tool in tools)
