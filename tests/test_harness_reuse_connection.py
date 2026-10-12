"""User-intent model switching with local synthetic encrypted references."""
import json
import unittest

from integration.harness_bridge import HarnessError
from tests import test_harness_bridge as fixtures


class ReuseConnectionTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.HarnessBridgeTests.setUp
    tearDown = fixtures.HarnessBridgeTests.tearDown
    credential = fixtures.HarnessBridgeTests.credential
    verified = fixtures.HarnessBridgeTests.verified
    async def applied(self):
        operation = await self.verified()
        return await self.bridge.apply(operation['id'], operation['revision'], True, ['learning', 'classroom'])

    async def test_api_reuse_does_not_read_new_key_or_call_model(self):
        await self.applied()
        old = self.store.harness_state('current')
        calls = len(self.transport.calls)
        result = await self.bridge.reuse_connection('deepseek-reasoner')
        self.assertEqual(len(self.transport.calls), calls)
        operation = result['operation']
        self.assertEqual(operation['status'], 'awaiting_model')
        self.assertEqual(operation['model'], 'deepseek-reasoner')
        self.assertEqual(self.store.harness_state()['secret_ref'], old['secret_ref'])
        self.assertEqual(self.store.harness_state('current'), old)
        self.assertNotIn('fixture-secret', json.dumps(result))
        self.assertNotIn('secret_ref', json.dumps(result))
        with self.assertRaises(HarnessError):
            await self.bridge.apply(operation['id'], operation['revision'], True, ['learning'])

    async def test_cancel_reused_operation_preserves_active_reference(self):
        await self.applied()
        old = self.store.harness_state('current')
        operation = (await self.bridge.reuse_connection('deepseek-reasoner'))['operation']
        await self.bridge.cancel(operation['id'], operation['revision'])
        self.assertEqual(self.store.harness_state('current'), old)
        self.assertTrue(self.store.harness_secret(old['secret_ref']))

    async def test_invalid_unchanged_credential_cannot_reprobe_through_reuse(self):
        await self.applied()
        operation = (await self.bridge.reuse_connection('deepseek-reasoner'))['operation']
        self.transport.probe_result = {'ok': False, 'error': {'code': 'provider_auth', 'status': 401}}
        failed = await self.bridge.probe(operation['id'], operation['revision'], 'deepseek-reasoner')
        self.assertEqual(failed['operation']['status'], 'credential_invalid')
        with self.assertRaises(HarnessError) as caught:
            await self.bridge.reuse_connection('deepseek-chat')
        self.assertEqual(caught.exception.code, 'credential_invalid')

    async def test_missing_connection_or_invalid_model_keeps_state(self):
        for model in ('', '../bad', None, 'x' * 151):
            with self.assertRaises(HarnessError):
                await self.bridge.reuse_connection(model)
        with self.assertRaises(HarnessError) as caught:
            await self.bridge.reuse_connection('deepseek-chat')
        self.assertEqual(caught.exception.code, 'connection_missing')
        self.assertIsNone(self.store.harness_state())

    async def test_active_operation_is_not_replaced(self):
        await self.applied()
        operation = await self.bridge.start()
        with self.assertRaises(HarnessError) as caught:
            await self.bridge.reuse_connection('deepseek-chat')
        self.assertEqual(caught.exception.code, 'operation_busy')
        self.assertEqual(self.store.harness_state()['id'], operation['operation']['id'])

    async def test_account_reuse_checks_auth_without_launching_authorization_or_model(self):
        await self.applied()
        current = self.store.harness_state('current')
        current['route'] = 'account'
        current.pop('secret_ref', None)
        self.store.save_harness_state(current, 'current')
        original = self.transport.host
        requests = []

        async def authenticated(method, path, body=None, timeout=45):
            requests.append(path)
            if path == '/account/status':
                return {'authenticated': True}
            return await original(method, path, body, timeout)

        self.transport.host = authenticated
        result = await self.bridge.reuse_connection('deepseek-reasoner')
        self.assertEqual(result['operation']['mode'], 'account')
        self.assertEqual(result['operation']['status'], 'awaiting_model')
        self.assertEqual(requests, ['/account/status'])
        self.assertEqual(self.store.harness_state('current'), current)

    async def test_expired_account_cannot_start_switch_or_change_current(self):
        await self.applied()
        current = self.store.harness_state('current')
        current['route'] = 'account'
        self.store.save_harness_state(current, 'current')
        previous = self.store.harness_state()
        with self.assertRaises(HarnessError) as caught:
            await self.bridge.reuse_connection('deepseek-reasoner')
        self.assertEqual(caught.exception.code, 'account_not_authenticated')
        self.assertEqual(self.store.harness_state(), previous)
        self.assertEqual(self.store.harness_state('current'), current)


if __name__ == '__main__':
    unittest.main()
