"""Local adapter fixtures only; never opens an account or inference endpoint."""
import asyncio
from contextlib import nullcontext
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from integration.unified_model_runtime import UnifiedModelRuntime, materialize_legacy_provider, install_unified_model_routes
from deeptutor.services.llm.config import LLMConfig, get_llm_config, set_scoped_llm_config, reset_scoped_llm_config
from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse, ToolCallRequest
from deeptutor.services.model_selection.runtime import resolved_model_snapshot, resolve_model_selection


class FixtureProvider(LLMProvider):
    provider_name = 'fixture'

    def __init__(self):
        super().__init__(api_key='fixture-only')
        self.calls = []
        self.cancelled = False
        self.mode = 'success'

    def get_default_model(self):
        return 'actual-model-a'

    async def chat(self, **kwargs):
        raise AssertionError('broker uses the adapter streaming path')

    async def chat_stream(self, **kwargs):
        self.calls.append(kwargs)
        await asyncio.sleep(0)
        assert get_llm_config().model == kwargs['model']
        if kwargs.get('on_reasoning_delta'):
            await kwargs['on_reasoning_delta']('fixture reasoning')
        if kwargs.get('on_content_delta'):
            await kwargs['on_content_delta']('fixture answer')
        if self.mode == 'cancel':
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.mode == 'fail':
            raise RuntimeError('HTTP 503 fixture-private-key https://private.invalid')
        return LLMResponse('fixture answer', [ToolCallRequest('tool-1', 'read_file', {'path': 'fixture.txt'})],
            finish_reason='tool_calls', usage={'prompt_tokens': 8, 'completion_tokens': 4}, reasoning_content='fixture reasoning')


@pytest.fixture
def runtime():
    state = {'model': 'actual-model-a'}
    provider = FixtureProvider()
    def resolver(selection):
        model = selection['model_id'] if selection else state['model']
        config = LLMConfig(model=model, api_key='fixture-private-key', base_url='https://fixture.invalid/v1',
            provider_name='openai-codex', binding='openai-codex', max_output_tokens=200,
            capabilities={'tools': True, 'vision': True, 'json_output': True})
        return config, {'profile_id': 'fixture-profile', 'model_id': model}, resolved_model_snapshot(config, selection)
    return UnifiedModelRuntime(resolver=resolver, provider_factory=lambda config: provider), provider, state


def body(execution, **fields):
    return {'model': execution['provider']['model'], 'messages': [{'role': 'user', 'content': 'fixture'}], **fields}


def authorization(execution):
    return 'Bearer ' + execution['provider']['api_key']


def test_frozen_default_and_restore_do_not_follow_new_default(runtime):
    broker, _, state = runtime
    first = broker.freeze()
    state['model'] = 'actual-model-b'
    assert broker.freeze()['resolved_model']['model'] == 'actual-model-b'
    assert broker.execution(first['execution_id'])['resolved_model']['model'] == 'actual-model-a'
    broker.leases.clear()
    recovered = broker.freeze(model_snapshot=first['model_snapshot'])
    assert recovered['resolved_model']['model'] == 'actual-model-a'
    assert recovered['resolved_model']['selection_source'] == 'default'
    corrupt = deepcopy(first['model_snapshot'])
    corrupt['resolved_model']['configuration_revision'] = 'changed'
    with pytest.raises(HTTPException) as error:
        broker.freeze(model_snapshot=corrupt)
    assert error.value.detail['code'] == 'model_configuration_changed'
    serialized = json.dumps(first['model_snapshot'])
    assert 'fixture-private-key' not in serialized
    assert 'fixture.invalid' not in serialized
    assert 'dsexec_' not in serialized


def test_private_guard_and_capability_rejections(runtime):
    broker, _, _ = runtime
    execution = broker.freeze()
    with pytest.raises(HTTPException) as error:
        broker.authorize(body(execution), 'Bearer wrong')
    assert error.value.status_code == 401
    lease = broker.lease(execution['execution_id'])
    lease.snapshot['capabilities'] = {'tools': False, 'vision': False, 'json_output': False}
    for fields, code in [({'tools': [{'type': 'function'}]}, 'model_tools_unsupported'),
        ({'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,fixture'}}]}]}, 'model_vision_unsupported'),
        ({'response_format': {'type': 'json_object'}}, 'model_json_unsupported')]:
        with pytest.raises(HTTPException) as error:
            broker.authorize(body(execution, **fields), authorization(execution))
        assert error.value.detail['code'] == code


