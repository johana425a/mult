"""Bulk material deletion fixtures: no installed service or user content is accessed."""
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'runtime' / 'test-data'
ROOT.mkdir(parents=True, exist_ok=True)
os.environ['EDUAGENT_DATA'] = tempfile.mkdtemp(prefix='bulk-import-', dir=ROOT)
from portal import app as api
from portal.storage import Store, now
from fastapi.testclient import TestClient


class BulkDeleteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='bulk-case-', dir=ROOT))
        self.store = Store(self.root)
        self.uploads = self.root / 'materials'
        self.uploads.mkdir()
        self.source = self.root / 'original-textbook.md'
        self.source.write_text('original textbook fixture', encoding='utf8')
        self.patches = [patch.object(api, 'store', self.store), patch.object(api, 'UPLOADS', self.uploads),
                        patch.object(api, 'MATERIAL_LOCKS', {})]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()

    def material(self, key, **extra):
        path = self.uploads / (key + '.md')
        path.write_text('imported copy fixture', encoding='utf8')
        self.store.insert('materials', {'id': key, 'title': key, 'filename': 'original.md', 'path': str(path),
            'text': 'imported copy fixture', 'char_count': 21, 'created_at': now(), **extra})
        return path

    async def test_batch_returns_partial_results_and_protects_classroom_sources(self):
        first = self.material('material_free', dt_material_id='native_shared')
        second = self.material('material_used')
        self.store.insert('lessons', {'id': 'lesson_fixture', 'material_id': 'material_used', 'status': 'ready', 'created_at': now()})
        with patch.object(api, 'dt_bridge') as native:
            result = await api.delete_materials(api.MaterialDeleteInput(ids=['material_free', 'material_used', 'material_free']))
        self.assertEqual(result['deleted_count'], 1)
        self.assertEqual(len(result['items']), 2)
        self.assertTrue(result['items'][0]['retained_shared'])
        self.assertEqual(result['items'][1]['code'], 'material_in_use')
        self.assertFalse(first.exists()); self.assertTrue(second.exists())
        self.assertIsNotNone(self.store.get('materials', 'material_used'))
        self.assertEqual(self.source.read_text('utf8'), 'original textbook fixture')
        native.assert_not_called()
        self.assertTrue((await api.delete_materials(api.MaterialDeleteInput(ids=['material_free'])))['items'][0]['deleted'])

    async def test_original_path_and_file_failure_remain_selected_candidates_for_retry(self):
        self.material('material_foreign')
        self.store.update('materials', 'material_foreign', path=str(self.source))
        self.material('material_locked')
        original_unlink = Path.unlink
        def locked(path, *args, **kwargs):
            if path.name == 'material_locked.md': raise PermissionError('fixture lock')
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', locked):
            result = await api.delete_materials(api.MaterialDeleteInput(ids=['material_foreign', 'material_locked']))
        self.assertEqual([item['code'] for item in result['items']], ['unowned_path', 'file_busy'])
        self.assertEqual(len(self.store.list('materials')), 2)
        self.assertTrue(self.source.exists())
        retry = await api.delete_materials(api.MaterialDeleteInput(ids=['material_locked']))
        self.assertEqual(retry['deleted_count'], 1)

    async def test_waits_for_sync_handshake_and_late_sync_cannot_recreate_row(self):
        self.material('material_sync')
        gate, entered = asyncio.Event(), asyncio.Event()
        class Native:
            async def import_material(self, *args, **kwargs):
                entered.set(); await gate.wait(); return {'material_id': 'native_synced'}
        with patch.object(api, 'dt_bridge', return_value=Native()):
            sync = asyncio.create_task(api.sync_material('material_sync'))
            await entered.wait()
            deleting = asyncio.create_task(api.delete_materials(api.MaterialDeleteInput(ids=['material_sync'])))
            await asyncio.sleep(0)
            self.assertFalse(deleting.done())
            gate.set(); await sync
            result = await deleting
        self.assertTrue(result['items'][0]['retained_shared'])
        self.assertIsNone(await api.sync_material('material_sync'))
        self.assertIsNone(self.store.get('materials', 'material_sync'))

    async def test_new_lesson_cannot_reference_a_deleted_source(self):
        self.material('material_gone')
        await api.delete_materials(api.MaterialDeleteInput(ids=['material_gone']))
        with self.assertRaisesRegex(ValueError, 'no longer available'):
            self.store.insert('lessons', {'id': 'lesson_late', 'material_id': 'material_gone', 'created_at': now()})
        self.assertEqual(self.store.list('lessons'), [])

    async def test_imported_file_shared_by_another_record_is_preserved(self):
        path = self.material('material_owner')
        self.material('material_shared')
        self.store.update('materials', 'material_shared', path=str(path))
        result = await api.delete_materials(api.MaterialDeleteInput(ids=['material_owner']))
        self.assertTrue(result['items'][0]['retained_shared'])
        self.assertTrue(path.is_file())
        self.assertIsNotNone(self.store.get('materials', 'material_shared'))

    async def test_http_contract_rejects_invalid_ids_and_supports_native_origin(self):
        self.material('material_route')
        client = TestClient(api.app)
        invalid = client.post('/api/materials/delete', json={'ids': ['../original']})
        self.assertEqual(invalid.status_code, 422)
        response = client.post('/api/materials/delete', json={'ids': ['material_route']}, headers={'origin': 'http://127.0.0.1:3792'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://127.0.0.1:3792')
        self.assertEqual(response.json()['deleted_count'], 1)


if __name__ == '__main__': unittest.main()
