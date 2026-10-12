"""Synthetic original-image cache and structured-worker failure contracts."""
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration import document_jobs as jobs


class DocumentAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='document-asset-jobs-', dir=jobs.ROOT / 'runtime')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.broker = jobs.DocumentJobs(test_root=self.root, python=Path(os.environ.get('DEEPSTEAM_TEST_PYTHON', sys.executable)))

    def test_original_image_does_not_wait_for_heavy_lane_and_cached_version_is_revalidated(self):
        from PIL import Image
        source = self.workspace / 'diagram.png'
        Image.new('RGB', (80, 50), 'blue').save(source)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        # Asset discovery does not run OCR; the fixture is a textless diagram.
        initial = jobs.reader.handle_request({'root': str(self.workspace), 'path': source.name, 'ocr': 'off'})
        payload = {'path': source.name, 'document_sha256': digest, 'asset_id': initial['units'][0]['assets'][0]['id']}
        with self.broker.worker_lock() as held:
            self.assertTrue(held)
            first = self.broker.asset(self.workspace, payload)
            self.assertTrue(first['ok'])
            with patch.object(jobs.reader, 'handle_request', side_effect=AssertionError('cached asset must not render again')):
                cached = self.broker.asset(self.workspace, payload)
        self.assertEqual(first, cached)
        self.assertTrue(first['asset']['base64'])
        Image.new('RGB', (80, 50), 'red').save(source)
        changed = jobs.handle({'root': str(self.workspace), 'action': 'asset', **payload}, test_root=self.root)
        self.assertFalse(changed['ok'])
        self.assertEqual(changed['error']['code'], 'SOURCE_CHANGED')

    def test_nonzero_worker_exit_retains_typed_error_without_technical_message(self):
        source = self.workspace / 'source.md'
        source.write_text('Synthetic source', encoding='utf-8')
        job = self.broker.submit(self.workspace, {'path': source.name, 'engine': 'builtin'})
        helper = self.root / 'synthetic_worker.py'
        helper.write_text('import json,sys\nprint(json.dumps({"ok":False,"status":"error","engine":"mineru","error":{"code":"parser_asset_missing","message":"INTERNAL_DIAGNOSTIC_ONLY"}}))\nsys.exit(2)\n', encoding='utf-8')
        value = self.broker._run_child(job['job_id'], self.broker.python, helper, {}, 10)
        self.assertFalse(value['ok'])
        self.assertEqual(value['error']['code'], 'parser_asset_missing')
        self.assertNotIn('INTERNAL_DIAGNOSTIC_ONLY', value['error']['message'])
        self.assertIn('Repair the installation', value['error']['message'])

    def test_inventory_dispatch_keeps_metadata_only_and_resumable_cursor(self):
        for index in range(23):
            (self.workspace / f'{index:02d}.txt').write_text('BODY_MUST_NOT_BE_RETURNED', encoding='utf-8')
        paths, cursor = [], None
        for _ in range(10):
            request = {'root': str(self.workspace), 'action': 'inventory', 'path': '.', 'limit': 7}
            if cursor:
                request['cursor'] = cursor
            result = jobs.handle(request, test_root=self.root)
            self.assertTrue(result['ok'], result)
            self.assertLessEqual(len(result['entries']), 7)
            self.assertNotIn('BODY_MUST_NOT_BE_RETURNED', json.dumps(result))
            paths.extend(row['path'] for row in result['entries'])
            cursor = result['next_cursor']
            if not cursor:
                break
        self.assertTrue(result['catalog_complete'])
        self.assertEqual(len(set(paths)), 23)
        self.assertEqual(len(paths), 23)

    def test_textless_structured_page_remains_partial_original_image_evidence(self):
        digest = 'a' * 64
        prior = {'ok': True, 'format': 'pdf', 'document': {'unit_count': 1}, 'units': [
            {'text': '', 'locator': {'page': 1}, 'assets': [{'id': 'pdf-page:1'}]}], 'warnings': []}
        parsed = {'source_sha256': digest, 'status': 'ready', 'units': [{'text': '', 'locator': {'page': 1}}]}
        result = jobs.located_window(parsed, {}, prior, self.root)
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['units'][0]['status'], 'needs_ocr')
        self.assertEqual(result['units'][0]['assets'], [{'id': 'pdf-page:1'}])
        self.assertFalse(result['coverage']['text_extraction_complete'])

    def test_document_level_upgrade_gap_survives_restart_and_clears_after_successful_structure(self):
        source = self.workspace / 'coverage.md'
        source.write_text('Synthetic full unit', encoding='utf-8')
        unit = {'unit_index': 1, 'locator': {'line': 1}, 'text': 'Synthetic full unit', 'status': 'ready',
                'unit_text_sha256': hashlib.sha256(b'Synthetic full unit').hexdigest(), 'coverage': {'unresolved': []}}
        self.broker.submit(self.workspace, {'path': source.name, 'engine': 'builtin'})
        def extracted(row):
            return {'ok': True, 'status': 'partial', 'engine': 'builtin', 'units': [unit],
                    'document': {'unit_count': 1, 'sha256': row['source_hash']},
                    'coverage': {'unresolved': ['structure_upgrade_unavailable']}}
        with patch.object(self.broker, '_execute', side_effect=extracted):
            self.broker.drain()
        restored = jobs.DocumentJobs(test_root=self.root)
        before = restored.coverage(self.workspace, {'path': source.name})
        self.assertEqual(before['extracted_units'], 1)
        self.assertFalse(before['extraction_complete'])
        self.assertEqual(before['unresolved'], ['structure_upgrade_unavailable'])
        self.broker.submit(self.workspace, {'path': source.name, 'engine': 'builtin', 'max_chars': 512})
        def upgraded(row):
            return {**extracted(row), 'engine': 'mineru', 'status': 'ready', 'coverage': {'unresolved': []}}
        with patch.object(self.broker, '_execute', side_effect=upgraded):
            self.broker.drain()
        after = restored.coverage(self.workspace, {'path': source.name})
        self.assertTrue(after['extraction_complete'])
        self.assertEqual(after['unresolved'], [])


if __name__ == '__main__':
    unittest.main()
