"""Anthropic prompt layering; generation and SDK mechanics are separate."""
from collections.abc import Callable
from dataclasses import dataclass
import json
from typing import Any, TYPE_CHECKING

from learnai.adapters.tutor.configuration import PreparedRequest, ResolvedRoleConfig

if TYPE_CHECKING:
    from learnai.eval.judge import JudgePacket

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


def system_block(block: SystemBlock) -> dict[str, Any]:
    result = {'type': 'text', 'text': block.text}
    if block.cache:
        result['cache_control'] = {'type': 'ephemeral'}
    return result


def tutor_payload(config: ResolvedRoleConfig, *, system: list[dict], messages: list[dict],
                  tools: list[dict], explore: bool, remaining_output: int) -> dict[str, Any]:
    from copy import deepcopy
    available = remaining_output - (config.profile.finalization_reserve_tokens if explore else 0)
    return {**deepcopy(dict(config.effective_settings)),
        'max_tokens': min(config.route.max_tokens, available), 'system': system,
        'messages': messages, 'tools': tools, 'tool_choice': {'type': 'auto' if explore else 'none'}}


def prepare_tutor(config: ResolvedRoleConfig, *, context: TurnContext,
                  count_tokens: Callable[[str], int]) -> PreparedRequest:
    """Select context against the exact initial body, without running read tools."""
    from learnai.adapters.tutor.context import ContextLimitError, render_context
    from learnai.adapters.tutor.tools import tool_definitions
    from learnai.adapters.tutor.anthropic.tool_schema import encode_tools
    from learnai.adapters.tutor.anthropic.turn_schema import TURN_SCHEMA
    from copy import deepcopy

    require_config(config, role='tutor')
    system = [SystemBlock(config.prompt.text, cache=True), SystemBlock(render_skill_pack(context), cache=True)]
    if preamble := render_session_preamble(context):
        system.append(SystemBlock(preamble, cache=True))
    wire_system = [system_block(block) for block in system]
    tools = list(encode_tools(tool_definitions())) + [{'name': 'submit_turn',
        'description': 'Submit the final tutor turn for engine validation.', 'input_schema': deepcopy(TURN_SCHEMA)}]
    explore = config.profile.max_round_trips > 1
    def payload(messages):
        return tutor_payload(config, system=wire_system, messages=messages, tools=tools,
                             explore=explore, remaining_output=config.profile.max_output_tokens)
    def counter(text):
        return count_tokens(json.dumps(payload([{'role': 'user', 'content': text.rsplit('\n', 1)[-1]}]),
                                        ensure_ascii=False, separators=(',', ':')))
    reservation = payload([])['max_tokens']
    try:
        prompt = build_prompt(context, config.prompt.text,
            input_budget=max(0, config.profile.context_input_tokens - reservation), count_tokens=counter)
    except ContextLimitError as exc:
        # Protected content could not fit. Preserve the rejected actual body for inspection.
        view = exc.context_view
        body = payload([{'role': 'user', 'content': render_context(context, view)}])
        admitted = False
    else:
        view = prompt.context_view
        body = payload(list(prompt.messages))
        admitted = True
    units = count_tokens(json.dumps(body, ensure_ascii=False, separators=(',', ':')))
    return PreparedRequest(body, units, reservation,
                           admitted and units + reservation <= config.profile.context_input_tokens, view)


def require_config(config: ResolvedRoleConfig, *, role: str) -> None:
    if config.provider != 'anthropic' or config.api_family != 'messages' or config.role != role or config.route.adapter != 'anthropic':
        raise ValueError(f'expected Anthropic {role} configuration')


def judge_payload(config: ResolvedRoleConfig, *, messages: tuple[dict, ...] | list[dict],
                  remaining_output: int) -> dict[str, Any]:
    from copy import deepcopy
    return {**deepcopy(dict(config.effective_settings)),
        'max_tokens': min(config.route.max_tokens, remaining_output),
        'system': config.prompt.text, 'messages': deepcopy(list(messages))}


def prepare_judge(config: ResolvedRoleConfig, *, packet: "JudgePacket",
                  count_tokens: Callable[[str], int]) -> PreparedRequest:
    from learnai.eval.judge import build_judge_messages
    require_config(config, role='judge')
    body = judge_payload(config, messages=build_judge_messages(packet),
                         remaining_output=config.profile.max_output_tokens)
    units = count_tokens(json.dumps(body, ensure_ascii=False, separators=(',', ':')))
    reservation = body['max_tokens']
    return PreparedRequest(body, units, reservation, units + reservation <= config.profile.context_input_tokens)
