from dataclasses import replace

import pytest

from learnai.application.ports import TutorDependencies
from learnai.application.providers import OperationRoutes, ProviderRegistry, ProviderServices, resolve_operation_routes
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.routing import Route
from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES
from learnai.domain.interaction import ResponseJob
from learnai.eval.accounting import RequestLedger
from tests.support.provider_fakes import RecordingFactory
from tests.adapters.tutor.test_rendering import make_context


def route(provider, name='tutor_dialogue'):
    return Route(name, provider, 'fictional-model', prompt='tutor_policy@1')


def services(factories, selected, environment=None):
    return ProviderServices(selected=selected, registry=ProviderRegistry(factories),
        environment=environment or {}, dependencies=TutorDependencies(None, {}),
        profiles=DEFAULT_BUDGET_PROFILES, prompts_root=PROMPTS_ROOT, ledger=RequestLedger())


def test_missing_selected_judge_key_prevents_every_client():
    factories = {name: RecordingFactory(name) for name in ('tutor_test', 'judge_test')}
    selected = OperationRoutes({ResponseJob.NORMAL: route('tutor_test')}, route('judge_test', 'judge'))
    mixed = services(factories, selected, {'TUTOR_TEST_KEY': 'secret'})
    with pytest.raises(ValueError, match='JUDGE_TEST_KEY'):
        mixed.validate()
    assert sum(factory.clients_created for factory in factories.values()) == 0


def test_unused_missing_package_and_key_and_empty_operation():
    unused = RecordingFactory('unused')
    unused.sdk_module = 'nonexistent_sdk'
    factory = RecordingFactory('selected')
    with services({'unused': unused, 'selected': factory}, OperationRoutes({}, None)) as operation:
        operation.validate()
        assert operation.resolved_configs == {}
    assert unused.clients_created == factory.clients_created == 0


def test_rejudge_only_and_lazy_client_reuse_and_closure():
    factory = RecordingFactory('judge_test')
    with services({'judge_test': factory}, OperationRoutes({}, route('judge_test', 'judge')),
                  {'JUDGE_TEST_KEY': 'secret'}) as operation:
        operation.validate()
        assert factory.clients_created == 0
        operation.judge(scenario_id='one')
        operation.judge(scenario_id='two')
        assert factory.clients_created == 1
    assert factory.clients_closed == 1


def test_second_provider_failure_closes_first_client():
    factories = {name: RecordingFactory(name) for name in ('first', 'second')}
    factories['second'].fail_creation = True
    selected = OperationRoutes({ResponseJob.NORMAL: route('first')}, route('second', 'judge'))
    with pytest.raises(RuntimeError, match='construction'):
        with services(factories, selected, {'FIRST_KEY': 'x', 'SECOND_KEY': 'x'}) as operation:
            operation.validate()
            operation.tutor(phase='tutor').begin_turn(make_context())
            operation.judge(scenario_id='one')
    assert factories['first'].clients_closed == 1


def test_selection_uses_actual_jobs_smoke_normal_and_rejudge_only():
    routes = {'tutor_dialogue': route('test'), 'rubric_judge': route('test', 'rubric_judge')}
    assert resolve_operation_routes(routes=routes, contexts=[], judge_route_name='absent',
        smoke=False, rejudge=False) == OperationRoutes({}, None)
    smoke = resolve_operation_routes(routes=routes, contexts=[], judge_route_name='absent', smoke=True, rejudge=False)
    assert set(smoke.tutors) == {ResponseJob.NORMAL} and smoke.judge is None
    rejudge = resolve_operation_routes(routes=routes, contexts=[], judge_route_name='rubric_judge', smoke=False, rejudge=True)
    assert rejudge.tutors == {} and rejudge.judge == routes['rubric_judge']


