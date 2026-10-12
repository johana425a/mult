"""Build a fresh public Electron runtime with verified app.asar and source mirror.

Never accesses another profile, starts services, deploys to the running app or
changes existing artifacts. Source copies and ASAR entries must match exactly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'downloads/electron-v44.7.0-win32-x64.zip'
ELECTRON_SHA = 'eee30dc8fa1f5ea95490e59f44e46ea68dd24c6e93d22facf70fe5c2d4c2665c'
APP_FILES = ('main.cjs', 'preload.cjs', 'policy.cjs', 'transport.cjs', 'storage-migration.cjs', 'oauth-placeholder.cjs', 'starting.html', 'package.json')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def plain(path):
    for current in (path, *path.parents):
        if current.exists():
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise RuntimeError('A plain local packaging path is required')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-name', required=True)
    parser.add_argument('--node', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'r5-desktop-[a-z0-9-]+', args.artifact_name):
        raise RuntimeError('A fresh dedicated desktop artifact name is required')
    artifact = plain(ROOT / 'installer' / args.artifact_name)
    if artifact.exists() or digest(plain(ARCHIVE)) != ELECTRON_SHA:
        raise RuntimeError('Fresh stage and pinned official Electron archive required')
    node = plain(args.node.absolute())
    if not node.is_file():
        raise RuntimeError('An existing bundled Node runtime is required')
    started = time.monotonic()
    source_rows = [{'path': name, 'bytes': plain(ROOT / 'desktop' / name).stat().st_size,
                    'sha256': digest(ROOT / 'desktop' / name)} for name in APP_FILES]
    target = artifact / 'runtime/desktop'
    target.mkdir(parents=True)
    with zipfile.ZipFile(ARCHIVE) as archive:
        for entry in archive.infolist():
            name = Path(entry.filename)
            if name.is_absolute() or '..' in name.parts or ':' in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                raise RuntimeError('Unsafe official Electron ZIP entry')
            if entry.is_dir():
                (target / name).mkdir(parents=True, exist_ok=True)
            else:
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, destination.open('xb') as output:
                    shutil.copyfileobj(source, output)
    (target / 'electron.exe').rename(target / 'DeepSteam Desktop.exe')
    mirror = target / 'resources/app'
    mirror.mkdir()
    for name in APP_FILES:
        shutil.copy2(ROOT / 'desktop' / name, mirror / name)
    for name in (name for name in APP_FILES if name.endswith('.cjs')):
        subprocess.run([str(node), '--check', str(mirror / name)], check=True, timeout=30)
    packed = subprocess.check_output([str(node), str(ROOT / 'installer/pack_desktop_asar.mjs'),
                                       str(mirror), str(target / 'resources/app.asar')], text=True, timeout=60)
    asar = json.loads(packed)
    if asar['files'] != sorted(source_rows, key=lambda row: row['path']):
        raise RuntimeError('Desktop source changed while packaging')
    for row in source_rows:
        if digest(ROOT / 'desktop' / row['path']) != row['sha256']:
            raise RuntimeError('Desktop source changed after the frozen copy')
    tool = ROOT / 'installer/desktop-build-tools/node_modules/@electron/asar'
    license_path = tool / 'LICENSE.md'
    if not license_path.is_file():
        license_path = tool / 'LICENSE'
    shutil.copy2(license_path, target / 'ASAR-BUILD-TOOL-LICENSE.txt')
    if not all((target / name).is_file() for name in ('LICENSE', 'LICENSES.chromium.html', 'resources/app.asar')):
        raise RuntimeError('Electron notices or packaged application missing')
    report = {'kind': 'deepsteam-public-desktop-runtime', 'artifact': str(artifact),
              'runtime': str(target), 'electron_version': '44.7.0', 'electron_archive_sha256': ELECTRON_SHA,
              'asar_tool_version': '4.3.1',
              'asar_tool_lock_sha256': digest(ROOT / 'installer/desktop-build-tools/package-lock.json'),
              'app_asar_sha256': digest(target / 'resources/app.asar'),
              'source_files': source_rows, 'all_asar_entry_bytes_verified': True,
              'source_mirror_matches_archive': True, 'node_syntax_checks_passed': True,
              'licenses_retained': True, 'credentials_or_private_profiles_copied': False,
              'services_started': False, 'deployed': False, 'written_to_e': False,
              'elapsed_seconds': round(time.monotonic() - started, 3)}
    report_path = artifact / 'desktop-build-report.json'
    report_path.write_text(json.dumps(report, indent=2), 'utf-8')
    print(json.dumps({'report': str(report_path), 'report_sha256': digest(report_path),
                      'runtime': str(target), 'app_asar_sha256': report['app_asar_sha256'],
                      'source_changed': False, 'services_started': False}, indent=2))


if __name__ == '__main__':
    main()
