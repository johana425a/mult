"""Durable local document work shared by all product entry points.

The caller supplies a server-authorized root, never an arbitrary model command.
SQLite owns requests/results. Two lanes, each owned by an OS file lock, do the
work: the read lane (quick reads, cached MinerU windows, preparation plans) and
the parse lane (local MinerU batches in one persistent worker). A read that
needs an unparsed MinerU batch parks until the parse lane has it, so other
documents keep moving. Waiting clients may disappear without killing a job.
Explicit cancellation is separate and a lane only advances after its child has
actually exited.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import uuid

from scripts.storage_paths import StoragePaths, assert_plain_path, select_storage
from scripts import workspace_document_reader as reader

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {'ready', 'partial', 'empty', 'needs_ocr', 'failed', 'cancelled'}
FIELDS = {'path', 'cursor', 'start_unit', 'ocr', 'max_chars', 'max_units',
          'asset_id', 'document_sha256', 'max_dimension', 'engine', 'job_id', 'tier'}
MAX_RESULT = 24 * 1024 * 1024
# Local MinerU tiers, all on this computer. adaptive (the default) parses with
# the small ONNX models first and sends only pages whose layout shows tables or
# display formulas through the standard tier's local MinerU2.5 VLM; standard
# runs the hybrid VLM pipeline on every page; advanced adds two-step VLM
# extraction with image analysis; basic never uses the VLM. Measured on a
# 4-core CPU: basic ~4-11 s/page, standard ~13 s/page with a text layer and
# ~100 s/page for scans, advanced ~105 s/page.
MINERU_TIERS = {'adaptive', 'basic', 'standard', 'advanced'}
DEFAULT_MINERU_TIER = 'adaptive'
DEFAULT_AUTO_TIER = 'adaptive'
# CPU VLM inference is slow, so VLM tiers parse smaller physical-page batches
# (earlier first results) with a longer per-batch limit.
MINERU_BATCH_PAGES = {'basic': 8, 'adaptive': 6, 'standard': 6, 'advanced': 4}
MINERU_TIMEOUT_SECONDS = {'basic': 1800, 'adaptive': 3600, 'standard': 3600, 'advanced': 3600}
# Parse-lane order: a read that is waiting (0), read-ahead of the next batches
# of a document being read (1), background preparation (2). A running batch is
# never preempted; it finishes first.
PARSE_PRIORITY = {'read': 0, 'read_ahead': 1, 'prepare': 2}
READ_AHEAD_BATCHES = 2
# The persistent worker keeps the models and the private VLM server loaded for
# follow-up batches, then exits so an idle desktop holds no inference memory.
PARSE_IDLE_SECONDS = 120
PREPARE_LIMIT = 50
WAIT_LIMIT_SECONDS = 50
MAX_RESPONSE_LINE = 4 * 1024 * 1024
# Formats where local MinerU adds evidence over the built-in reader.
MINERU_SUFFIXES = {'.pdf', '.pptx', '.docx', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
# Word/PowerPoint keep the built-in text and locations; MinerU parses their
# embedded images, which MinerU's own native Office path leaves unread.
OFFICE_IMAGE_FORMATS = {'docx', 'pptx'}
IMAGE_FORMATS = {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff', 'gif'}
IMAGE_SCOPE = '["embedded-image"]'  # content-addressed: one parse per image
IMAGE_TEXT_LIMIT = 8000


def failure(code, message, *, retryable=False, **extra):
    return {'ok': False, 'status': 'error', 'error': {
        'code': code, 'message': message, 'retryable': retryable}, **extra}


def runtime_python():
    portable = ROOT / 'runtime/python/python.exe'
    return portable if portable.is_file() else ROOT / 'runtime/deeptutor-venv/Scripts/python.exe'


def child_environment():
    allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'TEMP', 'TMP'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    try:
        limit = min(512 * 1024 * 1024, max(1024 * 1024, int(os.environ.get('EDUAGENT_DOCUMENT_MAX_BYTES', 200 * 1024 * 1024))))
    except ValueError:
        limit = 200 * 1024 * 1024
    env['EDUAGENT_DOCUMENT_MAX_BYTES'] = str(limit)
    return env


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _atomic_json(path, value):
    assert_plain_path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(_dump(value), encoding='utf-8')
    os.replace(temporary, path)


class DocumentJobs:
    def __init__(self, *, test_root=None, python=None):
        self.storage = select_storage(ROOT) if test_root is None else StoragePaths(ROOT, assert_plain_path(Path(test_root)))
        self.directory = self.storage.state_root / 'runtime/document-jobs'
        self.cache = self.storage.state_root / 'cache/document-jobs'
        self.storage.prepare(self.directory, self.cache)
        self.database = self.directory / 'jobs.sqlite'
        assert_plain_path(self.database)
        self.python = Path(python) if python else runtime_python()
        self.test_root = str(test_root) if test_root is not None else None
        # Set only while this instance runs the read lane: MinerU work is then
        # handed to the parse lane instead of running inline.
        self._lane = None
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, dedup TEXT UNIQUE NOT NULL,
                    scope TEXT NOT NULL, source_hash TEXT NOT NULL,
                    request TEXT NOT NULL, status TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    result TEXT, stage TEXT NOT NULL DEFAULT 'queued');
                CREATE INDEX IF NOT EXISTS document_queue ON jobs(status,created);
                CREATE TABLE IF NOT EXISTS documents (
                    scope TEXT NOT NULL, source_hash TEXT NOT NULL,
                    unit_count INTEGER NOT NULL, updated REAL NOT NULL, unresolved TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY(scope,source_hash));
                CREATE TABLE IF NOT EXISTS coverage (
                    scope TEXT NOT NULL, source_hash TEXT NOT NULL, unit_index INTEGER NOT NULL,
                    locator TEXT NOT NULL, text_hash TEXT NOT NULL, total_chars INTEGER NOT NULL,
                    spans TEXT NOT NULL, extraction_complete INTEGER NOT NULL,
                    unresolved TEXT NOT NULL, assets TEXT NOT NULL, engine TEXT NOT NULL,
                    updated REAL NOT NULL,
                    PRIMARY KEY(scope,source_hash,unit_index));
                CREATE TABLE IF NOT EXISTS parses (
                    key TEXT PRIMARY KEY, scope TEXT NOT NULL, source_hash TEXT NOT NULL,
                    root TEXT NOT NULL, path TEXT NOT NULL, tier TEXT NOT NULL,
                    batch_start INTEGER NOT NULL, batch_end INTEGER, unit_count INTEGER, pages INTEGER,
                    priority INTEGER NOT NULL, origin TEXT NOT NULL, status TEXT NOT NULL,
                    stage TEXT NOT NULL DEFAULT 'queued', attempt INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT,
                    created REAL NOT NULL, updated REAL NOT NULL, started REAL, finished REAL,
                    elapsed REAL, cold INTEGER);
                CREATE INDEX IF NOT EXISTS parse_queue ON parses(status,priority,created,batch_start);
                CREATE INDEX IF NOT EXISTS parse_document ON parses(scope,source_hash);
            ''')
            db.execute('BEGIN IMMEDIATE')
            if 'unresolved' not in {row[1] for row in db.execute('PRAGMA table_info(documents)')}:
                db.execute("ALTER TABLE documents ADD COLUMN unresolved TEXT NOT NULL DEFAULT '[]'")
            columns = {row[1] for row in db.execute('PRAGMA table_info(jobs)')}
            if 'kind' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'read'")
            if 'waiting_for' not in columns:
                db.execute('ALTER TABLE jobs ADD COLUMN waiting_for TEXT')
            if 'owner_hash' not in {row[1] for row in db.execute('PRAGMA table_info(parses)')}:
                # Embedded-image parses are keyed by image content; owner_hash
                # links them to the document whose progress they belong to.
                db.execute('ALTER TABLE parses ADD COLUMN owner_hash TEXT')

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=15)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA busy_timeout=15000')
            with db:
                yield db
        finally:
            db.close()

    def _source(self, root, payload):
        if set(payload) - FIELDS:
            raise ValueError('document_request_invalid')
        relative, suffix, content, digest = reader.source_bytes({'root': str(root), **payload})
        scope = _dump([str(Path(root).resolve()).casefold() if os.name == 'nt' else str(Path(root).resolve()), relative])
        return scope, suffix, content, digest

    def submit(self, root, payload):
        scope, _, _, digest = self._source(root, payload)
        engine = payload.get('engine', 'auto')
        if engine not in {'auto', 'builtin', 'mineru'}:
            raise ValueError('document_engine_invalid')
        if payload.get('tier', DEFAULT_MINERU_TIER) not in MINERU_TIERS:
            raise ValueError('document_engine_tier_invalid')
        request = {k: v for k, v in payload.items() if k != 'job_id'}
        request.update(root=str(Path(root).resolve()), document_sha256=digest, engine=engine, action='read')
        signature = hashlib.sha256((ROOT / 'scripts/workspace_document_reader.py').read_bytes() + Path(__file__).read_bytes()).hexdigest()
        mineru = ROOT / 'scripts/mineru_document_worker.py'
        if engine != 'builtin' and mineru.is_file():
            signature += hashlib.sha256(mineru.read_bytes()).hexdigest()
        dedup = hashlib.sha256(_dump([scope, request, signature, 'job-v1']).encode()).hexdigest()
        now = time.time()
        with self.connect() as db:
            if payload.get('job_id'):
                row = self._authorized(db, payload['job_id'], scope)
                if row['source_hash'] != digest:
                    return failure('SOURCE_CHANGED', 'The source changed and is waiting to be read again.')
                return self._view(row)
            db.execute('INSERT OR IGNORE INTO jobs(id,dedup,scope,source_hash,request,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, dedup, scope, digest, _dump(request), 'queued', now, now))
            row = db.execute('SELECT * FROM jobs WHERE dedup=?', (dedup,)).fetchone()
            # An explicit fresh read can retry a previous failure/cancellation;
            # polling with job_id never silently restarts it.
            missing = row['result'] and not (self.cache / row['result']).is_file()
            if row['status'] in {'failed', 'cancelled'} or missing:
                db.execute("UPDATE jobs SET status='queued',cancel_requested=0,result=NULL,stage='queued',waiting_for=NULL,updated=? WHERE id=?", (now, row['id']))
                row = db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone()
            return self._view(row)

    @staticmethod
    def _authorized(db, job_id, scope):
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
            raise ValueError('document_job_invalid')
        row = db.execute('SELECT * FROM jobs WHERE id=? AND scope=?', (job_id, scope)).fetchone()
        if row is None:
            raise ValueError('document_job_unknown')
        return row

    def status(self, root, payload, *, cancel=False):
        scope, _, _, digest = self._source(root, payload)
        with self.connect() as db:
            row = self._authorized(db, payload.get('job_id'), scope)
            if digest != row['source_hash']:
                return failure('SOURCE_CHANGED', 'The source changed. Read it again.', job_id=row['id'])
            if cancel and row['status'] not in TERMINAL:
                db.execute("UPDATE jobs SET cancel_requested=1,updated=?,stage='cancelling' WHERE id=?", (time.time(), row['id']))
                if row['status'] in {'queued', 'waiting'}:
                    self._finish(db, row['id'], failure('document_cancelled', 'Reading stopped.'), 'cancelled')
                    if row['status'] == 'waiting':
                        self._release_parse(db, row)
                row = db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone()
            return self._view(row, db)

    def _release_parse(self, db, row):
        """A stopped read drops MinerU work that only it wanted. Background
        preparation and batches other reads still wait for keep running."""
        key = row['waiting_for']
        if not key:
            return
        active = "SELECT 1 FROM jobs WHERE jobs.waiting_for=parses.key AND jobs.status IN ('queued','running','waiting') AND jobs.id<>?"
        now = time.time()
        stopped = _dump(failure('document_cancelled', 'Local MinerU parsing was stopped with the read that requested it.'))
        db.execute(f"UPDATE parses SET status='cancelled',stage='cancelled',error=?,finished=?,updated=? WHERE status='queued' "
                   f"AND origin IN ('read','read_ahead') AND scope=? AND COALESCE(owner_hash,source_hash)=? AND NOT EXISTS ({active})",
                   (stopped, now, now, row['scope'], row['source_hash'], row['id']))
        db.execute(f"UPDATE parses SET cancel_requested=1,stage='cancelling',updated=? WHERE status='running' AND key=? "
                   f"AND origin IN ('read','read_ahead') AND NOT EXISTS ({active})", (now, key, row['id']))

    def asset(self, root, payload):
        scope, _, _, digest = self._source(root, payload)
        # Version is mandatory even when a preview is cached. Original-image
        # requests never consume or wait for the heavy parse worker slot.
        if payload.get('document_sha256') != digest:
            return failure('SOURCE_VERSION_REQUIRED', 'Read the document before opening images for that source version.')
        signature = hashlib.sha256((ROOT / 'scripts/workspace_document_reader.py').read_bytes()).hexdigest()
        key = hashlib.sha256(_dump([scope, digest, payload.get('asset_id'), payload.get('max_dimension'), signature]).encode()).hexdigest()
        folder = self.cache / 'assets'
        self.storage.prepare(folder)
        path = assert_plain_path(folder / (key + '.json'))
        if path.is_file():
            return json.loads(path.read_text('utf-8'))
        result = reader.handle_request({'root': str(root), **payload, 'action': 'asset'})
        if result.get('ok'):
            self._source(root, payload)
            _atomic_json(path, result)
        return result

    def _view(self, row, db=None):
        common = {'job_id': row['id'], 'job_status': row['status'], 'stage': row['stage'], 'attempt': row['attempt']}
        if row['result']:
            path = assert_plain_path(self.cache / row['result'])
            if not path.is_relative_to(self.cache) or not path.is_file():
                return failure('document_cache_missing', 'The result needs recovery. Read again to resume.', retryable=True, **common)
            value = json.loads(path.read_text(encoding='utf-8'))
            return {**value, **common}
        if row['status'] == 'waiting' and row['waiting_for']:
            # Reported as running so existing pollers keep waiting; newer
            # clients use the parse progress to stop waiting and come back.
            with contextlib.ExitStack() as stack:
                connection = db or stack.enter_context(self.connect())
                parse = self._parse_progress(connection, [row['waiting_for']]).get(row['waiting_for'])
            pending = {'ok': True, 'status': 'running', 'retry_after_ms': 2000, **common}
            if parse:
                pending.update(parse=parse, message=pending_message(parse))
            return pending
        return {'ok': True, 'status': row['status'], 'retry_after_ms': 500, **common}

    def ensure_worker(self):
        self._spawn('worker.lock', '--drain')

    def ensure_parse_worker(self):
        self._spawn('parse.lock', '--drain-parses')

    def _spawn(self, lock, flag):
        if not self.python.is_file():
            raise OSError('document_runtime_unavailable')
        if self._lane_busy(lock):
            return  # The running lane re-checks its queue before it exits.
        argv = [str(self.python), '-I', '-B', str(ROOT / 'scripts/document_job_worker.py'), flag]
        if self.test_root:
            argv += ['--test-root', self.test_root]
        # No pipes inherited from a waiting HTTP client. Losing that client
        # does not terminate the owned document queue.
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=child_environment(), close_fds=True,
                         **({'creationflags': 0x08000000} if os.name == 'nt' else {'start_new_session': True}))
        threading.Thread(target=process.wait, name='document-dispatcher-reaper', daemon=True).start()

    def _lane_busy(self, name):
        with self._lane_lock(name) as acquired:
            return not acquired

    def _kick(self, lane):
        try:
            self.ensure_parse_worker() if lane == 'parse' else self.ensure_worker()
        except OSError:
            pass  # Work stays queued; the next client call starts the lane.

    def wait(self, root, payload, seconds=20):
        value = self.submit(root, payload)
        if value.get('status') not in {'queued', 'running'}:
            return value
        self.ensure_worker()
        if value.get('job_status') == 'waiting':
            self._kick('parse')
        deadline = time.monotonic() + min(WAIT_LIMIT_SECONDS, max(0, seconds))
        query = {'path': payload['path'], 'job_id': value['job_id']}
        while time.monotonic() < deadline:
            time.sleep(.15 if value.get('job_status') != 'waiting' else .5)
            value = self.status(root, query)
            if value.get('status') not in {'queued', 'running'}:
                return value
        return value

    def _finish(self, db, job_id, value, status=None):
        relative = job_id + '/result.json'
        self.storage.prepare(self.cache / job_id)
        _atomic_json(self.cache / relative, value)
        state = status or (value.get('status', 'ready') if value.get('ok') else 'failed')
        db.execute('UPDATE jobs SET status=?,result=?,stage=?,updated=? WHERE id=?',
                   (state, relative, state, time.time(), job_id))
        if value.get('ok') and isinstance(value.get('document', {}).get('unit_count'), int):
            job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            self._record_coverage(db, job, value)

    def _record_coverage(self, db, job, value):
        identity = (job['scope'], job['source_hash'])
        count = value['document']['unit_count']
        previous = db.execute('SELECT unresolved FROM documents WHERE scope=? AND source_hash=?', identity).fetchone()
        document_unresolved = set(json.loads(previous[0])) if previous else set()
        unit_unresolved = {code for unit in value.get('units', []) for code in unit.get('coverage', {}).get('unresolved', [])}
        document_unresolved.update(set(value.get('coverage', {}).get('unresolved', [])) - unit_unresolved)
        if value.get('engine') == 'mineru' and not value.get('upgrade_required'):
            document_unresolved.difference_update({'structure_upgrade_unavailable', 'structure_upgrade_incomplete', 'structure_mapping_unverified'})
        db.execute('INSERT OR REPLACE INTO documents(scope,source_hash,unit_count,updated,unresolved) VALUES(?,?,?,?,?)',
                   (*identity, count, time.time(), _dump(sorted(document_unresolved))))
        request = json.loads(job['request'])
        start, _ = reader.cursor_decode(request.get('cursor'), job['source_hash'])
        if request.get('start_unit'):
            start = request['start_unit'] - 1
        for offset, unit in enumerate(value.get('units', [])):
            index = unit.get('unit_index', start + offset + 1)
            if type(index) is not int or not 1 <= index <= count:
                continue
            text = unit.get('text', '')
            length = unit.get('total_chars', len(text))
            begin, end = unit.get('char_start', 0), unit.get('char_end', len(text))
            text_hash = unit.get('unit_text_sha256') or hashlib.sha256(text.encode()).hexdigest()
            prior = db.execute('SELECT * FROM coverage WHERE scope=? AND source_hash=? AND unit_index=?', (*identity, index)).fetchone()
            spans = json.loads(prior['spans']) if prior and prior['text_hash'] == text_hash else []
            spans = merge_spans([*spans, [begin, end]])
            unresolved = set(unit.get('coverage', {}).get('unresolved', []))
            if unit.get('status') in {'partial', 'needs_ocr'}:
                unresolved.add('source_review_required')
            complete = not unresolved and spans == [[0, length]]
            db.execute('INSERT OR REPLACE INTO coverage VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (*identity, index, _dump(unit.get('locator', {})), text_hash, length,
                        _dump(spans), int(complete), _dump(sorted(unresolved)),
                        _dump([item.get('id') for item in unit.get('assets', [])]),
                        value.get('engine', 'builtin'), time.time()))

    def coverage(self, root, payload):
        request = {k: v for k, v in payload.items() if k in FIELDS}
        scope, suffix, _, digest = self._source(root, request)
        limit = reader.bounded_int(payload.get('limit'), 100, 1, 200)
        offset = 0
        token = payload.get('coverage_cursor')
        if token:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(reader.normalize_cursor(token) or ''))
                if decoded['scope'] != hashlib.sha256(scope.encode()).hexdigest() or decoded['sha256'] != digest:
                    raise ValueError()
                offset = int(decoded['offset'])
                if offset < 0:
                    raise ValueError()
            except Exception:
                raise ValueError('document_coverage_cursor_invalid') from None
        with self.connect() as db:
            doc = db.execute('SELECT * FROM documents WHERE scope=? AND source_hash=?', (scope, digest)).fetchone()
            if doc is None:
                return {'ok': True, 'status': 'unread', 'document_sha256': digest, 'unit_count': None,
                        'entries': [], 'next_cursor': None, 'extraction_complete': False,
                        'scope': 'extraction_coverage', 'note': 'Not read yet. The full unit count will be known after initial extraction.'}
            count = doc['unit_count']
            if offset > count:
                raise ValueError('document_coverage_cursor_invalid')
            rows = {row['unit_index']: row for row in db.execute(
                'SELECT * FROM coverage WHERE scope=? AND source_hash=? AND unit_index>? AND unit_index<=?',
                (scope, digest, offset, min(count, offset + limit)))}
            completed = db.execute('SELECT COUNT(*),COALESCE(SUM(extraction_complete),0) FROM coverage WHERE scope=? AND source_hash=?', (scope, digest)).fetchone()
        entries = []
        for index in range(offset + 1, min(count, offset + limit) + 1):
            row = rows.get(index)
            if row is None:
                locator = {'page': index} if suffix == '.pdf' else {'slide': index} if suffix == '.pptx' else {'unit_index': index}
                entries.append({'unit_index': index, 'locator': locator, 'status': 'unread', 'read_ranges': []})
            else:
                entries.append({'unit_index': index, 'locator': json.loads(row['locator']),
                                'status': 'extracted' if row['extraction_complete'] else 'partial',
                                'read_ranges': json.loads(row['spans']), 'total_chars': row['total_chars'],
                                'unresolved': json.loads(row['unresolved']), 'asset_ids': json.loads(row['assets']), 'engine': row['engine']})
        next_offset = offset + len(entries)
        next_cursor = base64.urlsafe_b64encode(_dump({'scope': hashlib.sha256(scope.encode()).hexdigest(), 'sha256': digest, 'offset': next_offset}).encode()).decode() if next_offset < count else None
        return {'ok': True, 'status': 'ready', 'scope': 'extraction_coverage', 'document_sha256': digest,
                'unit_count': count, 'visited_units': completed[0], 'extracted_units': completed[1],
                'unread_units': count - completed[0], 'extraction_complete': completed[1] == count and not json.loads(doc['unresolved']),
                'unresolved': json.loads(doc['unresolved']),
                'entries': entries, 'next_cursor': next_cursor,
                'note': 'This ledger records extraction coverage, not model reading or understanding. Complete processing requires using each chunk and checking pending items.'}

    def cancelled(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT cancel_requested FROM jobs WHERE id=?', (job_id,)).fetchone()
            return row is None or bool(row[0])

    @contextlib.contextmanager
    def worker_lock(self):
        with self._lane_lock('worker.lock') as acquired:
            yield acquired

    @contextlib.contextmanager
    def parse_lock(self):
        with self._lane_lock('parse.lock') as acquired:
            yield acquired

    @contextlib.contextmanager
    def _lane_lock(self, name):
        lock_path = assert_plain_path(self.directory / name)
        handle = lock_path.open('a+b')
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        acquired = False
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            pass
        try:
            yield acquired
        finally:
            if acquired:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()

    def drain(self):
        """Read lane: quick reads, cached MinerU windows and preparation plans."""
        while True:
            with self.worker_lock() as acquired:
                if not acquired:
                    return
                self._lane = 'read'
                try:
                    self._drain_reads()
                finally:
                    self._lane = None
            # Work queued while this lane was exiting would otherwise wait for
            # the next client call; look once more after releasing the lock.
            if not self._queued('jobs'):
                return

    def _queued(self, table):
        with self.connect() as db:
            return db.execute(f"SELECT 1 FROM {table} WHERE status='queued' LIMIT 1").fetchone() is not None

    def _drain_reads(self):
        now = time.time()
        with self.connect() as db:
            # OS lock proves no former dispatcher survives. Completed
            # cache entries remain; only interrupted work is resumed.
            db.execute("UPDATE jobs SET status='queued',stage='recovering',updated=? WHERE status='running'", (now,))
            # A parked read whose parse is no longer pending resumes now.
            db.execute("UPDATE jobs SET status='queued',stage='resuming',updated=? WHERE status='waiting' AND NOT EXISTS "
                       "(SELECT 1 FROM parses WHERE parses.key=jobs.waiting_for AND parses.status IN ('queued','running'))", (now,))
        while True:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                # Reads before preparation plans; otherwise first come, first served.
                row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY kind='plan',created,id LIMIT 1").fetchone()
                if row is None:
                    return
                db.execute("UPDATE jobs SET status='running',stage='reading',attempt=attempt+1,updated=? WHERE id=?", (time.time(), row['id']))
            try:
                if self.cancelled(row['id']):
                    value = failure('document_cancelled', 'Reading stopped.')
                else:
                    value = self._plan(row) if row['kind'] == 'plan' else self._execute(row)
            except Exception as exc:
                code = exc.code if isinstance(exc, reader.ReaderError) else 'document_worker_failed'
                value = failure(code, 'Reading is incomplete. Read again to resume.', retryable=True)
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                state = db.execute('SELECT cancel_requested FROM jobs WHERE id=?', (row['id'],)).fetchone()
                if state is None or state[0]:
                    value = failure('document_cancelled', 'Reading stopped.')
                elif value.get('_park'):
                    # Parse-lane completion re-queues waiting reads in its own
                    # transaction; a parse that already finished resumes now.
                    pending = db.execute("SELECT 1 FROM parses WHERE key=? AND status IN ('queued','running')", (value['_park'],)).fetchone()
                    db.execute('UPDATE jobs SET status=?,waiting_for=?,stage=?,updated=? WHERE id=?',
                               ('waiting' if pending else 'queued', value['_park'], 'mineru' if pending else 'resuming', time.time(), row['id']))
                    continue
                self._finish(db, row['id'], value, 'cancelled' if value.get('error', {}).get('code') == 'document_cancelled' else None)

    def _execute(self, row):
        request = json.loads(row['request'])
        engine = request.pop('engine')
        self._source(request['root'], {k: v for k, v in request.items() if k in FIELDS})
        structured_cursor = is_structured_cursor(request.get('cursor'))
        lightweight_request = dict(request)
        if structured_cursor:
            index, _ = reader.cursor_decode(request['cursor'], row['source_hash'])
            lightweight_request.pop('cursor', None)
            lightweight_request.update(start_unit=index + 1, ocr='off', max_chars=100000)
        elif engine == 'mineru':
            # MinerU text replaces this pass, which only supplies units,
            # locators and page images; built-in OCR would be wasted time.
            lightweight_request['ocr'] = 'off'
        value = self._run_child(row['id'], self.python, ROOT / 'scripts/workspace_document_reader.py', lightweight_request, 180)
        if not value.get('ok'):
            return value
        value['engine'] = 'builtin'
        requires = structured_cursor or engine == 'mineru' or engine == 'auto' and needs_structure(value)
        if requires:
            value = self._upgrade(row, request, value, required=structured_cursor or engine == 'mineru', engine=engine)
        # Revalidate the original after the child exits, before committing.
        self._source(request['root'], {k: v for k, v in request.items() if k in FIELDS})
        return value

    def _run_child(self, job_id, python, helper, payload, timeout):
        self.storage.prepare(self.cache / job_id)
        out = self.cache / job_id / 'stdout.json'
        err = self.cache / job_id / 'progress.jsonl'
        with out.open('wb') as output, err.open('wb') as progress:
            process = subprocess.Popen([str(python), '-I', '-B', str(helper)], stdin=subprocess.PIPE,
                                       stdout=output, stderr=progress, env=child_environment(),
                                       **({'creationflags': 0x08000000} if os.name == 'nt' else {'start_new_session': True}))
            guard = _child_guard(process)
            try:
                process.stdin.write(_dump(payload).encode('utf-8')); process.stdin.close()
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if self.cancelled(job_id) or time.monotonic() >= deadline:
                        cancelled = self.cancelled(job_id)
                        _kill_tree(process)
                        return failure('document_cancelled' if cancelled else 'document_timeout',
                                       'Reading stopped.' if cancelled else 'Reading is incomplete. Retry to continue.', retryable=not cancelled)
                    if out.stat().st_size > MAX_RESULT or err.stat().st_size > MAX_RESULT:
                        _kill_tree(process)
                        return failure('document_result_limit', 'The result is too large. Read it in chunks.')
                    time.sleep(.15)
            finally:
                if process.poll() is None:
                    _kill_tree(process)
                process.wait()
                if guard:
                    guard()
        if out.stat().st_size > MAX_RESULT:
            return failure('document_result_limit', 'The result is too large. Read it in chunks.')
        try:
            value = json.loads(out.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError):
            return failure('document_reader_failed', 'Reading is incomplete. Retry to continue.', retryable=True)
        if process.returncode and (not isinstance(value, dict) or value.get('ok') is not False):
            return failure('document_reader_failed', 'Reading is incomplete. Retry to continue.', retryable=True)
        return mineru_failure(value)

    def _upgrade(self, row, request, lightweight, *, required, engine='mineru'):
        python, helper = mineru_runtime()
        if not python.is_file() or not helper.is_file():
            if required:
                return failure('document_engine_unavailable', 'The local MinerU runtime is not installed. Repair the DeepSteam document runtime; no remote parsing service is used.')
            return {**lightweight, 'status': 'partial', 'upgrade_required': True,
                    'structure_engine_status': {'engine': 'mineru', 'available': False, 'code': 'document_engine_unavailable',
                                                'remote_fallback': False},
                    'coverage': {**lightweight.get('coverage', {}), 'text_extraction_complete': False,
                                 'unresolved': sorted(set(lightweight.get('coverage', {}).get('unresolved', [])) | {'structure_upgrade_unavailable'})},
                    'warnings': [*lightweight.get('warnings', []), 'Scans or complex layouts still need advanced parsing. Local extraction and original images are retained.']}
        tier = mineru_tier(request, engine)
        if lightweight.get('format') in OFFICE_IMAGE_FORMATS:
            return self._office_images(row, request, lightweight, tier, helper)
        pages = MINERU_BATCH_PAGES[tier]
        pdf_batch = lightweight.get('format') == 'pdf'
        first, _ = reader.cursor_decode(request.get('cursor'), row['source_hash'])
        if request.get('start_unit'):
            first = request['start_unit'] - 1
        unit_count = lightweight['document']['unit_count']
        batch_start = first // pages * pages if pdf_batch else 0
        batch_end = min(batch_start + pages, unit_count) if pdf_batch else None
        cache_key = parse_key(row['scope'], row['source_hash'], tier, batch_start, batch_end, helper)
        container = self.cache / ('mineru-' + cache_key)
        self.storage.prepare(container)
        manifest = container / 'normalized.json'
        deferred = getattr(self, '_lane', None) == 'read'
        if manifest.is_file():
            parsed = json.loads(assert_plain_path(manifest).read_text('utf-8'))
            destination = container
        elif deferred:
            # The parse lane owns the local MinerU worker. This read parks
            # until its batch is ready instead of holding the read lane.
            parsed = self._request_parse(row, request, tier, cache_key, batch_start, batch_end, unit_count)
            if parsed is None:
                self._read_ahead(row, request, tier, helper, batch_end, unit_count)
                return {'ok': True, 'status': 'running', '_park': cache_key}
            destination = container
        else:
            # A killed/failed engine may leave files. Every attempt receives a
            # fresh owned directory, never an old output directory or source.
            destination = container / ('attempt-' + uuid.uuid4().hex)
            self.storage.prepare(destination)
            with self.connect() as db:
                db.execute("UPDATE jobs SET stage='structure',updated=? WHERE id=?", (time.time(), row['id']))
            source = Path(request['root']) / request['path']
            engine_hash = row['source_hash']
            if pdf_batch:
                source, engine_hash = pdf_subset(source, container, batch_start, batch_end)
                self._source(request['root'], {'path': request['path'], 'document_sha256': row['source_hash']})
            parsed = self._run_child(row['id'], python, helper, {
                'schema_version': 1, 'action': 'parse', 'source_path': str(source),
                'output_dir': str(destination), 'source_sha256': engine_hash,
                'engine_options': {'tier': tier}, 'request_id': row['id']}, MINERU_TIMEOUT_SECONDS[tier])
            parsed = self._accept_parse(parsed, destination, engine_hash, row['source_hash'], request['root'],
                                        request['path'], batch_start, batch_end, manifest)
        if deferred and parsed.get('ok'):
            self._read_ahead(row, request, tier, helper, batch_end, unit_count)
        if not parsed.get('ok'):
            if required or parsed.get('error', {}).get('code') == 'document_cancelled':
                return parsed
            return {**lightweight, 'status': 'partial', 'upgrade_required': True,
                    'structure_engine_status': {'engine': 'mineru', 'available': True, 'code': parsed.get('error', {}).get('code'),
                                                'remote_fallback': False},
                    'coverage': {**lightweight.get('coverage', {}), 'text_extraction_complete': False,
                                 'unresolved': sorted(set(lightweight.get('coverage', {}).get('unresolved', [])) | {'structure_upgrade_incomplete'})},
                    'warnings': [*lightweight.get('warnings', []), 'Advanced parsing is incomplete. This result contains local extraction only; check the original images.'],
                    'upgrade_error': parsed.get('error', {})}
        if pdf_batch:
            lightweight = {**lightweight, 'units': [unit for unit in lightweight.get('units', [])
                if batch_start < unit.get('locator', {}).get('page', 0) <= batch_end]}
        value = located_window(parsed, {**request, 'tier': tier}, lightweight, destination)
        if value.get('ok') and parsed.get('inference'):
            value['inference'] = parsed['inference']
        return value

    def _image_sources(self, row, request, lightweight):
        """Embedded images of this window as content-addressed PNG files.

        Images come from the confined reader's own asset contract (bounded,
        SHA-bound previews); each is stored once by content so the same image
        in another document or read is parsed only once.
        """
        images = []
        for position, unit in enumerate(lightweight.get('units', [])):
            for asset in unit.get('assets', []):
                rendered = self.asset(request['root'], {'path': request['path'], 'document_sha256': row['source_hash'],
                                                        'asset_id': asset['id'], 'max_dimension': 2048})
                if not rendered.get('ok'):
                    images.append({'position': position, 'asset_id': asset['id'], 'error': rendered.get('error', {})})
                    continue
                data = base64.b64decode(rendered['asset']['base64'])
                digest = hashlib.sha256(data).hexdigest()
                container = self.cache / ('image-' + digest)
                self.storage.prepare(container)
                target = assert_plain_path(container / 'source.png')
                if not target.is_file():
                    temporary = container / (uuid.uuid4().hex + '.tmp')
                    temporary.write_bytes(data)
                    os.replace(temporary, target)
                images.append({'position': position, 'asset_id': asset['id'], 'digest': digest, 'container': container})
        return images

    def _office_images(self, row, request, lightweight, tier, helper):
        """Word/PowerPoint: the built-in text, locations and cursor stay as
        they are; each embedded image in this window is parsed by local MinerU
        (adaptive by default: small models first, the VLM only for images that
        show tables or formulas) and attached as image_analysis."""
        python, _ = mineru_runtime()
        deferred = getattr(self, '_lane', None) == 'read'
        images = self._image_sources(row, request, lightweight)
        pending = []
        for image in images:
            if 'digest' not in image:
                continue
            key = parse_key(IMAGE_SCOPE, image['digest'], tier, 0, None, helper)
            container = self.cache / ('mineru-' + key)
            self.storage.prepare(container)
            manifest = container / 'normalized.json'
            if manifest.is_file():
                image['parsed'] = json.loads(assert_plain_path(manifest).read_text('utf-8'))
                continue
            if deferred:
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    existing = db.execute('SELECT * FROM parses WHERE key=?', (key,)).fetchone()
                    if existing is not None and existing['status'] in {'failed', 'cancelled'} and _field(row, 'waiting_for') == key:
                        image['parsed'] = json.loads(existing['error'] or 'null') or failure('parse_failed', 'Local MinerU could not parse this image.')
                        continue
                    self._enqueue_parse(db, existing, 'read', key=key, scope=row['scope'], source_hash=image['digest'],
                                        owner_hash=row['source_hash'], root=str(image['container']), path='source.png',
                                        tier=tier, batch_start=0, batch_end=None, unit_count=1)
                pending.append(key)
                continue
            destination = container / ('attempt-' + uuid.uuid4().hex)
            self.storage.prepare(destination)
            parsed = self._run_child(row['id'], python, helper, {
                'schema_version': 1, 'action': 'parse', 'source_path': str(image['container'] / 'source.png'),
                'output_dir': str(destination), 'source_sha256': image['digest'],
                'engine_options': {'tier': tier}, 'request_id': row['id']}, MINERU_TIMEOUT_SECONDS[tier])
            image['parsed'] = self._accept_parse(parsed, destination, image['digest'], image['digest'], str(image['container']),
                                                 'source.png', 0, None, manifest)
        if pending:
            self._kick('parse')
            return {'ok': True, 'status': 'running', '_park': pending[-1]}
        return attach_image_analysis(lightweight, images, tier)

    def _accept_parse(self, parsed, destination, engine_hash, source_hash, root, path, batch_start, batch_end, manifest):
        """Validate a worker result, map batch pages back to the original and
        commit the batch manifest. Shared by inline and parse-lane parsing."""
        if parsed.get('ok') and parsed.get('result_path'):
            if parsed['result_path'] != 'result.json':
                return failure('document_result_invalid', 'The advanced parser result location is invalid.')
            result_file = assert_plain_path(destination / 'result.json')
            if not result_file.is_file() or result_file.stat().st_size > 256 * 1024 * 1024:
                return failure('document_result_limit', 'The advanced parser result exceeds the limit. Split the document to continue.')
            parsed = json.loads(result_file.read_text('utf-8'))
        if parsed.get('ok'):
            if parsed.get('source_sha256') != engine_hash or not isinstance(parsed.get('units'), list):
                return failure('document_result_invalid', 'Advanced parser source verification failed.')
            if batch_end is not None:
                parsed = remap_pdf_batch(parsed, batch_start, batch_end, source_hash)
            self._source(root, {'path': path, 'document_sha256': source_hash})
            _atomic_json(manifest, parsed)
        return parsed

    def _request_parse(self, row, request, tier, key, batch_start, batch_end, unit_count):
        """Queue (or move up) the batch this read needs; None means park.

        A parse that failed or was stopped while this very read waited for it
        returns its error. A fresh read of the same pages retries it instead.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM parses WHERE key=?', (key,)).fetchone()
            if existing is not None and existing['status'] in {'failed', 'cancelled'} and _field(row, 'waiting_for') == key:
                return json.loads(existing['error'] or 'null') or failure(
                    'parse_failed', 'Local MinerU parsing is incomplete. Read again to retry. No remote service was used.', retryable=True)
            self._enqueue_parse(db, existing, 'read', key=key, scope=row['scope'], source_hash=row['source_hash'],
                                root=request['root'], path=request['path'], tier=tier, batch_start=batch_start,
                                batch_end=batch_end, unit_count=unit_count)
        self._kick('parse')
        return None

    @staticmethod
    def _enqueue_parse(db, existing, origin, **batch):
        """Insert, move up or retry one parse inside the caller's transaction.

        Background preparation keeps its claim when a read moves a batch up,
        so stopping that read does not stop the prepared work. Read-ahead
        never retries a batch that failed or was stopped.
        """
        now = time.time()
        priority = PARSE_PRIORITY[origin]
        if existing is None:
            pages = None if batch['batch_end'] is None else batch['batch_end'] - batch['batch_start']
            db.execute('INSERT INTO parses(key,scope,source_hash,root,path,tier,batch_start,batch_end,unit_count,pages,'
                       'priority,origin,status,stage,created,updated,owner_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (batch['key'], batch['scope'], batch['source_hash'], batch['root'], batch['path'], batch['tier'],
                        batch['batch_start'], batch['batch_end'], batch['unit_count'], pages, priority, origin,
                        'queued', 'queued', now, now, batch.get('owner_hash')))
            return True
        if existing['status'] in {'queued', 'running'}:
            claim = 'prepare' if 'prepare' in {origin, existing['origin']} else origin if priority < existing['priority'] else existing['origin']
            if (min(priority, existing['priority']), claim) != (existing['priority'], existing['origin']):
                db.execute('UPDATE parses SET priority=?,origin=?,updated=? WHERE key=?',
                           (min(priority, existing['priority']), claim, now, existing['key']))
            return False
        if origin == 'read_ahead' and existing['status'] != 'ready':
            return False
        # Failed, stopped, or completed but its cache entry was removed.
        db.execute("UPDATE parses SET status='queued',stage='queued',priority=?,origin=?,cancel_requested=0,error=NULL,"
                   "root=?,path=?,created=?,updated=? WHERE key=?",
                   (priority, origin, batch['root'], batch['path'], now, now, existing['key']))
        return True

    def _read_ahead(self, row, request, tier, helper, batch_end, unit_count):
        """Queue the next batches of a document being read, below waiting reads,
        so they are ready by the time the reader gets there."""
        if batch_end is None or batch_end >= unit_count:
            return
        pages = MINERU_BATCH_PAGES[tier]
        # A continuing read (it carries a cursor) is reading sequentially.
        count = READ_AHEAD_BATCHES if request.get('cursor') else 1
        queued = False
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for start in range(batch_end, min(unit_count, batch_end + count * pages), pages):
                end = min(start + pages, unit_count)
                key = parse_key(row['scope'], row['source_hash'], tier, start, end, helper)
                if (self.cache / ('mineru-' + key) / 'normalized.json').is_file():
                    continue
                existing = db.execute('SELECT * FROM parses WHERE key=?', (key,)).fetchone()
                queued |= self._enqueue_parse(db, existing, 'read_ahead', key=key, scope=row['scope'],
                                              source_hash=row['source_hash'], root=request['root'], path=request['path'],
                                              tier=tier, batch_start=start, batch_end=end, unit_count=unit_count)
        if queued:
            self._kick('parse')

    def drain_parses(self, *, idle_seconds=PARSE_IDLE_SECONDS):
        """Parse lane: local MinerU batches, one at a time, in one persistent worker."""
        while True:
            with self.parse_lock() as acquired:
                if not acquired:
                    return
                self._parse_lane(idle_seconds)
            if not self._queued('parses'):
                return

    def _parse_lane(self, idle_seconds):
        with self.connect() as db:
            # The lock proves no former parse lane survives.
            db.execute("UPDATE parses SET status='queued',stage='recovering',updated=? WHERE status='running'", (time.time(),))
        session = None
        idle_since = time.monotonic()
        try:
            while True:
                row = self._claim_parse()
                if row is None:
                    if session is None or not session.alive() or time.monotonic() - idle_since >= idle_seconds:
                        return
                    time.sleep(.5)
                    continue
                cold = session is None or not session.alive()
                started = time.monotonic()
                try:
                    if cold:
                        if session is not None:
                            session.close()
                        session = None
                        session = self._new_session()
                    value = self._run_parse(row, session)
                except reader.ReaderError as exc:
                    value = failure(exc.code, 'The source changed or is unavailable. Read it again; no remote service was used.')
                except OSError:
                    value = failure('document_engine_unavailable', 'The local MinerU worker could not start. Repair the DeepSteam document runtime; no remote service was used.')
                except Exception:
                    value = failure('parse_failed', 'Local MinerU parsing is incomplete. Read again to retry. No remote service was used.', retryable=True)
                if session is not None and not session.alive():
                    session.close()
                    session = None
                self._finish_parse(row, value, time.monotonic() - started, cold)
                idle_since = time.monotonic()
        finally:
            if session is not None:
                session.close()

    def _claim_parse(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM parses WHERE status='queued' ORDER BY priority,created,batch_start LIMIT 1").fetchone()
            if row is not None:
                now = time.time()
                db.execute("UPDATE parses SET status='running',stage='starting',attempt=attempt+1,started=?,updated=? WHERE key=?",
                           (now, now, row['key']))
            return row

    def _new_session(self):
        python, helper = mineru_runtime()
        if not python.is_file() or not helper.is_file():
            raise OSError('document_engine_unavailable')
        home = self.cache / 'mineru-worker'
        self.storage.prepare(home)
        return MinerUSession(python, helper, home, vlm_parallel=self.local_settings().get('vlm_parallel'))

    def local_settings(self):
        """Optional per-computer MinerU settings (written by the local
        benchmark); machine state, never part of the installation."""
        path = self.directory / 'mineru-local.json'
        try:
            value = json.loads(assert_plain_path(path).read_text('utf-8')) if path.is_file() else {}
        except (OSError, ValueError):
            return {}
        slots = value.get('vlm_parallel') if isinstance(value, dict) else None
        return {'vlm_parallel': slots} if type(slots) is int and 1 <= slots <= 4 else {}

    def _run_parse(self, row, session):
        key = row['key']
        if self._parse_cancelled(key):
            return failure('document_cancelled', 'Local MinerU parsing was stopped.')
        self._source(row['root'], {'path': row['path'], 'document_sha256': row['source_hash']})
        container = self.cache / ('mineru-' + key)
        self.storage.prepare(container)
        manifest = container / 'normalized.json'
        if manifest.is_file():
            return {'ok': True, 'status': 'ready', 'reused': True}
        destination = container / ('attempt-' + uuid.uuid4().hex)
        self.storage.prepare(destination)
        source, engine_hash = Path(row['root']) / row['path'], row['source_hash']
        if row['batch_end'] is not None:
            source, engine_hash = pdf_subset(source, container, row['batch_start'], row['batch_end'])
            self._source(row['root'], {'path': row['path'], 'document_sha256': row['source_hash']})
        parsed = session.parse({'schema_version': 1, 'action': 'parse', 'source_path': str(source),
                                'output_dir': str(destination), 'source_sha256': engine_hash,
                                'engine_options': {'tier': row['tier']}, 'request_id': uuid.uuid4().hex},
                               MINERU_TIMEOUT_SECONDS[row['tier']], cancelled=lambda: self._parse_cancelled(key),
                               progress=lambda stage: self._parse_stage(key, stage))
        parsed = self._accept_parse(parsed, destination, engine_hash, row['source_hash'], row['root'], row['path'],
                                    row['batch_start'], row['batch_end'], manifest)
        return {name: parsed[name] for name in ('ok', 'status', 'error', 'engine') if name in parsed}

    def _parse_cancelled(self, key):
        with self.connect() as db:
            row = db.execute('SELECT cancel_requested FROM parses WHERE key=?', (key,)).fetchone()
            return row is None or bool(row[0])

    def _parse_stage(self, key, stage):
        with self.connect() as db:
            db.execute("UPDATE parses SET stage=?,updated=? WHERE key=? AND status='running'", (str(stage)[:40], time.time(), key))

    def _finish_parse(self, row, value, elapsed, cold):
        now = time.time()
        code = (value.get('error') or {}).get('code')
        status = 'ready' if value.get('ok') else 'cancelled' if code == 'document_cancelled' else 'failed'
        error = None if value.get('ok') else _dump({name: value[name] for name in ('ok', 'status', 'error', 'engine') if name in value})
        # Only real engine time counts toward the speed shown to users.
        measured = elapsed if value.get('ok') and not value.get('reused') else None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE parses SET status=?,stage=?,error=?,cancel_requested=0,finished=?,updated=?,elapsed=?,cold=? WHERE key=?',
                       (status, status, error, now, now, measured, int(cold), row['key']))
            resumed = db.execute("UPDATE jobs SET status='queued',stage='resuming',updated=? WHERE status='waiting' AND waiting_for=?",
                                 (now, row['key'])).rowcount
        if resumed:
            self._kick('read')

    @staticmethod
    def _speeds(db):
        """Speed measured on this computer: median seconds per PDF page and per
        whole document for each tier, from recent batches (a warm worker, which
        excludes model loading, is preferred)."""
        rows = db.execute("SELECT tier,pages,elapsed,cold FROM parses WHERE status='ready' AND elapsed>0 "
                          "ORDER BY finished DESC LIMIT 200").fetchall()
        speeds = {}
        for kind in ('page', 'document'):
            for tier in MINERU_TIERS:
                samples = [(row['elapsed'] / row['pages'] if kind == 'page' else row['elapsed'], row['cold']) for row in rows
                           if row['tier'] == tier and (bool(row['pages']) if kind == 'page' else row['pages'] is None)]
                values = [value for value, cold in samples if not cold] or [value for value, _ in samples]
                if values:
                    speeds[(kind, tier)] = (statistics.median(values), len(values))
        return speeds

    @staticmethod
    def _parse_row_view(row, speeds):
        measured = speeds.get(('page' if row['pages'] else 'document', row['tier']))
        view = {'tier': row['tier'], 'origin': row['origin'], 'stage': row['stage'], 'unit_count': row['unit_count'],
                'pages': [row['batch_start'] + 1, row['batch_end']] if row['batch_end'] is not None else None,
                'speed': ({'seconds_per_page' if row['pages'] else 'seconds_per_document': round(measured[0], 1),
                           'basis': f'median of {measured[1]} recent batch(es) on this computer'} if measured
                          else {'basis': 'not measured on this computer yet; the first batch measures it'})}
        if row['status'] in {'failed', 'cancelled'} and row['error']:
            view['error'] = (json.loads(row['error']).get('error') or {})
        return view

    def _parse_progress(self, db, keys=()):
        """Queue position and remaining time for pending batches; the estimate
        uses only speeds measured on this computer and is None until known."""
        speeds = self._speeds(db)
        pending = db.execute("SELECT * FROM parses WHERE status IN ('queued','running') "
                             "ORDER BY status='queued',priority,created,batch_start").fetchall()
        now = time.time()
        clock, known, views = 0.0, True, {}
        for position, row in enumerate(pending):
            measured = speeds.get(('page' if row['pages'] else 'document', row['tier']))
            estimate = None if measured is None else (measured[0] * row['pages'] if row['pages'] else measured[0])
            running = row['status'] == 'running'
            elapsed = max(0.0, now - row['started']) if running and row['started'] else 0.0
            if estimate is None:
                known = False
            else:
                clock += max(5.0, estimate - elapsed) if running else estimate
            views[row['key']] = {**self._parse_row_view(row, speeds), 'state': 'parsing' if running else 'queued',
                                 'batches_ahead': position, 'eta_seconds': round(clock) if known else None,
                                 **({'elapsed_seconds': round(elapsed)} if running else {})}
        for key in keys:
            if key not in views:
                row = db.execute('SELECT * FROM parses WHERE key=?', (key,)).fetchone()
                if row is not None:
                    views[key] = {**self._parse_row_view(row, speeds), 'state': row['status']}
        return views

    def prepare(self, root, payload):
        """Queue background local MinerU parsing for up to 50 documents and
        return at once. Later reads with the same engine/tier use the results."""
        paths = payload.get('paths')
        paths = [paths] if isinstance(paths, str) else paths
        if not isinstance(paths, list) or not 1 <= len(paths) <= PREPARE_LIMIT or not all(isinstance(path, str) and path for path in paths):
            return failure('document_request_invalid', f'paths must list 1 to {PREPARE_LIMIT} document paths.')
        engine = payload.get('engine', 'auto')
        if engine not in {'auto', 'mineru'}:
            return failure('document_request_invalid', 'prepare uses engine=auto (documents that need structure) or engine=mineru (every page).')
        python, helper = mineru_runtime()
        if not python.is_file() or not helper.is_file():
            return failure('document_engine_unavailable', 'The local MinerU runtime is not installed. Repair the DeepSteam document runtime; no remote parsing service is used.')
        tier = payload.get('tier') if payload.get('tier') in MINERU_TIERS else DEFAULT_AUTO_TIER if engine == 'auto' else DEFAULT_MINERU_TIER
        signature = hashlib.sha256(Path(__file__).read_bytes() + helper.read_bytes()).hexdigest()
        entries, plans = {}, []
        for path in dict.fromkeys(paths):
            try:
                scope, suffix, _, digest = self._source(root, {'path': path})
            except (reader.ReaderError, OSError, ValueError) as exc:
                entries[path] = {'path': path, 'ok': False, 'error': source_error(exc)}
                continue
            if suffix not in MINERU_SUFFIXES:
                entries[path] = {'path': path, 'ok': True, 'state': 'not_needed',
                                 'message': 'The built-in reader handles this format; local MinerU adds nothing here.'}
                continue
            request = {'root': str(Path(root).resolve()), 'path': path, 'document_sha256': digest,
                       'engine': engine, 'tier': tier, 'action': 'plan'}
            dedup = hashlib.sha256(_dump([scope, request, signature, 'plan-v1']).encode()).hexdigest()
            now = time.time()
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT OR IGNORE INTO jobs(id,dedup,scope,source_hash,request,status,created,updated,kind) VALUES(?,?,?,?,?,?,?,?,?)',
                           (uuid.uuid4().hex, dedup, scope, digest, _dump(request), 'queued', now, now, 'plan'))
                row = db.execute('SELECT * FROM jobs WHERE dedup=?', (dedup,)).fetchone()
                if row['status'] in TERMINAL:
                    # Planning is cheap; planning again re-queues batches that
                    # failed or were stopped and never duplicates queued ones.
                    db.execute("UPDATE jobs SET status='queued',cancel_requested=0,result=NULL,stage='queued',updated=? WHERE id=?", (now, row['id']))
            plans.append((path, scope, digest, row['id']))
        if plans:
            self._kick('read')
            # Plans only inspect the documents; wait briefly so the reply can
            # already list the queued batches.
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and not self._plans_done([plan[3] for plan in plans]):
                time.sleep(.2)
        with self.connect() as db:
            for path, scope, digest, job_id in plans:
                entries[path] = {'path': path, 'ok': True, **self._document_progress(db, scope, digest)}
            totals = self._queue_totals(db)
        return {'ok': True, 'status': 'accepted', 'engine': engine, 'tier': tier, 'remote_api': False,
                'documents': [entries[path] for path in dict.fromkeys(paths)], 'queue': totals,
                'message': (f'Local MinerU parses these on this computer in the background, one batch at a time ({tier} tier). '
                            f'Read them later with engine={engine}' + (f' and tier={tier}' if payload.get('tier') in MINERU_TIERS else '') +
                            ' to use the parsed pages; pages that are ready return at once. Check progress with the queue action.')}

    def _plans_done(self, job_ids):
        with self.connect() as db:
            rows = db.execute(f"SELECT status FROM jobs WHERE id IN ({','.join('?' * len(job_ids))})", job_ids).fetchall()
            return all(row['status'] in TERMINAL for row in rows)

    def _plan(self, row):
        """Decide what local MinerU should parse for one document and queue it.

        engine=mineru queues every page; engine=auto queues the document only
        if the built-in reader (OCR off, fast, no text kept) finds pages that
        need structure, the same test a read uses before upgrading.
        """
        request = json.loads(row['request'])
        root, path, engine, tier = request['root'], request['path'], request['engine'], request['tier']
        self._source(root, {'path': path, 'document_sha256': row['source_hash']})
        python, helper = mineru_runtime()
        if not python.is_file() or not helper.is_file():
            return failure('document_engine_unavailable', 'The local MinerU runtime is not installed. Repair the DeepSteam document runtime; no remote parsing service is used.')
        start, needed, windows = 1, engine == 'mineru', []
        while True:
            value = self._run_child(row['id'], self.python, ROOT / 'scripts/workspace_document_reader.py',
                                    {'root': root, 'path': path, 'start_unit': start, 'ocr': 'off', 'max_units': 40,
                                     'max_chars': 100000, 'document_sha256': row['source_hash']}, 180)
            if not value.get('ok'):
                return value
            unit_count, kind = value['document']['unit_count'], value.get('format')
            needed = needed or needs_structure(value)
            office = kind in OFFICE_IMAGE_FORMATS
            if office:
                windows.append(value)  # Every embedded image is needed, not just the first.
            following = value.get('next_start_unit')
            if (needed and not office) or not value.get('truncated') or not isinstance(following, int) or self.cancelled(row['id']):
                break
            start = max(following, start + 1)
            if start > unit_count:
                break
        summary = {'engine': engine, 'tier': tier, 'unit_count': unit_count, 'format': kind, 'mineru_needed': needed}
        if not needed:
            return {'ok': True, 'status': 'ready', 'kind': 'plan', 'plan': {**summary, 'batches': 0},
                    'message': 'The built-in reader extracts this document fully (no scans, formulas, tables or images that need structure); nothing was queued.'}
        if kind in OFFICE_IMAGE_FORMATS:
            images = [image for window in windows for image in self._image_sources(row, request, window) if 'digest' in image]
            queued = 0
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                for image in images:
                    key = parse_key(IMAGE_SCOPE, image['digest'], tier, 0, None, helper)
                    if (self.cache / ('mineru-' + key) / 'normalized.json').is_file():
                        continue
                    existing = db.execute('SELECT * FROM parses WHERE key=?', (key,)).fetchone()
                    queued += self._enqueue_parse(db, existing, 'prepare', key=key, scope=row['scope'], source_hash=image['digest'],
                                                  owner_hash=row['source_hash'], root=str(image['container']), path='source.png',
                                                  tier=tier, batch_start=0, batch_end=None, unit_count=1)
            if queued:
                self._kick('parse')
            return {'ok': True, 'status': 'ready', 'kind': 'plan', 'plan': {**summary, 'embedded_images': len(images),
                                                                          'batches': len(images), 'newly_queued': queued}}
        if kind == 'pdf':
            pages = MINERU_BATCH_PAGES[tier]
            batches = [(begin, min(begin + pages, unit_count)) for begin in range(0, unit_count, pages)]
        else:
            batches = [(0, None)]
        queued = 0
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for begin, end in batches:
                key = parse_key(row['scope'], row['source_hash'], tier, begin, end, helper)
                if (self.cache / ('mineru-' + key) / 'normalized.json').is_file():
                    continue
                existing = db.execute('SELECT * FROM parses WHERE key=?', (key,)).fetchone()
                queued += self._enqueue_parse(db, existing, 'prepare', key=key, scope=row['scope'], source_hash=row['source_hash'],
                                              root=root, path=path, tier=tier, batch_start=begin, batch_end=end, unit_count=unit_count)
        if queued:
            self._kick('parse')
        return {'ok': True, 'status': 'ready', 'kind': 'plan', 'plan': {**summary, 'batches': len(batches), 'newly_queued': queued}}

    def queue(self, root, payload):
        """Background parsing progress for documents under this root and for
        the local MinerU queue as a whole; cancel=true stops listed documents."""
        paths = payload.get('paths') or []
        paths = [paths] if isinstance(paths, str) else paths
        if not isinstance(paths, list) or len(paths) > PREPARE_LIMIT or not all(isinstance(path, str) and path for path in paths):
            return failure('document_request_invalid', f'paths may list up to {PREPARE_LIMIT} document paths.')
        cancel = payload.get('cancel') is True
        documents, stopped = [], False
        base = Path(root).resolve()
        with self.connect() as db:
            if not paths:
                # Documents with pending batches under this root only; other
                # folders' paths are never listed.
                seen = {}
                own = Path(str(base).casefold() if os.name == 'nt' else str(base))
                for row in db.execute("SELECT scope,COALESCE(owner_hash,source_hash) AS document FROM parses "
                                      "WHERE status IN ('queued','running') ORDER BY created"):
                    try:
                        scope_root, relative = json.loads(row['scope'])
                        location = Path(scope_root) / relative
                    except (ValueError, TypeError):
                        continue
                    if location.is_relative_to(own) and (row['scope'], row['document']) not in seen and len(seen) < PREPARE_LIMIT:
                        seen[(row['scope'], row['document'])] = location.relative_to(own).as_posix()
                targets = [(path, scope, digest) for (scope, digest), path in seen.items()]
            else:
                targets = []
                for path in dict.fromkeys(paths):
                    try:
                        scope, _, _, digest = self._source(root, {'path': path})
                    except (reader.ReaderError, OSError, ValueError) as exc:
                        documents.append({'path': path, 'ok': False, 'error': source_error(exc)})
                        continue
                    targets.append((path, scope, digest))
            for path, scope, digest in targets:
                if cancel:
                    stopped |= self._cancel_document(db, scope, digest)
                documents.append({'path': path, 'ok': True, **self._document_progress(db, scope, digest)})
            totals = self._queue_totals(db)
        if stopped:
            self._kick('read')
        return {'ok': True, 'status': 'ready', 'remote_api': False, 'documents': documents, 'queue': totals}

    @staticmethod
    def _cancel_document(db, scope, digest):
        now = time.time()
        stopped = _dump(failure('document_cancelled', 'Background parsing of this document was stopped.'))
        db.execute("UPDATE parses SET status='cancelled',stage='cancelled',error=?,finished=?,updated=? WHERE scope=? AND COALESCE(owner_hash,source_hash)=? AND status='queued'",
                   (stopped, now, now, scope, digest))
        db.execute("UPDATE parses SET cancel_requested=1,stage='cancelling',updated=? WHERE scope=? AND COALESCE(owner_hash,source_hash)=? AND status='running'",
                   (now, scope, digest))
        db.execute("UPDATE jobs SET cancel_requested=1,updated=? WHERE kind='plan' AND scope=? AND source_hash=? AND status IN ('queued','running')",
                   (now, scope, digest))
        # Reads waiting on stopped batches resume and report the stop.
        return db.execute("UPDATE jobs SET status='queued',stage='resuming',updated=? WHERE status='waiting' AND waiting_for IN "
                          "(SELECT key FROM parses WHERE scope=? AND COALESCE(owner_hash,source_hash)=? AND status='cancelled')",
                          (now, scope, digest)).rowcount > 0

    def _document_progress(self, db, scope, digest):
        rows = db.execute('SELECT * FROM parses WHERE scope=? AND COALESCE(owner_hash,source_hash)=? ORDER BY tier,batch_start', (scope, digest)).fetchall()
        views = self._parse_progress(db)
        plan = db.execute("SELECT * FROM jobs WHERE kind='plan' AND scope=? AND source_hash=? ORDER BY updated DESC LIMIT 1", (scope, digest)).fetchone()
        tiers = {}
        for row in rows:
            entry = tiers.setdefault(row['tier'], {'batches': 0, 'ready': 0, 'parsing': 0, 'queued': 0, 'failed': 0, 'stopped': 0,
                                                    'pages_ready': 0, 'unit_count': row['unit_count']})
            entry['batches'] += 1
            entry[{'running': 'parsing', 'cancelled': 'stopped'}.get(row['status'], row['status'])] += 1
            if row['status'] == 'ready' and row['pages']:
                entry['pages_ready'] += row['pages']
        pending = [views[row['key']] for row in rows if row['key'] in views]
        errors = [error for error in (json.loads(row['error']).get('error') for row in rows if row['status'] == 'failed' and row['error']) if error][:3]
        plan_view = self._view(plan, db) if plan is not None else None
        if plan_view is not None and plan['status'] in {'queued', 'running'}:
            state = 'planning'
        elif any(view['state'] == 'parsing' for view in pending):
            state = 'parsing'
        elif pending:
            state = 'queued'
        elif errors:
            state = 'failed'
        elif rows and all(row['status'] == 'ready' for row in rows):
            state = 'ready'
        elif plan_view is not None and plan_view.get('plan', {}).get('mineru_needed') is False:
            state = 'not_needed'
        elif plan_view is not None and not plan_view.get('ok', True):
            state = 'failed'
            errors = [plan_view.get('error', {})]
        elif rows:
            state = 'stopped'
        else:
            state = 'not_prepared'
        result = {'state': state, 'tiers': tiers,
                  'eta_seconds': max((view['eta_seconds'] for view in pending), default=None)
                  if pending and all(view['eta_seconds'] is not None for view in pending) else None}
        if plan_view is not None and plan_view.get('plan'):
            result['plan'] = plan_view['plan']
        if plan_view is not None and plan_view.get('message'):
            result['message'] = plan_view['message']
        if errors:
            result['errors'] = errors
        return result

    def _queue_totals(self, db):
        views = self._parse_progress(db)
        running = next((view for view in views.values() if view['state'] == 'parsing'), None)
        origins = {origin: 0 for origin in PARSE_PRIORITY}
        pages = 0
        for row in db.execute("SELECT origin,pages FROM parses WHERE status='queued'"):
            origins[row['origin']] = origins.get(row['origin'], 0) + 1
            pages += row['pages'] or 0
        etas = [view['eta_seconds'] for view in views.values()]
        return {'workers': 1, 'mode': 'local MinerU on this computer, one batch at a time; waiting reads go first',
                'running': {key: running[key] for key in ('tier', 'pages', 'stage', 'elapsed_seconds', 'origin') if key in running} if running else None,
                'queued_batches': sum(origins.values()), 'queued_by_reason': origins, 'queued_pdf_pages': pages,
                'eta_seconds': max(etas) if etas and all(eta is not None for eta in etas) else None}


