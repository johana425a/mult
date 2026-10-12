"""Independent cross-boundary audit. All transport responses are keyless fixtures.

These checks prove local custody/state contracts, not official account access
or successful cloud inference. Retired onboarding tools must remain inactive.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration.harness_bridge import HarnessBridge, HarnessError, public_operation
from portal.storage import Store
from scripts.package_handoff import allowed


class HeldProbeTransport:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.first = True
        self.calls = []

    async def host(self, method, path, body=None, timeout=45):
        self.calls.append((method, path, body))
        if path == '/probe' and self.first:
            self.first = False
            self.started.set()
            await self.release.wait()
        if path == '/probe':
            return {'ok': True, 'vision_verified': False}
        if path == '/assistant':
            return {'reply': 'Enter the key in the dedicated secure field.', 'action': 'secure_credential',
                    'model_called': True, 'tool_calls': [{'arguments': 'private fixture'}]}
        raise AssertionError('Unexpected fixture request: ' + path)


class InterruptedCommitTransport:
    """Native commit takes effect, then its caller disappears before a reply."""
    def __init__(self):
        self.committed = asyncio.Event()
        self.release = asyncio.Event()
        self.catalog = {'services': {'llm': {'active_profile_id': 'original',
            'active_model_id': 'old-model', 'profiles': [{'id': 'original'}]}}}
        self.routes = {}
        self.parsing = {'image_description_model': None}

    async def native_service(self, method, path, body=None):
        from integration.learning_defaults import snapshot_defaults, select_defaults, restore_defaults
        if method == 'GET':
            return snapshot_defaults(self.catalog, self.parsing)
        if path == 'learning-defaults':
            self.catalog, self.parsing = select_defaults(self.catalog, self.parsing, body['profile_id'], body['vision'])
            return {'applied': True}
        self.catalog, self.parsing, restored = restore_defaults(self.catalog, self.parsing, body['profile_id'], body['snapshot'])
        return {'restored': restored}

    async def host(self, method, path, body=None, timeout=45):
        if path == '/probe':
            return {'ok': True, 'vision_verified': False}
        if path == '/routes':
            self.routes[body['route_id']] = deepcopy(body)
            return {'ok': True}
        if path.startswith('/routes/'):
            self.routes.pop(path.rsplit('/', 1)[1], None)
            return {'ok': True}
        raise AssertionError('Unexpected fixture host request: ' + path)

    async def native(self, method, path, body=None):
        if method == 'GET':
            return {'catalog': deepcopy(self.catalog)}
        if method == 'PUT':
            self.catalog = deepcopy(body['catalog'])
            return {'catalog': deepcopy(self.catalog)}
        profile = deepcopy(body['profile'])
        bucket = self.catalog['services']['llm']
        bucket['profiles'].append(profile)
        bucket.update(active_profile_id=profile['id'], active_model_id=body['active_model_id'])
        self.committed.set()
        await self.release.wait()
        return {'catalog': deepcopy(self.catalog)}


class HarnessContractAudit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Test-local deterministic protection is deliberately not DPAPI evidence.
        self.protection = patch('portal.storage.protect',
            side_effect=lambda value, decrypt=False: value.removeprefix('fixture:') if decrypt else 'fixture:' + value)
        self.protection.start()
        self.addCleanup(self.protection.stop)
        self.store = Store(Path(self.temp.name))
        self.transport = HeldProbeTransport()
        self.bridge = HarnessBridge(self.store, transport=self.transport)

    def test_public_operation_projects_no_credential_or_snapshot(self):
        value = public_operation({'id': 'one', 'revision': 2, 'secret_ref': 'private-ref',
            'guard': 'private-guard', 'api_key': 'private-key', 'authorization_url': 'private-url',
            'recovery': {'native_snapshot': 'private'}, 'previous': 'private', 'probe': {'ok': True}})
        encoded = json.dumps(value)
        self.assertNotIn('private', encoded)
        self.assertEqual(value['id'], 'one')

    async def test_model_tools_cannot_commit_or_take_arbitrary_authority(self):
        operation = self.bridge.credential('fixture-key-only')
        for _ in range(3):
            with self.assertRaises(HarnessError) as removed:
                await self.bridge.tool('apply_configuration',
                    {'confirm': True, 'api_key': 'private-key', 'targets': ['learning', 'classroom']},
                    operation['operation']['id'])
            self.assertEqual(removed.exception.code, 'onboarding_assistant_removed')
            self.assertEqual(removed.exception.status, 410)
            self.assertIsNone(self.bridge.current())
            self.assertEqual(self.transport.calls, [])
        for tool in ('shell', 'write_file', 'signout', 'http_request', 'configure_arbitrary_provider'):
            with self.assertRaises(HarnessError) as caught:
                await self.bridge.tool(tool, {}, operation['operation']['id'])
            self.assertEqual(caught.exception.code, 'onboarding_assistant_removed')

    async def test_pasted_key_is_rejected_before_model_or_session_call(self):
        secret = 'sk-fixturecredentialonly123456'
        with self.assertRaises(HarnessError) as removed:
            await self.bridge.assistant('My API key: ' + secret)
        self.assertEqual(removed.exception.code, 'onboarding_assistant_removed')
        self.assertNotIn(secret, str(removed.exception))
        self.assertEqual(self.transport.calls, [])

    async def test_retired_assistant_does_not_request_host_tool_arguments(self):
        with self.assertRaises(HarnessError) as removed:
            await self.bridge.assistant('I have no API. How do I connect?')
        self.assertEqual(removed.exception.code, 'onboarding_assistant_removed')
        self.assertNotIn('private fixture', str(removed.exception))
        self.assertEqual(self.transport.calls, [])

    async def test_old_probe_cannot_replace_a_new_operation_with_same_revision(self):
        first = self.bridge.credential('first-fixture-key')['operation']
        pending = asyncio.create_task(self.bridge.probe(first['id'], first['revision'], 'deepseek-chat'))
        await self.transport.started.wait()
        active = self.store.harness_state()
        await self.bridge.cancel(active['id'], active['revision'])
        second = self.bridge.credential('second-fixture-key')['operation']
        await self.bridge.probe(second['id'], second['revision'], 'deepseek-chat')
        # A new operation can happen to have the same revision. Force its local
        # version to the captured old revision to audit identity as well as CAS.
        second_state = self.store.harness_state()
        second_state['revision'] = 3
        self.store.save_harness_state(second_state)
        self.transport.release.set()
        try:
            await pending
        except HarnessError as exc:
            self.assertEqual(exc.code, 'stale_revision')
        saved = self.store.harness_state()
        self.assertEqual(saved['id'], second['id'], 'Late old probe replaced the new operation.')
        self.assertEqual(saved['secret_ref'], second_state['secret_ref'])

    async def test_interrupted_native_commit_has_a_durable_recovery_journal(self):
        transport = InterruptedCommitTransport()
        bridge = HarnessBridge(self.store, transport=transport)
        initial = bridge.credential('crash-fixture-key')['operation']
        verified = (await bridge.probe(initial['id'], initial['revision'], 'deepseek-chat'))['operation']
        applying = asyncio.create_task(bridge.apply(verified['id'], verified['revision'], True,
            ['learning', 'classroom']))
        await transport.committed.wait()
        applying.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await applying
        stored = self.store.harness_state()
        self.assertIsInstance(stored.get('recovery'), dict,
            'Configuration side effects began before a durable rollback journal was saved.')
        reopened = Store(Path(self.temp.name))
        restored = HarnessBridge(reopened, transport=transport)
        await restored.restore_routes()
        state = reopened.harness_state()
        self.assertIn(state['status'], ('rolled_back', 'rollback_required'))
        if state['status'] == 'rollback_required':
            result = await restored.rollback(state['id'], state['revision'], True)
            self.assertEqual(result['operation']['status'], 'rolled_back')
        self.assertEqual(transport.catalog['services']['llm']['active_profile_id'], 'original')
        self.assertEqual(transport.catalog['services']['llm']['profiles'], [{'id': 'original'}])
        self.assertIsNone(restored.current())

    def test_export_filter_excludes_new_live_state_names(self):
        for name in ('integration/harness/.dsh/credentials.json',
                     'integration/harness/control-token', 'desktop/userData/Cookies',
                     'integration/harness/account-state.json', 'integration/harness/node_modules/anything.js'):
            self.assertFalse(allowed(Path(name)), name)
        self.assertTrue(allowed(Path('integration/harness/sidecar.mjs')))


class HarnessRouteAudit(unittest.TestCase):
    """Actual HTTP routing and validation, using a temporary store and no Host."""
    def setUp(self):
        from fastapi.testclient import TestClient
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.dict('os.environ', {'EDUAGENT_DATA': self.temp.name}):
            self.api = importlib.import_module('portal.app')
        self.store_patch = patch.object(self.api, 'store', Store(Path(self.temp.name)))
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.host_patch = patch.object(self.api, 'harness_bridge')
        self.fake_host = self.host_patch.start()
        self.addCleanup(self.host_patch.stop)
        self.client = TestClient(self.api.app)
        self.addCleanup(self.client.close)

    def test_public_mutations_require_local_browser_origin(self):
        for origin in (None, 'https://evil.test', 'null', 'http://127.0.0.1.evil.test:3792'):
            headers = {'Origin': origin} if origin is not None else {}
            response = self.client.post('/api/harness/account/start', headers=headers)
            self.assertEqual(response.status_code, 403)
        self.fake_host.assert_not_called()

    def test_workspace_catalog_and_management_require_local_origin_before_dispatch(self):
        with patch.object(self.api, 'workspace_manager') as manager:
            for origin in (None, 'null', 'https://evil.test', 'http://127.0.0.1.evil.test:3792'):
                headers = {'Origin': origin} if origin is not None else {}
                for endpoint in ('/api/harness/workspaces', '/api/harness/workspace-management/catalog'):
                    self.assertEqual(self.client.get(endpoint, headers=headers).status_code, 403)
                self.assertEqual(self.client.patch('/api/harness/workspaces/native_fixture/manage',
                    headers=headers, json={'archived': True}).status_code, 403)
            manager.assert_not_called()

    def test_workspace_management_rejects_file_deletion_or_route_injection(self):
        with patch.object(self.api, 'workspace_manager') as manager:
            response = self.client.patch('/api/harness/workspaces/native_fixture/manage',
                headers={'Origin': 'http://127.0.0.1:3792'},
                json={'archived': True, 'delete_files': True, 'path': 'D:/foreign-fixture'})
            self.assertEqual(response.status_code, 422)
            manager.assert_not_called()

    def test_credential_validation_never_echoes_the_bad_payload(self):
        secret = 'fixture-private-payload-not-a-live-key'
        cases = [{'api_key': secret, 'unexpected': secret},
                 {'api_key': secret, 'model': [secret]},
                 {'api_key': secret, 'operation_id': [secret]}]
        for value in cases:
            response = self.client.post('/api/harness/credential', json=value,
                headers={'Origin': 'http://127.0.0.1:3792'})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(secret, response.text)
        self.fake_host.assert_not_called()

    def test_removed_assistant_endpoint_never_echoes_accidental_secrets(self):
        secret = 'fixture-private-payload-not-a-live-key'
        for value in ({'message': [secret]}, {'message': secret * 110}):
            response = self.client.post('/api/harness/assistant', json=value,
                headers={'Origin': 'http://127.0.0.1:3792'})
            self.assertEqual(response.status_code, 404)
            self.assertNotIn(secret, response.text)
        self.fake_host.assert_not_called()

    def test_internal_secret_resolution_requires_service_authentication(self):
        self.fake_host.return_value.authenticate_internal.return_value = False
        for headers in ({}, {'Authorization': 'Bearer fixture-wrong-internal-token'}):
            response = self.client.post('/api/harness/internal/secret',
                json={'secret_ref': 'fixture-ref', 'route_id': 'fixture-route'}, headers=headers)
            self.assertEqual(response.status_code, 401)
        self.fake_host.return_value.secret.assert_not_called()


if __name__ == '__main__':
    unittest.main()
