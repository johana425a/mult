"""Restricted config fixture tests. No live account, cloud API or inference."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from integration.harness_bridge import HarnessBridge, HarnessError, public_operation
from portal.storage import Store


class FixtureTransport:
    def __init__(self):
        self.calls = []
        self.routes = {}
        self.probe_result = {'ok': True, 'vision_verified': False}
        self.probe_wait = None
        self.fail_apply = False
        self.catalog = {'services': {'llm': {'profiles': [
            {'id': 'original', 'api_key': '********', 'models': [{'id': 'old', 'model': 'old-model'}]}],
            'active_profile_id': 'original', 'active_model_id': 'old'},
            'tts': {'profiles': [{'id': 'narration'}]}}, 'unrelated': 'retain'}
        self.parsing = {'image_description_model': None}

    async def native_service(self, method, path, body=None):
        if path == 'learning-context-metadata':
            from integration.context_metadata import patch_context_metadata
            transport = self
            class CatalogFixture:
                def update(self, mutator):
                    mutator(transport.catalog)
            return patch_context_metadata(CatalogFixture(), body)
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

    def token(self):
        return 'fixture-control-token-for-local-contract-only'

    async def host(self, method, path, body=None, timeout=45):
        self.calls.append((method, path, deepcopy(body)))
        if path == '/health':
            return {'ok': True}
        if path == '/account/status':
            return {'authenticated': False, 'balance_status': 'query_failed', 'token': 'must-never-escape'}
        if path == '/account/login/start':
            return {'authorization_url': 'https://platform.deepseek.com/dsh/authorize?state=fixture', 'attempt_id': 'fixture-attempt'}
        if path == '/models':
            return {'models': [{'id': 'deepseek-chat', 'label': 'fixture model', 'vision': False}]}
        if path == '/probe':
            if self.probe_wait:
                await self.probe_wait.wait()
            return deepcopy(self.probe_result)
        if path == '/routes':
            self.routes[body['route_id']] = deepcopy(body)
            return {'ok': True}
        if path.startswith('/routes/'):
            self.routes.pop(path.split('/')[-1], None)
            return {'ok': True}
        if path == '/assistant':
            return {'reply': 'Fixture response, not inference', 'model_called': False}
        return {'ok': True}

    async def native(self, method, path, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if method == 'GET':
            return {'catalog': deepcopy(self.catalog)}
        if path.endswith('/apply/provider'):
            bucket = self.catalog['services']['llm']
            bucket['profiles'].append(deepcopy(body['profile']))
            bucket.update(active_profile_id=body['profile']['id'], active_model_id=body['active_model_id'])
            if self.fail_apply:
                raise HarnessError('timeout', 'fixture timeout after commit', 503)
        if method == 'PUT':
            self.catalog = deepcopy(body['catalog'])
        return {'catalog': deepcopy(self.catalog)}


class HarnessBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='harness-contract-')
        self.store = Store(Path(self.folder.name))
        self.transport = FixtureTransport()
        self.bridge = HarnessBridge(self.store, transport=self.transport)

    def tearDown(self):
        self.folder.cleanup()

    def credential(self):
        return self.bridge.credential('fixture-secret-do-not-export')['operation']

    async def verified(self):
        op = self.credential()
        return (await self.bridge.probe(op['id'], op['revision'], 'deepseek-chat'))['operation']

    async def test_managed_capacity_tracks_real_model_and_retired_local_fails_closed(self):
        with self.assertRaises(HarnessError) as retired:
            self.bridge.provider({'model_mode': 'local'})
        self.assertEqual(retired.exception.code, 'model_selection_required')
        op = self.credential()
        op = (await self.bridge.probe(op['id'], op['revision'], 'deepseek-flash'))['operation']
        await self.bridge.apply(op['id'], op['revision'], True, ['learning', 'classroom'])
        current = self.store.harness_state('current')
        managed = self.bridge.provider(self.store.settings())
        self.assertEqual(managed['model'], current['route_id'])
        self.assertEqual(managed['context_window'], 1000000)
        self.assertEqual(managed['max_output_tokens'], 384000)
        self.assertEqual(self.bridge.connection(self.store.settings())['model'], 'deepseek-flash')
        model = self.transport.catalog['services']['llm']['profiles'][-1]['models'][0]
        self.assertEqual(model['actual_model'], 'deepseek-flash')
        self.assertEqual(model['context_window'], '1000000')
        with self.assertRaises(HarnessError) as retired:
            self.bridge.provider({'model_mode': 'local'})
        self.assertEqual(retired.exception.code, 'model_selection_required')

    async def test_existing_owned_route_context_migrates_without_probe_or_selection_reset(self):
        op = self.credential()
        op = (await self.bridge.probe(op['id'], op['revision'], 'deepseek-flash'))['operation']
        await self.bridge.apply(op['id'], op['revision'], True, ['learning', 'classroom'])
        current = self.store.harness_state('current')
        current.pop('context_metadata_revision', None)
        self.store.save_harness_state(current, 'current')
        bucket = self.transport.catalog['services']['llm']
        model = bucket['profiles'][-1]['models'][0]
        for key in ('actual_model', 'context_window', 'context_window_source', 'max_output_tokens'):
            model.pop(key, None)
        # A later explicit native selection and a custom name must survive.
        model['name'] = 'My model'
        bucket.update(active_profile_id='original', active_model_id='old')
        before_original = deepcopy(bucket['profiles'][0])
        self.transport.calls.clear()
        await self.bridge.reconcile_learning_defaults()
        bucket = self.transport.catalog['services']['llm']
        self.assertEqual(bucket['active_profile_id'], 'original')
        self.assertEqual(bucket['active_model_id'], 'old')
        self.assertEqual(bucket['profiles'][0], before_original)
        repaired = bucket['profiles'][-1]['models'][0]
        self.assertEqual(repaired['model'], current['route_id'])
        self.assertEqual(repaired['name'], 'My model')
        self.assertEqual(repaired['actual_model'], 'deepseek-flash')
        self.assertEqual(repaired['context_window'], '1000000')
        self.assertFalse(any('/probe' in path or '/account/' in path for _, path, _ in self.transport.calls))
        self.transport.calls.clear()
        await self.bridge.reconcile_learning_defaults()
        self.assertFalse(any(method == 'PUT' for method, _, _ in self.transport.calls))

    def test_account_limit_is_separate_from_api_and_unknown_not_invented(self):
        from integration.model_limits import managed_model_limits
        self.assertEqual(managed_model_limits('deepseek-flash', 'account')['context_window'], 1000000)
        self.assertEqual(managed_model_limits('deepseek-flash', 'account')['max_output_tokens'], 256000)
        self.assertEqual(managed_model_limits('deepseek-flash', 'apikey')['max_output_tokens'], 384000)
        self.assertEqual(managed_model_limits('unlisted-custom-model', 'apikey'), {})

    async def test_repeated_configuration_rollback_preserves_unrelated(self):
        self.store.save_settings({'model_mode': 'api', 'base_url': 'https://old.invalid/v1',
                                  'model': 'old-model', 'api_key': 'fixture-original-secret',
                                  'tts_mode': 'api', 'tts_api_key': 'fixture-narration-secret', 'tts_model': 'tts-old'})
        for _ in range(3):
            op = await self.verified()
            applied = await self.bridge.apply(op['id'], op['revision'], True, ['learning', 'classroom'])
            current = self.store.harness_state('current')
            self.assertEqual(self.transport.catalog['services']['llm']['active_profile_id'], current['profile_id'])
            self.assertNotIn('fixture-secret-do-not-export', json.dumps(self.transport.catalog))
            self.assertNotIn('api_key', json.dumps(self.transport.routes))
            self.assertEqual(self.bridge.secret(current['secret_ref'], current['route_id']), 'fixture-secret-do-not-export')
            self.assertEqual(self.store.settings(secret=True)['api_key'], '')
            reopened = Store(Path(self.folder.name))
            recovered = HarnessBridge(reopened, transport=FixtureTransport())
            await recovered.restore_routes()
            self.assertIn(current['route_id'], recovered.transport.routes)
            self.assertNotIn('fixture-secret-do-not-export', self.store.path.read_bytes().decode('latin1'))
            self.store.save_settings({'tts_model': 'tts-user-edited'})
            self.transport.catalog['unrelated'] = 'user-new-value'
            after = await self.bridge.rollback(op['id'], applied['operation']['revision'], True)
            self.assertEqual(after['operation']['status'], 'rolled_back')
            self.assertEqual(self.transport.catalog['services']['llm']['active_profile_id'], 'original')
            self.assertEqual(self.transport.catalog['unrelated'], 'user-new-value')
            self.assertEqual(self.transport.catalog['services']['tts']['profiles'][0]['id'], 'narration')
            settings = self.store.settings(secret=True)
            self.assertEqual(settings['api_key'], 'fixture-original-secret')
            self.assertEqual(settings['tts_api_key'], 'fixture-narration-secret')
            self.assertEqual(settings['tts_model'], 'tts-user-edited')

    async def test_401_blocks_retry_and_apply_until_new_credential(self):
        for _ in range(3):
            self.transport.probe_result = {'ok': False, 'error': {'code': 'provider_auth', 'status': 401}}
            op = self.credential()
            failed = (await self.bridge.probe(op['id'], op['revision'], 'deepseek-chat'))['operation']
            self.assertEqual(failed['status'], 'credential_invalid')
            with self.assertRaises(HarnessError):
                await self.bridge.probe(op['id'], failed['revision'], 'deepseek-chat')
            with self.assertRaises(HarnessError):
                await self.bridge.apply(op['id'], failed['revision'], True, ['learning'])
            replaced = self.bridge.credential('fixture-replaced-secret', op_id=op['id'], revision=failed['revision'])['operation']
            self.transport.probe_result = {'ok': True}
            result = await self.bridge.probe(op['id'], replaced['revision'], 'deepseek-chat')
            self.assertEqual(result['operation']['status'], 'verified')

    async def test_quota_is_not_auth_and_never_applies(self):
        for _ in range(3):
            self.transport.probe_result = {'ok': False, 'error': {'code': 'quota_exhausted', 'status': 402}}
            op = self.credential()
            failed = (await self.bridge.probe(op['id'], op['revision'], 'deepseek-chat'))['operation']
            self.assertEqual(failed['status'], 'probe_failed')
            self.assertEqual(failed['error_code'], 'quota_exhausted')
            with self.assertRaises(HarnessError):
                await self.bridge.apply(op['id'], failed['revision'], True, ['classroom'])

    async def test_cancel_discards_late_probe_across_new_operation(self):
        for _ in range(3):
            op = self.credential()
            self.transport.probe_wait = asyncio.Event()
            task = asyncio.create_task(self.bridge.probe(op['id'], op['revision'], 'deepseek-chat'))
            await asyncio.sleep(0)
            pending = self.store.harness_state()
            await self.bridge.cancel(op['id'], pending['revision'])
            next_op = self.credential()
            self.transport.probe_wait.set()
            with self.assertRaises(HarnessError):
                await task
            self.assertEqual(self.store.harness_state()['id'], next_op['id'])
            self.assertEqual(self.store.harness_state()['status'], 'awaiting_model')
            self.transport.probe_wait = None

    async def test_timeout_after_native_commit_compensates(self):
        for _ in range(3):
            op = await self.verified()
            self.transport.fail_apply = True
            with self.assertRaises(HarnessError):
                await self.bridge.apply(op['id'], op['revision'], True, ['learning', 'classroom'])
            self.assertEqual(len(self.transport.catalog['services']['llm']['profiles']), 1)
            self.assertEqual(self.transport.catalog['services']['llm']['active_profile_id'], 'original')
            self.assertIsNone(self.store.harness_state('current'))
            self.assertEqual(self.store.harness_state()['status'], 'apply_failed')

    async def test_confirmation_and_authority(self):
        op = await self.verified()
        with self.assertRaises(HarnessError):
            await self.bridge.apply(op['id'], op['revision'], False, ['learning'])
        with self.assertRaises(HarnessError) as removed:
            await self.bridge.tool('apply_configuration', {'confirm': True}, op['id'])
        self.assertEqual(removed.exception.code, 'onboarding_assistant_removed')
        self.assertEqual(removed.exception.status, 410)
        self.assertEqual(self.store.harness_state()['status'], 'verified')
        with self.assertRaises(HarnessError):
            await self.bridge.tool('write_file', {'path': 'C:/private'}, op['id'])

    async def test_restart_recovers_interrupted_commit_journal(self):
        for _ in range(3):
            op = await self.verified()
            applied = await self.bridge.apply(op['id'], op['revision'], True, ['learning', 'classroom'])
            journal = self.store.harness_state()
            journal.update(status='applying', recovery=deepcopy(self.store.harness_state('current')))
            self.store.save_harness_state(journal)
            reopened = HarnessBridge(Store(Path(self.folder.name)), transport=self.transport)
            await reopened.restore_routes()
            self.assertEqual(self.store.harness_state()['status'], 'rolled_back')
            self.assertIsNone(self.store.harness_state('current'))
            self.assertEqual(self.transport.catalog['services']['llm']['active_profile_id'], 'original')

    async def test_canonical_official_account_failure_blocks_retry(self):
        self.transport.probe_result = {'ok': False, 'code': 'ACCOUNT_TOKEN_INVALID', 'error': {'status': 502}}
        op = self.credential()
        failed = (await self.bridge.probe(op['id'], op['revision'], 'deepseek-chat'))['operation']
        self.assertEqual(failed['status'], 'credential_invalid')
        with self.assertRaises(HarnessError):
            await self.bridge.probe(op['id'], failed['revision'], 'deepseek-chat')

    async def test_no_secret_to_assistant_status_or_public_operation(self):
        for message in ('api_key: fixture-secret', 'password: fixture-password', 'sk-123456789abcd'):
            with self.assertRaises(HarnessError) as removed:
                await self.bridge.assistant(message)
            self.assertEqual(removed.exception.code, 'onboarding_assistant_removed')
            self.assertNotIn(message, str(removed.exception))
        self.assertFalse(any(c[1] == '/assistant' for c in self.transport.calls))
        state = await self.bridge.status()
        self.assertNotIn('must-never-escape', json.dumps(state))
        op = self.credential()
        self.assertNotIn('secret_ref', op)
        self.assertNotIn('fixture-secret-do-not-export', json.dumps(op))

    async def test_authorization_url_and_attempt_generation(self):
        started = await self.bridge.start()
        self.assertEqual(started['operation']['status'], 'authorizing')
        with self.assertRaises(HarnessError):
            await self.bridge.start()
        await self.bridge.cancel(started['operation']['id'], started['operation']['revision'])
        original = self.transport.host
        async def invalid_url(method, path, body=None, timeout=45):
            if path == '/account/login/start':
                return {'authorization_url': 'https://secret@platform.deepseek.com/dsh/authorize'}
            return await original(method, path, body, timeout)
        self.transport.host = invalid_url
        with self.assertRaises(HarnessError):
            await self.bridge.start()

    async def test_authorization_terminal_and_restart_recovery(self):
        original = self.transport.host
        state = {'authenticated': False, 'attempt_id': 'fixture-attempt', 'attempt': {'id': 'fixture-attempt', 'phase': 'waiting-browser'}}
        async def account_state(method, path, body=None, timeout=45):
            if path == '/account/status':
                return deepcopy(state)
            return await original(method, path, body, timeout)
        self.transport.host = account_state
        op = (await self.bridge.start())['operation']
        # A retained previous grant cannot complete a still-pending new login.
        state['authenticated'] = True
        self.assertEqual((await self.bridge.status())['operation']['status'], 'authorizing')
        state['attempt']['phase'] = 'expired'
        self.assertEqual((await self.bridge.status())['operation']['status'], 'failed')
        op = (await self.bridge.start())['operation']
        state = {'authenticated': True, 'attempt_id': None, 'attempt': None}
        recovered = await self.bridge.status()
        self.assertEqual(recovered['operation']['status'], 'awaiting_model')
        self.assertIsNone(recovered['operation']['probe'])
        await self.bridge.cancel(op['id'], recovered['operation']['revision'])
        self.assertEqual((await self.bridge.status())['operation']['status'], 'cancelled')

    async def test_removed_assistant_never_starts_host_or_creates_operation(self):
        with self.assertRaises(HarnessError) as removed:
            await self.bridge.assistant('I have an API connection. How do I connect it?')
        self.assertEqual(removed.exception.code, 'onboarding_assistant_removed')
        self.assertEqual(removed.exception.status, 410)
        self.assertEqual(self.transport.calls, [])
        self.assertIsNone(self.store.harness_state())


if __name__ == '__main__':
    unittest.main()
