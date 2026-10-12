"""Selected-source contracts; synthetic files and mocked generation only."""
import asyncio
import hashlib
import io
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'runtime' / 'test-data'
TESTS.mkdir(parents=True, exist_ok=True)
_IMPORT = tempfile.TemporaryDirectory(prefix='workspace-material-import-', dir=TESTS)
os.environ['EDUAGENT_DATA'] = _IMPORT.name
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from portal import app as api, material_sources as sources
from portal.storage import Store, now


def result(text='selected fixture', *, cursor=None, image=False):
    return {'ok': True, 'status': 'partial' if cursor else 'ready', 'text': text,
            'document': {'sha256': 'a' * 64, 'bytes': 42, 'unit_count': 20},
            'units': [{'text': text, 'locator': {'page': 3, 'page_kind': 'pdf_physical'},
                       'assets': [{'id': 'pdf-page:3'}] if image else []}],
            'truncated': bool(cursor), 'next_cursor': cursor, 'warnings': []}


class WorkspaceMaterialsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='workspace-material-case-', dir=TESTS)
        self.root = Path(self.directory.name)
        self.uploads = self.root / 'uploads'; self.uploads.mkdir()
        self.originals = self.root / 'textbooks'; self.originals.mkdir()
        self.original = self.originals / 'source.md'; self.original.write_text('Original fixture.', encoding='utf8')
        self.store = Store(self.root / 'state')
        self.patches = [patch.object(api, 'store', self.store), patch.object(api, 'UPLOADS', self.uploads),
                        patch.object(api, 'MATERIAL_LOCKS', {}), patch.object(api, 'ACTIVE_LESSONS', set())]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.directory.cleanup()

    async def add_workspace(self, parsed=None, **kwargs):
        with patch.object(sources, 'workspace_request', AsyncMock(return_value=parsed or result())):
            return await api.workspace_material(api.WorkspaceMaterialInput(
                workspace_id='native_fixture', path='source.md', document_sha256='a' * 64, **kwargs))

    async def test_workspace_reference_never_copies_original_and_delete_preserves_it(self):
        material = await self.add_workspace()
        self.assertEqual(list(self.uploads.iterdir()), [])
        self.assertEqual(material['source_kind'], 'workspace')
        self.assertNotIn('path', material)
        self.assertNotIn('source_snapshot', material)
        outcome = await api.delete_materials(api.MaterialDeleteInput(ids=[material['id']]))
        self.assertTrue(outcome['items'][0]['deleted'])
        self.assertEqual(self.original.read_text('utf8'), 'Original fixture.')

    async def test_generation_freezes_selected_hash_range_and_images_before_dispatch(self):
        material = await self.add_workspace(result(cursor='next', image=True), cursor='selected', max_units=1)
        calls = []
        async def document(workspace, action, **payload):
            calls.append((workspace, action, payload))
            if action == 'asset': return {'ok': True, 'status': 'ready', 'asset': {'base64': 'RklYVFVSRQ=='}}
            return result('different OCR must not replace selected text', cursor='next', image=True)
        execution = Mock(execution_config=AsyncMock(return_value={'provider': {'model': 'fixture', 'base_url': 'http://fixture.invalid'}, 'model_snapshot': None}))
        def close_task(coroutine, *args): coroutine.close()
        with patch.object(sources, 'workspace_request', side_effect=document), patch.object(api, 'harness_bridge', return_value=execution), patch.object(api, 'launch', side_effect=close_task):
            lesson = await api.create_lesson(api.LessonInput(material_id=material['id'], title='Fixture', goal='Read selected page'))
        stored = self.store.get('lessons', lesson['id'])
        frozen = json.loads(stored['source_snapshot'])
        self.assertEqual(frozen['images'], ['data:image/png;base64,RklYVFVSRQ=='])
        self.assertEqual(frozen['text'], 'selected fixture')
        self.assertEqual(frozen['image_sources'][0]['locator']['page'], 3)
        self.assertEqual(frozen['cursor'], 'selected')
        self.assertEqual(calls[0][2]['document_sha256'], 'a' * 64)
        self.assertEqual(calls[0][2]['max_units'], 1)
        self.assertNotIn('source_snapshot', lesson)
        bridge = Mock(generate=AsyncMock(return_value={'jobId': 'job_fixture'}),
                      poll=AsyncMock(return_value={'status': 'succeeded', 'classroomId': 'class_fixture', 'result': {'classroomId': 'class_fixture'}}),
                      classroom=AsyncMock(return_value={'id': 'class_fixture', 'scenes': []}))
        with patch.object(api, 'om_bridge', return_value=bridge), patch.object(api, 'sync_material', AsyncMock(return_value=None)), patch.object(sources, 'read_source', side_effect=AssertionError('must use frozen source')):
            await api.generate_lesson(lesson['id'], frozen_provider={'model': 'fixture'})
        self.assertEqual(bridge.generate.call_args.kwargs['image_urls'], frozen['images'])
        self.assertEqual(bridge.generate.call_args.kwargs['image_sources'][0]['source_document_name'], 'source.md')
        self.assertIn('Cover only the attached selected scope', bridge.generate.call_args.kwargs['requirement'])

    async def test_changed_version_rejects_before_model_acceptance(self):
        material = await self.add_workspace()
        bridge = Mock(execution_config=AsyncMock())
        with patch.object(sources, 'read_source', AsyncMock(side_effect=ValueError('Source version changed'))), patch.object(api, 'harness_bridge', return_value=bridge):
            with self.assertRaises(HTTPException) as failure:
                await api.create_lesson(api.LessonInput(material_id=material['id'], title='Fixture', goal='Fixture'))
        self.assertEqual(failure.exception.status_code, 409)
        bridge.execution_config.assert_not_called()
        self.assertEqual(self.store.list('lessons'), [])

    async def test_text_only_model_cannot_silently_drop_selected_images(self):
        material = await self.add_workspace()
        frozen = {'text': 'fixture', 'images': ['data:image/png;base64,RklYVFVSRQ==']}
        bridge = Mock(execution_config=AsyncMock(return_value={'provider': {'model': 'text-only'},
                      'resolved_model': {'capabilities': {'vision': False}}}))
        with patch.object(sources, 'classroom_snapshot', AsyncMock(return_value=frozen)), patch.object(api, 'harness_bridge', return_value=bridge), patch.object(api, 'launch') as launch:
            with self.assertRaises(HTTPException) as failure:
                await api.create_lesson(api.LessonInput(material_id=material['id'], title='Fixture', goal='Fixture'))
        self.assertEqual(failure.exception.status_code, 409)
        launch.assert_not_called()

    async def test_original_picture_reference_is_verified_without_refreshing_to_new_image(self):
        saved = result(image=True)
        saved['units'][0]['assets'][0]['id'] = 'md-image:1:1:old-hash'
        material = await self.add_workspace(saved)
        fresh = result(image=True)
        fresh['units'][0]['assets'][0]['id'] = 'md-image:1:1:new-hash'
        source = self.store.get('materials', material['id'])
        with patch.object(sources, 'read_source', AsyncMock(return_value=fresh)), patch.object(sources, 'workspace_request', AsyncMock(side_effect=ValueError('Image changed'))) as image:
            with self.assertRaisesRegex(ValueError, 'Image changed'):
                await sources.classroom_snapshot(source, self.uploads)
        self.assertEqual(image.call_args.kwargs['asset_id'], 'md-image:1:1:old-hash')

    async def test_reselecting_changed_markdown_image_creates_new_reference_with_same_document_hash(self):
        first_window = result(image=True)
        first_window['units'][0]['assets'][0]['id'] = 'md-image:1:1:old-hash'
        first = await self.add_workspace(first_window)
        second_window = result(image=True)
        second_window['units'][0]['assets'][0]['id'] = 'md-image:1:1:new-hash'
        second = await self.add_workspace(second_window)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(first['document_sha256'], second['document_sha256'])
        with patch.object(sources, 'read_source', AsyncMock(return_value=second_window)):
            ranged = await api.select_material_window(first['id'], api.DocumentReadInput())
        self.assertNotEqual(ranged['id'], first['id'])
        selected = json.loads(self.store.get('materials', ranged['id'])['source_snapshot'])
        self.assertEqual(selected['units'][0]['assets'][0]['id'], 'md-image:1:1:new-hash')

    async def test_upload_uses_shared_reader_and_stream_limit_checks_actual_bytes(self):
        reader = AsyncMock(return_value=result())
        with patch.object(sources, 'managed_request', reader), patch.object(sources, 'MAX_DOCUMENT_BYTES', 8):
            file = UploadFile(io.BytesIO(b'12345678'), filename='source.docx')
            material = await api.upload(file, workspace_id='native_fixture')
            self.assertEqual(material['workspace_id'], 'native_fixture')
            self.assertEqual(reader.call_args.args[0], self.uploads)
            with self.assertRaises(HTTPException) as failure:
                await api.upload(UploadFile(io.BytesIO(b'123456789'), filename='source.docx'))
            self.assertEqual(failure.exception.status_code, 413)
        self.assertEqual(len(list(self.uploads.iterdir())), 1)

    async def test_legacy_office_gets_explicit_conversion_hint(self):
        with self.assertRaises(HTTPException) as failure:
            await api.upload(UploadFile(io.BytesIO(b'legacy'), filename='source.ppt'))
        self.assertEqual(failure.exception.status_code, 415)
        self.assertIn('Convert legacy DOC/PPT files to DOCX/PPTX first.', failure.exception.detail)

    async def test_upload_range_keeps_shared_copy_until_last_reference_removed(self):
        with patch.object(sources, 'managed_request', AsyncMock(return_value=result())):
            initial = await api.save_material('fixture.md', b'fixture')
        source = self.store.get('materials', initial['id']); path = Path(source['path'])
        with patch.object(sources, 'read_source', AsyncMock(return_value=result('later range'))):
            selected = await api.select_material_window(initial['id'], api.DocumentReadInput(cursor='later'))
        await api.delete_materials(api.MaterialDeleteInput(ids=[initial['id']]))
        self.assertTrue(path.exists())
        await api.delete_materials(api.MaterialDeleteInput(ids=[selected['id']]))
        self.assertFalse(path.exists())
        self.assertTrue(self.original.exists())

    async def test_native_feedback_receives_selected_text_not_original_file(self):
        material = await self.add_workspace()
        async def importing(path, title=''):
            self.assertEqual(path.suffix, '.md')
            self.assertIn('selected fixture', path.read_text('utf8'))
            self.assertIn('Version: ' + 'a' * 64, path.read_text('utf8'))
            self.assertNotEqual(path, self.original)
            return {'material_id': 'native_selected'}
        with patch.object(api, 'dt_bridge', return_value=Mock(import_material=importing)):
            self.assertEqual(await api.sync_material(material['id']), 'native_selected')
        self.assertEqual(list(self.uploads.iterdir()), [])

    async def test_material_scope_and_lesson_reference_protection(self):
        material = await self.add_workspace()
        self.assertEqual((await api.materials(workspace_id='other'))['items'], [])
        self.store.insert('lessons', {'id': 'lesson_ref', 'material_id': material['id'], 'created_at': now()})
        result = await api.delete_materials(api.MaterialDeleteInput(ids=[material['id']]))
        self.assertEqual(result['items'][0]['code'], 'material_in_use')

    async def test_real_shared_reader_on_synthetic_markdown(self):
        from integration import workspace_documents
        python = Path(os.environ.get('DEEPSTEAM_TEST_PYTHON', sys.executable))
        helper = ROOT / 'scripts' / 'workspace_document_reader.py'
        with patch.object(workspace_documents, '_runtime_paths', return_value=(python, helper)), \
                patch.dict(os.environ, {'DEEPSTEAM_HARNESS_TEST_ROOT': str(self.root)}):
            parsed = await workspace_documents.read_managed_document(self.originals, 'source.md', max_units=1, max_chars=1000)
        self.assertTrue(parsed['ok'], parsed)
        self.assertEqual(parsed['document']['sha256'], hashlib.sha256(self.original.read_bytes()).hexdigest())
        self.assertIn('Original fixture.', parsed['text'])

    async def test_selected_window_reuse_does_not_duplicate_material_rows(self):
        first = await self.add_workspace()
        second = await self.add_workspace()
        self.assertEqual(first['id'], second['id'])
        with patch.object(sources, 'read_source', AsyncMock(return_value=result())):
            same = await api.select_material_window(first['id'], api.DocumentReadInput())
        self.assertEqual(first['id'], same['id'])
        self.assertEqual(len(self.store.list('materials')), 1)

    async def test_document_routes_forward_bounded_relative_requests_without_root(self):
        client = TestClient(api.app)
        reader = AsyncMock(return_value={'ok': True, 'entries': [], 'truncated': False})
        with patch.object(sources, 'workspace_request', reader):
            response = client.post('/api/workspaces/native_fixture/documents/list', json={'path': '', 'root': 'untrusted', 'limit': 200})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(reader.call_args.args, ('native_fixture', 'list'))
            self.assertEqual(reader.call_args.kwargs, {'path': '.', 'limit': 200})
            invalid = client.post('/api/workspaces/native_fixture/documents/read', json={'path': 'fixture.md', 'max_units': 10000})
            self.assertEqual(invalid.status_code, 422)

    async def test_only_verified_custom_native_workspace_can_be_registered(self):
        transport = Mock(host=AsyncMock(side_effect=[{'workspaces': []}, {'workspace': {'id': 'host_fixture', 'path': str(self.originals)}}]),
                         native_workspace=AsyncMock(return_value={'id': 'native_fixture', 'kind': 'custom', 'path': str(self.originals)}))
        with patch.object(api, 'authenticate_service'), patch.object(api, 'harness_bridge', return_value=Mock(transport=transport)):
            binding = await api.internal_workspace_directory('native_fixture', None)
        self.assertEqual(binding['harness_workspace_id'], 'host_fixture')
        self.assertEqual(transport.host.call_args.args[:2], ('POST', '/workspaces'))
        transport.host = AsyncMock(return_value={'workspaces': []})
        transport.native_workspace = AsyncMock(return_value={'kind': 'system', 'path': str(self.originals)})
        with patch.object(api, 'authenticate_service'), patch.object(api, 'harness_bridge', return_value=Mock(transport=transport)):
            with self.assertRaises(Exception):
                await api.internal_workspace_directory('native_system_fixture', None)
        self.assertEqual(transport.host.call_count, 1)

    async def test_bridge_transmits_structured_image_sources_and_preserves_old_callers(self):
        from integration.openmaic_bridge import OpenMAICBridge
        bridge = OpenMAICBridge()
        metadata = [{'image_index': 1, 'asset_id': 'pdf-page:3', 'locator': {'page': 3, 'page_kind': 'pdf_physical'},
                     'document_sha256': 'a' * 64, 'source_document_name': 'fixture.pdf'}]
        with patch.object(bridge, '_request', return_value={'jobId': 'fixture'}) as request:
            await bridge.generate('Fixture', source_text='Fixture', image_urls=['data:image/png;base64,RklYVFVSRQ=='], image_sources=metadata)
            self.assertEqual(request.call_args.args[2]['pdfContent']['image_sources'], metadata)
            await bridge.generate('Fixture', source_text='Fixture')
            self.assertNotIn('image_sources', request.call_args.args[2]['pdfContent'])


if __name__ == '__main__': unittest.main()
