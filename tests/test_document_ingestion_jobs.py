"""Synthetic complete-ingestion durability. No model/provider calls."""
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from integration import document_ingestion_jobs as module

PYTHON = Path(os.environ.get('DEEPSTEAM_TEST_PYTHON', sys.executable))


class IngestionJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ingestion-job-test-', dir=module.ROOT / 'runtime')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.pdf'
        self.source.write_bytes(b'SYNTHETIC FIXTURE; tests mock extraction')
        self.service = module.DocumentIngestions(test_root=self.root, python=PYTHON)

    @staticmethod
    def extracted(*args, **kwargs):
        return {'document': {'sha256': hashlib.sha256(Path(args[0]).read_bytes()).hexdigest(), 'unit_count': 1}, 'units': [{'text': 'Synthetic result', 'locator': {'page': 1}}],
                'images': [], 'coverage': {'document_fully_read': True}, 'warnings': [], 'status': 'ready'}

    def test_owner_partition_source_survives_original_removal_and_result_reuses_after_restart(self):
        first = self.service.prepare(self.source, 'owner-one')
        again = self.service.prepare(self.source, 'owner-one')
        other = self.service.prepare(self.source, 'owner-two')
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)
        retained = self.service._source(self.service._row(first))
        self.source.unlink()
        with patch.object(module.shared, 'extract_document', side_effect=self.extracted) as extract:
            self.service.run(first)
            restored = module.DocumentIngestions(test_root=self.root, python=PYTHON)
            restored.run(first)
        extract.assert_called_once()
        self.assertTrue(retained.is_file())
        result = restored.view(first)
        self.assertTrue(result['ok'])
        self.assertEqual(result['units'][0]['text'], 'Synthetic result')
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotEqual(result['recovery']['source_ref'], restored.view(other)['recovery']['source_ref'])

    def test_cross_owner_or_changed_bytes_cannot_resume_foreign_identity(self):
        first = self.service.prepare(self.source, 'owner-one')
        with self.assertRaises(ValueError):
            self.service.prepare(self.source, 'owner-two', ingestion_id=first)
        self.source.write_bytes(b'CHANGED SYNTHETIC DOCUMENT')
        with self.assertRaises(ValueError):
            self.service.prepare(self.source, 'owner-one', ingestion_id=first)

    def test_three_ingestions_queue_and_single_dispatcher_drains_all(self):
        ids = []
        for owner in ('first', 'second', 'third'):
            identity = self.service.prepare(self.source, owner)
            self.assertEqual(self.service.view(identity)['status'], 'queued')
            ids.append(identity)
        with patch.object(module.shared, 'extract_document', side_effect=self.extracted) as extract:
            self.service.drain()
        self.assertEqual(extract.call_count, 3)
        self.assertTrue(all(self.service.view(identity)['ok'] for identity in ids))

    def test_interrupted_running_assembly_is_recovered_when_os_lock_is_free(self):
        identity = self.service.prepare(self.source, 'owner-one')
        with self.service.jobs.connect() as db:
            db.execute("UPDATE ingestions SET status='running' WHERE id=?", (identity,))
        restored = module.DocumentIngestions(test_root=self.root, python=PYTHON)
        with patch.object(module.shared, 'extract_document', side_effect=self.extracted):
            restored.drain()
        self.assertTrue(restored.view(identity)['ok'])

    def test_cancelled_source_remains_and_poll_does_not_restart_until_fresh_request(self):
        identity = self.service.prepare(self.source, 'owner-one')
        result = self.service.cancel(identity)
        self.assertEqual(result['status'], 'cancelled')
        self.service.prepare(self.source, 'owner-one', ingestion_id=identity)
        self.assertEqual(self.service.view(identity)['status'], 'cancelled')
        self.assertTrue(self.service._source(self.service._row(identity)).is_file())
        self.service.prepare(self.source, 'owner-one')
        self.assertEqual(self.service.view(identity)['status'], 'queued')

    def test_cancelling_one_variant_keeps_shared_page_work_needed_by_another(self):
        first = self.service.prepare(self.source, 'owner-one', True)
        second = self.service.prepare(self.source, 'owner-one', False)
        source = self.service._source(self.service._row(first))
        page = self.service.jobs.submit(source.parent, {'path': source.name, 'engine': 'builtin'})
        self.service.cancel(first)
        with self.service.jobs.connect() as db:
            self.assertEqual(db.execute('SELECT cancel_requested FROM jobs WHERE id=?', (page['job_id'],)).fetchone()[0], 0)
        self.service.cancel(second)
        with self.service.jobs.connect() as db:
            self.assertEqual(db.execute('SELECT cancel_requested FROM jobs WHERE id=?', (page['job_id'],)).fetchone()[0], 1)

    def test_fixed_runtime_finishes_after_zero_waiter_and_original_cleanup(self):
        """Real local text extraction; no OCR/model inference or public data."""
        import pymupdf
        self.source.unlink()
        with pymupdf.open() as pdf:
            for number in range(1, 4):
                page = pdf.new_page()
                page.insert_text((50, 50), f'Synthetic durable reading page {number}')
            pdf.save(self.source)
        identity = self.service.prepare(self.source, 'synthetic-runtime-owner', False)
        initial = self.service.wait(identity, seconds=0)
        self.assertIn(initial['status'], {'queued', 'running'})
        self.source.unlink()
        restored = module.DocumentIngestions(test_root=self.root, python=PYTHON)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            result = restored.view(identity)
            if result.get('status') not in {'queued', 'running'}:
                break
            time.sleep(.2)
        self.assertTrue(result.get('ok'), result)
        self.assertEqual([unit['locator']['page'] for unit in result['units']], [1, 2, 3])
        self.assertTrue(result['coverage']['document_fully_read'])
        self.assertTrue(restored._source(restored._row(identity)).is_file())
        self.assertEqual(result['recovery'], initial['recovery'])
        self.assertEqual(restored.wait(identity, seconds=0), result)
        # Wait for the short background dispatcher to release its SQLite/file
        # handles before the fixture is removed on Windows.
        while time.monotonic() < deadline:
            with restored.lock() as held:
                if held:
                    break
            time.sleep(.1)


if __name__ == '__main__':
    unittest.main()
