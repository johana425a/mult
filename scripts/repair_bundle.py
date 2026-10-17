"""Stage, verify and apply reversible source patches without replacing running code."""
from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

APP = Path(__file__).resolve().parents[1]
STORE = APP / 'extensions' / 'repairs'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_bytes(data)
    os.replace(temp, path)

def save(folder, record):
    atomic(folder / 'manifest.json', json.dumps(record, ensure_ascii=False, indent=2).encode())

def scoped(root, name):
    path = (root / name).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('Patch paths must stay inside the chosen application copy.')
    return path

def run(args):
    STORE.mkdir(parents=True, exist_ok=True)
    action = args['action']
    if action == 'list':
        return {'repairs':[json.loads(p.read_text('utf-8')) for p in STORE.glob('*/manifest.json')]}
    if action == 'stage':
        root = Path(args['target_root']).resolve()
        if not root.is_dir():
            raise ValueError('The target application copy does not exist.')
        identifier = 'repair_' + uuid.uuid4().hex
        folder = STORE / identifier
        files = args.get('files') or []
        if not files or len(files) > 100:
            raise ValueError('A patch must contain 1 to 100 source files.')
        record = {'id':identifier, 'target_root':str(root), 'status':'staged', 'files':[], 'created_at':time.time()}
        seen = set()
        for item in files:
            target = scoped(root, item['path'])
            rel = target.relative_to(root).as_posix()
            if rel.casefold() in seen:
                raise ValueError('A patch cannot repeat a target file.')
            seen.add(rel.casefold())
            content = item['content'].encode('utf-8')
            original = target.read_bytes() if target.is_file() else None
            atomic(folder/'staged'/rel, content)
            if original is not None:
                atomic(folder/'original'/rel, original)
            record['files'].append({'path':rel, 'before':digest(original) if original is not None else None, 'after':digest(content)})
        save(folder, record)
        return record
    identifier = args.get('id', '')
    if not identifier.startswith('repair_') or len(identifier) != 39 or not identifier[7:].isalnum():
        raise ValueError('Invalid repair identity.')
    folder = STORE / identifier
    record = json.loads((folder/'manifest.json').read_text('utf-8'))
    root = Path(record['target_root']).resolve()
    if action == 'verify':
        for item in record['files']:
            file = scoped(folder/'staged', item['path'])
            data = file.read_bytes()
            if digest(data) != item['after']:
                raise ValueError('The staged file changed; create a new repair.')
            if file.suffix == '.py':
                ast.parse(data, filename=str(file))
            if file.suffix == '.json':
                json.loads(data)
        command = args.get('command')
        if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
            raise ValueError('Provide an actual validation command, with arguments as a list.')
        result = subprocess.run(command, cwd=folder/'staged', capture_output=True, timeout=min(600, int(args.get('timeout', 120))),
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0), encoding='utf-8', errors='replace')
        record['validation'] = {'exit_code':result.returncode, 'stdout':result.stdout[-12000:], 'stderr':result.stderr[-12000:], 'command':command}
        record['status'] = 'verified' if result.returncode == 0 else 'verification_failed'
        save(folder, record)
        return record
    if action in {'apply','rollback'} and root == APP and not args.get('_offline'):
        if record['status'] != ('verified' if action == 'apply' else 'applied'):
            raise ValueError('The patch must pass its validation command before application.')
        record['status'] = 'queued_for_restart' if action == 'apply' else 'rollback_on_restart'
        save(folder, record)
        return {**record, 'message':'Validated patch queued. It will be applied before services start on the next application restart.'}
    if action not in {'apply', 'rollback'}:
        raise ValueError('Unknown repair operation.')
    applying = action == 'apply'
    if record['status'] not in ({'verified','queued_for_restart'} if applying else {'applied','rollback_on_restart'}):
        raise ValueError('This operation does not match the repair state.')
    for item in record['files']:
        target = scoped(root, item['path'])
        actual = digest(target.read_bytes()) if target.is_file() else None
        if actual != item['before' if applying else 'after']:
            raise ValueError('The target changed after this patch was staged; do not overwrite another edit: ' + item['path'])
        replacement = folder/('staged' if applying else 'original')/item['path']
        expected = item['after' if applying else 'before']
        if expected is not None and digest(replacement.read_bytes()) != expected:
            raise ValueError('Patch backup checksum mismatch.')
    changed = []
    try:
        for item in record['files']:
            target = scoped(root, item['path'])
            replacement = folder/('staged' if applying else 'original')/item['path']
            if not applying and item['before'] is None:
                target.unlink()
            else:
                atomic(target, replacement.read_bytes())
            changed.append(item)
    except BaseException:
        for item in reversed(changed):
            target = scoped(root, item['path'])
            prior = folder/('original' if applying else 'staged')/item['path']
            if applying and item['before'] is None:
                target.unlink(missing_ok=True)
            else:
                atomic(target, prior.read_bytes())
        raise
    record['status'] = 'applied' if applying else 'rolled_back'
    save(folder, record)
    return record

def apply_pending():
    if not STORE.exists():
        return []
    pending = [json.loads(p.read_text('utf-8')) for p in STORE.glob('*/manifest.json')]
    pending = [p for p in pending if p['status'] in {'queued_for_restart','rollback_on_restart'}]
    if not pending:
        return []
    import socket
    for port in (3791,3792,3793,3794,3795,3796,8011):
        with socket.socket() as probe:
            probe.settimeout(.1)
            if probe.connect_ex(('127.0.0.1',port)) == 0:
                return [{'status':'deferred_running_services'}]
    return [run({'action':'apply' if p['status']=='queued_for_restart' else 'rollback','id':p['id'],'_offline':True}) for p in pending]

if __name__ == '__main__':
    try:
        value = run(json.load(sys.stdin))
        print(json.dumps({'ok':True,'result':value},ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False))
        sys.exit(1)