def attach_image_analysis(lightweight, images, tier):
    """Add local MinerU results for embedded images to their units; the text,
    locators and cursor of the built-in reading stay unchanged."""
    units = [dict(unit) for unit in lightweight.get('units', [])]
    parsed_count = vlm_count = 0
    figures = False
    for image in images:
        unit = units[image['position']]
        analyses = unit.setdefault('image_analysis', [])
        parsed = image.get('parsed') or {'ok': False, 'error': image.get('error') or {}}
        if not parsed.get('ok'):
            analyses.append({'asset_id': image['asset_id'], 'engine': 'mineru', 'error': parsed.get('error', {})})
            continue
        inference = parsed.get('inference', {})
        text = '\n\n'.join(str(item.get('text') or '') for item in parsed.get('units', [])).strip()
        adaptive = inference.get('adaptive') or {}
        figure = bool(adaptive.get('figure_pages'))
        figures |= figure
        parsed_count += 1
        vlm_count += bool(inference.get('vlm_used'))
        analyses.append({'asset_id': image['asset_id'], 'engine': 'mineru', 'tier': inference.get('actual_tier', tier),
                         'vlm_used': inference.get('vlm_used'), 'text': text[:IMAGE_TEXT_LIMIT],
                         'truncated': len(text) > IMAGE_TEXT_LIMIT, 'contains_figure': figure,
                         **({'note': 'A figure without readable text; read with tier=advanced for local VLM image analysis, or view the image.'}
                            if figure and not text else {})})
    for unit in units:
        analyses = unit.get('image_analysis')
        if not analyses:
            continue
        coverage = dict(unit.get('coverage', {}))
        unresolved = set(coverage.get('unresolved', []))
        if all(item.get('text') for item in analyses):
            unresolved -= {'embedded_image_text_unverified', 'text_not_recognized'}
        else:
            unresolved.add('embedded_image_text_unverified')
        coverage.update(unresolved=sorted(unresolved), image_analysis='mineru', visual_review_required=True)
        unit['coverage'] = coverage
        unit['status'] = 'partial' if unresolved else 'ready'
    truncated = lightweight.get('truncated')
    warnings = [*lightweight.get('warnings', [])]
    if images:
        warnings.append(f'Embedded images were parsed locally with MinerU ({tier} tier); see image_analysis on each unit. '
                        'Recognized text may contain errors; check the original images when it matters.')
    if figures:
        warnings.append('Some images are figures or charts; read with tier=advanced for local VLM image analysis.')
    return {**lightweight, 'units': units, 'engine': 'mineru' if images else 'builtin', 'structure_engine': 'mineru',
            'structure_scope': 'embedded_images', 'warnings': list(dict.fromkeys(warnings)),
            'status': 'partial' if truncated or any(unit.get('status') in {'partial', 'needs_ocr'} for unit in units) else 'ready',
            'image_analysis': {'images': len(images), 'parsed': parsed_count, 'vlm_images': vlm_count, 'tier': tier,
                               'remote_api': False},
            'coverage': {**lightweight.get('coverage', {}), 'structure_engine': 'mineru',
                         'text_extraction_complete': not truncated and not any(
                             unit.get('status') in {'partial', 'needs_ocr'} or unit.get('coverage', {}).get('unresolved') for unit in units),
                         'unresolved': sorted({code for unit in units for code in unit.get('coverage', {}).get('unresolved', [])})}}


