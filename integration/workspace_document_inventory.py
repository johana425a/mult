"""Bounded, durable file catalogues for large authorized workspaces.

This catalog contains metadata only. Actual reads revalidate the source and
record the content hash in the document job ledger. A finished catalogue is
never represented as finished reading.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import threading
import time
import uuid

from scripts.storage_paths import assert_plain_path, select_storage
from scripts.workspace_document_reader import SUPPORTED_FORMATS

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = frozenset({'.git', 'node_modules', '.deeptutor', '__pycache__',
                           '.dsh', '.codex', '.ssh'})
REPARSE = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
SCAN_BATCH = 250
_iterators = {}
_lock = threading.RLock()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class InventoryStore:
    def __init__(self, test_root=None):
        state = assert_plain_path(Path(test_root)) if test_root else select_storage(ROOT).state_root
        directory = assert_plain_path(state / 'runtime/document-jobs')
        directory.mkdir(parents=True, exist_ok=True)
        self.database = assert_plain_path(directory / 'inventory.sqlite')
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS inventories (
                    id TEXT PRIMARY KEY,scope TEXT NOT NULL,created REAL NOT NULL,
                    complete INTEGER NOT NULL DEFAULT 0,skipped INTEGER NOT NULL DEFAULT 0,
                    unavailable INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS inventory_scope ON inventories(scope,created);
                CREATE TABLE IF NOT EXISTS directories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,inventory TEXT NOT NULL,
                    path TEXT NOT NULL,offset INTEGER NOT NULL DEFAULT 0,
                    done INTEGER NOT NULL DEFAULT 0,UNIQUE(inventory,path));
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,inventory TEXT NOT NULL,
                    path TEXT NOT NULL,kind TEXT NOT NULL,bytes INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,supported INTEGER NOT NULL,
                    UNIQUE(inventory,path));
                CREATE INDEX IF NOT EXISTS inventory_entries ON entries(inventory,id);
            ''')
            if 'unavailable' not in {row[1] for row in db.execute('PRAGMA table_info(inventories)')}:
                db.execute('ALTER TABLE inventories ADD COLUMN unavailable INTEGER NOT NULL DEFAULT 0')
            db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', ('cursor_key', os.urandom(32).hex()))
            self.secret = bytes.fromhex(db.execute('SELECT value FROM metadata WHERE key=?', ('cursor_key',)).fetchone()[0])

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=20)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA busy_timeout=20000')
            with db:
                yield db
        finally:
            db.close()

    def _scope(self, trustedroot, raw):
        root = assert_plain_path(Path(trustedroot))
        if not root.is_dir():
            raise ValueError('The workspace folder does not exist. Select it again.')
        if not isinstance(raw, str) or len(raw) > 4096 or '\x00' in raw:
            raise ValueError('The directory scope is invalid.')
        path = PurePosixPath(raw.replace('\\', '/'))
        if path.is_absolute() or any(part == '..' or ':' in part for part in path.parts):
            raise ValueError('The directory scope must remain inside the selected workspace.')
        if any(part.casefold() in EXCLUDED_DIRS for part in path.parts):
            raise ValueError('This directory is outside the document scan scope.')
        folder = assert_plain_path(root.joinpath(*path.parts))
        if not folder.is_relative_to(root) or not folder.is_dir():
            raise ValueError('The directory scope must be a folder in the workspace.')
        relative = folder.relative_to(root).as_posix()
        scope = hashlib.sha256((os.path.normcase(str(root)) + '\0' + relative).encode()).hexdigest()
        return root, relative, scope

    def _encode(self, inventory, scope, offset):
        raw = _json({'v': 1, 'id': inventory, 'scope': scope, 'offset': offset}).encode()
        return base64.urlsafe_b64encode(raw + hmac.digest(self.secret, raw, 'sha256')).decode().rstrip('=')

    def _decode(self, cursor, scope):
        try:
            if not isinstance(cursor, str) or len(cursor) > 1024:
                raise ValueError()
            data = base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4))
            raw, signature = data[:-32], data[-32:]
            if not hmac.compare_digest(signature, hmac.digest(self.secret, raw, 'sha256')):
                raise ValueError()
            value = json.loads(raw)
            if (value.get('v') != 1 or value.get('scope') != scope or
                    type(value.get('offset')) is not int or value['offset'] < 0):
                raise ValueError()
            return value['id'], value['offset']
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise ValueError('The document catalog cursor is invalid. Scan again.') from None

    def _scan(self, db, inventory, root):
        """Advance at most 250 directory entries, never load a full tree."""
        remaining = SCAN_BATCH
        while remaining:
            row = db.execute('SELECT * FROM directories WHERE inventory=? AND done=0 ORDER BY id LIMIT 1',
                             (inventory,)).fetchone()
            if row is None:
                db.execute('UPDATE inventories SET complete=1 WHERE id=?', (inventory,))
                break
            key = (str(self.database), inventory, row['id'])
            try:
                folder = assert_plain_path(root / row['path'])
                cached = _iterators.pop(key, None)
                stream = cached[1] if cached and cached[0] == row['offset'] else None
                if cached and stream is None:
                    cached[1].close()
                if stream is None:
                    stream = os.scandir(folder)
                    # A process restart resumes its checkpoint. In-process calls
                    # keep the iterator, so large individual folders stay linear.
                    for _ in range(row['offset']):
                        if next(stream, None) is None:
                            break
                offset = row['offset']
                while remaining:
                    item = next(stream, None)
                    if item is None:
                        stream.close()
                        db.execute('UPDATE directories SET done=1 WHERE id=?', (row['id'],))
                        break
                    offset += 1
                    remaining -= 1
                    relative = (PurePosixPath(row['path']) / item.name).as_posix()
                    try:
                        info = item.stat(follow_symlinks=False)
                        forbidden = stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & REPARSE
                        if forbidden or (stat.S_ISDIR(info.st_mode) and item.name.casefold() in EXCLUDED_DIRS):
                            db.execute('UPDATE inventories SET skipped=skipped+1 WHERE id=?', (inventory,))
                        elif stat.S_ISDIR(info.st_mode):
                            db.execute('INSERT OR IGNORE INTO directories(inventory,path) VALUES (?,?)', (inventory, relative))
                        elif stat.S_ISREG(info.st_mode):
                            suffix = Path(item.name).suffix.lower()
                            db.execute('''INSERT OR IGNORE INTO entries(inventory,path,kind,bytes,mtime_ns,supported)
                                          VALUES (?,?,?,?,?,?)''',
                                       (inventory, relative, suffix.lstrip('.') or 'file', info.st_size,
                                        info.st_mtime_ns, int(suffix in SUPPORTED_FORMATS)))
                    except (OSError, ValueError):
                        db.execute('UPDATE inventories SET skipped=skipped+1,unavailable=unavailable+1 WHERE id=?', (inventory,))
                    db.execute('UPDATE directories SET offset=? WHERE id=?', (offset, row['id']))
                else:
                    _iterators[key] = (offset, stream)
            except (OSError, ValueError):
                db.execute('UPDATE directories SET done=1 WHERE id=?', (row['id'],))
                db.execute('UPDATE inventories SET skipped=skipped+1,unavailable=unavailable+1 WHERE id=?', (inventory,))
        if db.execute('SELECT 1 FROM directories WHERE inventory=? AND done=0 LIMIT 1', (inventory,)).fetchone() is None:
            db.execute('UPDATE inventories SET complete=1 WHERE id=?', (inventory,))
        # A bounded number of held directory handles; discarded ones resume
        # from the durable offset. No unbounded process cache.
        while len(_iterators) > 32:
            _, cached = _iterators.popitem()
            cached[1].close()

    def page(self, trustedroot, payload):
        try:
            if not isinstance(payload, dict) or set(payload) - {'path', 'cursor', 'limit', 'refresh'}:
                raise ValueError('The document catalog request is invalid.')
            root, relative, scope = self._scope(trustedroot, payload.get('path', '.'))
            limit = payload.get('limit', 100)
            if type(limit) is not int or not 1 <= limit <= 200:
                raise ValueError('Each batch must contain between 1 and 200 sources.')
            cursor = payload.get('cursor')
            if payload.get('refresh') and cursor:
                raise ValueError('A refresh cannot use an old catalog cursor.')
            with _lock, self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if cursor:
                    inventory, offset = self._decode(cursor, scope)
                    row = db.execute('SELECT id FROM inventories WHERE id=? AND scope=?', (inventory, scope)).fetchone()
                    if row is None:
                        raise ValueError('The document catalog is unavailable. Scan again.')
                else:
                    offset = 0
                    row = None if payload.get('refresh') else db.execute(
                        'SELECT id FROM inventories WHERE scope=? ORDER BY created DESC LIMIT 1', (scope,)).fetchone()
                    inventory = row['id'] if row else 'inventory_' + uuid.uuid4().hex
                    if row is None:
                        db.execute('INSERT INTO inventories(id,scope,created) VALUES (?,?,?)', (inventory, scope, time.time()))
                        db.execute('INSERT INTO directories(inventory,path) VALUES (?,?)', (inventory, relative))
                self._scan(db, inventory, root)
                rows = db.execute('SELECT * FROM entries WHERE inventory=? AND id>? ORDER BY id LIMIT ?',
                                  (inventory, offset, limit)).fetchall()
                last = rows[-1]['id'] if rows else offset
                state = db.execute('SELECT complete,skipped,unavailable FROM inventories WHERE id=?', (inventory,)).fetchone()
                total = db.execute('SELECT count(*) FROM entries WHERE inventory=?', (inventory,)).fetchone()[0]
                more = db.execute('SELECT 1 FROM entries WHERE inventory=? AND id>? LIMIT 1', (inventory, last)).fetchone()
                next_cursor = self._encode(inventory, scope, last) if more or not state['complete'] else None
                return {'ok': True, 'status': 'ready' if next_cursor is None else 'scanning',
                        'inventory_id': inventory, 'entries': [
                            {field: bool(row[field]) if field == 'supported' else row[field]
                             for field in ('path', 'kind', 'bytes', 'mtime_ns', 'supported')} for row in rows],
                        'next_cursor': next_cursor, 'catalog_complete': bool(state['complete']),
                        'total_discovered': total, 'skipped_entries': state['skipped'],
                        'excluded_entries': state['skipped'] - state['unavailable'],
                        'unavailable_entries': state['unavailable'],
                        'reading_complete': False}
        except (ValueError, OSError, sqlite3.Error) as error:
            return {'ok': False, 'status': 'error', 'error': {'code': 'inventory_unavailable',
                    'message': str(error) if isinstance(error, ValueError) else 'The document catalog is incomplete. Continue scanning shortly.',
                    'retryable': not isinstance(error, ValueError)}}
