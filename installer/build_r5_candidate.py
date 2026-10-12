"""Build a credential-free r5 desktop candidate from the preserved r4 payload.

All inputs are complete SHA-pinned inventories. This command neither deploys
the candidate, starts services, accesses account state nor writes to E. A root
acceptance receipt must explicitly permit distribution before a build.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import time
import zipfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
spec = importlib.util.spec_from_file_location('r5_zip_helpers', BASE / 'build_r4_candidate.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
VERSION = '2026.10.11-r5-startupfix'
MANIFEST_NAME = helpers.MANIFEST_NAME
TARGETS = {**helpers.COMPONENT_TARGETS, 'harness': 'runtime/harness',
           'desktop_runtime': 'runtime/desktop', 'desktop_source': 'desktop',
           'harness_bridge': 'integration/harness'}
ALLOWED_PREFIXES = (*helpers.SOURCE_FILE_PREFIXES, 'desktop/')
FORBIDDEN_PARTS = {'.dsh', '.deepseek', 'browser-profile', 'userdata'}
FORBIDDEN_FILES = {'control-token', 'account-state.json', 'credentials.json',
                   'cookies.json', 'auth.json', 'runtime.json'}
REQUIRED_GATES = ('desktop_cold_start_passed', 'desktop_exit_ownership_passed',
                  'headless_lifecycle_passed', 'qwen_guidance_real_model_passed',
                  'configuration_state_guards_passed', 'credentials_excluded_passed',
                  'original_features_preserved_passed', 'restart_preservation_passed')
LIVE_GATES = ('account_route_live_verified', 'api_key_route_live_verified',
              'learning_live_verified', 'classroom_live_verified')


def safe_name(name):
    name = helpers.safe_name(name)
    parts = Path(name).parts
    if any(part.casefold() in FORBIDDEN_PARTS for part in parts):
        raise RuntimeError('Harness or desktop private state is not distributable: ' + name)
    if Path(name).name.casefold() in FORBIDDEN_FILES:
        raise RuntimeError('Private runtime state is not distributable: ' + name)
    if name.startswith(('runtime/harness/profile/', 'runtime/harness/sessions/',
                        'runtime/desktop/profile/', 'runtime/desktop/sessions/')):
        raise RuntimeError('Account or browser state is not distributable: ' + name)
    return name


def receipt_status(receipt):
    if receipt.get('kind') != 'deepsteam-desktop-harness-acceptance':
        raise RuntimeError('An actual desktop/Harness acceptance receipt is required')
    if receipt.get('credentials_included') is not False or receipt.get('user_data_included') is not False:
        raise RuntimeError('Acceptance must explicitly exclude credentials and user data')
    missing = [name for name in (*REQUIRED_GATES, *LIVE_GATES) if receipt.get(name) is not True]
    return {'missing_gates': missing, 'distribution_ready': not missing and receipt.get('distribution_ready') is True}


def versioned_source(source, version=VERSION):
    anchor = 'internal const string Version = "2026.10.10-r3";'
    if source.count(anchor) != 1:
        raise RuntimeError('Unexpected original installer source version')
    return source.replace(anchor, 'internal const string Version = "' + version + '";', 1)


def load_plan(specification):
    if (specification.get('version') != VERSION
            or not re.fullmatch(r'r5-[a-z0-9-]+', specification.get('artifact_name', ''))):
        raise RuntimeError('A fresh r5-* candidate and the exact r5 version are required')
    baseline_path = helpers.checked_file(specification['baseline'])
    with zipfile.ZipFile(baseline_path) as archive:
        blob = archive.read(MANIFEST_NAME)
        if hashlib.sha256(blob).hexdigest() != specification['baseline']['manifest_sha256']:
            raise RuntimeError('Preserved r4 payload manifest changed')
        baseline_manifest = json.loads(blob)
        if baseline_manifest.get('version') != '2026.10.11-r4':
            raise RuntimeError('The verified r4 payload is required as baseline')
        baseline = helpers.rows_by_path(baseline_manifest)
        if set(archive.namelist()) != set(baseline) | {MANIFEST_NAME}:
            raise RuntimeError('Baseline ZIP and complete manifest differ')
        old_native = json.loads(archive.read('runtime/native-frontend.json'))
        old_frontend = json.loads(archive.read('installer/frontend-payload-manifest.json'))
        old_links = json.loads(archive.read('installer/junctions.json'))
    rows = {name: dict(row) for name, row in baseline.items()}
    components, sources, prefixes, seen = [], {}, [], set()
    native_receipt = None
    for original in specification['components']:
        component = dict(original)
        name, target = component['name'], safe_name(component['target'])
        if name in seen:
            raise RuntimeError('Repeated complete component: ' + name)
        seen.add(name)
        if name == 'native':
            build_id = specification['builds']['native']['build_id']
            if target != 'runtime/native-frontends/' + build_id or not re.fullmatch(r'\d{8}-\d{6}', build_id):
                raise RuntimeError('Native build identity differs')
            prefix = 'runtime/native-frontends/'
        elif TARGETS.get(name) == target:
            prefix = target + '/'
        else:
            raise RuntimeError('Component is outside the fixed desktop/Harness scope: ' + name)
        if any(prefix.startswith(other) or other.startswith(prefix) for other in prefixes):
            raise RuntimeError('Overlapping component replacements')
        prefixes.append(prefix)
        source = helpers.workspace_path(component['source'])
        inventory = json.loads(helpers.checked_file(component['inventory']).read_text('utf-8'))
        if inventory.get('source') != component['source'] or inventory.get('target') != target:
            raise RuntimeError('Inventory identity differs from component')
        actual = helpers.collect_tree(source, target)
        for item in actual:
            safe_name(target + '/' + item['path'])
        if (actual != inventory['files'] or inventory.get('file_count') != len(actual)
                or inventory.get('uncompressed_bytes') != sum(row['bytes'] for row in actual) or not actual):
            raise RuntimeError('A complete immutable component inventory is required')
        for obsolete in [path for path in rows if path.startswith(prefix)]:
            del rows[obsolete]
        for row in actual:
            path = target + '/' + row['path']
            rows[path] = {**row, 'path': path}
            sources[path] = source / row['path']
        component['rows'] = actual
        components.append(component)
    if (not {'harness', 'desktop_runtime', 'scripts'}.issubset(seen)
            or not {'integration', 'harness_bridge'}.intersection(seen)):
        raise RuntimeError('Complete Harness, desktop, scripts and Harness bridge components are required')
    if 'native' in seen:
        receipt_path = helpers.checked_file(specification['builds']['native']['receipt'])
        native_receipt = json.loads(receipt_path.read_text('utf-8'))
        if native_receipt.get('build_id') != specification['builds']['native']['build_id']:
            raise RuntimeError('Native source receipt differs from build')
        if native_receipt['build_id'] == old_native['build_id']:
            raise RuntimeError('A modified native build must use a new immutable identity')
        if not set(old_native.get('source_pages', [])).issubset(native_receipt.get('source_pages', [])):
            raise RuntimeError('An existing original page was removed')
        native_source = helpers.workspace_path(next(item['source'] for item in components if item['name'] == 'native'))
        entry = native_source / 'server.js'
        if not entry.is_file() or not (native_source / helpers.next_dist_dir(entry.read_bytes()) / 'BUILD_ID').is_file():
            raise RuntimeError('Modified native runtime lacks its configured Next entry/build')
    if 'openmaic' in seen:
        identity = specification.get('builds', {}).get('openmaic', {})
        om_source = helpers.workspace_path(next(item['source'] for item in components if item['name'] == 'openmaic'))
        if (not re.fullmatch(r'\d{8}-\d{6}', identity.get('build_id', ''))
                or (om_source / '.next/BUILD_ID').read_text('utf-8').strip() != identity.get('next_build_id')):
            raise RuntimeError('Modified OpenMAIC runtime lacks its frozen build identity')
    explicit = set()
    for item in specification.get('files', []):
        name = safe_name(item['path'])
        if (name in explicit or name in helpers.GENERATED_NAMES
                or not (name.startswith(ALLOWED_PREFIXES) or name in helpers.SOURCE_FILE_NAMES)):
            raise RuntimeError('Public file is repeated, generated or outside the source scope')
        source = helpers.checked_file(item)
        rows[name] = {'path': name, 'bytes': source.stat().st_size, 'sha256': item['sha256']}
        sources[name] = source
        explicit.add(name)
    links = (json.loads(helpers.checked_file(specification['junctions']).read_text('utf-8'))
             if specification.get('junctions') else old_links)
    helpers.validate_junctions(links, rows)
    required = ('runtime/harness/sidecar.mjs', 'runtime/desktop/DeepSteam Desktop.exe',
                'runtime/harness/DEEPSEEK-HARNESS-LICENSE.txt',
                'runtime/desktop/LICENSE', 'runtime/desktop/LICENSES.chromium.html',
                'runtime/desktop/resources/app/main.cjs', 'runtime/desktop/resources/app/preload.cjs',
                'scripts/harness_runtime.py',
                'scripts/desktop_runtime.py', 'integration/harness_bridge.py',
                'installer/Start-DeepSteam.ps1', 'installer/Stop-DeepSteam.ps1')
    if not all(name in rows for name in required):
        raise RuntimeError('An executable desktop/Harness entrypoint is missing')
    acceptance = json.loads(helpers.checked_file(specification['feature_acceptance']).read_text('utf-8'))
    readiness = receipt_status(acceptance)
    csharp = helpers.checked_file(specification['installer_source'])
    manifest = helpers.checked_file(specification['windows_manifest'])
    versioned_source(csharp.read_text('utf-8'))
    native_id = native_receipt['build_id'] if native_receipt else old_native['build_id']
    server_entries = {}
    with zipfile.ZipFile(baseline_path) as archive:
        for name in ('runtime/native-frontends/' + native_id + '/server.js',
                     'runtime/openmaic-standalone/server.js'):
            if name not in rows:
                raise RuntimeError('An original application runtime entry is absent: ' + name)
            blob = sources[name].read_bytes() if name in sources else archive.read(name)
            server_entries[name] = helpers.server_entry_policy(blob)
    return {'baseline_path': baseline_path, 'baseline': baseline, 'rows': rows,
            'sources': sources, 'components': components, 'old_native': old_native,
            'old_frontend': old_frontend, 'links': links, 'native_receipt': native_receipt,
            'acceptance': acceptance, 'readiness': readiness,
            'csharp_source': csharp, 'windows_manifest': manifest, 'server_entries': server_entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--expected-spec-sha256', required=True)
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--allow-pending-live', action='store_true',
                        help='Build an explicitly marked development preview; core software gates must pass')
    args = parser.parse_args()
    started = time.monotonic()
    specification_path = helpers.checked_file({'source': args.spec, 'sha256': args.expected_spec_sha256})
    specification = json.loads(specification_path.read_text('utf-8'))
    plan = load_plan(specification)
    artifact = BASE / specification['artifact_name']
    if artifact.exists():
        raise RuntimeError('Existing candidate retained; select a fresh r5-* name')
    if args.validate_only:
        print(json.dumps({'spec_validated': True, 'build_performed': False,
                          'candidate': str(artifact), **plan['readiness']}, indent=2))
        return
    preview = not plan['readiness']['distribution_ready']
    if preview:
        missing_core = [name for name in REQUIRED_GATES if plan['acceptance'].get(name) is not True]
        if (not args.allow_pending_live or missing_core
                or plan['acceptance'].get('status') != 'development-preview'
                or not isinstance(plan['acceptance'].get('pending_live_reason'), str)
                or not plan['acceptance']['pending_live_reason'].strip()):
            raise RuntimeError('Distribution acceptance is incomplete: ' + ', '.join(plan['readiness']['missing_gates']))
    effective_version = VERSION + ('-preview' if preview else '')
    artifact.mkdir()
    history = artifact / 'frozen-inputs'
    history.mkdir()
    (history / 'spec.json').write_bytes(specification_path.read_bytes())
    csharp = artifact / 'DeepSteamSetup-r5.cs'
    csharp.write_text(versioned_source(plan['csharp_source'].read_text('utf-8'), effective_version), 'utf-8')
    stub = artifact / 'DeepSteam-r5-stub.exe'
    helpers.compile_installer(csharp, plan['windows_manifest'], stub)
    rows = plan['rows']
    native = dict(plan['old_native'])
    if plan['native_receipt']:
        receipt = plan['native_receipt']
        target = 'runtime/native-frontends/' + receipt['build_id']
        native.update(build_id=receipt['build_id'], root=target, server=target + '/server.js')
        for key in ('package_lock_sha256', 'source_sha256', 'source_page_count', 'source_pages', 'build_auth_enabled'):
            if key in receipt:
                native[key] = receipt[key]
    generated = {'DeepSteam.exe': stub.read_bytes(), 'installer/DeepSteamSetup.cs': csharp.read_bytes(),
                 'installer/DeepSteam.manifest': plan['windows_manifest'].read_bytes(),
                 'installer/junctions.json': helpers.json_bytes(plan['links']),
                 'runtime/native-frontend.json': helpers.json_bytes(native)}
    generated.update(plan['server_entries'])
    for name, blob in generated.items():
        rows[name] = helpers.file_row(name, blob)
    frontend = {**plan['old_frontend'], 'version': effective_version, 'native_build_id': native['build_id'],
                'desktop_harness_included': True, 'credentials_and_user_data_copied': False,
                'junctions': len(plan['links']),
                'components': [helpers.component_inventory(target, rows) for target in
                               (native['root'], 'runtime/openmaic-standalone', 'runtime/render-service',
                                'runtime/desktop', 'runtime/harness')]}
    if specification.get('builds', {}).get('openmaic'):
        frontend.update(openmaic_build_id=specification['builds']['openmaic']['build_id'],
                        openmaic_next_build_id=specification['builds']['openmaic']['next_build_id'])
    generated['installer/frontend-payload-manifest.json'] = helpers.json_bytes(frontend)
    rows['installer/frontend-payload-manifest.json'] = helpers.file_row(
        'installer/frontend-payload-manifest.json', generated['installer/frontend-payload-manifest.json'])
    manifest = {'version': effective_version, 'platform': 'win-x64', 'file_count': len(rows),
                'uncompressed_bytes': sum(row['bytes'] for row in rows.values()),
                'files': sorted(rows.values(), key=lambda row: row['path'])}
    generated[MANIFEST_NAME] = helpers.json_bytes(manifest)
    replacements = {name: source for name, source in plan['sources'].items()
                    if name not in plan['baseline'] or rows[name] != plan['baseline'][name]}
    replacements.update(generated)
    removed = set(plan['baseline']) - set(rows)
    archive = artifact / 'payload-r5.zip'
    raw = helpers.repackage(plan['baseline_path'], archive, replacements, removed)
    verified = helpers.verify_archive(archive, rows, generated[MANIFEST_NAME])
    release = artifact / 'release'
    release.mkdir()
    executable = release / ('DeepSteam-Setup-' + effective_version + '-x64.exe')
    executable.write_bytes(stub.read_bytes())
    companion = executable.with_suffix('.payload.dat')
    overlay = helpers.append_companion(companion, archive)
    self_test = artifact / 'actual-windows-container-self-test.txt'
    subprocess.run([str(executable), '--self-test', str(self_test)], check=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    distribution = [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': helpers.digest(path)}
                    for path in (executable, companion)]
    for row in distribution:
        path = Path(row['path'])
        path.with_suffix(path.suffix + '.sha256').write_text(row['sha256'] + '  ' + path.name + '\n', 'utf-8')
    report = {'version': effective_version, 'release_kind': 'development-preview' if preview else 'verified-release',
              'pending_live_gates': plan['readiness']['missing_gates'] if preview else [],
              'distribution_files': distribution, 'payload_container': overlay,
              'all_file_sha_passed': True, 'crc_passed': True, 'files_sha_verified': verified,
              'actual_exe_self_test_passed': True, 'cold_start_validated': False,
              'feature_acceptance': plan['acceptance'], 'machine_state_bundled': False,
              'published_to_e': False, 'models_called_by_builder': False,
              'prior_r4_artifacts_unchanged': True, 'raw_archive_reuse': raw,
              'frozen_spec_sha256': args.expected_spec_sha256,
              'elapsed_seconds': round(time.monotonic() - started, 3)}
    (artifact / 'payload-manifest.json').write_bytes(generated[MANIFEST_NAME])
    (artifact / 'build-report.json').write_bytes(helpers.json_bytes(report))
    (release / 'DeepSteam-Package-Manifest.json').write_bytes(helpers.json_bytes(report))
    print(json.dumps({'build_report': str(artifact / 'build-report.json'),
                      'distribution_files': distribution, 'published_to_e': False,
                      'cold_start_validated': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
