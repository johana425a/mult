"""Deterministic contract tests; no external provider calls or model-quality claims."""
from __future__ import annotations
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1] / 'runtime' / 'test-data'
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ['EDUAGENT_DATA'] = tempfile.mkdtemp(prefix='portal-', dir=TEST_ROOT)

from fastapi.testclient import TestClient
from portal import app as api
from portal.storage import Store, identifier, now, protect


class FakeDeepTutor:
    calls = 0

    async def import_material(self, path, title=''):
        FakeDeepTutor.calls += 1
        return {'material_id': 'dt_' + path.stem}

    async def create_course(self, title, material_ids, instructions='', owner_callback=None):
        if owner_callback:
            await owner_callback('dt_course_fixture', 'dt_workspace_fixture')
        return {'course_id': 'dt_course_fixture'}

    async def submit_answer(self, **kwargs):
        return {'status': 'completed', 'session_id': 'fixture_session', 'turn_id': 'fixture_turn', 'feedback': 'CONTRACT TEST RESPONSE — not model output'}


class FakeOpenMAIC:
    inputs = []

    async def generate(self, **kwargs):
        self.inputs.append(kwargs)
        return {'jobId': 'fixture_job'}

    async def poll(self, job_id):
        return {'status': 'succeeded', 'result': {'classroomId': 'fixture_classroom'}, 'classroomId': 'fixture_classroom'}

    async def classroom(self, classroom_id):
        return {'id': classroom_id, 'scenes': []}