def parse_key(scope, source_hash, tier, batch_start, batch_end, helper):
    """Cache identity of one MinerU batch (format unchanged since v2)."""
    return hashlib.sha256(_dump([scope, source_hash, tier, batch_start, batch_end,
        'physical-pdf-batch-v2', _helper_digest(Path(helper))]).encode()).hexdigest()


_HELPER_DIGESTS = {}


def _helper_digest(helper):
    info = helper.stat()
    identity = (str(helper), info.st_mtime_ns, info.st_size)
    if identity not in _HELPER_DIGESTS:
        _HELPER_DIGESTS.clear()
        _HELPER_DIGESTS[identity] = hashlib.sha256(helper.read_bytes()).hexdigest()
    return _HELPER_DIGESTS[identity]


def source_error(exc):
    if isinstance(exc, reader.ReaderError):
        return {'code': exc.code, 'message': exc.message}
    if isinstance(exc, FileNotFoundError):
        return {'code': 'document_not_found', 'message': 'The file does not exist at this path. Check the path and retry.'}
    return {'code': 'document_request_invalid', 'message': 'The path is not a readable document in this location.'}


def _field(row, name):
    try:
        return row[name]
    except (KeyError, IndexError):
        return None


def mineru_failure(value):
    """Typed MinerU errors with user-facing text; worker diagnostics stay out
    of messages except the exact reason a local VLM cannot run."""
    if isinstance(value, dict) and value.get('ok') is False and value.get('engine') == 'mineru':
        code = value.get('error', {}).get('code', 'parse_failed')
        detail = str(value.get('error', {}).get('message') or '')[:600]
        message = ('The source changed. Read it again.' if code == 'source_changed' else
                   'The local MinerU VLM cannot run on this computer: ' + detail + ' No remote service was used.' if code == 'vlm_unavailable' else
                   'The local MinerU parser is not ready. Repair the installation; the original remains available. No remote service was used.' if code in {'parser_not_configured', 'parser_asset_missing'} else
                   'Local MinerU parsing is incomplete. Retry or view the original images. No remote service was used.')
        return {**value, 'error': {'code': code, 'message': message, 'retryable': code == 'parse_failed'}}
    return value if isinstance(value, dict) else failure('document_result_invalid', 'The reading result is invalid. Retry.')