def test_route_is_fixed_through_rejected_exchange_and_sink_identities_do_not_leak():
    from learnai.domain.enums import HelpRung
    from learnai.domain.turn import TutorTurn, TurnFeedback, RejectionReason
    first, second = RecordingFactory('first'), RecordingFactory('second')
    first.tutor_script = [TutorTurn('rejected', HelpRung.FULL_REVEAL), TutorTurn('accepted', HelpRung.NUDGE)]
    selected = OperationRoutes({ResponseJob.NORMAL: route('first'),
        ResponseJob.BRIEF: route('second', 'tutor_brief')}, route('second', 'judge'))
    operation = services({'first': first, 'second': second}, selected, {'FIRST_KEY': 'x', 'SECOND_KEY': 'x'})
    with operation:
        outer = operation.tutor(phase='tutor', scenario_id='outer').begin_turn(make_context())
        assert outer.respond().message == 'rejected'
        operation.tutor(phase='smoke', scenario_id='inner').respond(make_context())
        assert outer.respond(feedback=TurnFeedback(RejectionReason.RUNG_EXCEEDED, 'too much', TutorTurn('rejected', HelpRung.FULL_REVEAL))).message == 'accepted'
        outer.finish(accepted=TutorTurn('accepted', HelpRung.NUDGE), reason='accepted')
    assert len(first.requests) == 3 and second.requests == []
    assert [r.scenario_id for r in operation.ledger.records] == ['inner', 'outer', 'outer']
    assert [r.phase for r in operation.ledger.records] == ['smoke', 'tutor', 'tutor']
    assert {r.route_name for r in operation.ledger.records} == {'tutor_dialogue'}
    assert first.clients_created == first.clients_closed == 1


def test_selected_missing_sdk_or_invalid_settings_prevents_all_clients():
    first, second = RecordingFactory('first'), RecordingFactory('second')
    second.sdk_module = 'nonexistent_sdk'
    selected = OperationRoutes({ResponseJob.NORMAL: route('first')}, route('second', 'judge'))
    with pytest.raises(ValueError, match='SDK'):
        services({'first': first, 'second': second}, selected, {'FIRST_KEY': 'x', 'SECOND_KEY': 'x'}).validate()
    assert first.clients_created == second.clients_created == 0


@pytest.mark.parametrize('role', ['tutor', 'judge'])
def test_preflight_resolves_defaults_and_schema_hashes_without_clients_and_first_request_matches(tmp_path, role):
    from hashlib import sha256
    import json
    from learnai.adapters.content.registry import GeneratorRegistry
    from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
    from learnai.adapters.tutor.tools import tool_definitions
    from dataclasses import asdict
    from tests.eval.test_judge import packet, reply, ScriptedJudge
    from tests.support.scripted_client import final

    factory = AnthropicFactory()
    directory = tmp_path / 'policy'
    directory.mkdir()
    prompt_file = directory / 'v1.md'
    prompt_file.write_text('Original loaded policy.')
    selected = Route('selected-route', 'anthropic', 'fictional-model', prompt='policy@1')
    config = factory.resolve_config(selected, role=role, profiles=DEFAULT_BUDGET_PROFILES, prompts_root=tmp_path)
    assert config.effective_settings['stream'] is False
    assert config.effective_settings['max_tokens'] == 2048
    assert set(config.dependency_versions) == {'anthropic', 'httpx2'}
    prompt_file.write_text('Changed after resolution: must never reach request.')
    dependencies = TutorDependencies(GeneratorRegistry(()), {})
    p = packet()
    prepared = (factory.prepare_tutor(config, context=p.context, dependencies=dependencies) if role == 'tutor'
                else factory.prepare_judge(config, packet=p))
    assert prepared.admitted and prepared.input_units > 0
    sdk = ScriptedJudge([final() if role == 'tutor' else reply()])
    traces = []
    if role == 'tutor':
        factory.create_tutor(config=config, client=sdk.client, dependencies=dependencies,
                             trace_sink=traces.append).respond(p.context)
    else:
        factory.create_judge(config=config, client=sdk.client, trace_sink=traces.append).evaluate(p)
    assert sdk.wire_requests[0] == prepared.payload
    assert traces[0].provider_requests[0] == prepared.payload
    assert traces[0].settings == config.effective_settings
    assert traces[0].route_name == selected.name
    assert 'Original loaded policy.' in json.dumps(prepared.payload)
    assert 'Changed after resolution' not in json.dumps(prepared.payload)
    digest = lambda value: sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    assert config.schema_hashes['final_output'] == digest(prepared.payload['output_config']['format']['schema'])
    if role == 'tutor':
        assert config.schema_hashes['canonical_read_tools'] == digest([asdict(tool) for tool in tool_definitions()])
        assert config.schema_hashes['wire_read_tools'] == digest(prepared.payload['tools'][:-1])


