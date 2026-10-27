"""Default-config admission of real tutor moments and complete judge packets.

No provider call is needed: inspect the production exchange's initial payload
and the judge transport's exact framing with the production admission counter.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
from learnai.adapters.tutor.anthropic.judge import _JudgeExchange
from learnai.adapters.tutor.anthropic.config import resolve_config
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.anthropic.routing import load_budget_profiles, load_routes
from learnai.adapters.tutor.prompts import load_prompt
from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES, conservative_token_count
from learnai.domain.enums import HelpRung
from learnai.domain.turn import TutorTurn, validate_turn
from learnai.eval.fixtures import load_scenarios_dir
from learnai.eval.judge import JudgePacket, SCORE_SCHEMA, build_judge_messages
from learnai.eval.reference import build_reference
from learnai.eval.replay import prepare_scenario
from tests.eval.test_fixture_corpus import dependencies
from tests.support.scripted_client import ScriptedAnthropic

ROOT = Path(__file__).resolve().parents[2]
# Extra admission space beyond the complete request AND per-call output reserve.
# This allows a useful tool result / correction before the next bounded call.
CONTINUATION_HEADROOM = 8192
REPRESENTATIVE_TURN = TutorTurn(
    "Let's compare the operation you intended with the work you wrote. "
    "Keep the original exercise beside your current line, and check one change "
    "at a time. Which part can you justify already, and where do you first "
    "become unsure? We can focus on that transition before moving forward.",
    HelpRung.NUDGE,
)


def admission_size(payload):
    serialized = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    return conservative_token_count(serialized) + payload['max_tokens']


@pytest.mark.parametrize('profile_source', ['checked-in', 'defaults'])
def test_whole_eligible_corpus_admits_tutor_and_judge_with_headroom(dependencies, profile_source):
    path = ROOT / 'config/llm_routes.yaml'
    routes = load_routes(path)
    profiles = load_budget_profiles(path) if profile_source == 'checked-in' else DEFAULT_BUDGET_PROFILES
    sdk = ScriptedAnthropic([])
    tutor = AnthropicTutor(routes, sdk.client, dependencies['items'], dependencies['catalogue'],
                          budget_profiles=profiles, monotonic=sdk.clock)
    judge_route = routes['rubric_judge']
    judge_profile = profiles[judge_route.budget_profile]
    sizes = []
    for scenario in load_scenarios_dir(ROOT / 'eval/fixtures'):
        prepared = prepare_scenario(scenario, **dependencies)
        if prepared.context is None:
            continue
        context = prepared.context
        exchange = tutor.begin_turn(context)
        assert exchange.stop_reason is None, (scenario.id, exchange.stop_reason)
        payload = exchange._payload(explore=exchange.budget.can_explore())
        tutor_size = admission_size(payload)
        tutor_headroom = exchange.budget.profile.context_input_tokens - tutor_size
        assert tutor_headroom >= CONTINUATION_HEADROOM, (scenario.id, tutor_size, tutor_headroom)
        assert validate_turn(REPRESENTATIVE_TURN, context, dependencies['graph'],
                             dependencies['verifier']).accepted, scenario.id
        reference = build_reference(scenario, item=prepared.task.item,
            graph=dependencies['graph'], catalogue=dependencies['catalogue'],
            verifier=dependencies['verifier'])
        packet = JudgePacket(context, REPRESENTATIVE_TURN, reference)
        judge = _JudgeExchange(sdk.client, resolve_config(judge_route, role="judge", profiles=profiles, prompts_root=PROMPTS_ROOT),
            messages=build_judge_messages(packet),
            monotonic=sdk.clock, count_tokens=conservative_token_count, sleep=sdk.clock.sleep)
        # Same initial framing used by _model_call, including schema and policy.
        judge_payload = {**judge.settings,
            'max_tokens': min(judge_route.max_tokens, judge.budget.remaining_output_tokens),
            'system': judge.policy, 'messages': deepcopy(judge.messages)}
        judge_size = admission_size(judge_payload)
        judge_headroom = judge_profile.context_input_tokens - judge_size
        assert judge_headroom >= CONTINUATION_HEADROOM, (scenario.id, judge_size, judge_headroom)
        sizes.append((scenario.id, tutor_size, tutor_headroom, judge_size, judge_headroom))
        # Initial construction must neither send nor charge any attempt.
        assert exchange.trace.provider_requests == [] and judge.trace.provider_requests == []
        assert exchange.budget.model_calls == judge.budget.model_calls == 0
    assert len(sizes) >= 50
    assert sdk.requests == []
    print(profile_source, 'eligible=', len(sizes),
          'max_tutor=', max(sizes, key=lambda row: row[1]),
          'max_judge=', max(sizes, key=lambda row: row[3]))
