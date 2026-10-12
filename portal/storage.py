"""Local records and Windows user-bound encryption for user-entered provider keys."""
from __future__ import annotations

import base64
import ctypes
from contextlib import contextmanager
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from integration.local_qwen_defaults import is_local_provider, RETIRED_MODEL_CODE, RETIRED_MODEL_MESSAGE


def retire_local_settings(value):
    """Retire only the old product selection, retaining unrelated saved keys."""
    result = dict(value)
    selection = result.get('connection_selection')
    retired = (selection == 'local' or (selection not in ('current', 'native')
               and not result.get('harness_route_id')
               and (result.get('model_mode') == 'local' or is_local_provider(result))))
    if retired:
        result.update(model_mode='api', connection_selection='unconfigured',
                      selection_required=RETIRED_MODEL_CODE)
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix):
    return prefix + '_' + uuid.uuid4().hex


class _Blob(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(value: str, decrypt=False):
    if not value:
        return ''
    if os.name != 'nt':
        raise RuntimeError('This installation requires Windows DPAPI to store API keys.')
    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buffer = ctypes.create_string_buffer(raw)
    source = _Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    ok = function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        output = ctypes.string_at(result.data, result.length)
        return output.decode('utf-8') if decrypt else base64.b64encode(output).decode('ascii')
    finally:
        kernel32.LocalFree(result.data)


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'learning.sqlite3'
        self._lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS materials (
                id TEXT PRIMARY KEY, title TEXT, filename TEXT, path TEXT,
                text TEXT, char_count INTEGER, page_count INTEGER,
                preview_truncated INTEGER DEFAULT 0, dt_material_id TEXT,
                sync_error TEXT, created_at TEXT);
              CREATE TABLE IF NOT EXISTS lessons (
                id TEXT PRIMARY KEY, title TEXT, material_id TEXT, goal TEXT,
                status TEXT, job_id TEXT, classroom_id TEXT, classroom_url TEXT,
                dt_course_id TEXT, error TEXT, progress TEXT, created_at TEXT,
                updated_at TEXT);
              CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY, lesson_id TEXT, question TEXT, answer TEXT,
                feedback TEXT, status TEXT, error TEXT, dt_session_id TEXT,
                dt_turn_id TEXT, created_at TEXT, updated_at TEXT);
              CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT);
              CREATE TABLE IF NOT EXISTS harness_state (id TEXT PRIMARY KEY, value TEXT);
              CREATE TABLE IF NOT EXISTS harness_secrets (id TEXT PRIMARY KEY, protected TEXT, created_at TEXT);
            ''')
            columns = {r[1] for r in db.execute('PRAGMA table_info(lessons)')}
            for column in ('warning', 'tts_coverage', 'llm_selection', 'resolved_model', 'model_snapshot', 'dt_reading_workspace_id', 'source_snapshot', 'workspace_id', 'job_attempt_id', 'recovery_message'):
                if column not in columns:
                    db.execute(f'ALTER TABLE lessons ADD COLUMN {column} TEXT')
            material_columns = {r[1] for r in db.execute('PRAGMA table_info(materials)')}
            for column in ('source_kind', 'workspace_id', 'relative_path', 'document_sha256', 'source_cursor', 'source_snapshot', 'source_max_units'):
                if column not in material_columns:
                    db.execute(f'ALTER TABLE materials ADD COLUMN {column} TEXT')
            # Existing failed lessons remain failed and get no inferred review
            # link. Only the verified retained-draft path sets these markers.
            if 'review_required' not in columns:
                db.execute('ALTER TABLE lessons ADD COLUMN review_required INTEGER DEFAULT 0')
            if 'source_fidelity' not in columns:
                db.execute('ALTER TABLE lessons ADD COLUMN source_fidelity TEXT')
            if 'retryable' not in columns:
                db.execute('ALTER TABLE lessons ADD COLUMN retryable INTEGER DEFAULT 0')
            # Repair the previous full-form TTS-save bug only for the exact
            # application-owned route tuple. Explicit subsequent selections
            # and unrelated/custom addresses are left untouched.
            setting_row = db.execute('SELECT value FROM settings WHERE id=1').fetchone()
            route_row = db.execute('SELECT value FROM harness_state WHERE id=?', ('current',)).fetchone()
            if setting_row and route_row:
                setting = json.loads(setting_row['value'])
                route = json.loads(route_row['value'])
                if (isinstance(route, dict) and route.get('guard') and 'classroom' in route.get('targets', [])
                        and not setting.get('harness_route_id') and not setting.get('connection_selection')
                        and setting.get('model_mode') == 'api'
                        and str(setting.get('base_url', '')).rstrip('/') == 'http://127.0.0.1:3796/v1'
                        and setting.get('model') == route.get('route_id')):
                    setting.update(harness_route_id=route['route_id'], connection_selection='current')
                    db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(setting),))
            # Migrate transport selection only. Lesson snapshots, historical
            # model labels and encrypted credentials must remain untouched.
            setting_row = db.execute('SELECT value FROM settings WHERE id=1').fetchone()
            if setting_row:
                setting = json.loads(setting_row['value'])
                migrated = retire_local_settings(setting)
                if migrated != setting:
                    db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(migrated),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                yield db
        finally:
            # sqlite's own context manager commits but does not close. An
            # explicit close is needed for repeatable Windows backups/moves.
            db.close()

    def insert(self, table, item):
        if table not in {'materials', 'lessons', 'attempts'}:
            raise ValueError('Unknown table')
        with self._lock, self.connect() as db:
            keys = list(item)
            if table == 'lessons' and item.get('material_id'):
                db.execute('BEGIN IMMEDIATE')
                if not db.execute('SELECT id FROM materials WHERE id=?', (item['material_id'],)).fetchone():
                    raise ValueError('Lesson material is no longer available')
            db.execute(f'INSERT INTO {table} ({",".join(keys)}) VALUES ({",".join("?" for _ in keys)})', [item[k] for k in keys])
        return item

    def delete_material_copy(self, key, uploads):
        """Delete an unreferenced app-owned import, never a source/workspace path."""
        with self._lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM materials WHERE id=?', (key,)).fetchone()
            if row is None:
                return {'id': key, 'deleted': True}
            references = db.execute('SELECT COUNT(*) FROM lessons WHERE material_id=?', (key,)).fetchone()[0]
            if references:
                return {'id': key, 'deleted': False, 'code': 'material_in_use',
                        'error': f'This material is still used by {references} lessons and was preserved. Delete the linked classrooms before deleting the material.'}
            if row['source_kind'] == 'workspace':
                db.execute('DELETE FROM materials WHERE id=?', (key,))
                return {'id': key, 'deleted': True, 'retained_shared': True}
            path = Path(row['path'])
            root = Path(uploads).resolve()
            suffix = path.suffix.lower()
            import re
            ranged = row['source_kind'] == 'upload_range' and re.fullmatch(r'material_[a-f0-9]{32}', path.stem)
            if (suffix not in {'.pdf', '.md', '.txt', '.docx', '.pptx', '.xlsx'} or not (path.name == key + suffix or ranged)
                    or path.is_symlink() or path.resolve().parent != root):
                return {'id': key, 'deleted': False, 'code': 'unowned_path',
                        'error': 'The material file is not an application-managed imported copy. The original file and record were preserved.'}
            # The transaction prevents a new classroom from acquiring a deleted
            # source between this ownership check and removing its row.
            shared_copy = any(Path(other['path']).resolve() == path.resolve()
                              for other in db.execute("SELECT path FROM materials WHERE id<>? AND path IS NOT NULL AND path<>''", (key,)))
            if not shared_copy:
                path.unlink(missing_ok=True)
            db.execute('DELETE FROM materials WHERE id=?', (key,))
            return {'id': key, 'deleted': True, 'retained_shared': bool(row['dt_material_id']) or shared_copy}

    def update(self, table, key, **changes):
        if table not in {'materials', 'lessons', 'attempts'}:
            raise ValueError('Unknown table')
        with self._lock, self.connect() as db:
            if table == 'lessons':
                current = db.execute('SELECT status FROM lessons WHERE id=?', (key,)).fetchone()
                if current and current['status'] == 'deleting':
                    # Late handshake IDs must still be retained for cleanup; normal status cannot revive it.
                    changes = {k: v for k, v in changes.items() if k in {'job_id', 'classroom_id', 'dt_course_id', 'dt_reading_workspace_id', 'error', 'updated_at'}}
                    if not changes:
                        return
            columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
            if not changes or set(changes) - columns:
                raise ValueError('Invalid update fields')
            db.execute(f'UPDATE {table} SET {",".join(k + "=?" for k in changes)} WHERE id=?', [*changes.values(), key])

    def begin_lesson_delete(self, key):
        with self._lock, self.connect() as db:
            row = db.execute('SELECT * FROM lessons WHERE id=?', (key,)).fetchone()
            if row:
                db.execute("UPDATE lessons SET status='deleting', progress=?, error=NULL, updated_at=? WHERE id=?", ('Stopping the task and deleting permanently. Source materials will be preserved.', now(), key))
            return dict(row) if row else None

    def finish_lesson_delete(self, key):
        with self._lock, self.connect() as db:
            db.execute('DELETE FROM attempts WHERE lesson_id=?', (key,))
            db.execute("DELETE FROM lessons WHERE id=? AND status='deleting'", (key,))

    def get(self, table, key):
        if table not in {'materials', 'lessons', 'attempts'}:
            raise ValueError('Unknown table')
        with self.connect() as db:
            row = db.execute(f'SELECT * FROM {table} WHERE id=?', (key,)).fetchone()
            return dict(row) if row else None

    def list(self, table):
        if table not in {'materials', 'lessons', 'attempts'}:
            raise ValueError('Unknown table')
        with self.connect() as db:
            return [dict(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY created_at DESC')]

    def settings(self, secret=False):
        defaults = dict(model_mode='api', base_url='', model='', tts_enabled=True, tts_mode='local', tts_base_url='', tts_model='', tts_voice='', api_key='', tts_api_key='')
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE id=1').fetchone()
        if row:
            saved = retire_local_settings(json.loads(row['value']))
            defaults.update(saved)
            if 'tts_mode' not in saved and (saved.get('tts_base_url') or saved.get('tts_model')):
                defaults['tts_mode'] = 'api'
        defaults['connection_mode'] = (defaults.get('connection_selection') or
            ('current' if defaults.get('harness_route_id') else 'custom' if defaults.get('base_url') and defaults.get('model') else 'unconfigured'))
        defaults.pop('connection_selection', None)
        for key in ('api_key', 'tts_api_key'):
            stored = defaults.pop(key + '_protected', '')
            defaults[key + '_set' if key == 'api_key' else 'tts_key_set'] = bool(stored)
            local_secret = (key == 'api_key' and (defaults.get('harness_route_id') or defaults.get('connection_mode') in ('native', 'unconfigured'))) or (key == 'tts_api_key' and defaults.get('tts_mode') == 'local')
            if secret and not local_secret:
                defaults[key] = protect(stored, decrypt=True)
            elif secret:
                # Unselected and delegated routes never decrypt another key.
                defaults[key] = ''
            else:
                defaults.pop(key, None)
        return defaults

    def save_settings(self, changes):
        with self._lock, self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE id=1').fetchone()
            current = retire_local_settings(json.loads(row['value'])) if row else {}
            changes = dict(changes)
            selection = changes.pop('connection_mode', None)
            if selection == 'local' or changes.get('model_mode') == 'local':
                raise ValueError(RETIRED_MODEL_MESSAGE)
            if selection not in (None, 'current', 'custom', 'native', 'unconfigured'):
                raise ValueError('Invalid model connection selection')
            if selection == 'current':
                active_row = db.execute('SELECT value FROM harness_state WHERE id=?', ('current',)).fetchone()
                active = json.loads(active_row['value']) if active_row else None
                if not active or not all(active.get(key) for key in ('route_id', 'guard', 'model')):
                    raise ValueError('No validated current connection')
                # A narration form may still carry old transport fields. The
                # explicit current selection is authoritative; credentials are
                # never converted to a browser-visible provider key.
                for key in ('model_mode', 'base_url', 'model', 'api_key', 'clear_api_key'):
                    changes.pop(key, None)
                current.update(model_mode='api', base_url='http://127.0.0.1:3796/v1',
                               model=active['route_id'], harness_route_id=active['route_id'], connection_selection='current')
            elif selection == 'unconfigured':
                for key in ('model_mode', 'base_url', 'model', 'api_key', 'clear_api_key'):
                    changes.pop(key, None)
                current.pop('harness_route_id', None)
                current.update(model_mode='api', connection_selection='unconfigured')
            elif selection == 'native':
                for key in ('model_mode', 'base_url', 'model', 'api_key', 'clear_api_key'):
                    changes.pop(key, None)
                current.pop('harness_route_id', None)
                current.update(connection_selection='native', model_mode='api')
            else:
                # Presence is not intent. Legacy forms send the full unchanged
                # model tuple, an empty key and clear=false on every TTS save.
                changed_model = any(key in changes and changes[key] != current.get(key, 'api' if key == 'model_mode' else '')
                                    for key in ('model_mode', 'base_url', 'model'))
                changed_credential = bool(changes.get('api_key') or changes.get('clear_api_key'))
                if selection == 'custom' or changed_model or changed_credential:
                    current.pop('harness_route_id', None)
                    current['connection_selection'] = 'custom'
            if selection == 'custom' and changes.get('model_mode') is None:
                changes['model_mode'] = 'api'
            candidate = {**current, **{key: changes[key] for key in ('model_mode', 'base_url', 'model') if key in changes}}
            if candidate.get('connection_selection') == 'custom' and is_local_provider(candidate):
                raise ValueError(RETIRED_MODEL_MESSAGE)
            if (not candidate.get('harness_route_id') and candidate.get('connection_selection') != 'native' and candidate.get('model_mode') == 'api'
                    and (str(candidate.get('base_url', '')).rstrip('/') == 'http://127.0.0.1:3796/v1'
                         or str(candidate.get('model', '')).startswith('dsroute_'))):
                raise ValueError('Managed connection must be selected as current')
            if selection == 'custom':
                current.pop('harness_route_id', None)
            if current.get('connection_selection') in ('current', 'native', 'custom'):
                current.pop('selection_required', None)
            for key in ('model_mode', 'base_url', 'model', 'tts_enabled', 'tts_mode', 'tts_base_url', 'tts_model', 'tts_voice'):
                if key in changes:
                    current[key] = changes[key]
            for key in ('api_key', 'tts_api_key'):
                if changes.get('clear_' + key):
                    current.pop(key + '_protected', None)
                elif changes.get(key):
                    current[key + '_protected'] = protect(changes[key])
            db.execute('INSERT OR REPLACE INTO settings(id,value) VALUES(1,?)', (json.dumps(current),))
        return self.settings()

    def harness_state(self, key='operation'):
        with self.connect() as db:
            row = db.execute('SELECT value FROM harness_state WHERE id=?', (key,)).fetchone()
        return json.loads(row['value']) if row else None

    def save_harness_state(self, value, key='operation', expected_revision=None):
        """Compare-and-swap prevents late network results reviving cancelled work."""
        with self._lock, self.connect() as db:
            row = db.execute('SELECT value FROM harness_state WHERE id=?', (key,)).fetchone()
            existing = json.loads(row['value']) if row else None
            if expected_revision is not None and (not existing or existing.get('revision') != expected_revision
                    or (isinstance(value, dict) and existing.get('id') != value.get('id'))):
                return False
            db.execute('INSERT OR REPLACE INTO harness_state(id,value) VALUES(?,?)',
                       (key, json.dumps(value, ensure_ascii=False)))
        return True

    def put_harness_secret(self, value):
        ref = identifier('hsecret')
        with self._lock, self.connect() as db:
            db.execute('INSERT INTO harness_secrets(id,protected,created_at) VALUES(?,?,?)',
                       (ref, protect(value), now()))
        return ref

    def harness_secret(self, ref):
        with self.connect() as db:
            row = db.execute('SELECT protected FROM harness_secrets WHERE id=?', (ref,)).fetchone()
        if not row:
            raise ValueError('Unknown credential reference')
        return protect(row['protected'], decrypt=True)

    def delete_harness_secret(self, ref):
        with self._lock, self.connect() as db:
            db.execute('DELETE FROM harness_secrets WHERE id=?', (ref,))

    def harness_settings_snapshot(self):
        # Snapshot only addressed model fields; TTS and unrelated settings stay live.
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE id=1').fetchone()
        value = json.loads(row['value']) if row else {}
        return {key: {'present': key in value, 'value': value.get(key)}
                for key in ('model_mode', 'base_url', 'model', 'harness_route_id', 'connection_selection')}

    def apply_harness_settings(self, route_id, model):
        with self._lock, self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE id=1').fetchone()
            value = json.loads(row['value']) if row else {}
            value.update(model_mode='api', base_url='http://127.0.0.1:3796/v1',
                         model=model, harness_route_id=route_id, connection_selection='current')
            value.pop('selection_required', None)
            db.execute('INSERT OR REPLACE INTO settings(id,value) VALUES(1,?)', (json.dumps(retire_local_settings(value)),))

    def restore_harness_settings(self, route_id, snapshot):
        with self._lock, self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE id=1').fetchone()
            value = json.loads(row['value']) if row else {}
            # A later manual selection belongs to the user and must not be undone.
            if value.get('harness_route_id') != route_id:
                return False
            for key, original in snapshot.items():
                if original['present']:
                    value[key] = original['value']
                else:
                    value.pop(key, None)
            db.execute('INSERT OR REPLACE INTO settings(id,value) VALUES(1,?)', (json.dumps(retire_local_settings(value)),))
        return True