class PortalTests(unittest.TestCase):
    def setUp(self):
        api.store = Store(Path(tempfile.mkdtemp(prefix='case-', dir=TEST_ROOT)))
        api.UPLOADS = api.store.root / 'materials'
        api.UPLOADS.mkdir()
        self.dt = patch.object(api, 'dt_bridge', return_value=FakeDeepTutor())
        self.om = patch.object(api, 'om_bridge', return_value=FakeOpenMAIC())
        self.dt.start()
        self.om.start()
        # Model dispatch is an independent broker contract. These portal
        # fixtures exercise selected-source flow without touching any service.
        bridge = api.harness_bridge()
        async def execution(**kwargs):
            settings = api.store.settings(secret=True)
            return {'provider': {key: settings.get(key, '') for key in ('model', 'base_url', 'api_key')},
                    'resolved_model': {'model': settings.get('model')}, 'model_snapshot': None}
        async def selected(settings=None):
            return (await execution())['provider']
        self.execution = patch.object(bridge, 'execution_config', side_effect=execution)
        self.selection = patch.object(bridge, 'selected_provider', side_effect=selected)
        self.restore = patch.object(bridge, 'restore_routes', return_value=None)
        self.execution.start(); self.selection.start(); self.restore.start()
        self.client = TestClient(api.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.dt.stop()
        self.om.stop()
        self.execution.stop(); self.selection.stop(); self.restore.stop()

    def upload(self):
        result = self.client.post('/api/materials', files={'file': ('source.md', '# Test\nAn original local fixture', 'text/markdown')})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def settings(self):
        return self.client.put('/api/settings', json={'model_mode': 'api', 'base_url': 'http://127.0.0.1:9876/v1', 'model': 'contract-only', 'api_key': 'not-a-real-key-test-fixture'})

    def test_encrypt_and_public_settings(self):
        result = self.settings()
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['api_key_set'])
        self.assertNotIn('api_key', result.json())
        self.assertNotIn(b'not-a-real-key-test-fixture', api.store.path.read_bytes())
        self.assertEqual(api.store.settings(secret=True)['api_key'], 'not-a-real-key-test-fixture')
        self.client.put('/api/settings', json={'base_url': 'http://127.0.0.1:9876/v1', 'model': 'contract-only', 'api_key': ''})
        self.assertTrue(self.client.get('/api/settings').json()['api_key_set'])
        self.client.put('/api/settings', json={'clear_api_key': True})
        self.assertFalse(self.client.get('/api/settings').json()['api_key_set'])

    def test_cross_origin_and_host_rejected(self):
        response = self.client.put('/api/settings', headers={'origin': 'https://untrusted.example'}, json={'model': 'wrong'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get('/api/settings', headers={'host': 'untrusted.example'}).status_code, 400)

    def test_does_not_accept_credentials_in_url(self):
        result = self.client.put('/api/settings', json={'base_url': 'https://user:secret@example.com/v1'})
        self.assertEqual(result.status_code, 422)

    def test_upload_round_trip_and_path_not_disclosed(self):
        # The source checkout does not bundle the installed reader runtime.
        # Exercise API persistence here; extraction has separate document tests.
        parsed = {'ok': True, 'status': 'ready', 'text': '# Test\nAn original local fixture',
                  'document': {'sha256': 'a' * 64, 'unit_count': 1},
                  'units': [], 'truncated': False}
        with patch.object(api.material_sources, 'managed_request', return_value=parsed) as reader:
            result = self.upload()
        reader.assert_awaited_once()
        self.assertNotIn('path', result)
        fetched = self.client.get('/api/materials/' + result['id']).json()
        self.assertIn('An original local fixture', fetched['text_preview'])
        self.assertEqual(self.client.get('/api/materials/' + result['id'] + '/file').status_code, 200)

    def test_reject_mislabelled_pdf(self):
        result = self.client.post('/api/materials', files={'file': ('bad.pdf', b'not a PDF', 'application/pdf')})
        self.assertEqual(result.status_code, 400)

    def test_no_provider_no_generation(self):
        self.client.put('/api/settings', json={'model_mode': 'api'})
        source = self.upload()
        result = self.client.post('/api/lessons', json={'material_id': source['id'], 'title': 'Test', 'goal': 'Test'})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(len(api.store.list('lessons')), 0)

    def test_native_frontend_can_use_api_without_opening_external_origins(self):
        allowed = self.client.options('/api/settings', headers={
            'Origin': 'http://127.0.0.1:3792', 'Access-Control-Request-Method': 'PUT',
            'Access-Control-Request-Headers': 'content-type'})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers.get('access-control-allow-origin'), 'http://127.0.0.1:3792')
        rejected = self.client.put('/api/settings', json={}, headers={'Origin': 'https://unrelated.example'})
        self.assertEqual(rejected.status_code, 403)
        self.assertNotIn('access-control-allow-origin', rejected.headers)
        redirect = self.client.get('/', follow_redirects=False)
        self.assertEqual(redirect.status_code, 307)
        self.assertEqual(redirect.headers['location'], 'http://127.0.0.1:3792/chat')
        legacy = self.client.get('/legacy', follow_redirects=False)
        self.assertEqual(legacy.status_code, 307)
        self.assertEqual(legacy.headers['location'], redirect.headers['location'])
        self.assertEqual(self.client.get('/static/index.html').status_code, 404)
        for name in ('index.html', 'app.js', 'styles.css'):
            self.assertFalse((Path(__file__).resolve().parents[1] / 'portal' / 'static' / name).exists())

    def test_selected_text_provider_and_lesson_identity(self):
        self.settings()
        source = self.upload()
        result = self.client.post('/api/lessons', json={'material_id': source['id'], 'title': 'Test', 'goal': 'Explain test'})
        self.assertEqual(result.status_code, 202, result.text)
        lid = result.json()['id']
        # Drain background task through TestClient's event loop.
        self.client.portal.call(self._drain)
        lesson = self.client.get('/api/lessons/' + lid).json()
        self.assertEqual(lesson['status'], 'ready', lesson)
        self.assertEqual(lesson['classroom_id'], 'fixture_classroom')
        self.assertEqual(lesson['dt_course_id'], 'dt_course_fixture')
        # This Markdown fixture has no pictures. Workspace image forwarding is
        # covered with explicit asset responses in test_workspace_materials.
        self.assertEqual(FakeOpenMAIC.inputs[-1]['image_urls'], [])
        self.assertIn('An original local fixture', FakeOpenMAIC.inputs[-1]['source_text'])
        self.assertNotIn('api_key', str(api.store.list('lessons')))

    @staticmethod
    async def _drain():
        if api.TASKS:
            await asyncio.gather(*list(api.TASKS))

    def test_answers_preserved_when_tutor_fails(self):
        self.settings()
        source = self.upload()
        item = {'id': identifier('lesson'), 'title': 'Fixture', 'material_id': source['id'], 'goal': 'test', 'status': 'ready', 'created_at': now(), 'updated_at': now()}
        api.store.insert('lessons', item)
        async def fail(**kwargs):
            return {'status': 'failed', 'feedback': '', 'session_id': 'preserved_native_session', 'error': 'not-a-real-key-test-fixture'}
        with patch.object(FakeDeepTutor, 'submit_answer', side_effect=fail):
            response = self.client.post('/api/lessons/' + item['id'] + '/attempts', json={'question': 'Why?', 'answer': 'My first answer'})
            self.assertEqual(response.status_code, 202)
            self.client.portal.call(self._drain)
        attempt = self.client.get('/api/attempts').json()['items'][0]
        self.assertEqual(attempt['answer'], 'My first answer')
        self.assertEqual(attempt['status'], 'saved')
        self.assertEqual(attempt['dt_session_id'], 'preserved_native_session')
        self.assertNotIn('not-a-real-key-test-fixture', attempt['error'])
        reopened = Store(api.store.root)
        self.assertEqual(reopened.get('attempts', attempt['id'])['answer'], 'My first answer')

    def test_exports_exclude_secrets(self):
        self.settings()
        self.upload()
        result = self.client.get('/api/export-records')
        self.assertEqual(result.status_code, 200)
        self.assertNotIn('not-a-real-key-test-fixture', result.text)
        self.assertNotIn('api_key_protected', result.text)
        self.assertNotIn('settings', result.json())

    def test_missing_narration_warning_is_retained(self):
        self.settings()
        source = self.upload()
        async def partial(job_id):
            return {'status': 'succeeded', 'result': {'classroomId': 'fixture_classroom', 'warning': 'No narration written', 'ttsCoverage': {'written': 0, 'total': 2}}, 'classroomId': 'fixture_classroom'}
        with patch.object(FakeOpenMAIC, 'poll', side_effect=partial):
            result = self.client.post('/api/lessons', json={'material_id': source['id'], 'title': 'Test', 'goal': 'Explain test'})
            self.client.portal.call(self._drain)
        lesson = self.client.get('/api/lessons/' + result.json()['id']).json()
        self.assertEqual(lesson['status'], 'ready')
        self.assertIn('No narration written', lesson['warning'])
        self.assertIn('"written": 0', lesson['tts_coverage'])

    def test_transient_poll_resumes_same_job(self):
        self.settings()
        source = self.upload()
        calls = []
        async def recovery(job_id):
            calls.append(job_id)
            if len(calls) == 1:
                raise ConnectionError('temporary local service outage')
            return {'status': 'succeeded', 'classroomId': 'fixture_classroom'}
        async def immediate(seconds):
            return None
        with patch.object(FakeOpenMAIC, 'poll', side_effect=recovery), patch.object(api.asyncio, 'sleep', side_effect=immediate):
            result = self.client.post('/api/lessons', json={'material_id': source['id'], 'title': 'Test', 'goal': 'Explain test'})
            self.client.portal.call(self._drain)
        lesson = self.client.get('/api/lessons/' + result.json()['id']).json()
        self.assertEqual(lesson['status'], 'ready')
        self.assertEqual(calls, ['fixture_job', 'fixture_job'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
