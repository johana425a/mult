"""Isolated failed-draft propagation/schema checks; no models or services."""
from __future__ import annotations

import asyncio
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # Embedded Python may otherwise pin the old runtime.
TEST_ROOT = ROOT / 'runtime/test-data'
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ['EDUAGENT_DATA'] = tempfile.mkdtemp(prefix='review-import-', dir=TEST_ROOT)

from fastapi.testclient import TestClient
from portal import app as api
from portal.storage import Store


class ReviewDraftTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='review-case-', dir=TEST_ROOT)
        api.store = Store(Path(self.temporary.name))
        api.UPLOADS = api.store.root / 'materials'
        api.UPLOADS.mkdir()
        api.store.insert('materials', {'id': 'source', 'title': 'Software fixture', 'path': 'not-read',
                                       'text': 'Original software fixture', 'char_count': 25})
        api.store.insert('lessons', {'id': 'lesson', 'title': 'Software fixture', 'material_id': 'source',
                                    'goal': 'test', 'status': 'queued', 'job_id': 'testjob'})
        self.client = TestClient(api.app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def run_job(self, response, saved=None):
        class Bridge:
            async def poll(self, job_id):
                self.polled_id = job_id
                return response

            async def classroom(self, cid):
                if isinstance(saved, Exception):
                    raise saved
                return saved

        bridge = Bridge()
        with patch.object(api, 'om_bridge', return_value=bridge):
            asyncio.run(api.generate_lesson('lesson', resume=True))
        return api.store.get('lessons', 'lesson')

    @staticmethod
    def failed_result():
        return {'status': 'failed', 'error': 'SOURCE_FIDELITY_REVIEW_REQUIRED: test audit failed',
                'result': {'reviewRequired': True, 'sourceFidelity': 'needs_review',
                           'classroomId': 'retained_draft', 'url': 'https://untrusted.invalid/ignored',
                           'scenesCount': 99}}

    @staticmethod
    def saved_draft():
        return {'id': 'retained_draft', 'stage': {'id': 'retained_draft',
                'sourceFidelity': {'status': 'needs_review'}}, 'scenes': [{'id': 'real-scene'}]}

    def test_retained_draft_remains_failed_with_explicit_review_keys(self):
        lesson = self.run_job(self.failed_result(), self.saved_draft())
        self.assertEqual(lesson['status'], 'failed')
        self.assertEqual(lesson['review_required'], 1)
        self.assertEqual(lesson['source_fidelity'], 'needs_review')
        self.assertEqual(lesson['classroom_id'], 'retained_draft')
        self.assertEqual(lesson['classroom_url'], 'http://127.0.0.1:3793/classroom/retained_draft')
        self.assertIsNone(lesson['tts_coverage'])
        self.assertIn('verification pending', lesson['progress'])
        self.assertIn('SOURCE_FIDELITY_REVIEW_REQUIRED', lesson['error'])
        exported = self.client.get('/api/export-records').json()
        self.assertEqual(exported['lessons'][0]['review_required'], 1)
        self.assertEqual(exported['lessons'][0]['source_fidelity'], 'needs_review')

    def test_normal_failure_keeps_no_review_location(self):
        lesson = self.run_job({'status': 'failed', 'error': 'ordinary failure'})
        self.assertEqual(lesson['status'], 'failed')
        self.assertEqual(lesson['review_required'], 0)
        self.assertIsNone(lesson['source_fidelity'])
        self.assertIsNone(lesson['classroom_id'])
        self.assertIsNone(lesson['classroom_url'])

    def test_unverified_or_missing_draft_cannot_gain_a_review_entry(self):
        for saved in (None, ConnectionError('unreadable draft'),
                      {**self.saved_draft(), 'scenes': []},
                      {**self.saved_draft(), 'reserved': True},
                      {**self.saved_draft(), 'id': 'wrong'},
                      {**self.saved_draft(), 'stage': {'id': 'retained_draft', 'sourceFidelity': {'status': 'verified'}}}):
            with self.subTest(saved=saved):
                lesson = self.run_job(self.failed_result(), saved)
                self.assertEqual(lesson['status'], 'failed')
                self.assertEqual(lesson['review_required'], 0)
                self.assertIsNone(lesson['classroom_url'])

    def test_marker_without_valid_draft_id_is_not_a_review_result(self):
        response = self.failed_result()
        response['result']['classroomId'] = '../outside'
        lesson = self.run_job(response, self.saved_draft())
        self.assertEqual(lesson['review_required'], 0)
        self.assertIsNone(lesson['classroom_url'])

    def test_success_keeps_ready_behavior_and_no_review_marker(self):
        lesson = self.run_job({'status': 'succeeded', 'result': {'classroomId': 'success_draft'}},
                              {'id': 'success_draft', 'scenes': []})
        self.assertEqual(lesson['status'], 'ready')
        self.assertEqual(lesson['classroom_id'], 'success_draft')
        self.assertEqual(lesson['review_required'], 0)
        self.assertIsNone(lesson['source_fidelity'])

    def test_schema_addition_preserves_all_old_fields_and_attempts(self):
        legacy = api.store.root / 'legacy'
        legacy.mkdir()
        database = legacy / 'learning.sqlite3'
        with closing(sqlite3.connect(database)) as db:
            db.executescript('''CREATE TABLE lessons (
                id TEXT PRIMARY KEY, title TEXT, material_id TEXT, goal TEXT,
                status TEXT, job_id TEXT, classroom_id TEXT, classroom_url TEXT,
                dt_course_id TEXT, error TEXT, progress TEXT, created_at TEXT,
                updated_at TEXT, warning TEXT, tts_coverage TEXT);
                CREATE TABLE attempts (id TEXT PRIMARY KEY, lesson_id TEXT,
                question TEXT, answer TEXT, feedback TEXT, status TEXT, error TEXT,
                dt_session_id TEXT, dt_turn_id TEXT, created_at TEXT, updated_at TEXT);''')
            lesson_values = ('old_lesson', 'Previous title', 'material', 'Previous goal', 'failed', 'oldjob',
                             'oldcid', 'http://127.0.0.1:3793/classroom/oldcid', 'dtcourse',
                             'old error', 'old progress', 'created', 'updated', 'old warning', '{"written":0}')
            attempt_values = ('attempt', 'old_lesson', 'Previous question', 'Original first answer', 'Previous feedback', 'saved',
                              None, 'dtsession', 'dtturn', 'created', 'updated')
            db.execute('INSERT INTO lessons VALUES (' + ','.join('?' for _ in lesson_values) + ')', lesson_values)
            db.execute('INSERT INTO attempts VALUES (' + ','.join('?' for _ in attempt_values) + ')', attempt_values)
            db.commit()
            columns = [row[1] for row in db.execute('PRAGMA table_info(lessons)')]
            before_attempts = db.execute('SELECT * FROM attempts').fetchall()
        migrated = Store(legacy)
        after = migrated.get('lessons', 'old_lesson')
        self.assertEqual(tuple(after[column] for column in columns), lesson_values)
        self.assertEqual(after['review_required'], 0)
        self.assertIsNone(after['source_fidelity'])
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual(db.execute('SELECT * FROM attempts').fetchall(), before_attempts)
        # A schema addition changes SQLite bytes; the claim is original field
        # preservation, never equality of the old and new database hashes.


if __name__ == '__main__':
    unittest.main(verbosity=2)
