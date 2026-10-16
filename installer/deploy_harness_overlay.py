"""Apply a SHA-frozen program overlay to one stopped DeepSteam installation.

An overlay contains public program files only, never model settings, profile,
account state, user data or storage selection. Each existing changed file is
retained for rollback. This does not build an installer or publish to E.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import re

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
module_spec = importlib.util.spec_from_file_location('harness_overlay_builder', BASE / 'build_r5_candidate.py')
build = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(build)
sys.path.insert(0, str(ROOT / 'scripts'))
from storage_paths import assert_plain_path

ALLOWED_TARGETS = ('runtime/desktop/', 'runtime/harness/', 'integration/harness/', 'desktop/', 'portal/')
ALLOWED_FILES = {'scripts/harness_runtime.py', 'scripts/desktop_runtime.py', 'scripts/portal_runtime.py',
                 'scripts/installation_identity.py',
                 'integration/harness_bridge.py',
                 'installer/Start-DeepSteam.ps1', 'installer/Stop-DeepSteam.ps1',
                 'README.md', 'HANDOFF.md', 'runtime/native-frontend.json'}


def native_target(name):
    return re.fullmatch(r'runtime/native-frontends/(\d{8}-\d{6})/.+', name)


def selected_files(descriptor):
    selected = []
    seen = set()
    for row in descriptor['files']:
        name = build.safe_name(row['path'])
        if name in seen or not (name.startswith(ALLOWED_TARGETS) or name in ALLOWED_FILES or native_target(name)):
            raise RuntimeError('Overlay target is repeated or outside program scope: ' + name)
        seen.add(name)
        source = build.helpers.checked_file(row)
        if row.get('bytes', source.stat().st_size) != source.stat().st_size:
            raise RuntimeError('Overlay source length changed: ' + name)
        selected.append((name, source, row['sha256']))
    if not selected:
        raise RuntimeError('An empty overlay is not an update')
    return selected


def check_native(selected, install):
    native_rows = [(name, source, expected) for name, source, expected in selected if native_target(name)]
    manifests = [source for name, source, _ in selected if name == 'runtime/native-frontend.json']
    if not native_rows and not manifests:
        return
    if not native_rows or len(manifests) != 1:
        raise RuntimeError('A new native runtime and its portable manifest must be deployed together')
    ids = {native_target(name).group(1) for name, _, _ in native_rows}
    if len(ids) != 1:
        raise RuntimeError('Only one immutable native build may be deployed by an overlay')
    build_id = next(iter(ids))
    expected_root = 'runtime/native-frontends/' + build_id
    manifest = json.loads(manifests[0].read_text('utf-8'))
    if (manifest.get('build_id') != build_id or manifest.get('root') != expected_root
            or manifest.get('server') != expected_root + '/server.js'):
        raise RuntimeError('Native manifest contains nonportable or mismatched runtime paths')
    if expected_root + '/server.js' not in {name for name, _, _ in native_rows}:
        raise RuntimeError('The immutable native server entry is missing')
    destination = assert_plain_path(install / expected_root)
    if destination.exists() and any(path.is_file() or path.is_symlink() or path.is_junction()
                                    for path in destination.rglob('*')):
        raise RuntimeError('An existing immutable native build cannot be overwritten')


def check_install(install):
    root = assert_plain_path(install)
    if (not (root / 'DeepSteam.exe').is_file() or not (root / 'runtime/python/python.exe').is_file()
            or root == ROOT.resolve()):
        raise RuntimeError('A separate existing DeepSteam installation is required')
    import psutil
    occupied = [connection.laddr.port for connection in psutil.net_connections(kind='inet')
                if connection.status == 'LISTEN' and connection.laddr.port in {3791, 3792, 3793, 3794, 3795, 3796, 8011}]
    if occupied:
        raise RuntimeError('Stop application services before overlay; occupied ports: ' + ', '.join(map(str, sorted(set(occupied)))))
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-root', type=Path, required=True)
    parser.add_argument('--inventory', required=True, help='Workspace-relative public overlay inventory')
    parser.add_argument('--expected-inventory-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    inventory_path = build.helpers.checked_file({'source': args.inventory, 'sha256': args.expected_inventory_sha256})
    descriptor = json.loads(inventory_path.read_text('utf-8'))
    if descriptor.get('kind') != 'deepsteam-harness-program-overlay':
        raise RuntimeError('An explicit public program overlay inventory is required')
    selected = selected_files(descriptor)
    install = check_install(args.install_root)
    check_native(selected, install)
    for name, _, _ in selected:
        target = assert_plain_path(install / name)
        if not target.is_relative_to(install):
            raise RuntimeError('Overlay target escaped the checked installation')
    if args.check_only:
        print(json.dumps({'overlay_validated': True, 'files': len(selected), 'changed': False}, indent=2))
        return
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d-%H%M%S')
    transaction = install / 'runtime' / ('harness-overlay-' + stamp)
    if transaction.exists():
        raise RuntimeError('Existing overlay retained; wait before retrying')
    staged, backup = transaction / 'staged', transaction / 'original-program-files'
    staged.mkdir(parents=True)
    installed = []
    try:
        for name, source, expected in selected:
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if build.helpers.digest(target) != expected:
                raise RuntimeError('Staged copy SHA differs: ' + name)
        for name, _, expected in selected:
            target = assert_plain_path(install / name)
            original = backup / name
            existed = target.exists()
            if existed:
                if not target.is_file():
                    raise RuntimeError('Program overlay cannot replace a directory: ' + name)
                original.parent.mkdir(parents=True, exist_ok=True)
                target.replace(original)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                (staged / name).replace(target)
            except Exception:
                if existed:
                    original.replace(target)
                raise
            installed.append((name, existed))
            if build.helpers.digest(target) != expected:
                raise RuntimeError('Installed overlay SHA differs: ' + name)
    except Exception:
        for name, existed in reversed(installed):
            target = assert_plain_path(install / name)
            if target.is_file():
                target.unlink()
            if existed:
                (backup / name).replace(target)
        raise
    report = {'kind': 'deepsteam-harness-program-overlay-applied', 'installed_at': stamp,
              'program_root': str(install), 'inventory_sha256': args.expected_inventory_sha256,
              'files_verified': len(selected), 'rollback_originals': str(backup),
              'user_data_modified': False, 'model_settings_modified': False,
              'storage_selection_modified': False, 'credentials_copied': False,
              'services_started': False, 'published_to_e': False}
    (transaction / 'overlay-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
