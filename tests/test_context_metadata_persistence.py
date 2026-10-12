"""Real native JSON catalog + Harness SQLite persistence; no network or models.

The native transport boundary uses the same provider merge, secret restoration,
catalog normalization and JSON serialization as the native settings endpoints.
Only synthetic temporary profiles are read or written.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from deeptutor.services.config.model_catalog import (
    ModelCatalogService, redact_catalog_secrets, restore_catalog_secrets,
)
from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
from deeptutor.services.model_selection.llm import list_llm_options
from deeptutor.services.settings.provider_edit import merge_provider_edit
from integration.harness_bridge import GATEWAY, HarnessBridge, HarnessError
from integration.context_metadata import patch_context_metadata
from portal.storage import Store


class StoredNativeTransport:
    def __init__(self, path):
        self.service = ModelCatalogService(path)
        self.calls = []
        self.drop_metadata = False
        self.before_patch = None

    async def native(self, method, path, body=None):
        self.calls.append((method, path))
        current = self.service.load()
        if method == 'PUT':
            proposed = restore_catalog_secrets(body['catalog'], current)
            if self.drop_metadata:
                for profile in proposed['services']['llm']['profiles']:
                    for model in profile['models']:
                        model.pop('context_window', None)
            self.service.save(proposed)
        elif method == 'POST' and path.endswith('/apply/provider'):
            proposed = merge_provider_edit(current, body['service'], body['profile'],
                active_model_id=body['active_model_id'], activate=body['activate'])
            self.service.apply(proposed)
        elif method != 'GET':
            raise AssertionError('Unexpected native operation')
        # Reopen the real backing file and serialize the public API result.
        reopened = ModelCatalogService(self.service.path).load()
        return json.loads(json.dumps({'catalog': redact_catalog_secrets(reopened)}))

    async def host(self, *args, **kwargs):
        raise AssertionError('No account, inference or gateway calls permitted')

    async def native_service(self, method, path, body=None):
        if method != 'POST' or path != 'learning-context-metadata':
            raise AssertionError('Existing learning defaults must be preserved')
        self.calls.append((method, path))
        if self.before_patch:
            hook, self.before_patch = self.before_patch, None
            hook()
        result = patch_context_metadata(self.service, body)
        if self.drop_metadata:
            self.service.update(lambda catalog: catalog['services']['llm']['profiles'][0]['models'][0].pop('context_window', None))
        return result


class ContextMetadataPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='deepsteam-capacity-persistence-')
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'portal')
        self.transport = StoredNativeTransport(self.root / 'native-model-catalog.json')
        self.bridge = HarnessBridge(self.store, transport=self.transport)
        self.route = {'route_id': 'dsroute_fixture', 'profile_id': 'deepsteam-harness-dsroute_fixture',
            'model': 'deepseek-flash', 'route': 'apikey', 'targets': ['learning', 'classroom'],
            'learning_defaults_revision': 1, 'context_metadata_revision': 1}
        self.store.save_harness_state(self.route, 'current')
        catalog = self.transport.service.load()
        bucket = catalog['services']['llm']
        bucket.update(active_profile_id=self.route['profile_id'], active_model_id=self.route['route_id'])
        bucket['profiles'] = [self.legacy_profile(), {
            'id': 'manual', 'name': 'Manual', 'binding': 'openai',
            'base_url': 'https://fixture.invalid/v1', 'api_key': 'fixture-manual-secret',
            'models': [{'id': 'manual-model', 'model': 'user-custom', 'context_window': '45000'}]}]
        self.transport.service.save(catalog)

    def tearDown(self):
        self.temp.cleanup()

    def legacy_profile(self):
        # Matches the observed old release: no managed_by or capacity fields.
        return {'id': self.route['profile_id'], 'name': 'DeepSeek desktop fixture',
            'binding': 'openai', 'base_url': GATEWAY + '/v1', 'api_key': 'fixture-gateway-only',
            'models': [{'id': self.route['route_id'], 'model': self.route['route_id'],
                        'name': 'deepseek-flash', 'capabilities': {'tools': True, 'vision': True}}]}

    def catalog(self):
        return ModelCatalogService(self.transport.service.path).load()

    async def test_old_unlabelled_profile_and_existing_revision_repair_on_disk(self):
        await self.bridge.reconcile_learning_defaults()
        catalog = self.catalog()
        selected = catalog['services']['llm']
        model = selected['profiles'][0]['models'][0]
        self.assertEqual(model['context_window'], '1000000')
        self.assertEqual(model['max_output_tokens'], 384000)
        self.assertEqual(model['actual_model'], 'deepseek-flash')
        self.assertEqual(model['context_window_source'], 'deepseek-official-api-2026-10-11')
        self.assertEqual(selected['active_model_id'], self.route['route_id'])
        self.assertEqual(selected['profiles'][0]['api_key'], 'fixture-gateway-only')
        self.assertEqual(selected['profiles'][1]['api_key'], 'fixture-manual-secret')
        resolved = resolve_llm_runtime_config(catalog=catalog)
        self.assertEqual(resolved.context_window, 1000000)
        self.assertEqual(resolved.display_model, 'deepseek-flash')
        option = next(item for item in list_llm_options(catalog)['options']
                      if item['model_id'] == self.route['route_id'])
        self.assertEqual(option['context_window'], 1000000)
        self.assertEqual(option['actual_model'], 'deepseek-flash')
        reopened_store = Store(self.root / 'portal')
        self.assertEqual(reopened_store.harness_state('current')['context_metadata_revision'], 1)
        self.transport.calls.clear()
        before = self.transport.service.path.read_bytes()
        await HarnessBridge(reopened_store, transport=self.transport).reconcile_learning_defaults()
        self.assertEqual(self.transport.calls, [('GET', '/api/settings/catalog')])
        self.assertEqual(before, self.transport.service.path.read_bytes())

    async def test_later_field_loss_is_repaired_without_overriding_manual_selection(self):
        await self.bridge.reconcile_learning_defaults()
        catalog = self.catalog()
        bucket = catalog['services']['llm']
        bucket.update(active_profile_id='manual', active_model_id='manual-model')
        model = bucket['profiles'][0]['models'][0]
        model.update(context_window='16384', name='Personal label')
        model.pop('max_output_tokens')
        original_manual = deepcopy(bucket['profiles'][1])
        self.transport.service.save(catalog)
        await self.bridge.reconcile_learning_defaults()
        bucket = self.catalog()['services']['llm']
        self.assertEqual(bucket['active_profile_id'], 'manual')
        self.assertEqual(bucket['active_model_id'], 'manual-model')
        self.assertEqual(bucket['profiles'][1], original_manual)
        self.assertEqual(bucket['profiles'][0]['models'][0]['name'], 'Personal label')
        self.assertEqual(bucket['profiles'][0]['models'][0]['context_window'], '1000000')

    async def test_foreign_gateway_or_route_identity_is_never_modified(self):
        for mutation in ('gateway', 'profile', 'route', 'foreign-owner'):
            with self.subTest(mutation=mutation):
                catalog = self.catalog()
                profile = self.legacy_profile()
                if mutation == 'gateway':
                    profile['base_url'] = 'https://fixture.invalid/v1'
                elif mutation == 'profile':
                    profile['id'] = 'deepsteam-harness-another-route'
                elif mutation == 'route':
                    profile['models'][0]['model'] = 'user-custom'
                else:
                    profile['managed_by'] = 'another-provider'
                catalog['services']['llm']['profiles'][0] = profile
                self.transport.service.save(catalog)
                before = self.transport.service.path.read_bytes()
                await self.bridge.reconcile_learning_defaults()
                self.assertEqual(before, self.transport.service.path.read_bytes())

    async def test_native_serializer_failure_does_not_claim_success_and_is_retryable(self):
        self.transport.drop_metadata = True
        with self.assertRaises(HarnessError) as error:
            await self.bridge.reconcile_learning_defaults()
        self.assertEqual(error.exception.code, 'context_metadata_not_saved')
        self.assertNotIn('context_metadata_revision', Store(self.root / 'portal').harness_state('current'))
        self.transport.drop_metadata = False
        await self.bridge.reconcile_learning_defaults()
        self.assertEqual(self.catalog()['services']['llm']['profiles'][0]['models'][0]['context_window'], '1000000')
        self.assertEqual(Store(self.root / 'portal').harness_state('current')['context_metadata_revision'], 1)

    async def test_new_provider_apply_path_preserves_capacity_and_public_secret_redaction(self):
        profile = self.legacy_profile()
        profile['managed_by'] = 'deepsteam-harness'
        profile['models'][0].update(actual_model='deepseek-flash', context_window='1000000',
            max_output_tokens=384000, context_window_source='deepseek-official-api-2026-10-11')
        public = await self.transport.native('POST', '/api/settings/apply/provider', {
            'service': 'llm', 'profile': profile, 'activate': True, 'active_model_id': self.route['route_id']})
        self.assertNotIn('fixture-gateway-only', json.dumps(public))
        self.assertEqual(public['catalog']['services']['llm']['profiles'][0]['models'][0]['context_window'], '1000000')
        self.assertEqual(self.catalog()['services']['llm']['profiles'][0]['managed_by'], 'deepsteam-harness')

    async def test_user_save_between_bridge_read_and_atomic_patch_is_preserved(self):
        def concurrent_user_save():
            def edit(catalog):
                bucket = catalog['services']['llm']
                bucket.update(active_profile_id='manual', active_model_id='manual-model')
                bucket['profiles'][0]['models'][0]['name'] = 'Name changed while migrating'
                bucket['profiles'][1].update(name='Concurrent edit', api_key='fixture-new-manual-secret')
                catalog['concurrent_user_extension'] = {'must': 'survive'}
            self.transport.service.update(edit)
        self.transport.before_patch = concurrent_user_save
        await self.bridge.reconcile_learning_defaults()
        catalog = self.catalog()
        bucket = catalog['services']['llm']
        self.assertEqual(bucket['active_profile_id'], 'manual')
        self.assertEqual(bucket['active_model_id'], 'manual-model')
        self.assertEqual(bucket['profiles'][0]['models'][0]['name'], 'Name changed while migrating')
        self.assertEqual(bucket['profiles'][1]['name'], 'Concurrent edit')
        self.assertEqual(bucket['profiles'][1]['api_key'], 'fixture-new-manual-secret')
        self.assertEqual(catalog['concurrent_user_extension'], {'must': 'survive'})
        self.assertEqual(bucket['profiles'][0]['models'][0]['context_window'], '1000000')
        self.assertFalse(any(method == 'PUT' for method, _ in self.transport.calls))

    def test_actual_catalog_write_lock_serializes_user_save_then_metadata_merge(self):
        entered, release, patch_started = Event(), Event(), Event()
        def edit(catalog):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Fixture lock release timed out')
            bucket = catalog['services']['llm']
            bucket.update(active_profile_id='manual', active_model_id='manual-model')
            bucket['profiles'][1]['name'] = 'Concurrent locked save'
        def metadata_write():
            patch_started.set()
            return patch_context_metadata(self.transport.service, {'routes': [
                {key: self.route[key] for key in ('profile_id', 'route_id', 'model', 'route')}]})
        with ThreadPoolExecutor(max_workers=2) as pool:
            user_future = pool.submit(self.transport.service.update, edit)
            try:
                self.assertTrue(entered.wait(5))
                metadata_future = pool.submit(metadata_write)
                self.assertTrue(patch_started.wait(5))
                self.assertFalse(metadata_future.done())
            finally:
                release.set()
            user_future.result(timeout=5)
            self.assertEqual(metadata_future.result(timeout=5)['updated'], 1)
        bucket = self.catalog()['services']['llm']
        self.assertEqual(bucket['active_model_id'], 'manual-model')
        self.assertEqual(bucket['profiles'][1]['name'], 'Concurrent locked save')
        self.assertEqual(bucket['profiles'][0]['models'][0]['context_window'], '1000000')

    async def test_authenticated_internal_route_accepts_only_metadata_identities(self):
        from fastapi import FastAPI
        import httpx
        from integration.deeptutor_shared_provider import install_routes
        app = FastAPI()
        install_routes(app, token_loader=lambda: 'fixture-internal-control')
        route_path = '/api/contest/internal/learning-context-metadata'
        body = {'routes': [{key: self.route[key] for key in ('profile_id', 'route_id', 'model', 'route')}]}
        writes = []
        @contextmanager
        def runtime_write_fixture():
            writes.append('enter')
            yield
            writes.append('leave')
        with patch('deeptutor.services.config.get_model_catalog_service', return_value=self.transport.service), \
                patch('deeptutor.api.routers.settings._runtime_catalog_write', runtime_write_fixture):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                denied = await client.post(route_path, json=body)
                self.assertEqual(denied.status_code, 401)
                headers = {'Authorization': 'Bearer fixture-internal-control'}
                browser = await client.post(route_path, json=body, headers={**headers, 'Origin': 'http://fixture'})
                self.assertEqual(browser.status_code, 403)
                rejected = await client.post(route_path, json={**body, 'active_model_id': 'manual-model'}, headers=headers)
                self.assertEqual(rejected.status_code, 422)
                accepted = await client.post(route_path, json=body, headers=headers)
                self.assertEqual(accepted.status_code, 200)
                self.assertEqual(accepted.json(), {'matched': 1, 'updated': 1})
        self.assertNotIn('fixture-gateway-only', accepted.text)
        self.assertTrue(writes)
        bucket = self.catalog()['services']['llm']
        self.assertEqual(bucket['active_model_id'], self.route['route_id'])
        self.assertEqual(bucket['profiles'][0]['models'][0]['context_window'], '1000000')


if __name__ == '__main__':
    unittest.main()