def test_runtime_budget_adjustment_is_recorded_separately_from_initial_preparation():
    from learnai.adapters.content.registry import GeneratorRegistry
    from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
    from tests.support.scripted_client import ScriptedAnthropic, final, FakeMonotonic
    factory = AnthropicFactory()
    selected = Route('tutor_dialogue', 'anthropic', 'fictional-model', prompt='tutor_math@1', max_tokens=8000)
    config = factory.resolve_config(selected, role='tutor', profiles=DEFAULT_BUDGET_PROFILES, prompts_root=PROMPTS_ROOT)
    deps = TutorDependencies(GeneratorRegistry(()), {})
    context = make_context()
    prepared = factory.prepare_tutor(config, context=context, dependencies=deps)
    sdk, traces, clock = ScriptedAnthropic([final()]), [], FakeMonotonic()
    tutor = factory.create_tutor(config=config, client=sdk.client, dependencies=deps, trace_sink=traces.append)
    tutor.monotonic = clock
    exchange = tutor.begin_turn(context)
    clock.advance(9)
    turn = exchange.respond()
    exchange.finish(accepted=turn, reason='accepted')
    actual = traces[0].provider_requests[0]
    assert prepared.payload['tool_choice'] == {'type': 'auto'}
    assert actual['tool_choice'] == {'type': 'none'}
    assert prepared.output_reservation == 7168 and actual['max_tokens'] == 8000


def test_resolved_and_prepared_values_are_copy_isolated():
    from learnai.adapters.tutor.configuration import PreparedRequest
    factory = RecordingFactory('test')
    settings = {'nested': {'control': ['original']}}
    config = replace(factory.resolve_config(route('test'), role='tutor', profiles=DEFAULT_BUDGET_PROFILES,
                                           prompts_root=PROMPTS_ROOT), effective_settings=settings)
    prepared = PreparedRequest(settings, 1, 1, True)
    settings['nested']['control'][0] = 'mutated'
    assert config.effective_settings['nested']['control'] == ['original']
    assert prepared.payload['nested']['control'] == ['original']


