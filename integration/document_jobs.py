"""Durable local document work shared by all product entry points.

The caller supplies a server-authorized root, never an arbitrary model command.
SQLite owns requests/results; an OS file lock owns the single heavy worker.
Waiting clients may disappear without killing a job. Explicit cancellation is
separate and the worker only advances after its child has actually exited.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
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
# Local MinerU tiers. advanced and standard run the locally installed MinerU2.5
# VLM through llama.cpp on this computer; basic runs only the small ONNX models
# and is used only when a caller asks for it explicitly. An explicit
# engine=mineru request defaults to advanced; an automatic upgrade from
# engine=auto defaults to the faster standard tier.
MINERU_TIERS = {'basic', 'standard', 'advanced'}
DEFAULT_MINERU_TIER = 'advanced'
DEFAULT_AUTO_TIER = 'standard'
# CPU VLM inference is slow, so VLM tiers parse smaller physical-page batches
# (earlier first results) with a longer per-batch limit.
MINERU_BATCH_PAGES = {'basic': 8, 'standard': 6, 'advanced': 4}
MINERU_TIMEOUT_SECONDS = {'basic': 1800, 'standard': 3600, 'advanced': 3600}


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
            ''')
            db.execute('BEGIN IMMEDIATE')
            if 'unresolved' not in {row[1] for row in db.execute('PRAGMA table_info(documents)')}:
                db.execute("ALTER TABLE documents ADD COLUMN unresolved TEXT NOT NULL DEFAULT '[]'")

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
                db.execute("UPDATE jobs SET status='queued',cancel_requested=0,result=NULL,stage='queued',updated=? WHERE id=?", (now, row['id']))
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
                if row['status'] == 'queued':
                    self._finish(db, row['id'], failure('document_cancelled', 'Reading stopped.'), 'cancelled')
                row = db.execute('SELECT * FROM jobs WHERE id=?', (row['id'],)).fetchone()
            return self._view(row)

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

    def _view(self, row):
        common = {'job_id': row['id'], 'job_status': row['status'], 'stage': row['stage'], 'attempt': row['attempt']}
        if row['result']:
            path = assert_plain_path(self.cache / row['result'])
            if not path.is_relative_to(self.cache) or not path.is_file():
                return failure('document_cache_missing', 'The result needs recovery. Read again to resume.', retryable=True, **common)
            value = json.loads(path.read_text(encoding='utf-8'))
            return {**value, **common}
        return {'ok': True, 'status': row['status'], 'retry_after_ms': 500, **common}

    def ensure_worker(self):
        if not self.python.is_file():
            raise OSError('document_runtime_unavailable')
        argv = [str(self.python), '-I', '-B', str(ROOT / 'scripts/document_job_worker.py'), '--drain']
        if self.test_root:
            argv += ['--test-root', self.test_root]
        # No pipes inherited from a waiting HTTP client. Losing that client
        # does not terminate the owned document queue.
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=child_environment(), close_fds=True,
                         **({'creationflags': 0x08000000} if os.name == 'nt' else {'start_new_session': True}))
        threading.Thread(target=process.wait, name='document-dispatcher-reaper', daemon=True).start()

    def wait(self, root, payload, seconds=20):
        value = self.submit(root, payload)
        if value.get('status') not in {'queued', 'running'}:
            return value
        self.ensure_worker()
        deadline = time.monotonic() + min(20, max(0, seconds))
        query = {'path': payload['path'], 'job_id': value['job_id']}
        while time.monotonic() < deadline:
            time.sleep(.15)
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
        lock_path = assert_plain_path(self.directory / 'worker.lock')
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
        with self.worker_lock() as acquired:
            if not acquired:
                return
            with self.connect() as db:
                # OS lock proves no former dispatcher survives. Completed
                # cache entries remain; only interrupted work is resumed.
                db.execute("UPDATE jobs SET status='queued',stage='recovering',updated=? WHERE status='running'", (time.time(),))
            while True:
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created,id LIMIT 1").fetchone()
                    if row is None:
                        return
                    db.execute("UPDATE jobs SET status='running',stage='reading',attempt=attempt+1,updated=? WHERE id=?", (time.time(), row['id']))
                try:
                    if self.cancelled(row['id']):
                        value = failure('document_cancelled', 'Reading stopped.')
                    else:
                        value = self._execute(row)
                except Exception as exc:
                    code = exc.code if isinstance(exc, reader.ReaderError) else 'document_worker_failed'
                    value = failure(code, 'Reading is incomplete. Read again to resume.', retryable=True)
                with self.connect() as db:
                    if self.cancelled(row['id']):
                        value = failure('document_cancelled', 'Reading stopped.')
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
        if isinstance(value, dict) and value.get('ok') is False and value.get('engine') == 'mineru':
            code = value.get('error', {}).get('code', 'parse_failed')
            detail = str(value.get('error', {}).get('message') or '')[:600]
            message = ('The source changed. Read it again.' if code == 'source_changed' else
                       'The local MinerU VLM cannot run on this computer: ' + detail + ' No remote service was used.' if code == 'vlm_unavailable' else
                       'The local MinerU parser is not ready. Repair the installation; the original remains available. No remote service was used.' if code in {'parser_not_configured', 'parser_asset_missing'} else
                       'Local MinerU parsing is incomplete. Retry or view the original images. No remote service was used.')
            return {**value, 'error': {'code': code, 'message': message, 'retryable': code == 'parse_failed'}}
        return value if isinstance(value, dict) else failure('document_result_invalid', 'The reading result is invalid. Retry.')

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
        pages = MINERU_BATCH_PAGES[tier]
        pdf_batch = lightweight.get('format') == 'pdf'
        first, _ = reader.cursor_decode(request.get('cursor'), row['source_hash'])
        if request.get('start_unit'):
            first = request['start_unit'] - 1
        batch_start = first // pages * pages if pdf_batch else 0
        batch_end = min(batch_start + pages, lightweight['document']['unit_count']) if pdf_batch else None
        cache_key = hashlib.sha256(_dump([row['scope'], row['source_hash'], tier, batch_start, batch_end,
            'physical-pdf-batch-v2', hashlib.sha256(helper.read_bytes()).hexdigest()]).encode()).hexdigest()
        container = self.cache / ('mineru-' + cache_key)
        self.storage.prepare(container)
        manifest = container / 'normalized.json'
        if manifest.is_file():
            parsed = json.loads(assert_plain_path(manifest).read_text('utf-8'))
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
                if pdf_batch:
                    parsed = remap_pdf_batch(parsed, batch_start, batch_end, row['source_hash'])
                self._source(request['root'], {'path': request['path'], 'document_sha256': row['source_hash']})
                _atomic_json(manifest, parsed)
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
                'advanced': 'local MinerU2.5 VLM, two-step extraction with image analysis (default for engine=mineru)',
                'standard': 'local MinerU2.5 VLM with hybrid layout (default for automatic upgrades from engine=auto)',
                'basic': 'small local ONNX models only, no VLM (explicit request only)'}}
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
    portable_pages = original.get('format') in {'pdf', 'pptx'}
    mapped = 0
    for prior in original.get('units', []):
        if units:
            remaining -= 2  # The two-character separator also uses the budget.
        if remaining <= 0:
            break
        locator = prior.get('locator') or {}
        matches = [unit for unit in parsed['units'] if unit.get('locator') == locator
                   or (portable_pages and unit.get('locator', {}).get('page') == locator.get('page', locator.get('slide')))]
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
        if not isinstance(request, dict) or set(request) - (FIELDS | {'root', 'action', 'wait_seconds', 'limit', 'refresh', 'coverage_cursor'}):
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
            return jobs.status(root, payload, cancel=action == 'cancel')
        if action != 'read':
            raise ValueError('document_action_invalid')
        return jobs.wait(root, payload, request.get('wait_seconds', 20))
    except reader.ReaderError as exc:
        return failure(exc.code, exc.message)
    except (ValueError, OSError, sqlite3.Error):
        return failure('document_request_invalid', 'The source path or reading service is unavailable. Select the source again and retry.')
