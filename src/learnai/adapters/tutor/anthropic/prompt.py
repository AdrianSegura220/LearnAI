"""Anthropic prompt layering; generation and SDK mechanics are separate."""
from collections.abc import Callable
from dataclasses import dataclass
import json
from typing import Any

from learnai.adapters.tutor.context import ContextView, render_context, select_context
from learnai.adapters.tutor.rendering import render_session_preamble, render_skill_pack
from learnai.domain.turn import TurnContext, TurnFeedback


@dataclass(frozen=True, slots=True)
class SystemBlock:
    text: str
    cache: bool = False


@dataclass(frozen=True, slots=True)
class Prompt:
    system: tuple[SystemBlock, ...]
    messages: tuple[dict[str, Any], ...]
    context_view: ContextView


def build_prompt(
    context: TurnContext, policy: str, *, input_budget: int,
    count_tokens: Callable[[str], int],
) -> Prompt:
    """Cache policy/skill only; account for the entire text input in one count.

    The counter receives newline-joined system texts followed by the serialized
    volatile message. Task-specific provider/token framing can be included by
    the injected counter, without assuming that token counts are additive.
    """
    system = (SystemBlock(policy, cache=True), SystemBlock(render_skill_pack(context), cache=True))
    preamble = render_session_preamble(context)
    if preamble:
        system += (SystemBlock(preamble, cache=True),)
    prefix = "\n".join(block.text for block in system) + "\n"
    view = select_context(
        context, input_budget=input_budget,
        count_tokens=lambda volatile: count_tokens(prefix + volatile),
    )
    return Prompt(system, ({"role": "user", "content": render_context(context, view)},), view)


def correction_text(feedback: TurnFeedback) -> str:
    """Serialize private validation feedback for the retained provider exchange."""
    return json.dumps({"reason": feedback.reason.name, "detail": feedback.detail},
                      ensure_ascii=False, separators=(",", ":"))