def test_public_default_updates_only_reference_and_keeps_running_client(runtime):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from deeptutor.api.routers.auth import require_auth
    broker, _, _ = runtime
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    install_unified_model_routes(app, lambda request: None, runtime=broker)
    catalog = {'services': {'llm': {'active_profile_id': 'old', 'active_model_id': 'old-model',
        'profiles': [{'id': 'fixture-profile', 'api_key': 'fixture-private-key',
            'models': [{'id': 'actual-model-a', 'model': 'actual-model-a'}]}]},
        'embedding': {'active_profile_id': 'embedding-unchanged'}}}
    before_profiles = deepcopy(catalog['services']['llm']['profiles'])
    service = SimpleNamespace(update=lambda callback: callback(catalog))
    with patch('deeptutor.services.config.get_model_catalog_service', return_value=service), \
         patch('deeptutor.services.llm.client.reset_llm_client') as reset:
        result = TestClient(app).put('/api/contest/models/default', json={
            'llm_selection': {'profile_id': 'fixture-profile', 'model_id': 'actual-model-a'}})
    assert result.status_code == 200
    assert catalog['services']['llm']['active_model_id'] == 'actual-model-a'
    assert catalog['services']['llm']['profiles'] == before_profiles
    assert catalog['services']['embedding']['active_profile_id'] == 'embedding-unchanged'
    assert 'fixture-private-key' not in result.text
    reset.assert_not_called()


def test_oauth_factory_selects_native_adapter_without_copying_credentials():
    from deeptutor.services.llm.provider_factory import _build_runtime_provider
    provider = SimpleNamespace()
    config = LLMConfig(model='fixture-codex-model', api_key='', binding='openai_codex', provider_name='openai_codex')
    with patch('deeptutor.services.llm.provider_core.openai_codex_provider.OpenAICodexProvider', return_value=provider) as factory:
        assert _build_runtime_provider(config) is provider
    factory.assert_called_once_with(default_model='fixture-codex-model')
    snapshot = resolved_model_snapshot(config)
    assert snapshot['capabilities']['tools'] is True
    assert snapshot['capabilities']['json_output'] is False


