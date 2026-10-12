"""Durable document queue contracts using synthetic local files only.

All requests select builtin explicitly. Most executions are deterministic
stubs; real subprocess checks use only Markdown and the packaged Python.
"""
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from integration import document_jobs as module


PYTHON = Path(os.environ.get('DEEPSTEAM_TEST_PYTHON', sys.executable))


class DocumentJobsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix='document-jobs-tests-', dir=module.ROOT / 'runtime')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.assertTrue(self.root.is_relative_to((module.ROOT / 'runtime').resolve()))
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.jobs = module.DocumentJobs(test_root=self.root, python=PYTHON)

    def source(self, name='fixture.md', text='# Synthetic source\nQueue evidence 12345.'):
        path = self.workspace / name
        path.write_text(text, encoding='utf-8')
        return path

    @staticmethod
    def payload(path, **extra):
        return {'path': path.name, 'engine': 'builtin', **extra}

    def status(self, path, job, **kwargs):
        return self.jobs.status(
            self.workspace, self.payload(path, job_id=job['job_id']), **kwargs)

    @staticmethod
    def ready(row):
        request = json.loads(row['request'])
        assert request['engine'] == 'builtin'
        return {'ok': True, 'status': 'ready', 'text': request['path'],
                'document': {'sha256': row['source_hash']}, 'engine': 'builtin'}

    def row(self, job):
        with self.jobs.connect() as db:
            return db.execute('SELECT * FROM jobs WHERE id=?', (job['job_id'],)).fetchone()

    def require_python(self):
        if not PYTHON.is_file():
            self.skipTest('Packaged Python is unavailable for the subprocess fixture')

    def until(self, condition, seconds=10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.02)
        self.fail('Synthetic worker did not reach the expected state before the deadline')

    @staticmethod
    def covered_unit(index, full_text, begin=0, end=None, *, status='ready', unresolved=()):
        end = len(full_text) if end is None else end
        return {
            'unit_index': index,
            'unit_text_sha256': hashlib.sha256(full_text.encode('utf-8')).hexdigest(),
            'locator': {'section': index},
            'text': full_text[begin:end],
            'char_start': begin,
            'char_end': end,
            'total_chars': len(full_text),
            'truncated_unit': begin != 0 or end != len(full_text),
            'status': status,
            'coverage': {'unresolved': list(unresolved)},
            'assets': [{'id': f'synthetic-asset:{index}', 'base64': 'MUST_NOT_EXPOSE_ASSET_BYTES'}],
        }

    def record_units(self, path, units, count, **request_options):
        job = self.jobs.submit(self.workspace, self.payload(path, **request_options))

        def execute(row):
            value = self.ready(row)
            value['document']['unit_count'] = count
            value['units'] = units
            value['text'] = '\n'.join(unit['text'] for unit in units)
            return value

        with patch.object(self.jobs, '_execute', side_effect=execute):
            self.jobs.drain()
        self.assertTrue(self.status(path, job)['ok'])
        return job

    def test_coverage_pages_twelve_units_without_source_text_and_keeps_unread_gaps(self):
        texts = [f'# Section {index}\nSOURCE_BODY_SENTINEL_{index}.' for index in range(1, 13)]
        path = self.source(text='\n\n'.join(texts))
        self.record_units(path, [
            self.covered_unit(1, texts[0]),
            self.covered_unit(4, texts[3], status='partial', unresolved=['diagram_review']),
            self.covered_unit(9, texts[8]),
        ], 12, start_unit=1)
        entries, sizes, cursor = [], [], None
        while True:
            query = self.payload(path, limit=5)
            if cursor:
                query['coverage_cursor'] = cursor
            page = self.jobs.coverage(self.workspace, query)
            self.assertEqual(page['unit_count'], 12)
            self.assertEqual(page['visited_units'], 3)
            self.assertEqual(page['extracted_units'], 2)
            self.assertEqual(page['unread_units'], 9)
            self.assertFalse(page['extraction_complete'])
            self.assertNotIn('SOURCE_BODY_SENTINEL', json.dumps(page))
            self.assertNotIn('MUST_NOT_EXPOSE_ASSET_BYTES', json.dumps(page))
            self.assertTrue(all('text' not in entry for entry in page['entries']))
            entries.extend(page['entries'])
            sizes.append(len(page['entries']))
            cursor = page['next_cursor']
            if not cursor:
                break
            self.assertLessEqual(len(sizes), 3, 'Coverage pagination repeated a page')
        self.assertEqual(sizes, [5, 5, 2])
        self.assertEqual([entry['unit_index'] for entry in entries], list(range(1, 13)))
        self.assertEqual(entries[0]['status'], 'extracted')
        self.assertEqual(entries[0]['read_ranges'], [[0, len(texts[0])]])
        self.assertEqual(entries[0]['asset_ids'], ['synthetic-asset:1'])
        self.assertEqual(entries[3]['status'], 'partial')
        self.assertIn('diagram_review', entries[3]['unresolved'])
        self.assertEqual(entries[8]['locator'], {'section': 9})
        self.assertTrue(all(entries[index - 1]['status'] == 'unread'
                            for index in (2, 3, 5, 6, 7, 8, 10, 11, 12)))

    def test_coverage_merges_overlapping_long_unit_fragments_across_restart(self):
        text = 'LONG_SYNTHETIC_SECTION_' * 180
        path = self.source(text=text)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.record_units(path, [self.covered_unit(1, text, 0, 800)], 1, max_chars=800)
        self.record_units(path, [self.covered_unit(1, text, 600, 1500)], 1,
                          cursor=module.reader.cursor_encode(digest, 0, 600), max_chars=900)
        self.jobs = module.DocumentJobs(test_root=self.root, python=PYTHON)
        partial = self.jobs.coverage(self.workspace, self.payload(path))
        self.assertEqual(partial['entries'][0]['read_ranges'], [[0, 1500]])
        self.assertEqual(partial['entries'][0]['status'], 'partial')
        self.assertFalse(partial['extraction_complete'])
        self.record_units(path, [self.covered_unit(1, text, 1500, len(text))], 1,
                          cursor=module.reader.cursor_encode(digest, 0, 1500))
        self.jobs = module.DocumentJobs(test_root=self.root, python=PYTHON)
        complete = self.jobs.coverage(self.workspace, self.payload(path))
        self.assertEqual(complete['visited_units'], 1)
        self.assertEqual(complete['extracted_units'], 1)
        self.assertEqual(complete['entries'][0]['read_ranges'], [[0, len(text)]])
        self.assertEqual(complete['entries'][0]['status'], 'extracted')
        self.assertTrue(complete['extraction_complete'])
        self.assertNotIn(text, json.dumps(complete))
        # A changed extraction for the same source/unit has a different text
        # hash; its ranges cannot inherit completeness from the previous text.
        revised = 'REVISED_SYNTHETIC_EXTRACTION_' * 150
        self.record_units(path, [self.covered_unit(1, revised, 20, 40)], 1,
                          cursor=module.reader.cursor_encode(digest, 0, 20), max_chars=20)
        changed_text = self.jobs.coverage(self.workspace, self.payload(path))
        self.assertEqual(changed_text['entries'][0]['read_ranges'], [[20, 40]])
        self.assertEqual(changed_text['extracted_units'], 0)
        self.assertFalse(changed_text['extraction_complete'])

    def test_coverage_source_version_change_starts_unread_and_does_not_merge_old_ranges(self):
        path = self.source(text='Original synthetic source.')
        self.record_units(path, [self.covered_unit(1, 'Original section text.')], 12)
        original = self.jobs.coverage(self.workspace, self.payload(path, limit=2))
        old_cursor = original['next_cursor']
        path.write_text('Changed synthetic source with different content.', encoding='utf-8')
        unread = self.jobs.coverage(self.workspace, self.payload(path))
        self.assertEqual(unread['status'], 'unread')
        self.assertEqual(unread['entries'], [])
        self.assertIsNone(unread['unit_count'])
        self.assertFalse(unread['extraction_complete'])
        self.assertNotEqual(unread['document_sha256'], original['document_sha256'])
        with self.assertRaisesRegex(ValueError, 'document_coverage_cursor_invalid'):
            self.jobs.coverage(self.workspace, self.payload(path, coverage_cursor=old_cursor))
        fresh_text = 'Fresh version section two.'
        self.record_units(path, [self.covered_unit(2, fresh_text, 5, 10)], 12, start_unit=2)
        fresh = self.jobs.coverage(self.workspace, self.payload(path))
        self.assertEqual(fresh['visited_units'], 1)
        self.assertEqual(fresh['extracted_units'], 0)
        self.assertEqual(fresh['unread_units'], 11)
        self.assertEqual(fresh['entries'][0]['status'], 'unread')
        self.assertEqual(fresh['entries'][1]['read_ranges'], [[5, 10]])

    def test_coverage_rejects_tampered_or_cross_root_cursors(self):
        path = self.source()
        self.record_units(path, [self.covered_unit(1, 'Synthetic section text.')], 12)
        first = self.jobs.coverage(self.workspace, self.payload(path, limit=2))
        token = first['next_cursor']
        decoded = json.loads(base64.urlsafe_b64decode(token))
        for alteration in ({'scope': '0' * 64}, {'sha256': '0' * 64},
                           {'offset': -1}, {'offset': 13}):
            with self.subTest(alteration=alteration):
                forged = base64.urlsafe_b64encode(json.dumps({**decoded, **alteration}).encode()).decode()
                with self.assertRaisesRegex(ValueError, 'document_coverage_cursor_invalid'):
                    self.jobs.coverage(self.workspace, self.payload(path, coverage_cursor=forged))
        with self.assertRaisesRegex(ValueError, 'document_coverage_cursor_invalid'):
            self.jobs.coverage(self.workspace, self.payload(path, coverage_cursor='not-a-cursor!'))
        foreign = self.root / 'foreign-coverage'
        foreign.mkdir()
        (foreign / path.name).write_bytes(path.read_bytes())
        with self.assertRaisesRegex(ValueError, 'document_coverage_cursor_invalid'):
            self.jobs.coverage(foreign, self.payload(path, coverage_cursor=token))
        self.assertEqual(self.jobs.coverage(foreign, self.payload(path))['status'], 'unread')
        self.assertEqual(self.jobs.coverage(self.workspace, self.payload(path))['visited_units'], 1)

    def test_concurrent_submit_deduplicates_and_result_survives_new_broker(self):
        source = self.source()
        with ThreadPoolExecutor(max_workers=6) as pool:
            values = list(pool.map(
                lambda _: self.jobs.submit(self.workspace, self.payload(source)), range(12)))
        self.assertEqual(len({value['job_id'] for value in values}), 1)
        replacement = module.DocumentJobs(test_root=self.root, python=PYTHON)
        with patch.object(replacement, '_execute', side_effect=self.ready) as execute:
            replacement.drain()
        execute.assert_called_once()
        reloaded = module.DocumentJobs(test_root=self.root, python=PYTHON)
        final = reloaded.submit(self.workspace, self.payload(source))
        self.assertEqual(final['job_id'], values[0]['job_id'])
        self.assertEqual(final['status'], 'ready')
        self.assertEqual(final['attempt'], 1)
        self.assertEqual(final['document']['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_three_waiting_documents_complete_in_fifo_order(self):
        paths = [self.source(f'{index}.md') for index in range(3)]
        jobs = [self.jobs.submit(self.workspace, self.payload(path)) for path in paths]
        with self.jobs.connect() as db:
            for index, job in enumerate(jobs):
                db.execute('UPDATE jobs SET created=? WHERE id=?', (100 + index, job['job_id']))
        order = []

        def execute(row):
            order.append(row['id'])
            return self.ready(row)

        with patch.object(self.jobs, '_execute', side_effect=execute):
            self.jobs.drain()
        self.assertEqual(order, [job['job_id'] for job in jobs])
        self.assertTrue(all(self.status(path, job)['status'] == 'ready'
                            for path, job in zip(paths, jobs)))

    def test_queued_cancel_does_not_execute_or_block_the_next_document(self):
        first, second = self.source('first.md'), self.source('second.md')
        cancelled = self.jobs.submit(self.workspace, self.payload(first))
        waiting = self.jobs.submit(self.workspace, self.payload(second))
        value = self.status(first, cancelled, cancel=True)
        self.assertEqual(value['job_status'], 'cancelled')
        self.assertEqual(value['error']['code'], 'document_cancelled')
        with patch.object(self.jobs, '_execute', side_effect=self.ready) as execute:
            self.jobs.drain()
        self.assertEqual([call.args[0]['id'] for call in execute.call_args_list], [waiting['job_id']])
        self.assertEqual(self.status(second, waiting)['status'], 'ready')
        # Polling cannot revive an explicitly cancelled request; a fresh read can.
        self.assertEqual(self.status(first, cancelled)['job_status'], 'cancelled')
        retry = self.jobs.submit(self.workspace, self.payload(first))
        self.assertEqual(retry['job_id'], cancelled['job_id'])
        self.assertEqual(retry['status'], 'queued')

    def test_failed_worker_does_not_poison_the_next_document(self):
        first, second = self.source('broken.md'), self.source('healthy.md')
        broken = self.jobs.submit(self.workspace, self.payload(first))
        healthy = self.jobs.submit(self.workspace, self.payload(second))

        def execute(row):
            if row['id'] == broken['job_id']:
                raise RuntimeError('Synthetic worker failure')
            return self.ready(row)

        with patch.object(self.jobs, '_execute', side_effect=execute):
            self.jobs.drain()
        failure = self.status(first, broken)
        self.assertEqual(failure['job_status'], 'failed')
        self.assertTrue(failure['error']['retryable'])
        self.assertEqual(self.status(second, healthy)['status'], 'ready')

    def test_interrupted_running_job_recovers_after_dispatcher_lock_is_released(self):
        path = self.source()
        job = self.jobs.submit(self.workspace, self.payload(path))
        with self.jobs.connect() as db:
            db.execute("UPDATE jobs SET status='running',stage='reading',attempt=1 WHERE id=?",
                       (job['job_id'],))
        restarted = module.DocumentJobs(test_root=self.root, python=PYTHON)
        with patch.object(restarted, '_execute', side_effect=self.ready) as execute:
            restarted.drain()
        execute.assert_called_once()
        self.assertEqual(self.status(path, job)['status'], 'ready')
        self.assertEqual(self.status(path, job)['attempt'], 2)

    def test_worker_lock_prevents_a_second_dispatcher_from_running_same_job(self):
        path = self.source()
        job = self.jobs.submit(self.workspace, self.payload(path))
        second = module.DocumentJobs(test_root=self.root, python=PYTHON)
        with self.jobs.worker_lock() as acquired:
            self.assertTrue(acquired)
            with patch.object(second, '_execute') as execute:
                second.drain()
            execute.assert_not_called()
        self.assertEqual(self.status(path, job)['status'], 'queued')

    def test_missing_completed_result_is_requeued_by_a_fresh_read(self):
        path = self.source()
        job = self.jobs.submit(self.workspace, self.payload(path))
        with patch.object(self.jobs, '_execute', side_effect=self.ready):
            self.jobs.drain()
        result = (self.jobs.cache / self.row(job)['result']).resolve()
        self.assertTrue(result.is_relative_to(self.root))
        result.unlink()
        lost = self.status(path, job)
        self.assertFalse(lost['ok'])
        self.assertEqual(lost['error']['code'], 'document_cache_missing')
        self.assertTrue(lost['error']['retryable'])
        retry = self.jobs.submit(self.workspace, self.payload(path))
        self.assertEqual(retry['job_id'], job['job_id'])
        self.assertEqual(retry['status'], 'queued')
        with patch.object(self.jobs, '_execute', side_effect=self.ready):
            self.jobs.drain()
        self.assertEqual(self.status(path, job)['status'], 'ready')
        self.assertEqual(self.status(path, job)['attempt'], 2)

    def test_identical_bytes_in_another_root_cannot_inspect_cancel_or_resume_job(self):
        path = self.source()
        job = self.jobs.submit(self.workspace, self.payload(path))
        foreign_root = self.root / 'other-workspace'
        foreign_root.mkdir()
        (foreign_root / path.name).write_bytes(path.read_bytes())
        query = self.payload(path, job_id=job['job_id'])
        with self.assertRaisesRegex(ValueError, 'document_job_unknown'):
            self.jobs.status(foreign_root, query)
        with self.assertRaisesRegex(ValueError, 'document_job_unknown'):
            self.jobs.status(foreign_root, query, cancel=True)
        with self.assertRaisesRegex(ValueError, 'document_job_unknown'):
            self.jobs.submit(foreign_root, query)
        self.assertEqual(self.row(job)['cancel_requested'], 0)
        other = self.jobs.submit(foreign_root, self.payload(path))
        self.assertNotEqual(other['job_id'], job['job_id'])

    def test_source_sha_change_rejects_poll_and_prevents_stale_job_execution(self):
        path = self.source()
        job = self.jobs.submit(self.workspace, self.payload(path))
        path.write_text('# Different synthetic version', encoding='utf-8')
        self.assertEqual(self.status(path, job)['error']['code'], 'SOURCE_CHANGED')
        with patch.object(self.jobs, '_run_child') as child:
            self.jobs.drain()
        child.assert_not_called()
        row = self.row(job)
        result = json.loads((self.jobs.cache / row['result']).read_text('utf-8'))
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(result['error']['code'], 'SOURCE_CHANGED')
        fresh = self.jobs.submit(self.workspace, self.payload(path))
        self.assertNotEqual(fresh['job_id'], job['job_id'])

    def test_source_change_during_parse_never_commits_the_old_text(self):
        path = self.source()
        job = self.jobs.submit(self.workspace, self.payload(path))

        def replace_source(*args, **kwargs):
            path.write_text('Updated while the synthetic worker ran.', encoding='utf-8')
            return {'ok': True, 'status': 'ready', 'text': 'STALE TEXT', 'units': []}

        with patch.object(self.jobs, '_run_child', side_effect=replace_source):
            self.jobs.drain()
        row = self.row(job)
        value = json.loads((self.jobs.cache / row['result']).read_text('utf-8'))
        self.assertEqual(value['error']['code'], 'SOURCE_CHANGED')
        self.assertNotIn('STALE TEXT', str(value))

    def test_zero_wait_client_can_reconnect_to_durable_markdown_result(self):
        self.require_python()
        path = self.source()
        queued = self.jobs.wait(self.workspace, self.payload(path), seconds=0)
        self.assertIn(queued['status'], {'queued', 'running'})
        replacement = module.DocumentJobs(test_root=self.root, python=PYTHON)
        query = self.payload(path, job_id=queued['job_id'])
        self.until(lambda: replacement.status(self.workspace, query)['job_status'] in module.TERMINAL)
        value = replacement.status(self.workspace, query)
        self.assertTrue(value['ok'], value)
        self.assertIn('Queue evidence 12345', value['text'])
        self.assertEqual(value['engine'], 'builtin')
        self.assertTrue(value['units'])
        for index, unit in enumerate(value['units'], start=1):
            self.assertEqual(unit['unit_index'], index)
            self.assertEqual(unit['unit_text_sha256'],
                             hashlib.sha256(unit['text'].encode('utf-8')).hexdigest())

        def dispatcher_has_exited():
            with replacement.worker_lock() as acquired:
                return acquired

        self.until(dispatcher_has_exited)

    def test_running_cancel_kills_owned_child_and_next_real_markdown_job_succeeds(self):
        self.require_python()
        slow, next_source = self.source('slow.md'), self.source('next.md')
        first = self.jobs.submit(self.workspace, self.payload(slow))
        second = self.jobs.submit(self.workspace, self.payload(next_source))
        marker = self.root / 'child-started.txt'
        helper = self.root / 'synthetic_slow_worker.py'
        helper.write_text(
            'import json, os, pathlib, sys, time\n'
            'request = json.load(sys.stdin)\n'
            'pathlib.Path(request["marker"]).write_text(str(os.getpid()))\n'
            'time.sleep(30)\n'
            'print(json.dumps({"ok": True, "status": "ready", "text": "too late"}))\n',
            encoding='utf-8')
        real_execute = self.jobs._execute
        real_guard = module._child_guard
        processes, guards, failures = [], [], []

        def guard(process):
            processes.append(process)
            result = real_guard(process)
            guards.append(result is not None)
            return result

        def execute(row):
            if row['id'] == first['job_id']:
                return self.jobs._run_child(
                    row['id'], PYTHON, helper, {'marker': str(marker)}, timeout=15)
            return real_execute(row)

        def drain():
            try:
                self.jobs.drain()
            except BaseException as exc:
                failures.append(exc)

        with patch.object(self.jobs, '_execute', side_effect=execute), \
                patch.object(module, '_child_guard', side_effect=guard):
            thread = threading.Thread(target=drain, name='synthetic-document-dispatcher')
            thread.start()
            try:
                self.until(marker.is_file)
                self.assertEqual(self.status(slow, first)['job_status'], 'running')
                self.status(slow, first, cancel=True)
                thread.join(10)
                self.assertFalse(thread.is_alive(), 'Cancellation did not release worker capacity')
            finally:
                if thread.is_alive():
                    self.status(slow, first, cancel=True)
                    for process in processes:
                        if process.poll() is None:
                            module._kill_tree(process)
                    thread.join(10)
        self.assertEqual(failures, [])
        self.assertEqual(self.status(slow, first)['job_status'], 'cancelled')
        value = self.status(next_source, second)
        self.assertTrue(value['ok'], value)
        self.assertIn('Queue evidence 12345', value['text'])
        self.assertEqual(value['engine'], 'builtin')
        self.assertEqual(len(processes), 2)
        self.assertTrue(all(process.poll() is not None for process in processes))
        if os.name == 'nt':
            self.assertEqual(guards, [True, True], 'Windows Job Object must own both children')


if __name__ == '__main__':
    unittest.main()
