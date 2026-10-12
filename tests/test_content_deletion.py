"""Permanent-delete fixtures only. No installed service, model or user store is accessed."""
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'runtime' / 'test-data'
ROOT.mkdir(parents=True, exist_ok=True)
os.environ['EDUAGENT_DATA'] = tempfile.mkdtemp(prefix='delete-import-', dir=ROOT)
from portal.storage import Store, now
from portal.content_deletion import delete_lesson_content


class Bridge:
    def __init__(self):
        self.calls = []
        self.fail = False
    async def delete_job(self, key, preserve_classroom_ids=None):
        self.calls.append(('job', key))
        self.protected = preserve_classroom_ids
        if self.fail:
            raise RuntimeError('Stopping')
    async def delete_classroom(self, key):
        self.calls.append(('classroom', key))
    async def _request(self, method, path):
        self.calls.append((method, path))


class DeleteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='delete-case-', dir=ROOT))
        self.store = Store(self.root)
        self.source = self.root / 'original.md'
        self.source.write_text('Original source must survive', encoding='utf8')
        self.store.insert('materials', {'id': 'material_one', 'path': str(self.source), 'created_at': now()})
        self.store.insert('lessons', {'id': 'lesson_one', 'title': 'Fixture', 'material_id': 'material_one', 'status': 'ready', 'job_id': 'job_one', 'classroom_id': 'class_one', 'dt_course_id': 'course_one', 'created_at': now()})
        self.store.insert('attempts', {'id': 'attempt_one', 'lesson_id': 'lesson_one', 'dt_session_id': 'session_one', 'created_at': now()})
        self.bridge = Bridge()

    async def test_delete_preserves_source_and_is_idempotent(self):
        await delete_lesson_content(self.store, 'lesson_one', {}, self.bridge, self.bridge)
        self.assertIsNone(self.store.get('lessons', 'lesson_one'))
        self.assertEqual(self.store.list('attempts'), [])
        self.assertEqual(self.source.read_text('utf8'), 'Original source must survive')
        self.assertIsNotNone(self.store.get('materials', 'material_one'))
        self.assertIn(('DELETE', '/api/sessions/session_one'), self.bridge.calls)
        await delete_lesson_content(self.store, 'lesson_one', {}, self.bridge, self.bridge)

    async def test_cleanup_failure_retains_retry_and_refuses_late_revival(self):
        self.bridge.fail = True
        with self.assertRaises(RuntimeError):
            await delete_lesson_content(self.store, 'lesson_one', {}, self.bridge, self.bridge)
        self.store.update('lessons', 'lesson_one', status='ready', progress='Late success', classroom_id='class_late')
        self.assertEqual(self.store.get('lessons', 'lesson_one')['status'], 'deleting')
        self.assertIsNotNone(self.store.get('attempts', 'attempt_one'))
        # Reopen simulates restart; the persisted deleting row resumes the same purge.
        self.bridge.fail = False
        await delete_lesson_content(Store(self.root), 'lesson_one', {}, self.bridge, self.bridge)
        self.assertIn(('classroom', 'class_late'), self.bridge.calls)

    async def test_known_active_feedback_stops_before_native_delete(self):
        settled = asyncio.Event()
        async def feedback():
            try: await asyncio.Event().wait()
            finally: settled.set()
        task = asyncio.create_task(feedback())
        await asyncio.sleep(0)
        await delete_lesson_content(self.store, 'lesson_one', {'attempt_one': task}, self.bridge, self.bridge)
        self.assertTrue(settled.is_set())

    async def test_shared_upstream_ids_are_not_purged(self):
        self.store.insert('lessons', {'id': 'lesson_two', 'status': 'ready', 'job_id': 'job_one', 'classroom_id': 'class_one', 'dt_course_id': 'course_one', 'created_at': now()})
        self.store.insert('attempts', {'id': 'attempt_two', 'lesson_id': 'lesson_two', 'dt_session_id': 'session_one', 'created_at': now()})
        await delete_lesson_content(self.store, 'lesson_one', {}, self.bridge, self.bridge)
        self.assertEqual(self.bridge.calls, [])

    async def test_job_cleanup_preserves_classroom_shared_by_different_job(self):
        self.store.insert('lessons', {'id': 'lesson_two', 'status': 'ready', 'job_id': 'job_two', 'classroom_id': 'class_one', 'created_at': now()})
        await delete_lesson_content(self.store, 'lesson_one', {}, self.bridge, self.bridge)
        self.assertEqual(self.bridge.protected, ['class_one'])
        self.assertNotIn(('classroom', 'class_one'), self.bridge.calls)

    async def test_native_errors_other_than_missing_are_retryable_failures(self):
        import httpx
        for status in (400, 500):
            response = httpx.Response(status, request=httpx.Request('DELETE', 'http://fixture.invalid/'))
            async def fail(*args): raise httpx.HTTPStatusError('fixture failure', request=response.request, response=response)
            with patch.object(self.bridge, '_request', side_effect=fail):
                with self.assertRaises(httpx.HTTPStatusError):
                    await delete_lesson_content(self.store, 'lesson_one', {}, self.bridge, self.bridge)
            self.assertEqual(self.store.get('lessons', 'lesson_one')['status'], 'deleting')

    async def test_course_ownership_is_recorded_before_resource_attachment_can_fail(self):
        from integration.deeptutor_bridge import DeepTutorBridge
        native = DeepTutorBridge()
        async def request(method, path, **kwargs):
            if path == '/api/reading/workspaces': return {'workspace_id': 'workspace_created'}
            if path == '/api/courses': return {'course': {'id': 'course_created'}}
            raise RuntimeError('Fixture attachment failed')
        async def record(course_id, workspace_id):
            if course_id: self.store.update('lessons', 'lesson_one', dt_course_id=course_id)
        with patch.object(native, '_request', side_effect=request):
            with self.assertRaisesRegex(RuntimeError, 'attachment failed'):
                await native.create_course('Fixture', ['material_one'], owner_callback=record)
        await delete_lesson_content(self.store, 'lesson_one', {}, self.bridge, self.bridge)
        self.assertIn(('DELETE', '/api/courses/course_created'), self.bridge.calls)