def pending_message(parse):
    """Model-facing note for a read that is waiting on local MinerU."""
    pages = parse.get('pages')
    what = f'pages {pages[0]}-{pages[1]}' if pages else 'this document'
    if parse.get('state') == 'parsing':
        state = f'is parsing {what}'
    else:
        ahead = parse.get('batches_ahead', 0)
        state = f'has {what} queued behind {ahead} batch{"" if ahead == 1 else "es"}'
    eta = parse.get('eta_seconds')
    timing = (f'about {max(1, round(eta / 60))} min left' if eta is not None
              else 'its speed on this computer is not measured yet (the first batch measures it)')
    return (f'Local MinerU ({parse.get("tier")} tier) {state}; {timing}. You do not need to wait: work on other files, '
            'then read this document again with the same arguments; the parse keeps running and the read resumes from it. '
            'Other documents can be queued for background parsing with the prepare action. Everything runs on this computer.')


class MinerUSession:
    """A persistent local MinerU worker (``mineru_document_worker.py --serve``).

    The MinerU models and the private llama.cpp VLM server load once and serve
    many batches. One JSON request per line in, one JSON summary per line out;
    full results stay in each batch's own output directory. A cancelled or
    timed-out batch kills the worker tree; the next batch starts a fresh one.
    """

    def __init__(self, python, helper, home, *, vlm_parallel=None):
        self.home = Path(home)
        self.process = subprocess.Popen(
            [str(python), '-I', '-B', str(helper), '--serve', '--home', str(self.home),
             *(['--vlm-parallel', str(vlm_parallel)] if vlm_parallel else [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_environment(),
            **({'creationflags': 0x08000000} if os.name == 'nt' else {'start_new_session': True}))
        self.guard = None
        try:
            self.guard = _child_guard(self.process)
        except OSError:
            self.close(kill=True)
            raise
        self.lines = queue.Queue()
        self.stages = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._read_responses, name='mineru-worker-responses', daemon=True).start()
        threading.Thread(target=self._read_diagnostics, name='mineru-worker-diagnostics', daemon=True).start()

    def alive(self):
        return self.process.poll() is None

    def _read_responses(self):
        # Each reader thread owns and closes its pipe; the pipes break when the
        # worker tree exits, so these threads always finish.
        stream = self.process.stdout
        try:
            while True:
                line = stream.readline(MAX_RESPONSE_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_RESPONSE_LINE:
                    self.lines.put(b'')  # Protocol violation: treated as a crash.
                    break
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self.lines.put(None)
            with contextlib.suppress(OSError, ValueError):
                stream.close()

    def _read_diagnostics(self):
        # Progress events update the stage; other output goes to a bounded
        # local log in the worker home for troubleshooting.
        stream = self.process.stderr
        log_path = self.home / 'serve-worker.log'
        try:
            mode = 'wb' if not log_path.is_file() or log_path.stat().st_size > 2 * 1024 * 1024 else 'ab'
            with open(assert_plain_path(log_path), mode) as log:
                written = 0
                for line in iter(lambda: stream.readline(65536), b''):
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = None
                    if isinstance(event, dict) and event.get('event') == 'progress':
                        with self.lock:
                            self.stages[str(event.get('request_id', ''))] = str(event.get('stage', ''))[:40]
                    elif written < 2 * 1024 * 1024:
                        log.write(line)
                        written += len(line)
        except (OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(OSError, ValueError):
                stream.close()

    def parse(self, payload, timeout, *, cancelled, progress=None):
        request_id = payload['request_id']
        try:
            self.process.stdin.write((_dump(payload) + '\n').encode('utf-8'))
            self.process.stdin.flush()
        except (OSError, ValueError):
            self.close(kill=True)
            return failure('parse_failed', 'The local MinerU worker stopped. Read again to retry. No remote service was used.', retryable=True)
        deadline = time.monotonic() + timeout
        checked, reported = 0.0, None
        while True:
            try:
                line = self.lines.get(timeout=.25)
            except queue.Empty:
                line = False
            if line is None or line == b'':
                self.close(kill=True)
                return failure('parse_failed', 'The local MinerU worker stopped during parsing. Read again to retry. No remote service was used.', retryable=True)
            if line:
                try:
                    value = json.loads(line.decode('utf-8'))
                except (ValueError, UnicodeError):
                    self.close(kill=True)
                    return failure('document_reader_failed', 'The local MinerU worker returned an invalid result. Read again to retry.', retryable=True)
                if isinstance(value, dict) and value.get('request_id') == request_id:
                    return mineru_failure(value)
                continue  # A stale reply from an earlier, abandoned request.
            now = time.monotonic()
            if progress is not None:
                with self.lock:
                    stage = self.stages.get(request_id)
                if stage and stage != reported:
                    reported = stage
                    progress(stage)
            if now - checked >= .5:
                checked = now
                if cancelled():
                    self.close(kill=True)
                    return failure('document_cancelled', 'Local MinerU parsing was stopped.')
            if now >= deadline:
                self.close(kill=True)
                return failure('document_timeout', 'Local MinerU parsing timed out. Retry to continue, or use the standard tier. No remote service was used.', retryable=True)

    def close(self, *, kill=False):
        process = self.process
        if process.poll() is None and not kill:
            # End of input stops the serve loop, which shuts down the private
            # VLM server before the worker exits.
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            _kill_tree(process)
        if self.guard is not None:
            self.guard()
            self.guard = None
        with contextlib.suppress(OSError, ValueError):
            process.stdin.close()


def mineru_tier(request, engine):
    """Tier for this read. An explicit tier wins; a structured cursor keeps the
    tier its pages were parsed with, so later pages never switch mode (or batch
    size) mid-document; otherwise the default depends on how MinerU was asked."""
    if request.get('tier') in MINERU_TIERS:
        return request['tier']
    cursor_tier = structured_cursor(request.get('cursor')).get('tier')
    if cursor_tier in MINERU_TIERS:
        return cursor_tier
    return DEFAULT_AUTO_TIER if engine == 'auto' else DEFAULT_MINERU_TIER


def mineru_runtime():
    """Fixed installation paths of the local MinerU runtime; never PATH lookup."""
    return ROOT / 'runtime/mineru/python.exe', ROOT / 'scripts/mineru_document_worker.py'


def engine_status(*, verify=False):
    """Report what local MinerU would run: model, backend, tier and readiness.

    ``verify`` additionally starts the private llama.cpp server and reads back
    the model it loaded (no document inference). Nothing contacts the network.
    """
    python, helper = mineru_runtime()
    base = {'engine': 'mineru', 'remote_api': False, 'api_key_required': False,
            'default_tier': DEFAULT_MINERU_TIER, 'default_auto_tier': DEFAULT_AUTO_TIER, 'tiers': {
                'adaptive': 'default: small local ONNX models first; only pages with tables or display formulas use the local MinerU2.5 VLM (standard)',
                'standard': 'local MinerU2.5 VLM with hybrid layout on every page; scanned pages are slow on a CPU',
                'advanced': 'local MinerU2.5 VLM, two-step extraction with image analysis; slowest, use for figures whose meaning matters',
                'basic': 'small local ONNX models only, never the VLM'}}
    if not python.is_file() or not helper.is_file():
        return {**base, 'ok': False, 'installed': False,
                'error': {'code': 'document_engine_unavailable', 'message': 'The local MinerU runtime is not installed in this DeepSteam folder.'}}
    try:
        completed = subprocess.run([str(python), '-I', '-B', str(helper), '--verify-vlm' if verify else '--health'],
                                   stdin=subprocess.DEVNULL, capture_output=True, env=child_environment(),
                                   timeout=240 if verify else 90,
                                   **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
        value = json.loads(completed.stdout.decode('utf-8') or '{}')
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {**base, 'ok': False, 'installed': True,
                'error': {'code': 'document_engine_check_failed', 'message': type(exc).__name__}}
    return {**base, 'installed': True, **(value if isinstance(value, dict) else {})}


def pdf_subset(source, directory, first, end):
    """Copy at most eight physical pages without editing the original PDF."""
    import pymupdf
    subset = assert_plain_path(directory / 'source-pages.pdf')
    if not subset.is_file():
        temporary = directory / (uuid.uuid4().hex[:12] + '.pdf')
        try:
            with pymupdf.open(source) as original, pymupdf.open() as target:
                if not 0 <= first < end <= len(original) or end - first > 8:
                    raise ValueError('document_page_range_invalid')
                target.insert_pdf(original, from_page=first, to_page=end - 1)
                target.save(temporary, garbage=3, deflate=True)
            os.replace(temporary, subset)
        finally:
            temporary.unlink(missing_ok=True)
    with subset.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return subset, digest


def remap_pdf_batch(parsed, first, end, original_hash):
    subset_hash = parsed['source_sha256']
    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        output = {key: visit(item) for key, item in value.items()}
        locator = value.get('locator')
        if isinstance(locator, dict) and 'page' in locator:
            page = locator['page']
            if type(page) is not int or not 1 <= page <= end - first:
                raise ValueError('document_page_mapping_invalid')
            output['locator'] = {**locator, 'page': page + first, 'page_idx': page + first - 1}
        return output
    result = visit(parsed)
    for unit in result['units']:
        if 'page' not in unit.get('locator', {}):
            raise ValueError('document_page_mapping_missing')
        unit['unit_index'] = unit['locator']['page']
        unit['page_idx'] = unit['locator']['page_idx']
    result.update(source_sha256=original_hash, source_subset_sha256=subset_hash,
                  source_page_start=first, source_page_end=end)
    result['coverage'] = {**result.get('coverage', {}), 'scope': 'source_page_range',
                          'subset_fully_processed': result.get('coverage', {}).get('full_document', False),
                          'full_document': False, 'source_page_start': first + 1, 'source_page_end': end}
    return result


def needs_structure(value):
    return any(row.get('extraction') in {'ocr', 'text+ocr', 'visual_only'} or row.get('status') in {'needs_ocr', 'partial'}
               or row.get('equations') or row.get('table')
               or any(mark in row.get('text', '') for mark in ('∫', '∑', '√', '≠', '≤', '≥', '∂'))
               for row in value.get('units', []))


def is_structured_cursor(token):
    # The ordinary cursor validator reports malformed input with guidance.
    return (reader.cursor_payload(token) or {}).get('engine') == 'mineru'


def structured_cursor(token):
    return reader.cursor_payload(token) or {}


def restart_failure(code, reason, index):
    """Reject a stale cursor without serving misaligned text, and say exactly
    how to continue: re-reading the unit from its start never skips content."""
    unit = index + 1
    return failure(code, f'{reason} Continue with start_unit={unit} (no cursor) to re-read unit {unit} from its beginning.',
                   restart_start_unit=unit)


def merge_spans(spans):
    merged = []
    for begin, end in sorted(spans):
        if merged and begin <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([begin, end])
    return merged


def located_window(parsed, request, original, destination):
    """Keep the reader's original units/cursor/asset ids; add structured evidence.

MinerU block counts are not physical PDF page counts. Join by source locator,
not by block index. Unsupported Office mappings remain explicit partial data.
"""
    units = []
    budget = reader.bounded_int(request.get('max_chars'), 12000, 256, 100000)
    remaining = budget
    start, offset = reader.cursor_decode(request.get('cursor'), parsed['source_sha256'])
    signature = hashlib.sha256()
    for unit in parsed['units']:
        signature.update(_dump([unit.get('locator', {}), unit.get('text', '')]).encode())
    text_version = signature.hexdigest()
    if is_structured_cursor(request.get('cursor')):
        previous_cursor = structured_cursor(request['cursor'])
        crossing_batch = (offset == 0 and start == previous_cursor.get('batch_end')
                          and start == parsed.get('source_page_start'))
        if previous_cursor.get('text_version') != text_version and not crossing_batch:
            return restart_failure('document_structure_changed', 'The advanced parser result changed since this cursor was issued.', start)
    if offset and not is_structured_cursor(request.get('cursor')):
        return restart_failure('document_cursor_engine_changed', 'This cursor came from the built-in reader, not the advanced parser.', start)
    if request.get('start_unit'):
        start = request['start_unit'] - 1
    index = start
    portable_pages = original.get('format') in {'pdf', 'pptx'} | IMAGE_FORMATS
    mapped = 0
    for prior in original.get('units', []):
        if units:
            remaining -= 2  # The two-character separator also uses the budget.
        if remaining <= 0:
            break
        locator = prior.get('locator') or {}
        matches = [unit for unit in parsed['units'] if unit.get('locator') == locator
                   or (portable_pages and unit.get('locator', {}).get('page') == locator.get('page', locator.get('slide', locator.get('image'))))]
        # Logical Office sections cannot be equated to paragraphs or printed
        # pages. Keep the proven builtin stream when no exact mapping exists.
        if not portable_pages or not matches:
            if is_structured_cursor(request.get('cursor')):
                return failure('document_structure_mapping_missing', f'The structured result has no verified mapping for unit {index + 1}. Continue with start_unit={index + 1} and engine=builtin.',
                               restart_start_unit=index + 1)
            return {**original, 'engine': 'builtin', 'structure_engine': 'mineru', 'status': 'partial',
                    'coverage': {**original.get('coverage', {}), 'text_extraction_complete': False,
                                 'unresolved': sorted(set(original.get('coverage', {}).get('unresolved', [])) | {'structure_mapping_unverified'})},
                    'warnings': [*original.get('warnings', []), 'Advanced parsing is retained. This location has no verified page mapping; continue chunked reading of the original extraction.']}
        text = '\n\n'.join(str(item.get('text') or '') for item in matches)
        if not text.strip():
            text = prior.get('text', '')
        if offset > len(text):
            return restart_failure('document_structure_cursor_invalid', 'The advanced pagination position no longer fits this unit.', index)
        end = min(len(text), offset + remaining)
        equations = [item if item.get('format') else {'format': 'latex', 'text': item.get('content', ''),
            'status': 'partial', 'source_format': 'mineru'} for unit in matches for item in unit.get('equations', []) if isinstance(item, dict)]
        tables = [table for unit in matches for table in ([unit['table']] if unit.get('table') else unit.get('tables', []))]
        metadata = {'equations': equations, **({'table': tables[0], 'tables': tables} if tables else {})}
        # Structural metadata must not circumvent the text response budget.
        fragmented = bool(offset or end < len(text) or len(_dump(metadata)) > budget)
        if fragmented:
            metadata = {'equations': [], 'tables': []}
        row = {**prior, 'text': text[offset:end], 'char_start': offset, 'char_end': end, 'total_chars': len(text),
                      'unit_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                      'unit_index': index + 1, 'truncated_unit': end < len(text),
                      'extraction': 'mineru', 'status': 'partial' if any(m.get('status') == 'partial' for m in matches) else 'ready',
                      **metadata,
                      'coverage': {'text_method': 'mineru', 'visual_assets': len(prior.get('assets', [])),
                                   'unresolved': sorted({code for m in matches for code in m.get('coverage', {}).get('unresolved', [])}),
                                   'visual_review_required': True, 'structure_extracted': True,
                                   'structured_content': 'fragmented' if fragmented else 'returned'},
                      'structure_source': {'engine': 'mineru', 'source_sha256': parsed['source_sha256']}}
        if fragmented:
            row.pop('table', None)
        if not text.strip() and prior.get('assets'):
            row['status'] = 'needs_ocr'
            row['coverage']['unresolved'].append('visual_content_requires_review')
        units.append(row)
        mapped += 1
        remaining -= end - offset
        if end < len(text):
            offset = end
            break
        index, offset = index + 1, 0
    truncated = index < original['document']['unit_count']
    cursor = base64.urlsafe_b64encode(_dump({'v': reader.SCHEMA_VERSION, 'sha256': parsed['source_sha256'],
        'index': index, 'offset': offset, 'engine': 'mineru', 'text_version': text_version,
        'batch_end': parsed.get('source_page_end'),
        **({'tier': request['tier']} if request.get('tier') in MINERU_TIERS else {})}).encode()).decode() if truncated else None
    advanced_warnings = [item if isinstance(item, str) else str(item.get('message') or 'Some advanced parsing regions need verification. View the original images.')
                         for item in parsed.get('warnings', []) if isinstance(item, (str, dict))]
    warnings = list(dict.fromkeys([*original.get('warnings', []), *advanced_warnings,
                                  'Advanced parsing retains original page images for checking formulas, tables, and figures.']))
    return {**original, 'engine': 'mineru', 'engine_version': parsed.get('engine_version'),
            'status': 'partial' if truncated or parsed.get('status') == 'partial' or any(r['status'] in {'partial', 'needs_ocr'} for r in units) else 'ready',
            'navigation': reader.navigation(original['document']['unit_count'], units, truncated, index, offset, cursor),
            'truncated': truncated, 'next_cursor': cursor, 'next_start_unit': index + 1 if truncated else None,
            'units': units, 'text': '\n\n'.join(row['text'] for row in units), 'warnings': warnings,
            'coverage': {**original.get('coverage', {}), 'structure_engine': 'mineru',
                         'document_fully_read': start == 0 and not request.get('cursor') and not truncated,
                         'returned_unit_count': len(units), 'structure_mapped_units': mapped,
                         'structure_page_range': [parsed.get('source_page_start', 0) + 1, parsed.get('source_page_end', original['document']['unit_count'])],
                         'returned_locators': [r['locator'] for r in units],
                         'text_extraction_complete': not truncated and not any(r['status'] in {'partial', 'needs_ocr'} or r['coverage']['unresolved'] for r in units),
                         'unresolved': sorted({c for r in units for c in r['coverage']['unresolved']}),
                         'semantic_completeness': 'not_guaranteed'}}


def _kill_tree(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        executable = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'System32/taskkill.exe'
        subprocess.run([str(executable), '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000, timeout=15)
    else:
        import signal
        os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        process.kill()
    process.wait(timeout=15)


def _child_guard(process):
    """Kill descendants if the dispatcher itself crashes (Windows Job Object)."""
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                    ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
                    ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]; kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended(); info.basic.flags = 0x2000
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle, int(process._handle)):
        if handle:
            kernel.CloseHandle(handle)
        _kill_tree(process)
        raise OSError('document_process_isolation_failed')
    return lambda: kernel.CloseHandle(handle)


def handle(request, *, test_root=None, python=None):
    try:
        if not isinstance(request, dict) or set(request) - (FIELDS | {'root', 'action', 'wait_seconds', 'limit', 'refresh', 'coverage_cursor', 'paths', 'cancel'}):
            raise ValueError('document_request_invalid')
        root = request.get('root')
        action = request.get('action', 'read')
        if action == 'engine_status':
            return engine_status(verify=request.get('refresh') is True)
        if action != 'inventory':
            # One shared repair point for the Harness tool, DeepTutor and Portal:
            # placeholder cursors, numeric strings and page numbers sent as a
            # cursor must not turn into a permanent "invalid position" loop.
            request = reader.normalize_read_request(request)
        payload = {k: v for k, v in request.items() if k in FIELDS}
        if action == 'inventory':
            from integration.workspace_document_inventory import InventoryStore
            return InventoryStore(test_root=test_root).page(root, {k: v for k, v in request.items() if k in {'path', 'cursor', 'limit', 'refresh'}})
        jobs = DocumentJobs(test_root=test_root, python=python)
        if action == 'coverage':
            return jobs.coverage(root, {k: v for k, v in request.items() if k in FIELDS | {'limit', 'coverage_cursor'}})
        if action == 'asset':
            # Original images never wait behind a heavy parse. They are still
            # read through the same confined, SHA-bound reader contract.
            return jobs.asset(root, payload)
        if action in {'status', 'cancel'}:
            value = jobs.status(root, payload, cancel=action == 'cancel')
            if action == 'status' and value.get('job_status') in {'queued', 'waiting'}:
                # Polling also restarts a lane that stopped unexpectedly.
                jobs._kick('parse' if value['job_status'] == 'waiting' else 'read')
            return value
        if action == 'prepare':
            return jobs.prepare(root, request)
        if action == 'queue':
            return jobs.queue(root, request)
        if action != 'read':
            raise ValueError('document_action_invalid')
        try:
            seconds = float(request.get('wait_seconds', 20))
        except (TypeError, ValueError):
            seconds = 20
        return jobs.wait(root, payload, seconds if seconds == seconds else 20)
    except reader.ReaderError as exc:
        return failure(exc.code, exc.message)
    except (ValueError, OSError, sqlite3.Error):
        return failure('document_request_invalid', 'The source path or reading service is unavailable. Select the source again and retry.')