def test_cli_selects_independent_providers_and_records_actual_role_metadata(tmp_path, monkeypatch):
    import json
    import yaml
    from learnai.eval.__main__ import main
    from tests.eval.test_report_cli import routes_file, cli_args, run_artifact
    from learnai.domain.enums import HelpRung
    from learnai.domain.turn import TutorTurn

    path = routes_file(tmp_path)
    raw = yaml.safe_load(path.read_text())
    for name, settings in raw['routes'].items():
        settings['adapter'] = 'judge_test' if name == 'rubric_judge' else 'tutor_test'
    path.write_text(yaml.safe_dump(raw))
    factories = {name: RecordingFactory(name) for name in ('tutor_test', 'judge_test')}
    factories['tutor_test'].tutor_script = [TutorTurn('Review the previous line.', HelpRung.NUDGE)]
    monkeypatch.setenv('TUTOR_TEST_KEY', 'private-tutor-key')
    monkeypatch.setenv('JUDGE_TEST_KEY', 'private-judge-key')
    judge_factory = factories['judge_test']
    original_prepare = judge_factory.prepare_judge
    def prepare(config, *, packet):
        # Fresh judge preparation sees only an actually generated accepted candidate.
        assert len(factories['tutor_test'].requests) == 2
        assert packet.turn.message == 'Review the previous line.'
        return original_prepare(config, packet=packet)
    judge_factory.prepare_judge = prepare
    assert main(cli_args(tmp_path, path), provider_factories=factories) == 0
    run = run_artifact(tmp_path)
    manifest = json.loads((run / 'manifest.json').read_text())
    material = manifest['material']
    for role, name, provider in [('tutor', 'tutor_dialogue', 'tutor_test'), ('judge', 'rubric_judge', 'judge_test')]:
        identity = material['identities'][role][name]
        assert identity['provider'] == provider and identity['api_family'] == 'fictional-api'
        assert identity['schema_hashes']['final_output'] == 'final-hash'
        assert material['role_dependencies'][role]['pytest']
        assert material['settings']['routes'][name]['effective_settings']['default_control'] == 'resolved'
    assert material['pricing_snapshots']['schema_version'] == 2
    assert 'private-tutor-key' not in json.dumps(manifest) and 'private-judge-key' not in json.dumps(manifest)
    records = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    assert [r['provider'] for r in records] == ['tutor_test', 'tutor_test', 'judge_test', 'judge_test']
    assert all(f.clients_created == f.clients_closed == 1 for f in factories.values())


def test_cli_no_tutor_and_no_smoke_needs_no_sdk_key_or_judge_route(tmp_path):
    import yaml
    from learnai.eval.__main__ import main
    from tests.eval.test_report_cli import routes_file, cli_args
    path = routes_file(tmp_path)
    raw = yaml.safe_load(path.read_text())
    for settings in raw['routes'].values():
        settings['adapter'] = 'unused'
        settings['prompt'] = 'absent@1'
    del raw['routes']['rubric_judge']
    path.write_text(yaml.safe_dump(raw))
    factory = RecordingFactory('unused')
    factory.sdk_module = 'not_installed'
    assert main(cli_args(tmp_path, path, only='extra-malformed-submit'),
                provider_factories={'unused': factory}) == 0
    assert factory.clients_created == 0 and factory.prepared == []


def test_unknown_provider_anywhere_is_structural_before_client(tmp_path, monkeypatch):
    import yaml
    from learnai.eval.__main__ import main
    from tests.eval.test_report_cli import routes_file, cli_args
    path = routes_file(tmp_path)
    raw = yaml.safe_load(path.read_text())
    raw['routes']['unused'] = {'adapter': 'unknown', 'model': 'fictional'}
    path.write_text(yaml.safe_dump(raw))
    from tests.support.provider_fakes import anthropic_override
    factories = anthropic_override(lambda **kwargs: pytest.fail('constructed a client'))
    assert main(cli_args(tmp_path, path), provider_factories=factories) == 2


@pytest.mark.parametrize('role', ['tutor', 'judge'])
def test_nonadmitted_preparation_sends_no_request_and_retains_failure_trace(role):
    from learnai.adapters.content.registry import GeneratorRegistry
    from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
    from learnai.eval.judge import JudgeError
    from tests.eval.test_judge import packet, ScriptedJudge
    factory = AnthropicFactory()
    profiles = {'normal': replace(DEFAULT_BUDGET_PROFILES['normal'], context_input_tokens=10)}
    config = factory.resolve_config(Route('selected', 'anthropic', 'fictional', prompt='tutor_math@1'),
        role=role, profiles=profiles, prompts_root=PROMPTS_ROOT)
    deps = TutorDependencies(GeneratorRegistry(()), {})
    p, sdk, traces = packet(), ScriptedJudge([]), []
    prepared = (factory.prepare_tutor(config, context=p.context, dependencies=deps) if role == 'tutor'
                else factory.prepare_judge(config, packet=p))
    assert not prepared.admitted and prepared.input_units > 10
    if role == 'tutor':
        assert factory.create_tutor(config=config, client=sdk.client, dependencies=deps,
                                    trace_sink=traces.append).respond(p.context) is None
    else:
        with pytest.raises(JudgeError, match='context_limit'):
            factory.create_judge(config=config, client=sdk.client, trace_sink=traces.append).evaluate(p)
    assert sdk.wire_requests == [] and len(traces) == 1 and traces[0].attempts == []


