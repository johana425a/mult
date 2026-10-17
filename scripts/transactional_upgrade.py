"""Explicit program-only upgrades with durable intent and crash reconciliation.

Callers stop owned backend services before apply/recover/rollback. This module
never restarts the desktop, scans arbitrary user directories, or deletes data.
All sources, target roots and preserved state are explicit plan inputs.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid


def longpath(path):
    path = Path(path)
    if os.name == 'nt' and path.is_absolute() and not str(path).startswith('\\\\?\\'):
        return Path('\\\\?\\' + str(path))
    return path


def sha(path):
    path = longpath(path)
    if not path.is_file():
        return None
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    # Windows scanners may briefly hold the old journal without delete sharing.
    # Keep both complete files and retry replacement; never truncate in place.
    for attempt in range(12):
        try:
            os.replace(temporary, path)
            break
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in {5, 32, 33} or attempt == 11:
                raise
            time.sleep(min(.2, .025 * (attempt + 1)))


def child(root, name):
    root = root.resolve()
    if not name or Path(name).is_absolute() or ':' in name or '..' in Path(name).parts:
        raise ValueError('Unsafe relative program path')
    path = root / name
    if not path.resolve().is_relative_to(root) or path.resolve() == root:
        raise ValueError('Program path escapes its declared root')
    return longpath(path)


def snapshot(path):
    path = longpath(path)
    if not path.exists():
        return None
    if path.is_file():
        return {'kind': 'file', 'bytes': path.stat().st_size, 'sha256': sha(path)}
    if path.is_symlink() or path.is_junction():
        raise ValueError('A replacement tree must be a materialized directory')
    rows = []
    for here, dirs, files in os.walk(path, followlinks=False):
        for name in dirs:
            item = Path(here) / name
            if item.is_symlink() or item.is_junction():
                raise ValueError('Materialize dependency links before staging: ' + str(item))
        for name in sorted(files):
            item = Path(here) / name
            if item.is_symlink():
                raise ValueError('File links are not upgrade payloads')
            rows.append({'path': item.relative_to(path).as_posix(), 'bytes': item.stat().st_size, 'sha256': sha(item)})
    rows.sort(key=lambda row: row['path'])
    return {'kind': 'tree', 'files': rows, 'sha256': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}


def copy(source, target):
    source, target = longpath(source), longpath(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def prepare(root, folder, changes, preserved=()):
    root, folder = Path(root).resolve(), Path(folder).resolve()
    if (folder / 'receipt.json').exists():
        raise ValueError('An existing transaction must be recovered, not replaced')
    rows = []
    names = [row['path'] for row in changes]
    for index, change in enumerate(changes):
        name = change['path']
        if any(name == other or name.startswith(other.rstrip('/') + '/') or other.startswith(name.rstrip('/') + '/') for other in names[:index]):
            raise ValueError('Overlapping upgrade targets')
        target = child(root, name)
        source = Path(change['source']).resolve()
        before, after = snapshot(target), snapshot(source)
        if after is None:
            raise ValueError('Missing candidate: ' + str(source))
        if 'expected_before' in change and before != change['expected_before']:
            raise ValueError('The live source changed during review: ' + name)
        stage = child(folder, 'staged/' + name)
        copy(source, stage)
        if snapshot(stage) != after or snapshot(target) != before:
            raise ValueError('Source or live bytes changed while staging')
        if before and before['kind'] == 'file':
            copy(target, child(folder, 'previous/' + name))
        rows.append({'path': name, 'before': before, 'after': after, 'status': 'prepared'})
    data = {name: snapshot(child(root, name)) for name in preserved}
    receipt = {'schema': 1, 'root': str(root), 'status': 'prepared', 'created_at': time.time(), 'rows': rows, 'preserved_before': data}
    atomic(folder / 'receipt.json', receipt)
    return receipt


def run(folder, *, rollback=False, after_mutation=lambda *_: None):
    folder = Path(folder).resolve()
    record = json.loads((folder / 'receipt.json').read_text('utf-8'))
    root = Path(record['root'])
    if record['status'] == ('rolled_back' if rollback else 'applied'):
        verify(folder, rollback=rollback)
        return record
    if record['status'] == 'rolled_back' and not rollback:
        raise ValueError('A rolled-back transaction cannot be reapplied')
    record['status'] = 'rolling_back' if rollback else 'applying'
    atomic(folder / 'receipt.json', record)
    rows = list(reversed(record['rows'])) if rollback else record['rows']
    for index, row in enumerate(rows):
        target = child(root, row['path'])
        old = child(folder, 'previous/' + row['path'])
        stage = child(folder, 'staged/' + row['path'])
        current = snapshot(target)
        wanted = row['before'] if rollback else row['after']
        if current == wanted:
            row['status'] = 'restored' if rollback else 'applied'
            atomic(folder / 'receipt.json', record)
            continue
        if current not in (row['before'], row['after'], None):
            raise ValueError('An unrelated edit prevents recovery: ' + row['path'])
        row['status'] = 'restore_intent' if rollback else 'replace_intent'
        atomic(folder / 'receipt.json', record)  # Durable intent precedes every mutation.
        if rollback:
            if row['before'] is not None and snapshot(old) != row['before']:
                raise ValueError('Rollback bytes are missing or changed')
            if target.exists():
                failed = child(folder, 'failed/' + row['path'])
                if failed.exists():
                    raise ValueError('Unexpected duplicate failed candidate')
                failed.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, failed)
                after_mutation(index, 'removed_new')
            if row['before'] is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                if old.is_dir():
                    os.replace(old, target)
                else:
                    temporary = target.with_name(target.name + '.rollback-' + uuid.uuid4().hex)
                    shutil.copy2(old, temporary)
                    os.replace(temporary, target)
                after_mutation(index, 'restored_old')
        else:
            if snapshot(stage) != row['after']:
                raise ValueError('Staged candidate is missing or changed')
            if row['after']['kind'] == 'tree':
                if target.exists():
                    if old.exists():
                        raise ValueError('Unexpected duplicate original tree')
                    old.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, old)
                    after_mutation(index, 'moved_old')
                elif row['before'] is not None and snapshot(old) != row['before']:
                    raise ValueError('Original tree missing during recovery')
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(stage, target)
            else:
                if row['before'] is not None and snapshot(old) != row['before']:
                    raise ValueError('Original file backup missing or changed')
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + '.upgrade-' + uuid.uuid4().hex)
                shutil.copy2(stage, temporary)
                os.replace(temporary, target)
            after_mutation(index, 'installed_new')
        if snapshot(target) != wanted:
            raise ValueError('Post-write byte verification failed')
        row['status'] = 'restored' if rollback else 'applied'
        atomic(folder / 'receipt.json', record)
    record['status'] = 'rolled_back' if rollback else 'applied'
    record['completed_at'] = time.time()
    atomic(folder / 'receipt.json', record)
    verify(folder, rollback=rollback)
    return record


def verify(folder, *, rollback=False):
    folder = Path(folder)
    record = json.loads((folder / 'receipt.json').read_text('utf-8'))
    root = Path(record['root'])
    if not record['rows']:
        raise ValueError('Empty upgrade evidence')
    for row in record['rows']:
        if snapshot(child(root, row['path'])) != row['before' if rollback else 'after']:
            raise ValueError('Deployed file/tree bytes differ: ' + row['path'])
    preserved = {name: snapshot(child(root, name)) for name in record['preserved_before']}
    if preserved != record['preserved_before']:
        raise ValueError('Preserved state bytes changed')
    return {'passed': True, 'targets': len(record['rows']), 'trees_checked': sum(row['after']['kind'] == 'tree' for row in record['rows']),
        'preserved_paths_checked': len(preserved), 'preserved_hashes_equal': preserved == record['preserved_before']}
