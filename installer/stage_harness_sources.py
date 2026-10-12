"""Copy public integration/desktop sources into a new dependency-free D stage.

This is source preparation only. Host runtime/dependencies are owned by their
builder and must be frozen separately after it is ready. Original source, model
files, credentials, databases, E and existing installation remain unchanged.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import time

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
module_spec = importlib.util.spec_from_file_location('harness_source_stage_inventory', BASE / 'prepare_harness_delivery.py')
delivery = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(delivery)
build = delivery.build
SKIP_DIRS = {'node_modules', '__pycache__', '.git', '.dsh', '.deepseek', 'downloads',
             '.pytest_cache', '.mypy_cache', 'profile', 'browser-profile', 'userdata',
             'harness-state', 'cache', 'logs'}
SKIP_FILES = {'control-token', 'account-state.json', 'credentials.json', 'cookies.json',
              'auth.json', 'runtime.json'}


def source_files(source, target):
    files, skipped = [], []
    for directory, directories, names in os.walk(source, followlinks=False):
        kept = []
        for name in sorted(directories):
            path = Path(directory) / name
            relative = path.relative_to(source).as_posix()
            if name.casefold() in SKIP_DIRS or name.casefold().startswith('.next'):
                skipped.append({'path': relative + '/', 'reason': 'dependency, private state or generated directory'})
            elif path.is_symlink() or path.is_junction():
                raise RuntimeError('Unexpected source reparse point: ' + relative)
            else:
                kept.append(name)
        directories[:] = kept
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(source).as_posix()
            if (name.casefold() in SKIP_FILES or name.casefold().startswith('.env')
                    or path.suffix.casefold() in {'.pyc', '.pyo', '.sqlite', '.sqlite3', '.db', '.pem', '.pfx', '.p12', '.tsbuildinfo'}):
                skipped.append({'path': relative, 'reason': 'private state, local environment or generated file'})
                continue
            if path.is_symlink() or path.is_junction():
                raise RuntimeError('Unexpected source reparse file: ' + relative)
            output_name = target + '/' + relative
            delivery.scan_public(path, output_name)
            files.append((relative, path, build.helpers.digest(path)))
    return files, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-name', required=True, help='Fresh r5-sources-* installer child')
    parser.add_argument('--directory', action='append', choices=['integration', 'desktop', 'scripts', 'portal'], required=True)
    args = parser.parse_args()
    started = time.monotonic()
    if not re.fullmatch(r'r5-sources-[a-z0-9-]+', args.artifact_name):
        raise RuntimeError('A fresh plain r5-sources-* stage is required')
    artifact = BASE / args.artifact_name
    if artifact.exists() or len(args.directory) != len(set(args.directory)):
        raise RuntimeError('Existing stage retained; repeated directory not allowed')
    planned = []
    for name in args.directory:
        source = build.helpers.workspace_path(name)
        files, skipped = source_files(source, name)
        if not files:
            raise RuntimeError('No public source files found: ' + name)
        planned.append((name, files, skipped))
    artifact.mkdir()
    report = {'artifact': artifact.relative_to(ROOT).as_posix(), 'components': [],
              'private_state_copied': False, 'dependencies_copied': False,
              'runtime_host_frozen': False, 'source_changed': False,
              'services_started': False, 'user_data_copied': False, 'written_to_e': False}
    for name, files, skipped in planned:
        destination = artifact / name
        for relative, source, expected in files:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if build.helpers.digest(target) != expected or build.helpers.digest(source) != expected:
                raise RuntimeError('Source changed while preparing public stage: ' + name + '/' + relative)
        rows = build.helpers.collect_tree(destination, name)
        report['components'].append({'name': name, 'source': destination.relative_to(ROOT).as_posix(),
                                     'target': name, 'file_count': len(rows),
                                     'uncompressed_bytes': sum(row['bytes'] for row in rows),
                                     'excluded': skipped})
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    output = artifact / 'source-stage-report.json'
    output.write_bytes(build.helpers.json_bytes(report))
    print(json.dumps({'report': output.relative_to(ROOT).as_posix(),
                      'components': report['components'], 'runtime_host_frozen': False,
                      'source_changed': False, 'written_to_e': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
