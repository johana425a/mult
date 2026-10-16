"""Resumable complete-document assembly over the shared bounded page queue.

The assembly worker is not another parser slot. It consumes the one shared
heavy queue, keeping its original and completed aggregate when HTTP disappears.
Owner scope is selected by the server, never from public extractor settings.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid

from integration.document_jobs import DocumentJobs, ROOT, _atomic_json, _dump, child_environment, failure
from integration import shared_document_extraction as shared
from scripts.storage_paths import assert_plain_path

MAX_OUTPUT = 128 * 1024 * 1024


class DocumentIngestions:
    def __init__(self, *, test_root=None, python=None):
        self.jobs = DocumentJobs(test_root=test_root, python=python)
        self.cache = self.jobs.cache / 'ingestions'
        self.jobs.storage.prepare(self.cache)
        with self.jobs.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS ingestions (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, source_hash TEXT NOT NULL,
                source TEXT NOT NULL, options TEXT NOT NULL, status TEXT NOT NULL,
                updated REAL NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
                result TEXT)''')

    def prepare(self, source, owner_scope, include_assets=True, ingestion_id=None):
        if not isinstance(owner_scope, str) or not 1 <= len(owner_scope) <= 256 or any(ord(c) < 32 for c in owner_scope):
            raise ValueError('document_owner_invalid')
        source = assert_plain_path(Path(source))
        if source.suffix.lower() not in shared.SUPPORTED_FORMATS or not source.is_file() or not 0 < source.stat().st_size <= 200 * 1024 * 1024:
            raise ValueError('document_source_invalid')
        with source.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        scope = hashlib.sha256(owner_scope.encode()).hexdigest()
        # One combined digest keeps Windows paths short without collapsing
        # owner isolation (the full scope and source digest stay in SQLite).
        directory = self.cache / 'sources' / hashlib.sha256((scope + digest).encode()).hexdigest()
        self.jobs.storage.prepare(directory)
        retained = assert_plain_path(directory / ('source' + source.suffix.lower()))
        intact = False
        if retained.is_file():
            with retained.open('rb') as stream:
                intact = hashlib.file_digest(stream, 'sha256').hexdigest() == digest
        if not intact:
            temporary = directory / (uuid.uuid4().hex + '.upload')
            try:
                shutil.copyfile(source, temporary)
                with temporary.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                        raise ValueError('document_source_changed')
                os.replace(temporary, retained)
            finally:
                temporary.unlink(missing_ok=True)
        options = {'include_assets': bool(include_assets)}
        signature = shared.reader_signature() + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        identity = hashlib.sha256(_dump([scope, digest, retained.suffix, options, signature]).encode()).hexdigest()[:32]
        if ingestion_id is not None and ingestion_id != identity:
            raise ValueError('document_ingestion_scope_invalid')
        with self.jobs.connect() as db:
            db.execute("INSERT OR IGNORE INTO ingestions(id,scope,source_hash,source,options,status,updated) VALUES(?,?,?,?,?,'queued',?)",
                       (identity, scope, digest, str(retained.relative_to(self.jobs.cache)), _dump(options), time.time()))
            row = db.execute('SELECT * FROM ingestions WHERE id=?', (identity,)).fetchone()
            if ingestion_id is None and (row['status'] in {'failed', 'cancelled'} or row['result'] and not (self.cache / row['result']).is_file()):
                db.execute("UPDATE ingestions SET status='queued',cancel_requested=0,result=NULL,updated=? WHERE id=?", (time.time(), identity))
        return identity

    def _row(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity):
            raise ValueError('document_ingestion_invalid')
        with self.jobs.connect() as db:
            row = db.execute('SELECT * FROM ingestions WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('document_ingestion_unknown')
        return row

    def view(self, identity):
        row = self._row(identity)
        recovery = {'ingestion_id': identity, 'source_ref': hashlib.sha256((row['scope'] + row['source_hash']).encode()).hexdigest(),
                    'document_sha256': row['source_hash']}
        if row['result']:
            result = assert_plain_path(self.cache / row['result'])
            if not result.is_relative_to(self.cache) or not result.is_file() or result.stat().st_size > MAX_OUTPUT:
                return {'ok': False, 'status': 'error', 'error': 'The document result needs recovery. Read it again to resume.', 'recovery': recovery}
            return {**json.loads(result.read_text('utf-8')), 'recovery': recovery}
        return {'ok': False, 'status': row['status'], 'retry_after_ms': 500, 'recovery': recovery,
                'message': 'The document is queued or being read. Its task and original file are retained.'}

    def wait(self, identity, *, seconds=20):
        value = self.view(identity)
        if value.get('status') not in {'queued', 'running'}:
            return value
        arguments = [str(self.jobs.python), '-I', '-B', str(ROOT / 'scripts/openmaic_document_extract.py'), '--ingest', identity]
        if self.jobs.test_root:
            arguments += ['--test-root', self.jobs.test_root]
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=child_environment(), close_fds=True,
            **({'creationflags': 0x08000000} if os.name == 'nt' else {'start_new_session': True}))
        threading.Thread(target=process.wait, daemon=True, name='document-ingestion-reaper').start()
        deadline = time.monotonic() + min(20, max(0, seconds))
        while time.monotonic() < deadline:
            time.sleep(.15)
            value = self.view(identity)
            if value.get('status') not in {'queued', 'running'}:
                return value
        return value

    @contextlib.contextmanager
    def lock(self, identity=None):
        if identity is not None:
            self._row(identity)
        directory = self.cache / identity if identity else self.cache
        self.jobs.storage.prepare(directory)
        stream = assert_plain_path(directory / 'worker.lock').open('a+b')
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        held = False
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = True
        except OSError:
            pass
        try:
            yield held
        finally:
            if held:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)
            stream.close()

    def cancel(self, identity):
        row = self._row(identity)
        source = self._source(row)
        scope, _, _, _ = self.jobs._source(source.parent, {'path': source.name})
        with self.jobs.connect() as db:
            if row['status'] not in {'ready', 'partial', 'failed', 'cancelled'}:
                db.execute('UPDATE ingestions SET cancel_requested=1,updated=? WHERE id=?', (time.time(), identity))
                others = db.execute("SELECT COUNT(*) FROM ingestions WHERE id<>? AND source=? AND status IN ('queued','running') AND cancel_requested=0", (identity, row['source'])).fetchone()[0]
                if not others:
                    db.execute("UPDATE jobs SET cancel_requested=1,stage='cancelling',updated=? WHERE scope=? AND status IN ('queued','running')", (time.time(), scope))
                if row['status'] == 'queued':
                    self._finish(identity, {'ok': False, 'status': 'cancelled', 'error': 'Reading stopped. The original file is retained.'}, db=db)
        return self.view(identity)

    def _source(self, row):
        source = assert_plain_path(self.jobs.cache / row['source'])
        if not source.is_relative_to(self.cache / 'sources'):
            raise ValueError('document_ingestion_source_invalid')
        with source.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != row['source_hash']:
                raise ValueError('document_source_changed')
        return source

    def _finish(self, identity, result, *, db=None):
        relative = identity + '/result.json'
        self.jobs.storage.prepare(self.cache / identity)
        if len(_dump(result).encode()) > MAX_OUTPUT:
            result = {'ok': False, 'status': 'error', 'error': 'The full document exceeds the application limit. Split it and retry.'}
        _atomic_json(self.cache / relative, result)
        state = result.get('status', 'ready') if result.get('ok') else 'cancelled' if result.get('status') == 'cancelled' else 'failed'
        def update(connection):
            connection.execute('UPDATE ingestions SET status=?,result=?,updated=? WHERE id=?', (state, relative, time.time(), identity))
        if db is not None:
            update(db)
        else:
            with self.jobs.connect() as connection:
                update(connection)

    def run(self, identity):
        with self.lock(identity) as held:
            if not held:
                return
            row = self._row(identity)
            if row['result']:
                return
            with self.jobs.connect() as db:
                db.execute("UPDATE ingestions SET status='running',updated=? WHERE id=?", (time.time(), identity))
            try:
                if row['cancel_requested']:
                    raise shared.SharedDocumentError('Reading stopped.')
                source = self._source(row)
                shared.runtime_paths = lambda: (self.jobs.python, ROOT / 'scripts/workspace_document_reader.py')
                result = shared.extract_document(source, **json.loads(row['options']),
                    cancelled=lambda: bool(self._row(identity)['cancel_requested']))
                self._source(row)
                coverage = result.get('coverage') or {}
                # The default reader enumerates every source unit and delivers
                # the text layer plus original pixels. It does not claim that
                # pending scans/figures have already been recognized by a model.
                image_ready = (result.get('requires_image_reading') is True
                    and coverage.get('source_units_enumerated') is True
                    and coverage.get('text_layer_complete') is True
                    and bool(result.get('images')))
                if (result.get('document', {}).get('sha256') != row['source_hash']
                        or (coverage.get('document_fully_read') is not True and not image_ready)):
                    raise shared.SharedDocumentError('Document reading is incomplete. The original and task are retained.')
                images = [{k: v for k, v in image.items() if k != 'data'} | {'base64': base64.b64encode(image['data']).decode('ascii')}
                          for image in result.get('images', [])]
                result = {**result, 'images': images, 'ok': True}
            except Exception as exc:
                message = str(exc) if isinstance(exc, shared.SharedDocumentError) else 'Reading is incomplete. The original is retained; read again to resume.'
                result = {'ok': False, 'status': 'error', 'error': message}
            if self._row(identity)['cancel_requested']:
                result = {'ok': False, 'status': 'cancelled', 'error': 'Reading stopped. The original file is retained.'}
            self._finish(identity, result)

    def drain(self):
        # Only one complete-document assembler waits on the shared parser at
        # a time; other HTTP calls are short status waiters, not extra engines.
        with self.lock() as held:
            if not held:
                return
            while True:
                with self.jobs.connect() as db:
                    row = db.execute("SELECT id FROM ingestions WHERE status IN ('queued','running') AND result IS NULL ORDER BY updated,id LIMIT 1").fetchone()
                if row is None:
                    return
                self.run(row['id'])
