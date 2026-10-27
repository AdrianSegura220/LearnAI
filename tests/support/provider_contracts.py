"""Actual-SDK provider pairs; identity capture stays entirely in test delegates."""
from dataclasses import dataclass, replace
import json
from pathlib import Path

import yaml

from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
from learnai.adapters.tutor.openai.wiring import OpenAIFactory
from learnai.application.artifacts import load_saved_run
from learnai.eval import __main__ as cli

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
    from tests.eval.test_judge import ScriptedJudge, reply, score_data
    from tests.support.scripted_client import final as anthropic_final
    from tests.support.scripted_openai import ResponseReply, ScriptedOpenAI, final as openai_final, message
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


def prepare_role(factory, config, *, context=None, dependencies=None, packet=None):
    """Measure the real resolved role encoder without constructing any client."""
    if config.role == 'tutor':
        return factory.prepare_tutor(config, context=context, dependencies=dependencies)
    return factory.prepare_judge(config, packet=packet)


def provider_route(route, provider):
    """Keep configured identity and limits with explicit provider test controls."""
    return replace(route, adapter=provider,
        model='scripted-openai-model' if provider == 'openai' else route.model,
        thinking=None if provider == 'openai' else route.thinking)


@dataclass
class ProviderEngine:
    provider: str
    engine: object
    session: object
    sdk: object
    tutor: object
    traces: list
    contexts: list
    configs: list
    factory: object
    dependencies: object

    def context(self, request_index=0):
        request = self.sdk.requests[request_index]
        return json.loads(request['input' if self.provider == 'openai' else 'messages'][0]['content'])

    def results(self, request_index=-1):
        """Expose paired tool identifiers and semantic results from native captures."""
        request = self.sdk.requests[request_index]
        if self.provider == 'openai':
            return [(item['call_id'], json.loads(item['output'])) for item in request['input']
                    if item.get('type') == 'function_call_output']
        return [(block['tool_use_id'], json.loads(block['content']))
                for message in request['messages'] if isinstance(message['content'], list)
                for block in message['content'] if block['type'] == 'tool_result']


def scripted_engine(provider, replies, *, profiles=None):
    """Real engine/router/adapters and official SDKs; only HTTP and clock are scripted.

    Replies use the existing Anthropic test script vocabulary. Translation affects
    replies only; requests are always captured directly from each native SDK.
    """
    from learnai.adapters.content.generators.quadratics import QUADRATICS_TEMPLATES
    from learnai.adapters.content.registry import GeneratorRegistry
    from learnai.adapters.tutor.anthropic.adapter import AnthropicTutor
    from learnai.adapters.tutor.openai.adapter import OpenAITutor
    from learnai.adapters.tutor.prompts import PROMPTS_ROOT
    from learnai.adapters.tutor.routing import load_budget_profiles, load_routes, resolve_tutor_route
    from learnai.application.ports import TutorDependencies
    from learnai.application.tutor_router import TutorRouter
    from learnai.domain.interaction import ResponseJob
    from tests.domain.test_engine import CLUSTER, build
    from tests.support.scripted_client import ScriptedAnthropic
    from tests.support.scripted_openai import ResponseReply, ScriptedOpenAI, call, message, usage

    if provider == 'anthropic':
        sdk = ScriptedAnthropic(replies)
        factory = AnthropicFactory()
    else:
        native = []
        for index, reply in enumerate(replies, start=1):
            output = []
            for position, block in enumerate(reply.content):
                if block['type'] == 'tool_use':
                    if block['name'] == 'submit_turn':
                        output.append(message(json.dumps({'diagnosis': None, 'proposals': [], **block['input']})))
                    else:
                        identifier = block.get('id', f'tool-{index}-{position}')
                        output.append(call(block['name'], block['input'], call_id=identifier, id='fc-' + identifier))
                else:
                    output.append(message(block['text']))
            native.append(ResponseReply(output, elapsed=reply.elapsed, http_status=reply.status,
                                        usage=usage(output_tokens=reply.output_tokens)))
        sdk = ScriptedOpenAI(native)
        factory = OpenAIFactory()
    routes = load_routes(ROOT / 'config/llm_routes.yaml')
    profiles = profiles if profiles is not None else load_budget_profiles(ROOT / 'config/llm_routes.yaml')
    deps = TutorDependencies(GeneratorRegistry(QUADRATICS_TEMPLATES), CLUSTER.misconceptions)
    traces, contexts, configs = [], [], []
    selected = {}
    for job in (ResponseJob.BRIEF, ResponseJob.NORMAL, ResponseJob.SUBSTANTIAL):
        route = resolve_tutor_route(routes, job)
        selected[job] = provider_route(route, provider)

    def create(route, context):
        config = factory.resolve_config(route, role='tutor', profiles=profiles, prompts_root=PROMPTS_ROOT)
        contexts.append(context)
        configs.append(config)
        options = dict(monotonic=sdk.clock, sleep=sdk.clock.sleep, trace_sink=traces.append)
        if provider == 'anthropic':
            return AnthropicTutor({route.name: route}, sdk.client, deps.items, deps.catalogue,
                                  resolved_config=config, **options)
        return OpenAITutor(config, sdk.client, deps.items, deps.catalogue, **options)

    tutor = TutorRouter(selected, create)
    engine, session, _ = build(tutor)
    return ProviderEngine(provider, engine, session, sdk, tutor, traces, contexts, configs, factory, deps)