def test_shared_sdk_transport_are_attributed_to_both_actual_roles():
    from learnai.adapters.content.registry import GeneratorRegistry
    from learnai.application.providers import default_registry
    tutors = {ResponseJob.NORMAL: Route('tutor_dialogue', 'anthropic', 'fictional', prompt='tutor_math@1')}
    judge = Route('rubric_judge', 'anthropic', 'fictional', prompt='rubric_judge@1')
    operation = ProviderServices(selected=OperationRoutes(tutors, judge), registry=default_registry(),
        environment={'ANTHROPIC_API_KEY': 'fake'}, dependencies=TutorDependencies(GeneratorRegistry(()), {}),
        profiles=DEFAULT_BUDGET_PROFILES, prompts_root=PROMPTS_ROOT, ledger=RequestLedger())
    operation.validate()
    for role, name in [('tutor', 'tutor_dialogue'), ('judge', 'rubric_judge')]:
        config = operation.resolved_configs[role, name]
        assert set(config.dependency_versions) == {'anthropic', 'httpx2'}
        assert all(config.dependency_versions.values())
    assert operation._clients == {}


def test_preparation_rejects_other_provider_or_role():
    from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
    fake = RecordingFactory('other')
    config = fake.resolve_config(route('other'), role='tutor', profiles=DEFAULT_BUDGET_PROFILES, prompts_root=PROMPTS_ROOT)
    with pytest.raises(ValueError, match='Anthropic'):
        AnthropicFactory().prepare_tutor(config, context=make_context(), dependencies=TutorDependencies(None, {}))


def test_missing_selected_transport_package_prevents_all_clients():
    factories = {name: RecordingFactory(name) for name in ('first', 'second')}
    factories['second'].role_dependencies = {'judge': ('missing-transport-for-test',)}
    operation = services(factories, OperationRoutes({ResponseJob.NORMAL: route('first')}, route('second', 'judge')),
                         {'FIRST_KEY': 'x', 'SECOND_KEY': 'x'})
    with pytest.raises(ValueError, match='missing-transport-for-test'):
        operation.validate()
    assert all(factory.clients_created == 0 for factory in factories.values())


def test_unknown_dependency_version_is_null_without_importing_sdk(monkeypatch):
    import importlib.metadata
    from learnai.adapters.tutor.anthropic.wiring import AnthropicFactory
    monkeypatch.setattr(importlib.metadata, 'version', lambda name: None)
    config = AnthropicFactory().resolve_config(Route('selected', 'anthropic', 'fictional', prompt='tutor_math@1'),
        role='tutor', profiles=DEFAULT_BUDGET_PROFILES, prompts_root=PROMPTS_ROOT)
    assert config.dependency_versions == {'anthropic': None, 'httpx2': None}


def test_close_failure_does_not_replace_original_error_and_other_clients_close():
    first, second = RecordingFactory('first'), RecordingFactory('second')
    create = first.create_client
    def bad_close(*, api_key):
        client = create(api_key=api_key)
        close = client.close
        def fail():
            close()
            raise RuntimeError('secondary close failure')
        client.close = fail
        return client
    first.create_client = bad_close
    operation = services({'first': first, 'second': second},
        OperationRoutes({ResponseJob.NORMAL: route('first')}, route('second', 'judge')),
        {'FIRST_KEY': 'x', 'SECOND_KEY': 'x'})
    with pytest.raises(ValueError, match='original failure'):
        with operation:
            operation.tutor(phase='tutor').begin_turn(make_context())
            operation.judge(scenario_id='case')
            raise ValueError('original failure')
    assert first.clients_closed == second.clients_closed == 1
