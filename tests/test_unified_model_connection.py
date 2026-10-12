"""Origin, workspace, and credential custody checks with isolated fixtures.

Current model resolution and streaming contracts are covered by
test_unified_model_runtime.py. Superseded pre-unified API assumptions and
the retired local model are intentionally not treated as current behavior.
These fixtures never provide real model or account evidence.
"""
import asyncio
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from integration.harness_bridge import HarnessBridge, HarnessError, GATEWAY
from integration.openmaic_bridge import OpenMAICBridge
from portal.storage import Store


class Transport:
    def __init__(self):
        self.calls = []
        self.catalog = {'services': {'llm': {'profiles': [], 'active_profile_id': '', 'active_model_id': ''}}}
        self.fail_workspace = None
        self.native_result = None
        self.parsing = {'image_description_model': None}
        self.workspace_rows = []
        self.native_workspace_rows = []

    def token(self):
        return 'test-service-authentication-token-never-production'

    async def host(self, method, path, body=None, timeout=45):
        self.calls.append((method, path, deepcopy(body)))
        if self.fail_workspace and path.startswith('/sessions/'):
            raise self.fail_workspace
        if path == '/probe':
            return {'ok': True, 'vision_verified': True}
        if path == '/workspaces' and method == 'GET':
            return {'workspaces': deepcopy(self.workspace_rows)}
        if path.startswith('/workspaces') or path.startswith('/sessions') or path.startswith('/approvals'):
            return {'fixture': True, 'method': method, 'path': path}
        return {'ok': True}

    async def native(self, method, path, body=None):
        if method == 'GET':
            return {'catalog': deepcopy(self.catalog)}
        if path.endswith('/apply/provider'):
            bucket = self.catalog['services']['llm']
            bucket['profiles'].append(deepcopy(body['profile']))
            bucket.update(active_profile_id=body['profile']['id'], active_model_id=body['active_model_id'])
        return {'catalog': deepcopy(self.catalog)}

    async def native_internal(self):
        return deepcopy(self.native_result)

    async def native_service(self, method, path, body=None):
        from integration.learning_defaults import snapshot_defaults, select_defaults, restore_defaults
        from integration.embedding_route_guard import embedding_status
        if path == 'embedding-status':
            return embedding_status(self.catalog)
        if method == 'GET':
            return snapshot_defaults(self.catalog, self.parsing)
        if path == 'learning-defaults':
            self.catalog, self.parsing = select_defaults(self.catalog, self.parsing, body['profile_id'], body['vision'])
            return {'applied': True}
        self.catalog, self.parsing, restored = restore_defaults(self.catalog, self.parsing, body['profile_id'], body['snapshot'])
        return {'restored': restored}

    async def native_workspace(self, workspace_id):
        if workspace_id != 'native_workspace_fixture':
            raise HarnessError('workspace_missing', 'The workspace is not registered.', 404)
        return {'workspace_id': workspace_id, 'path': self.workspace_rows[0]['path']}

    async def native_workspace_service(self, method, path='workspaces', body=None):
        # Registration now checks both existing catalogs before reusing a
        # folder. This fixture intentionally supplies only the read contract;
        # unexpected writes must still fail instead of becoming fake success.
        if method != 'GET' or path != 'workspaces' or body is not None:
            raise AssertionError('Unexpected native workspace fixture mutation')
        self.calls.append(('NATIVE_GET', path, None))
        return {'workspaces': deepcopy(self.native_workspace_rows)}

    async def host_attachment(self, session_id, attachment_id):
        if session_id != 'session_fixture' or attachment_id != 'attachment_fixture':
            raise HarnessError('attachment_unavailable', 'The image is unavailable.', 404)
        return b'\x89PNG\r\nfixture-only-bytes', 'image/png'


class UnifiedConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='unified-connection-fixtures-')
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.transport = Transport()
        self.bridge = HarnessBridge(self.store, transport=self.transport)
        with patch.dict(os.environ, {'EDUAGENT_DATA': self.temp.name}):
            self.api = importlib.import_module('portal.app')
        self.patch_store = patch.object(self.api, 'store', self.store)
        self.patch_bridge = patch.object(self.api, 'harness_bridge', return_value=self.bridge)
        self.patch_store.start(); self.patch_bridge.start()
        self.addCleanup(self.patch_store.stop); self.addCleanup(self.patch_bridge.stop)
        self.client = TestClient(self.api.app)
        self.addCleanup(self.client.close)
        self.headers = {'Origin': 'http://127.0.0.1:3792'}

    def applied(self):
        async def create():
            op = self.bridge.credential('fixture-only-api-secret-not-live')['operation']
            op = (await self.bridge.probe(op['id'], op['revision'], 'fixture-deepseek-model'))['operation']
            await self.bridge.apply(op['id'], op['revision'], True, ['learning', 'classroom'])
        asyncio.run(create())
        return self.store.harness_state('current')

    def test_tts_partial_write_preserves_model_and_preexisting_api_keys(self):
        self.store.save_settings({'model_mode': 'api', 'base_url': 'https://example.invalid/v1',
            'model': 'original-model', 'api_key': 'fixture-preexisting-key'})
        current = self.applied()
        self.client.put('/api/settings', json={'tts_mode': 'api', 'tts_base_url': 'https://tts.invalid/v1',
            'tts_api_key': 'fixture-narration-key', 'tts_model': 'voice-model'}, headers=self.headers)
        self.assertEqual(self.bridge.provider(self.store.settings())['api_key'], current['guard'])
        private = self.store.settings(secret=True)
        self.assertEqual(private['api_key'], '')
        self.assertEqual(private['tts_api_key'], 'fixture-narration-key')
        self.client.put('/api/settings', json={'connection_mode': 'custom', 'base_url': 'https://example.invalid/v1',
            'model': 'original-model'}, headers=self.headers)
        self.assertEqual(self.store.settings(secret=True)['api_key'], 'fixture-preexisting-key')

    def test_orphan_gateway_changes_rejected_without_erasing_saved_route(self):
        current = self.applied()
        for changes in ({'connection_mode': 'custom'}, {'model': 'dsroute_unknown'}, {'clear_api_key': True}):
            response = self.client.put('/api/settings', json=changes, headers=self.headers)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(self.store.settings()['harness_route_id'], current['route_id'])

    def test_missing_current_and_mismatch_fail_closed(self):
        self.assertEqual(self.client.put('/api/settings', json={'connection_mode': 'current'}, headers=self.headers).status_code, 409)
        self.applied()
        settings = self.store.settings()
        settings['harness_route_id'] = 'dsroute_stale'
        with self.assertRaises(HarnessError) as caught:
            self.bridge.provider(settings)
        self.assertEqual(caught.exception.code, 'connection_unavailable')
        settings.pop('harness_route_id')
        with self.assertRaises(HarnessError):
            self.bridge.provider(settings)

    def test_workspace_routes_require_origin_and_reject_credential_fields(self):
        self.assertEqual(self.client.get('/api/harness/workspaces').status_code, 403)
        self.assertEqual(self.client.get('/api/harness/workspaces', headers={'Origin': 'https://evil.test'}).status_code, 403)
        self.assertEqual(self.transport.calls, [])
        response = self.client.post('/api/harness/workspaces', json={'path': self.temp.name, 'name': 'Synthetic workspace'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn(('NATIVE_GET', 'workspaces', None), self.transport.calls)
        self.assertEqual(self.transport.calls[-1], ('POST', '/workspaces',
            {'path': self.temp.name, 'name': 'Synthetic workspace'}))
        accepted_calls = deepcopy(self.transport.calls)
        response = self.client.post('/api/harness/workspaces', json={'path': self.temp.name, 'api_key': 'accidental-fixture-secret'}, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('accidental-fixture-secret', response.text)
        self.assertEqual(self.client.post('/api/harness/sessions/session_fixture/turn', json={'text': 'fixture task', 'route_id': 'stale'}, headers=self.headers).status_code, 422)
        self.assertEqual(self.transport.calls, accepted_calls)

    def test_workspace_cancel_approval_and_events_bridge_preserves_ownership_ids(self):
        self.assertEqual(self.client.get('/api/harness/sessions/session_fixture/events?after_seq=9', headers=self.headers).status_code, 200)
        self.assertEqual(self.transport.calls[-1][1], '/sessions/session_fixture/events?after_seq=9')
        self.assertEqual(self.client.post('/api/harness/sessions/session_fixture/cancel', json={}, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post('/api/harness/approvals/approval_fixture', json={'session_id': 'session_fixture', 'decision': 'deny'}, headers=self.headers).status_code, 200)
        self.assertEqual(self.transport.calls[-1][2], {'session_id': 'session_fixture', 'decision': 'deny'})
        self.assertEqual(self.client.post('/api/harness/approvals/approval_fixture', json={'session_id': 'session_fixture', 'decision': 'always'}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get('/api/harness/sessions/session_fixture/events?after_seq=-1', headers=self.headers).status_code, 200)
        self.assertEqual(self.transport.calls[-1][1], '/sessions/session_fixture/events?after_seq=-1')
        self.assertEqual(self.client.get('/api/harness/sessions/session_fixture/events?after_seq=-2', headers=self.headers).status_code, 422)

    def test_workspace_actual_error_code_is_not_replaced_by_success(self):
        self.transport.fail_workspace = HarnessError('route_changed', 'The connection changed. Start again.', 409)
        response = self.client.post('/api/harness/sessions/session_fixture/turn', json={'text': 'fixture task'}, headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'route_changed')

    def test_guarded_migration_repairs_exact_old_tts_bug_only(self):
        current = self.applied()
        with self.store.connect() as db:
            value = json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()['value'])
            value.pop('harness_route_id'); value.pop('connection_selection')
            db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(value),))
        reopened = Store(self.store.root)
        self.assertEqual(reopened.settings()['harness_route_id'], current['route_id'])
        for marker, model in [('custom', current['route_id']), (None, 'unrelated-model')]:
            with reopened.connect() as db:
                value.pop('harness_route_id', None)
                if marker:
                    value['connection_selection'] = marker
                else:
                    value.pop('connection_selection', None)
                value['model'] = model
                db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(value),))
            self.assertNotIn('harness_route_id', Store(self.store.root).settings())

    def test_attachment_binary_preview_keeps_session_identity_and_origin(self):
        endpoint = '/api/harness/sessions/session_fixture/attachments/attachment_fixture'
        self.assertEqual(self.client.get(endpoint).status_code, 403)
        response = self.client.get(endpoint, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertTrue(response.content.startswith(b'\x89PNG'))
        self.assertEqual(self.client.get('/api/harness/sessions/foreign_session/attachments/attachment_fixture', headers=self.headers).status_code, 404)

    def test_persisted_native_workspace_id_opens_only_matched_registered_folder(self):
        self.transport.workspace_rows = [{'id': 'harness_workspace_fixture', 'path': self.temp.name}]
        headers = {'Authorization': 'Bearer ' + self.transport.token()}
        endpoint = '/api/harness/internal/workspaces/native_workspace_fixture'
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        response = self.client.get(endpoint, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['harness_workspace_id'], 'harness_workspace_fixture')
        self.assertEqual(response.json()['path'], str(Path(self.temp.name).resolve()))
        self.assertEqual(self.client.get('/api/harness/internal/workspaces/unknown_fixture', headers=headers).status_code, 404)


class NativeServerOnlyEndpointTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from integration.deeptutor_shared_provider import install_routes
        self.calls = 0
        def resolver():
            self.calls += 1
            return (SimpleNamespace(model='fixture-model', base_url='https://native.invalid/v1',
                binding='custom', provider_mode='api', provider_name='custom', api_format='openai_chat',
                extra_headers={}, capabilities={}), 'fixture-native-secret', 'Fixture profile')
        app = FastAPI()
        install_routes(app, token_loader=lambda: 'fixture-local-service-token', resolver=resolver)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_native_provider_route_authenticates_before_secret_resolution(self):
        for headers in ({}, {'Authorization': 'Bearer wrong'}, {'Authorization': 'Bearer fixture-local-service-token', 'Origin': 'http://127.0.0.1:3792'}):
            response = self.client.get('/api/contest/internal/provider', headers=headers)
            self.assertIn(response.status_code, (401, 403))
            self.assertNotIn('fixture-native-secret', response.text)
        self.assertEqual(self.calls, 0)
        response = self.client.get('/api/contest/internal/provider', headers={'Authorization': 'Bearer fixture-local-service-token'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['provider']['api_key'], 'fixture-native-secret')
        self.assertEqual(self.calls, 1)


if __name__ == '__main__':
    unittest.main()
