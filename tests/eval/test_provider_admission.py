"""Full-corpus admission through SDK-free production factory preparation."""
import builtins
from collections import Counter
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
from learnai.adapters.tutor.openai.wiring import OpenAIFactory
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.routing import load_budget_profiles, load_routes, resolve_tutor_route
from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES, conservative_token_count
from learnai.application.ports import TutorDependencies
from learnai.domain.enums import HelpRung
from learnai.domain.turn import TutorTurn, validate_turn
from learnai.eval.fixtures import load_scenarios_dir
from learnai.eval.judge import JudgePacket
from learnai.eval.reference import build_reference
from learnai.eval.replay import prepare_scenario
from tests.eval.test_fixture_corpus import dependencies
from tests.support.provider_contracts import prepare_role, provider_route

ROOT = Path(__file__).resolve().parents[2]
CONTINUATION_HEADROOM = 8192
CANDIDATE = TutorTurn(
    "Let's compare the operation you intended with the work you wrote. "
    "Keep the original exercise beside your current line, and check one change "
    "at a time. Which part can you justify already, and where do you first "
    "become unsure? We can focus on that transition before moving forward.", HelpRung.NUDGE)


@pytest.fixture(scope='module')
def corpus_packets(dependencies):
    scenarios = load_scenarios_dir(ROOT / 'eval/fixtures')
    assert len(scenarios) == 71
    opportunities = []
    for scenario in scenarios:
        prepared = prepare_scenario(scenario, **dependencies)
        if prepared.context is None:
            continue
        context = prepared.context
        assert validate_turn(CANDIDATE, context, dependencies['graph'],
                             dependencies['verifier']).accepted, scenario.id
        # References derive independently from the exercise and evaluator scenario.
        reference = build_reference(scenario, item=prepared.task.item,
            graph=dependencies['graph'], catalogue=dependencies['catalogue'],
            verifier=dependencies['verifier'])
        opportunities.append((scenario, JudgePacket(context, CANDIDATE, reference)))
    assert len(opportunities) == 54
    assert sum(s.family == 'ladder' for s, _ in opportunities) >= 15
    diagnoses = Counter(p.context.diagnosis for s, p in opportunities if s.family == 'diagnosis')
    for name in ('mc.foil.drops.cross', 'mc.square.distributes', 'mc.gcf.partial',
                 'mc.factor.sign', 'mc.diffsquares.sum', 'mc.zeroproduct.misapplied'):
        assert diagnoses[name] >= 2
    return opportunities


@pytest.mark.parametrize('provider', ['anthropic', 'openai'])
@pytest.mark.parametrize('profile_source', ['checked-in', 'defaults'])
def test_complete_corpus_admits_both_roles_with_continuation_headroom(
        dependencies, corpus_packets, provider, profile_source, monkeypatch):
    routes = load_routes(ROOT / 'config/llm_routes.yaml')
    profiles = (load_budget_profiles(ROOT / 'config/llm_routes.yaml')
                if profile_source == 'checked-in' else DEFAULT_BUDGET_PROFILES)
    factory = AnthropicFactory() if provider == 'anthropic' else OpenAIFactory()
    deps = TutorDependencies(dependencies['items'], dependencies['catalogue'])
    actual_import = builtins.__import__
    forbidden = []

    def no_sdk(name, *args, **kwargs):
        if name.split('.')[0] in {'anthropic', 'openai'}:
            forbidden.append(name)
            raise AssertionError('admission imported an SDK: ' + name)
        return actual_import(name, *args, **kwargs)

    def no_client_or_network(*args, **kwargs):
        forbidden.append('client/network')
        raise AssertionError('admission must not construct clients or use network')

    monkeypatch.setattr(builtins, '__import__', no_sdk)
    monkeypatch.setattr(factory, 'create_client', no_client_or_network)
    monkeypatch.setattr(socket, 'socket', no_client_or_network)
    measurements = {'tutor': [], 'judge': []}
    failures = []
    for scenario, packet in corpus_packets:
        for role in measurements:
            route = (resolve_tutor_route(routes, packet.context.response_job)
                     if role == 'tutor' else routes['rubric_judge'])
            config = factory.resolve_config(provider_route(route, provider), role=role,
                                            profiles=profiles, prompts_root=PROMPTS_ROOT)
            prepared = prepare_role(factory, config, context=packet.context, dependencies=deps, packet=packet)
            # Recount the actual encoder output with the production counter.
            assert prepared.input_units == conservative_token_count(json.dumps(
                prepared.payload, ensure_ascii=False, separators=(',', ':')))
            size = prepared.input_units + prepared.output_reservation
            margin = config.profile.context_input_tokens - size
            measurements[role].append((size, margin, scenario.id, config.route.name))
            if not prepared.admitted or margin < CONTINUATION_HEADROOM:
                failures.append((role, scenario.id, size, margin, prepared.admitted))
    for role, rows in measurements.items():
        assert len(rows) == 54
        print(provider, profile_source, role, 'max=', max(rows), 'min_margin=', min(r[1] for r in rows))
    print('actual_jobs=', dict(Counter(packet.context.response_job.name for _, packet in corpus_packets)))
    assert forbidden == []
    assert failures == []


def test_admission_module_loads_without_either_provider_sdk():
    script = """
import builtins
original = builtins.__import__
def no_sdk(name, *args, **kwargs):
    if name.split('.')[0] in {'openai', 'anthropic'}:
        raise AssertionError('SDK import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = no_sdk
import tests.eval.test_provider_admission
"""
    result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
