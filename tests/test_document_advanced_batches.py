"""Real synthetic PDF slicing with mocked structure engine, never model inference."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integration import document_jobs as module


class AdvancedBatchTests(unittest.TestCase):
    def setUp(self):
        import pymupdf
        self.temp = tempfile.TemporaryDirectory(prefix='advanced-batch-', dir=module.ROOT / 'runtime')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.pdf'
        with pymupdf.open() as pdf:
            for number in range(1, 18):
                page = pdf.new_page()
                page.insert_text((50, 50), f'ORIGINAL PHYSICAL PAGE {number}')
            pdf.save(self.source)
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.jobs = module.DocumentJobs(test_root=self.root)
        job = self.jobs.submit(self.root, {'path': self.source.name, 'engine': 'builtin'})
        with self.jobs.connect() as db:
            self.row = db.execute('SELECT * FROM jobs WHERE id=?', (job['job_id'],)).fetchone()
        self.calls = []

    def engine(self, job_id, python, helper, request, timeout):
        import pymupdf
        subset = Path(request['source_path'])
        self.assertNotEqual(subset, self.source)
        self.assertEqual(hashlib.sha256(subset.read_bytes()).hexdigest(), request['source_sha256'])
        with pymupdf.open(subset) as pdf:
            self.assertLessEqual(len(pdf), 8)
            texts = [page.get_text().strip() for page in pdf]
        self.calls.append(texts)
        return {'ok': True, 'status': 'ready', 'source_sha256': request['source_sha256'],
                'units': [{'text': text, 'locator': {'kind': 'pdf_page', 'page': i + 1, 'page_idx': i},
                           'assets': [{'locator': {'page': i + 1}, 'id': f'subset-{i}'}]}
                          for i, text in enumerate(texts)],
                'warnings': [{'code': 'synthetic_review', 'message': 'Review original source image'}],
                'coverage': {'full_document': True}}

    def read(self, cursor=None, engine=None):
        request = {'root': str(self.root), 'path': self.source.name, 'max_chars': 5000, 'max_units': 40, 'ocr': 'off'}
        if cursor:
            request['cursor'] = cursor
        light = module.reader.handle_request(request)
        self.assertTrue(light['ok'], light)
        with patch.object(self.jobs, '_run_child', side_effect=engine or self.engine), patch.object(Path, 'is_file', autospec=True, side_effect=lambda p: True if str(p).replace('\\', '/').endswith('runtime/mineru/python.exe') else Path.exists(p)):
            return self.jobs._upgrade(self.row, request, light, required=True)

    def test_seventeen_pages_cross_three_batches_preserve_source_and_reuse_completed_cache(self):
        pages, texts, token = [], [], None
        for _ in range(5):
            result = self.read(token)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['document']['unit_count'], 17)
            self.assertEqual(result['document']['sha256'], self.digest)
            self.assertLessEqual(len(result['units']), 8)
            self.assertFalse(result['coverage']['document_fully_read'])
            self.assertTrue(all(unit['structure_source']['source_sha256'] == self.digest for unit in result['units']))
            pages.extend(unit['locator']['page'] for unit in result['units'])
            texts.extend(unit['text'] for unit in result['units'])
            self.assertTrue(all(unit['assets'][0]['id'] == f"pdf-page:{unit['locator']['page']}" for unit in result['units']))
            token = result['next_cursor']
            if not token:
                break
        self.assertEqual(pages, list(range(1, 18)))
        self.assertEqual(texts, [f'ORIGINAL PHYSICAL PAGE {i}' for i in range(1, 18)])
        self.assertEqual([len(call) for call in self.calls], [8, 8, 1])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.digest)
        self.assertIn('Review original source image', result['warnings'])
        reused = self.read()
        self.assertEqual([unit['locator']['page'] for unit in reused['units']], list(range(1, 9)))
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(reused['truncated'])
        self.assertEqual(reused['coverage']['structure_page_range'], [1, 8])

    def test_locator_remap_covers_nested_assets_and_rejects_outside_subset(self):
        parsed = {'source_sha256': 'subset', 'units': [{'locator': {'page': 2}, 'assets': [{'locator': {'page': 2}}]}],
                  'warnings': [{'locator': {'page': 2}}], 'coverage': {'full_document': True}}
        mapped = module.remap_pdf_batch(parsed, 8, 16, self.digest)
        self.assertEqual(mapped['units'][0]['locator']['page'], 10)
        self.assertEqual(mapped['units'][0]['assets'][0]['locator']['page_idx'], 9)
        self.assertEqual(mapped['warnings'][0]['locator']['page'], 10)
        self.assertFalse(mapped['coverage']['full_document'])
        self.assertEqual(mapped['source_sha256'], self.digest)
        parsed['units'][0]['locator']['page'] = 9
        with self.assertRaises(ValueError):
            module.remap_pdf_batch(parsed, 8, 16, self.digest)

    def test_failed_second_batch_keeps_prior_cache_coverage_and_resumes_after_restart(self):
        first = self.read()
        with self.jobs.connect() as db:
            self.jobs._record_coverage(db, self.row, first)
        cursor = first['next_cursor']
        failed = self.read(cursor, engine=lambda *args: module.failure('document_timeout', 'Synthetic interrupted batch', retryable=True))
        self.assertFalse(failed['ok'])
        self.jobs = module.DocumentJobs(test_root=self.root)
        ledger = self.jobs.coverage(self.root, {'path': self.source.name})
        self.assertEqual(ledger['visited_units'], 8)
        self.assertEqual(ledger['unread_units'], 9)
        self.assertFalse(ledger['extraction_complete'])
        self.assertEqual(len(self.calls), 1)
        self.read()  # Prior batch is reused after the failed later batch.
        self.assertEqual(len(self.calls), 1)
        second = self.read(cursor)
        with self.jobs.connect() as db:
            self.jobs._record_coverage(db, self.row, second)
        final = self.read(second['next_cursor'])
        with self.jobs.connect() as db:
            self.jobs._record_coverage(db, self.row, final)
        ledger = self.jobs.coverage(self.root, {'path': self.source.name})
        self.assertEqual(ledger['visited_units'], 17)
        self.assertEqual(ledger['unread_units'], 0)
        self.assertEqual([len(call) for call in self.calls], [8, 8, 1])
        self.assertIsNone(final['next_cursor'])


if __name__ == '__main__':
    unittest.main()
