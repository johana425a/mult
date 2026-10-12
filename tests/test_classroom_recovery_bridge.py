"""Offline restart/retry contracts. Providers and job service are in-memory fakes."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).resolve().parents[1]
_TEMP = _ROOT / 'runtime' / 'test-data'
_TEMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('EDUAGENT_DATA', str(_TEMP / 'recovery-module'))
from portal import app as api
from portal.storage import Store
from integration.openmaic_bridge import OpenMAICBridge


class RecoveryContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='recovery-', dir=_TEMP)
        self.addCleanup(self.temp.cleanup)
        self.original = api.store
        api.store = Store(Path(self.temp.name))
        self.addCleanup(setattr, api, 'store', self.original)
        api.store.insert('materials', {'id': 'material_fixture', 'title': 'fixture', 'filename': 'fixture.md', 'created_at': '2026-10-12'})
        api.store.insert('lessons', {
            'id': 'lesson_fixture', 'material_id': 'material_fixture', 'status': 'interrupted',
            'job_id': 'job_fixture', 'job_attempt_id': 'attempt_old', 'retryable': 1,
            'model_snapshot': json.dumps({'model': 'mock-only'}), 'created_at': '2026-10-12'})
        self.om = AsyncMock()
        self.harness = AsyncMock()
        self.harness.execution_config.return_value = {
            'provider': {'model': 'mock-only', 'base_url': 'http://127.0.0.1:1/v1'},
            'model_snapshot': {'model': 'mock-only'}, 'execution_id': 'exec_fixture'}
        self.patches = [patch.object(api, 'om_bridge', return_value=self.om),
                        patch.object(api, 'harness_bridge', return_value=self.harness)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def test_poll_interrupted_is_terminal_without_generation(self):
        self.om.poll.return_value = {'status': 'interrupted', 'attemptId': 'attempt_old',
                                    'retryable': True, 'error': 'Executor restarted', 'done': True}
        await api.generate_lesson('lesson_fixture', resume=True)
        row = api.store.get('lessons', 'lesson_fixture')
        self.assertEqual(row['status'], 'interrupted')
        self.assertEqual(row['retryable'], 1)
        self.om.poll.assert_awaited_once()
        self.om.generate.assert_not_awaited()
        self.om.retry.assert_not_awaited()
        self.harness.execution_config.assert_not_awaited()

    async def test_explicit_retry_uses_saved_model_and_rejoins_new_attempt(self):
        self.om.retry.return_value = {'jobId': 'job_fixture', 'attemptId': 'attempt_new'}
        self.om.poll.return_value = {'status': 'succeeded', 'attemptId': 'attempt_new',
                                    'result': {'classroomId': 'class_fixture'}, 'retryable': False}
        self.om.classroom.return_value = {'id': 'class_fixture'}
        coroutines = []
        with patch.object(api, 'launch', side_effect=lambda coro, *_: coroutines.append(coro)):
            result = await api.retry_lesson('lesson_fixture', api.RetryLessonInput(attempt_id='attempt_old'))
        self.assertEqual(result['status'], 'generating')
        self.harness.execution_config.assert_awaited_once_with(model_snapshot={'model': 'mock-only'})
        await coroutines[0]
        self.assertEqual(api.store.get('lessons', 'lesson_fixture')['status'], 'ready')
        self.assertEqual(api.store.get('lessons', 'lesson_fixture')['job_attempt_id'], 'attempt_new')
        self.om.generate.assert_not_awaited()
        args = self.om.retry.call_args.args
        self.assertEqual(args[:2], ('job_fixture', 'attempt_old'))

    async def test_stale_click_does_not_resolve_or_send_model(self):
        with self.assertRaises(api.HTTPException) as caught:
            await api.retry_lesson('lesson_fixture', api.RetryLessonInput(attempt_id='outdated_attempt'))
        self.assertEqual(caught.exception.status_code, 409)
        self.harness.execution_config.assert_not_awaited()

    async def test_deleting_cannot_retry(self):
        api.store.begin_lesson_delete('lesson_fixture')
        with self.assertRaises(api.HTTPException) as caught:
            await api.retry_lesson('lesson_fixture', api.RetryLessonInput(attempt_id='attempt_old'))
        self.assertEqual(caught.exception.status_code, 409)
        self.harness.execution_config.assert_not_awaited()

    async def test_legacy_interrupted_has_no_inferred_retry(self):
        self.om.poll.return_value = {'status': 'interrupted', 'attemptId': 'legacy',
                                    'retryable': False, 'done': True}
        await api.generate_lesson('lesson_fixture', resume=True)
        self.assertEqual(api.store.get('lessons', 'lesson_fixture')['retryable'], 0)

    async def test_bridge_retry_only_passes_ids_in_body(self):
        bridge = OpenMAICBridge()
        with patch.object(bridge, '_request', return_value={'attemptId': 'next'}) as request:
            await bridge.retry('job_fixture', 'attempt_old', {
                'model': 'mock-only', 'model_snapshot': {'model': 'mock-only'},
                'api_key': 'fake-secret-not-real', 'tts_enabled': False})
        args = request.call_args.args
        self.assertEqual(args[2], {'jobId': 'job_fixture', 'retry': True, 'retryFromAttempt': 'attempt_old'})
        self.assertNotIn('fake-secret', json.dumps(args[2]))
        self.assertNotIn('x-api-key', args[3])

    async def test_completed_task_rejects_retry(self):
        api.store.update('lessons', 'lesson_fixture', status='ready')
        with self.assertRaises(api.HTTPException):
            await api.retry_lesson('lesson_fixture', api.RetryLessonInput(attempt_id='attempt_old'))


if __name__ == '__main__':
    unittest.main()