@pytest.mark.asyncio
async def test_stream_preserves_tools_reasoning_usage_images_and_frozen_scope(runtime):
    broker, provider, _ = runtime
    execution = broker.freeze()
    records = []
    async def measure(call, **kwargs):
        records.append(kwargs.pop('provider'))
        return await call(**kwargs)
    outer = LLMConfig(model='unrelated-inherited', api_key='fixture')
    token = set_scoped_llm_config(outer)
    try:
        with patch('deeptutor.services.llm.metrics.measure_provider_call', measure):
            request = body(execution, stream=True, max_tokens=999,
                messages=[{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,fixture'}}]}])
            response = await broker.completion(request, authorization(execution))
            text = ''.join([part async for part in response.body_iterator])
        assert len(records) == 1
        assert provider.calls[0]['model'] == 'actual-model-a'
        assert provider.calls[0]['max_tokens'] == 200
        assert provider.calls[0]['messages'][0]['content'][0]['type'] == 'image_url'
        assert get_llm_config().model == 'unrelated-inherited'
        for expected in ('fixture answer', 'fixture reasoning', 'read_file', 'prompt_tokens', '[DONE]'):
            assert expected in text
        assert 'fixture-private-key' not in text
        assert 'dsexec_' not in text
    finally:
        reset_scoped_llm_config(token)


@pytest.mark.asyncio
async def test_cancelling_consumer_cancels_provider(runtime):
    broker, provider, _ = runtime
    provider.mode = 'cancel'
    execution = broker.freeze()
    async def measure(call, **kwargs):
        kwargs.pop('provider')
        return await call(**kwargs)
    with patch('deeptutor.services.llm.metrics.measure_provider_call', measure):
        response = await broker.completion(body(execution, stream=True), authorization(execution))
        iterator = response.body_iterator
        await anext(iterator)
        await anext(iterator)
        await iterator.aclose()
    assert provider.cancelled


@pytest.mark.asyncio
async def test_failure_after_delta_never_retries_or_exposes_private_error(runtime):
    broker, provider, _ = runtime
    provider.mode = 'fail'
    execution = broker.freeze()
    async def measure(call, **kwargs):
        kwargs.pop('provider')
        return await call(**kwargs)
    with patch('deeptutor.services.llm.metrics.measure_provider_call', measure):
        response = await broker.completion(body(execution, stream=True), authorization(execution))
        text = ''.join([part async for part in response.body_iterator])
    assert len(provider.calls) == 1
    assert text.count('fixture answer') == 1
    assert '503' in text
    assert 'fixture-private-key' not in text
    assert 'private.invalid' not in text


@pytest.mark.parametrize('selection', [{}, {'profile_id': ' ', 'model_id': ' '}, {'profile_id': 12, 'model_id': 2},
    {'profile_id': 'x'}, {'profile_id': 'x', 'model_id': 'y', 'api_key': 'bad'}, []])
def test_malformed_selection_never_falls_back_to_default(selection):
    with pytest.raises(ValueError):
        resolve_model_selection(selection)


def test_snapshot_capacity_protocol_changes_invalidate_restore():
    config = LLMConfig(model='actual', api_key='fixture', max_output_tokens=50, api_version='version-a')
    previous = resolved_model_snapshot(config)['configuration_revision']
    config.max_output_tokens = 75
    assert resolved_model_snapshot(config)['configuration_revision'] != previous
    config.max_output_tokens = 50
    config.api_version = 'version-b'
    assert resolved_model_snapshot(config)['configuration_revision'] != previous
    config.api_version = 'version-a'
    config.extra_headers = {'OpenAI-Project': 'fixture-routing-project'}
    assert resolved_model_snapshot(config)['configuration_revision'] != previous
    config.extra_headers = {'Authorization': 'fixture-rotated-token'}
    assert resolved_model_snapshot(config)['configuration_revision'] == previous


@pytest.mark.asyncio
async def test_parallel_models_use_separate_scope_and_one_usage_record_each(runtime, tmp_path):
    broker, _, _ = runtime
    first = broker.freeze({'profile_id': 'fixture-profile', 'model_id': 'actual-first'}, surface='classroom')
    second = broker.freeze({'profile_id': 'fixture-profile', 'model_id': 'actual-second'}, surface='workspace')
    records = []
    with patch('deeptutor.services.llm.usage_ledger.ledger_path', return_value=tmp_path / 'fixture.sqlite'), \
         patch('deeptutor.services.llm.usage_ledger.record_call', side_effect=lambda path, record, **kw: records.append((record, kw))):
        results = await asyncio.gather(*[
            broker.completion(body(execution), authorization(execution)) for execution in (first, second)])
    assert [json.loads(result.body)['model'] for result in results] == ['actual-first', 'actual-second']
    assert len(records) == 2
    assert {record['resolved_model_id'] for record, _ in records} == {'actual-first', 'actual-second'}
    assert {meta['source'] for _, meta in records} == {'deepsteam-classroom', 'deepsteam-workspace'}
    assert len({record['call_id'] for record, _ in records}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['fail', 'cancel'])
async def test_failure_and_cancel_record_usage_once(runtime, tmp_path, mode):
    broker, provider, _ = runtime
    provider.mode = mode
    execution = broker.freeze()
    records = []
    with patch('deeptutor.services.llm.usage_ledger.ledger_path', return_value=tmp_path / 'fixture.sqlite'), \
         patch('deeptutor.services.llm.usage_ledger.record_call', side_effect=lambda path, record, **kw: records.append(record)):
        response = await broker.completion(body(execution, stream=True), authorization(execution))
        if mode == 'cancel':
            await anext(response.body_iterator)
            await anext(response.body_iterator)
            await response.body_iterator.aclose()
        else:
            _ = [part async for part in response.body_iterator]
    assert len(records) == 1
    assert records[0]['resolved_model_id'] == 'actual-model-a'
    assert records[0]['status'] in ('interrupted', 'failed')
    assert len(provider.calls) == 1


def test_legacy_credentials_protocol_and_limits_update_without_switching_default():
    catalog = {'services': {'llm': {'active_profile_id': 'unchanged', 'profiles': []}}}
    service = SimpleNamespace(update=lambda callback: callback(catalog))
    first = {'base_url': 'https://fixture.invalid/v1', 'model': 'actual', 'api_key': 'fixture-old', 'provider_type': 'openai'}
    with patch('deeptutor.services.config.get_model_catalog_service', return_value=service), \
         patch('deeptutor.api.routers.settings._runtime_catalog_write', return_value=nullcontext()):
        selection = materialize_legacy_provider(first)
        second = {**first, 'api_key': 'fixture-new', 'provider_type': 'anthropic', 'max_output_tokens': 500}
        assert materialize_legacy_provider(second) == selection
        with pytest.raises(HTTPException):
            materialize_legacy_provider({**first, 'model': 'dsexec_self_reference'})
    profile = catalog['services']['llm']['profiles'][0]
    assert len(catalog['services']['llm']['profiles']) == 1
    assert profile['api_key'] == 'fixture-new'
    assert profile['binding'] == 'anthropic'
    assert profile['models'][0]['max_output_tokens'] == 500
    assert catalog['services']['llm']['active_profile_id'] == 'unchanged'
