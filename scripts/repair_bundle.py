"""Durable source repair transactions. Live application writes require stopped services."""
from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import uuid

APP = Path(__file__).resolve().parents[1]
STORE = APP / 'extensions' / 'repairs'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    path = Path(path)
    if os.name == 'nt' and path.is_absolute() and not str(path).startswith('\\\\?\\'):
        value = str(path)
        path = Path('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temp.open('wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(12):
        try:
            os.replace(temp, path)
            break
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in {5, 32, 33} or attempt == 11:
                raise
            time.sleep(min(.2, .025 * (attempt + 1)))


def save(folder, record):
    atomic(folder / 'manifest.json', json.dumps(record, ensure_ascii=False, indent=2).encode())


def scoped(root, name):
    root = root.resolve()
    path = (root / name).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('Patch paths must stay inside the chosen application copy.')
    return path


def redact(value):
    sensitive = r'(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret|authorization|proxy-authorization|cookie|set-cookie)'
    if isinstance(value, dict):
        return {key: '[redacted]' if re.fullmatch(sensitive, str(key), re.I) else redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    text = str(value)
    # Structured output often contains multiple cookies inside a single field.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return json.dumps(redact(parsed), ensure_ascii=False)
    except (ValueError, TypeError):
        pass
    # Quoted fields may occur inside log messages or command source arguments.
    text = re.sub(r'(?i)([\"\']?(?:cookie|set-cookie|authorization|proxy-authorization)[\"\']?\s*[:=]\s*)([\"\'])(.*?)(\2)',
        lambda match: match[1] + match[2] + '[redacted]' + match[2], text)
    # Header values extend to the end of the line, not the first semicolon.
    text = re.sub(r'(?im)((?:^|\b)(?:cookie|set-cookie|authorization|proxy-authorization)\s*[:=]\s*)[^\r\n]+', r'\1[redacted]', text)
    text = re.sub(r'(?i)\bBearer\s+[^\s\"\']+', 'Bearer [redacted]', text)
    text = re.sub(r'\b(?:sk-|dsexec-|ghp_|github_pat_)[A-Za-z0-9_-]+', '[redacted]', text)
    text = re.sub(r'(?i)((?:api[_-]?key|token|password|secret|authorization|cookie)[\"\']?\s*[:=]\s*[\"\']?)[^\s\"\',;]+', r'\1[redacted]', text)
    return text


def redact_command(command):
    result = []
    hide_next = False
    for value in command:
        result.append('[redacted]' if hide_next else redact(value))
        hide_next = bool(re.fullmatch(r'--?(?:cookie|set-cookie|authorization|proxy-authorization|api[-_]?key|token|password|secret)', value, re.I))
    return result


def services_stopped():
    for port in (3791, 3792, 3793, 3794, 3795, 3796, 8011):
        with socket.socket() as probe:
            probe.settimeout(.1)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                return False
    return True


def actual_hash(path):
    if path.exists() and not path.is_file():
        raise ValueError('A patch target is not an ordinary file: ' + str(path))
    return digest(path.read_bytes()) if path.is_file() else None


def transition(folder, record, action):
    """Reconcile the bytes, not a possibly stale per-file progress flag."""
    root = Path(record['target_root']).resolve()
    applying = action == 'apply'
    desired_key = 'after' if applying else 'before'
    source_dir = 'staged' if applying else 'original'
    for item in record['files']:
        target = scoped(root, item['path'])
        actual = actual_hash(target)
        if actual not in {item['before'], item['after']}:
            raise ValueError('The target has an unrelated edit: ' + item['path'])
        expected = item[desired_key]
        if expected is not None and actual_hash(scoped(folder / source_dir, item['path'])) != expected:
            raise ValueError('Patch backup checksum mismatch: ' + item['path'])
    record['status'] = 'applying' if applying else 'rolling_back'
    record['transaction'] = {'id': uuid.uuid4().hex, 'action': action, 'started_at': time.time()}
    save(folder, record)
    for item in record['files']:
        target = scoped(root, item['path'])
        expected = item[desired_key]
        if actual_hash(target) not in {item['before'], item['after']}:
            raise ValueError('The target changed during the repair: ' + item['path'])
        item['phase'] = action + '_intent'
        save(folder, record)
        if actual_hash(target) != expected:
            if expected is None:
                target.unlink(missing_ok=True)
            else:
                atomic(target, scoped(folder / source_dir, item['path']).read_bytes())
        if actual_hash(target) != expected:
            raise ValueError('Repair verification failed: ' + item['path'])
        item['phase'] = action + '_done'
        save(folder, record)
    record['status'] = 'applied' if applying else 'rolled_back'
    record['transaction']['completed_at'] = time.time()
    save(folder, record)
    return record


def run(args, *, offline=False):
    # offline is internal to the stopped-service updater. JSON callers cannot
    # bypass the guard by passing _offline or by choosing APP/integration.
    STORE.mkdir(parents=True, exist_ok=True)
    action = args['action']
    if action == 'list':
        return {'repairs': [json.loads(p.read_text('utf-8')) for p in STORE.glob('*/manifest.json')]}
    if action == 'stage':
        root = Path(args['target_root']).resolve()
        if not root.is_dir():
            raise ValueError('The target application copy does not exist.')
        identifier = 'repair_' + uuid.uuid4().hex
        folder = STORE / identifier
        files = args.get('files') or []
        if not files or len(files) > 100:
            raise ValueError('A patch must contain 1 to 100 source files.')
        record = {'schema': 2, 'id': identifier, 'target_root': str(root), 'status': 'staged', 'files': [], 'created_at': time.time()}
        seen = set()
        for item in files:
            target = scoped(root, item['path'])
            rel = target.relative_to(root).as_posix()
            if rel.casefold() in seen:
                raise ValueError('A patch cannot repeat a target file.')
            seen.add(rel.casefold())
            content = item['content'].encode('utf-8')
            before = actual_hash(target)
            atomic(folder / 'staged' / rel, content)
            if before is not None:
                atomic(folder / 'original' / rel, target.read_bytes())
                if actual_hash(folder / 'original' / rel) != before:
                    raise ValueError('The original changed during staging.')
            record['files'].append({'path': rel, 'before': before, 'after': digest(content)})
        save(folder, record)
        return record
    identifier = args.get('id', '')
    if not re.fullmatch(r'repair_[a-f0-9]{32}', identifier):
        raise ValueError('Invalid repair identity.')
    folder = STORE / identifier
    record = json.loads((folder / 'manifest.json').read_text('utf-8'))
    root = Path(record['target_root']).resolve()
    if action == 'verify':
        if record['status'] not in {'staged', 'checks_passed', 'verified', 'verification_failed'}:
            raise ValueError('Checks cannot reset an in-progress or applied transaction.')
        for item in record['files']:
            file = scoped(folder / 'staged', item['path'])
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
        result = subprocess.run(command, cwd=folder / 'staged', capture_output=True,
            timeout=min(600, int(args.get('timeout', 120))), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            encoding='utf-8', errors='replace')
        record['validation'] = {'syntax': 'passed', 'command_check': 'passed' if result.returncode == 0 else 'failed',
            'behavior_fix': 'not_established', 'exit_code': result.returncode,
            'stdout': redact(result.stdout)[-12000:], 'stderr': redact(result.stderr)[-12000:],
            'command': redact_command(command),
            'staged_hashes': {item['path']: item['after'] for item in record['files']}}
        record['status'] = 'checks_passed' if result.returncode == 0 else 'verification_failed'
        save(folder, record)
        return record
    if action not in {'apply', 'rollback'}:
        raise ValueError('Unknown repair operation.')
    allowed = {'checks_passed', 'verified', 'queued_for_restart', 'applying', 'rolling_back', 'applied', 'rolled_back', 'rollback_on_restart'}
    if record['status'] not in allowed or not record.get('validation') or record['validation'].get('exit_code') != 0:
        raise ValueError('The patch must pass its checks before application or rollback.')
    live_targets = any(scoped(root, item['path']).is_relative_to(APP.resolve()) for item in record['files'])
    if live_targets and (not offline or not services_stopped()):
        record['status'] = 'queued_for_restart' if action == 'apply' else 'rollback_on_restart'
        save(folder, record)
        return {**record, 'message': 'Queued for the stopped-service updater. No running application file was replaced.'}
    return transition(folder, record, action)


def apply_pending():
    if not STORE.exists():
        return []
    records = [json.loads(p.read_text('utf-8')) for p in STORE.glob('*/manifest.json')]
    pending = [p for p in records if p['status'] in {'queued_for_restart', 'rollback_on_restart', 'applying', 'rolling_back'}]
    if not pending:
        return []
    if not services_stopped():
        return [{'status': 'deferred_running_services'}]
    return [run({'action': 'rollback' if p['status'] in {'rollback_on_restart', 'rolling_back'} else 'apply', 'id': p['id']}, offline=True) for p in pending]


if __name__ == '__main__':
    try:
        print(json.dumps({'ok': True, 'result': run(json.load(sys.stdin))}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': redact(exc)}, ensure_ascii=False))
        sys.exit(1)
