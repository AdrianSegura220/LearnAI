"""Actual-SDK provider pairs; identity capture stays entirely in test delegates."""
from dataclasses import dataclass
import json
from pathlib import Path

import yaml

from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
from learnai.adapters.tutor.openai.wiring import OpenAIFactory
from learnai.application.artifacts import load_saved_run
from learnai.eval import __main__ as cli
from tests.eval.test_judge import ScriptedJudge, reply, score_data
from tests.support.scripted_client import final as anthropic_final
from tests.support.scripted_openai import ResponseReply, ScriptedOpenAI, final as openai_final, message

ROOT = Path(__file__).resolve().parents[2]
PAIR_CASES = ('leak-solve.factoring', 'extra-nonmonic')


@dataclass
class PairRun:
    outcomes: dict
    packets: dict
    request_roles: tuple[str, ...]
    request_providers: tuple[str, ...]
    wire_judge_payloads: tuple[dict, ...]
    records: tuple
    run: Path
    sdks: dict
    exit_code: int


def write_routes(tmp_path, *, tutor_provider, judge_provider, jobs=None):
    """Use identical fictional model labels, distinct provider pricing and real defaults."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load((ROOT / 'config/llm_routes.yaml').read_text())
    jobs = jobs or {}
    for name, route in data['routes'].items():
        provider = judge_provider if name == 'rubric_judge' else jobs.get(name, tutor_provider if name == 'tutor_dialogue' else 'anthropic')
        route.update(adapter=provider, model='same-model')
        if provider == 'openai':
            route.pop('thinking', None)
            route['effort'] = 'low'
        # Reserved routes have no active role, but explicit prompts allow opt-in tests.
        route.setdefault('prompt', 'tutor_math@1')
    for profile in data['budget_profiles'].values():
        profile['context_input_tokens'] = 200000
    data['pricing'] = {'schema_version': 2, 'snapshots': [
        {'provider': provider, 'version': 'script@1', 'date': '2026-10-27',
         'retrieved_at': '2026-10-27', 'currency': 'USD', 'unit': 1000000,
         'source_url': 'https://example.test/prices', 'conditions': {},
         'rates': {'same-model': {'input': rate, 'cache_read': '1', 'cache_write_5m': '3',
                                  'cache_write_1h': '3', 'output': '4'}}}
        for provider, rate in (('anthropic', '2'), ('openai', '5'))]}
    path = tmp_path / 'routes.yaml'
    path.write_text(yaml.safe_dump(data))
    return path


def scripted_factories(sdks, *, packets=None, constructed=None):
    """Delegate all selected construction/evaluation except in-memory client ownership."""
    factories = {}
    for provider, base in (('anthropic', AnthropicFactory), ('openai', OpenAIFactory)):
        class Factory(base):
            def create_client(self, *, api_key):
                if constructed is not None:
                    constructed.append((self.provider, api_key))
                return sdks[self.provider].client

            def create_judge(self, **kwargs):
                judge = super().create_judge(**kwargs)
                if packets is None:
                    return judge
                class CapturingJudge:
                    def evaluate(self, packet):
                        packets[packet.context.interaction.task_id.removeprefix('eval-task:')] = packet
                        return judge.evaluate(packet)
                return CapturingJudge()
        factories[provider] = Factory()
    return factories


def run_scripted_pair(*, tutor_provider: str, judge_provider: str, tmp_path: Path, monkeypatch) -> PairRun:
    scripts = {'anthropic': [], 'openai': []}
    final = anthropic_final if tutor_provider == 'anthropic' else openai_final
    scripts[tutor_provider].extend([final('Check the factors.'), final('Compare the coefficients.')])
    scores = reply if judge_provider == 'anthropic' else lambda: ResponseReply([message(json.dumps(score_data()))])
    scripts[judge_provider].extend([scores(), scores()])
    sdks = {'anthropic': ScriptedJudge(scripts['anthropic']), 'openai': ScriptedOpenAI(scripts['openai'])}
    outcomes, packets, wire = {}, {}, []
    actual_run = cli.run_scenario
    def capture_outcome(scenario, **kwargs):
        outcome = actual_run(scenario, **kwargs)
        outcomes[scenario.id] = outcome
        return outcome
    with monkeypatch.context() as scoped:
        scoped.setattr(cli, 'run_scenario', capture_outcome)
        for provider, sdk in sdks.items():
            scoped.setenv(provider.upper() + '_API_KEY', 'scripted-key')
            original = sdk._validate
            def capture(data, *, provider=provider, original=original):
                wire.append((provider, json.loads(json.dumps(data))))
                return original(data)
            scoped.setattr(sdk, '_validate', capture)
        routes = write_routes(tmp_path, tutor_provider=tutor_provider, judge_provider=judge_provider)
        code = cli.main(['run', '--fixtures', str(ROOT / 'eval/fixtures'), '--routes', str(routes),
            '--out', str(tmp_path / 'runs'), '--only', ','.join(PAIR_CASES), '--no-smoke'],
            provider_factories=scripted_factories(sdks, packets=packets))
    assert code == 0, f'scripted pair CLI returned {code}'
    for provider, sdk in sdks.items():
        if provider not in (tutor_provider, judge_provider):
            sdk.client.close()
    run = next((tmp_path / 'runs').iterdir())
    saved = load_saved_run(run)
    payloads, roles = [], []
    for provider, body in wire:
        is_judge = (body.get('text', {}).get('format', {}).get('name') == 'rubric_scores'
                    if provider == 'openai' else 'mathematics' in body.get('output_config', {}).get('format', {}).get('schema', {}).get('properties', {}))
        roles.append('judge' if is_judge else 'tutor')
        if is_judge:
            payloads.append(json.loads(body['input' if provider == 'openai' else 'messages'][0]['content']))
    return PairRun(outcomes, packets, tuple(roles), tuple(provider for provider, _ in wire),
                   tuple(payloads), saved.records, run, sdks, code)
