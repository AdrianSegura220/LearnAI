from dataclasses import asdict, replace
import json
import os
import subprocess
import sys

import pytest

from learnai.adapters.tutor.configuration import schema_hash
from learnai.adapters.tutor.openai.config import request_settings, resolve_config, validate_route
from learnai.adapters.tutor.openai.encoding import prepare_tutor
from learnai.adapters.tutor.openai.wiring import OpenAIFactory
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES, conservative_token_count
from learnai.adapters.tutor.routing import Route
from learnai.adapters.tutor.tools import tool_definitions
from learnai.application.ports import TutorDependencies
from learnai.adapters.content.registry import GeneratorRegistry
from tests.adapters.tutor.test_rendering import make_context
from tests.adapters.tutor.openai.test_adapter import setup
from tests.support.scripted_openai import final

ROUTE = Route('opt_in', 'openai', 'scripted', prompt='tutor_math@1')


def test_defaults_and_limits_are_explicit_and_sdk_free():
    settings = request_settings(ROUTE)
    assert settings == {'model':'scripted','max_output_tokens':2048,'stream':False,
        'store':False,'include':['reasoning.encrypted_content'],'reasoning':{'effort':'none'},
        'truncation':'disabled'}
    factory = OpenAIFactory()
    config = factory.resolve_config(ROUTE,role='tutor',profiles=DEFAULT_BUDGET_PROFILES,prompts_root=PROMPTS_ROOT)
    assert config.dependency_versions.keys() == {'openai','httpx2'}
    assert set(config.schema_hashes) == {'final_output','canonical_read_tools','wire_read_tools'}
    assert config.schema_hashes['canonical_read_tools'] == schema_hash([asdict(t) for t in tool_definitions()])
    assert factory.role_dependencies['judge'] == ('openai','httpx2')


@pytest.mark.parametrize('changes', [
    {'adapter':'anthropic'}, {'thinking':'adaptive'}, {'effort':'max'}, {'temperature':3},
    {'temperature':0.2,'effort':'low'}, {'prompt':None},
    {'provider_options':{'previous_response_id':'resp'}}, {'provider_options':{'store':True}},
    {'provider_options':{'prompt_cache_retention':'forever'}},
    {'provider_options':{'service_tier':'auto'}}, {'provider_options':{'prompt_cache_key':''}},
])
def test_unsupported_settings_fail_before_provider_calls(changes):
    with pytest.raises(ValueError):
        validate_route(replace(ROUTE,**changes),role='tutor')


def test_supported_settings_are_encoded_without_arbitrary_passthrough():
    route = replace(ROUTE,effort='none',temperature=0.2,provider_options={
        'prompt_cache_key':'prefix-v1','prompt_cache_retention':'24h','service_tier':'default'})
    validate_route(route,role='tutor')
    result = request_settings(route)
    assert result['temperature'] == 0.2 and result['reasoning'] == {'effort':'none'}
    assert result['prompt_cache_retention'] == '24h' and result['service_tier'] == 'default'


def test_prepared_request_schema_hashes_and_effective_settings_match_real_first_wire():
    tutor,sdk,_ = setup([final()],count_tokens=conservative_token_count)
    dependencies = TutorDependencies(GeneratorRegistry(()),{})
    prepared = OpenAIFactory().prepare_tutor(tutor.config,context=make_context(),dependencies=dependencies)
    assert prepared.admitted
    assert tutor.respond(make_context()) is not None
    assert prepared.payload == sdk.requests[0]
    assert prepared.input_units == conservative_token_count(json.dumps(prepared.payload,ensure_ascii=False,separators=(',',':')))
    assert prepared.output_reservation == sdk.requests[0]['max_output_tokens']
    assert tutor.config.schema_hashes['wire_read_tools'] == schema_hash(sdk.requests[0]['tools'])
    assert tutor.config.schema_hashes['final_output'] == schema_hash(sdk.requests[0]['text']['format']['schema'])
    for key,value in tutor.config.effective_settings.items():
        if key != 'max_output_tokens':
            assert sdk.requests[0][key] == value
    for tool in sdk.requests[0]['tools']:
        assert set(tool['parameters']['required']) == set(tool['parameters']['properties'])
        assert tool['parameters']['additionalProperties'] is False


def test_resolve_and_prepare_do_not_import_any_sdk():
    code = '''
import sys
from learnai.adapters.tutor.openai.wiring import OpenAIFactory
from learnai.adapters.tutor.routing import Route
from learnai.adapters.tutor.runtime import DEFAULT_BUDGET_PROFILES
from learnai.adapters.tutor.prompts import PROMPTS_ROOT
from learnai.application.ports import TutorDependencies
from learnai.adapters.content.registry import GeneratorRegistry
from tests.adapters.tutor.test_rendering import make_context
factory = OpenAIFactory()
config = factory.resolve_config(Route('selected','openai','scripted',prompt='tutor_math@1'),
    role='tutor',profiles=DEFAULT_BUDGET_PROFILES,prompts_root=PROMPTS_ROOT)
factory.prepare_tutor(config,context=make_context(),dependencies=TutorDependencies(GeneratorRegistry(()),{}))
assert not any(m.split('.')[0] in {'openai','anthropic','httpx2'} for m in sys.modules)
'''
    completed = subprocess.run([sys.executable,'-c',code],env={k:v for k,v in os.environ.items()
        if k not in ('ANTHROPIC_API_KEY','OPENAI_API_KEY')},capture_output=True,text=True)
    assert completed.returncode == 0, completed.stderr