class DeleteRouteTests(unittest.TestCase):
    def test_native_origin_delete_preflight_and_idempotent_route(self):
        from fastapi.testclient import TestClient
        from portal import app as api
        isolated = Store(Path(tempfile.mkdtemp(prefix='delete-route-', dir=ROOT)))
        with patch.object(api, 'store', isolated):
            client = TestClient(api.app)
            preflight = client.options('/api/lessons/lesson_missing', headers={
                'origin': 'http://127.0.0.1:3792', 'access-control-request-method': 'DELETE'})
            self.assertEqual(preflight.status_code, 200)
            self.assertIn('DELETE', preflight.headers['access-control-allow-methods'])
            response = client.delete('/api/lessons/lesson_missing', headers={'origin': 'http://127.0.0.1:3792'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()['deleted'])

    def test_existing_lesson_route_deletes_owned_links_and_preserves_original(self):
        from fastapi.testclient import TestClient
        from portal import app as api
        isolated = Store(Path(tempfile.mkdtemp(prefix='delete-route-existing-', dir=ROOT)))
        original = isolated.root / 'original.md'
        original.write_text('source fixture', encoding='utf8')
        isolated.insert('materials', {'id': 'source_one', 'path': str(original), 'created_at': now()})
        isolated.insert('lessons', {'id': 'lesson_route', 'material_id': 'source_one', 'status': 'ready', 'job_id': 'job_route', 'classroom_id': 'class_route', 'created_at': now()})
        bridge = Bridge()
        with patch.object(api, 'store', isolated), patch.object(api, 'om_bridge', return_value=bridge), patch.object(api, 'dt_bridge', return_value=bridge):
            response = TestClient(api.app).delete('/api/lessons/lesson_route', headers={'origin': 'http://127.0.0.1:3792'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers['access-control-allow-origin'], 'http://127.0.0.1:3792')
        self.assertIsNone(isolated.get('lessons', 'lesson_route'))
        self.assertTrue(original.is_file())
        self.assertEqual(bridge.calls, [('job', 'job_route'), ('classroom', 'class_route')])


if __name__ == '__main__': unittest.main()
