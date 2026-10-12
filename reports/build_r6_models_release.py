"""Build the reviewed r6 program delta over the immutable public r5 payload.

Only public manifests, a verified official tzdata wheel and frozen build files
are inputs. Models/runtime dependencies are copied as compressed ZIP records.
Never reads an installed user's data or starts application/model services.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2026.10.12-r6-models'
ARTIFACT = ROOT / 'installer/r6-models-20261012'
INPUTS = ROOT / 'installer/r6-models-inputs-20261012'
SPEC = ROOT / 'reports/r6-models-spec-20261012.json'
WHEEL = ROOT / 'downloads/tzdata-2026.5-py2.py3-none-any.whl'
WHEEL_SHA = 'b683bd1b6659ddcd810ff02ad09ba821d4bf1065072805063eb35c49617905ac'
BASELINE = ROOT / 'installer/r5-unified-visual-release-20261012/release/DeepSteam-Setup-2026.10.12-r5-visual-x64.payload.dat'
BASELINE_SHA = '7681d7ef164bab5aa91ddc20dda7e928af6bc2223c509b3cffde4d61d05a596d'
BASELINE_MANIFEST_SHA = 'b0e29849ea46cc6f066475cb5cb04fc7498c59f6ed737e6f28bc44d3b83aecee'
OM = 'runtime/openmaic-standalone/'
PYTHON = 'runtime/python/Lib/site-packages/'
OVERLAY = 'runtime/deeptutor-packages/'
NATIVE = 'runtime/native-frontends/'
module = importlib.util.spec_from_file_location('r6_verified_zip_helpers', ROOT / 'installer/build_r4_candidate.py')
h = importlib.util.module_from_spec(module)
module.loader.exec_module(h)


def descriptor(path):
    path = Path(path)
    return {'source': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size, 'sha256': h.digest(path)}


def write_new(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(contents if isinstance(contents, bytes) else h.json_bytes(contents))


def program_target(name):
    h.safe_name(name)
    parts = {p.casefold() for p in PurePosixPath(name).parts}
    if (parts.intersection({'.dsh', '.deepseek', 'browser-profile', 'userdata', 'harness-state'})
            or PurePosixPath(name).name.casefold() in {'control-token', 'account-state.json', 'credentials.json', 'cookies.json', 'auth.json', 'runtime.json'}
            or name.startswith(('runtime/desktop/profile/', 'runtime/desktop/sessions/',
                                'runtime/harness/profile/', 'runtime/harness/sessions/'))):
        raise RuntimeError('Private runtime state is not distributable: ' + name)
    if name in {'runtime/native-frontend.json', OM + 'server.js'}:
        return
    if name in {'installer/document-runtime-requirements.txt', 'installer/document-runtime-lock.json',
                'installer/document-fixtures/scanned-cn.png', 'installer/prepare_install.py'}:
        return
    if name.startswith(('integration/', 'portal/', 'scripts/')) and PurePosixPath(name).suffix in {'.py', '.mjs', '.cjs', '.js'}:
        return
    if name.startswith((PYTHON + 'deeptutor/', OVERLAY + 'deeptutor/')) and PurePosixPath(name).suffix in {'.py', '.yaml'}:
        return
    if name.startswith((NATIVE, OM + '.next/', OM + 'public/')):
        return
    if name.startswith(PYTHON + 'tzdata/') or name.startswith(PYTHON + 'tzdata-2026.5.dist-info/'):
        return
    if name.startswith('runtime/harness/') and len(PurePosixPath(name).parts) == 3 and PurePosixPath(name).suffix in {'.mjs', '.py'}:
        return
    raise RuntimeError('Not an explicitly allowed program target: ' + name)


def read_baseline(check_digest=True):
    if check_digest and h.digest(BASELINE) != BASELINE_SHA:
        raise RuntimeError('Verified public baseline changed')
    with BASELINE.open('rb') as stream:
        stream.seek(-64, 2)
        magic, offset, length, digest = struct.unpack('<16sQQ32s', stream.read(64))
    if magic.rstrip(b'\0') != h.TRAILER_MAGIC or offset != 0 or length + 64 != BASELINE.stat().st_size:
        raise RuntimeError('Baseline companion trailer is invalid')
    with zipfile.ZipFile(BASELINE) as archive:
        blob = archive.read(h.MANIFEST_NAME)
        if hashlib.sha256(blob).hexdigest() != BASELINE_MANIFEST_SHA:
            raise RuntimeError('Baseline public manifest changed')
        manifest = json.loads(blob)
        rows = h.rows_by_path(manifest)
        if len(archive.infolist()) != len(rows) + 1 or set(archive.namelist()) != set(rows) | {h.MANIFEST_NAME}:
            raise RuntimeError('Baseline archive membership differs')
        metadata = {name: json.loads(archive.read(name)) for name in (
            'installer/junctions.json', 'runtime/native-frontend.json', 'installer/frontend-payload-manifest.json')}
    return rows, metadata


def prepare_timezone():
    if h.digest(WHEEL) != WHEEL_SHA or WHEEL.stat().st_size != 347996:
        raise RuntimeError('Official tzdata wheel differs')
    selected = {}
    with zipfile.ZipFile(WHEEL) as wheel:
        if wheel.testzip() is not None:
            raise RuntimeError('tzdata wheel CRC failed')
        names = wheel.namelist()
        if not names or any(PurePosixPath(n).parts[0] not in {'tzdata', 'tzdata-2026.5.dist-info'} for n in names):
            raise RuntimeError('Unexpected timezone wheel contents')
        for name in names:
            h.safe_name(name)
            target = INPUTS / 'tzdata-site' / name
            blob = wheel.read(name)
            if target.exists():
                if target.read_bytes() != blob:
                    raise RuntimeError('Existing staged timezone file differs')
            else:
                write_new(target, blob)
            selected[PYTHON + name] = {'path': PYTHON + name, **descriptor(target)}
    return selected


def prepare(args):
    if SPEC.exists():
        raise RuntimeError('The r6 specification must be fresh')
    baseline, metadata = read_baseline()
    receipts = []
    selected = {}
    for name in [args.program_manifest, args.dependency_manifest, *args.extra_manifest]:
        path = h.workspace_path(name)
        value = json.loads(path.read_text('utf8'))
        if value.get('user_data_copied') is not False or value.get('credentials_copied') is not False:
            raise RuntimeError('Only public program manifests may be used')
        receipts.append(descriptor(path))
        for row in value['files']:
            program_target(row['target'])
            source = h.checked_file(row)
            selected[row['target']] = {'path': row['target'], **descriptor(source)}
    native_path = h.workspace_path(args.native_receipt)
    native = json.loads(native_path.read_text('utf8'))
    build_id = native['build_id']
    if not re.fullmatch(r'\d{8}-\d{6}', build_id):
        raise RuntimeError('A final native build receipt is required')
    native_root = NATIVE + build_id + '/'
    selected = {k: v for k, v in selected.items() if not k.startswith(NATIVE) or k.startswith(native_root)}
    selected.pop('runtime/native-frontend.json', None)
    if native_root + 'server.js' not in selected:
        raise RuntimeError('Final native manifest not supplied')
    native_dist = h.next_dist_dir(h.checked_file(selected[native_root + 'server.js']).read_bytes())
    if native_root + native_dist + '/BUILD_ID' not in selected:
        raise RuntimeError('Final native BUILD_ID missing')
    om_id = h.checked_file(selected[OM + '.next/BUILD_ID']).read_text('utf8').strip()
    if om_id != 'TsCMZsnb68I61xgsBBwNV':
        raise RuntimeError('Wrong final OpenMAIC build')
    # Existing complete dependencies remain in the baseline; verify the exact
    # package metadata for every alias traced by this changed OM build.
    original = json.loads(h.workspace_path(args.program_manifest).read_text('utf8'))
    for alias in original.get('verified_existing_dependency_aliases', []):
        target = OM + alias['installed_relative_target'] + '/package.json'
        if baseline.get(target, {}).get('sha256') != alias['package_sha256']:
            raise RuntimeError('OpenMAIC dependency baseline differs: ' + target)
    selected.update(prepare_timezone())
    old_id = metadata['runtime/native-frontend.json']['build_id']
    links = []
    for link in metadata['installer/junctions.json']:
        links.append({key: value.replace(NATIVE + old_id + '/', native_root) if key in {'path', 'target'} else value for key, value in link.items()})
    # Latest native build's explicit package targets must agree with the old
    # dependency closure after relocation; no links escape the package.
    removed_prefixes = [NATIVE, OM + '.next/', OM + 'public/']
    rows = {k: dict(v) for k, v in baseline.items() if not any(k.startswith(p) for p in removed_prefixes)}
    rows.update({k: {x: v[x] for x in ('path', 'bytes', 'sha256')} for k, v in selected.items()})
    h.validate_junctions(links, rows)
    acceptance = h.workspace_path(args.acceptance)
    if json.loads(acceptance.read_text('utf8')).get('passed') is not True:
        raise RuntimeError('Current root software acceptance must have passed')
    plan = {'kind': 'deepsteam-r6-models-frozen-package', 'version': VERSION,
            'artifact': ARTIFACT.relative_to(ROOT).as_posix(),
            'baseline': {'source': BASELINE.relative_to(ROOT).as_posix(), 'bytes': BASELINE.stat().st_size,
                         'sha256': BASELINE_SHA, 'manifest_sha256': BASELINE_MANIFEST_SHA},
            'inputs': receipts, 'native_receipt': descriptor(native_path), 'native': native,
            'openmaic_next_build_id': om_id, 'tzdata_wheel': descriptor(WHEEL),
            'files': sorted(selected.values(), key=lambda r: r['path']),
            'replace_prefixes': removed_prefixes, 'junctions': links,
            'installer_source': descriptor(ROOT / 'installer/DeepSteamSetup.cs'),
            'windows_manifest': descriptor(ROOT / 'installer/DeepSteam.manifest'),
            'feature_acceptance': descriptor(acceptance),
            'deferred_validation': ['fresh_cloud_inference', 'real_api_key', 'fresh_classroom_generation', 'second_physical_computer', 'fresh_full_cold_install'],
            'user_data_copied': False, 'credentials_copied': False, 'models_downloaded': False,
            'old_complete_dependencies_reused': True}
    write_new(SPEC, plan)
    print(json.dumps({'spec': descriptor(SPEC), 'overlay_files': len(selected),
                      'overlay_bytes': sum(r['bytes'] for r in selected.values()), 'full_build_performed': False}), flush=True)


def load_plan(expected):
    if h.digest(SPEC) != expected:
        raise RuntimeError('Frozen r6 specification changed')
    plan = json.loads(SPEC.read_text('utf8'))
    if plan['version'] != VERSION or plan['artifact'] != ARTIFACT.relative_to(ROOT).as_posix():
        raise RuntimeError('Unexpected release identity')
    baseline, metadata = read_baseline()
    for record in [*plan['inputs'], *plan.get('extra_share_files', []), plan['native_receipt'], plan['tzdata_wheel'], plan['feature_acceptance'],
                   plan['installer_source'], plan['windows_manifest']]:
        h.checked_file(record)
    removed_files = set(plan.get('remove_files', []))
    for name in removed_files:
        h.safe_name(name)
    rows = {k: dict(v) for k, v in baseline.items()
            if k not in removed_files and not any(k.startswith(p) for p in plan['replace_prefixes'])}
    sources = {}
    for row in plan['files']:
        name = row['path']
        program_target(name)
        if name in sources:
            raise RuntimeError('Duplicate overlay target')
        sources[name] = h.checked_file(row)
        rows[name] = {k: row[k] for k in ('path', 'bytes', 'sha256')}
    if plan.get('kind') == 'deepsteam-document-delivery-frozen-package-v1':
        if 'validate_document_rows' not in globals():
            raise RuntimeError('Document release validation requires the current document builder')
        validate_document_rows(rows)
    h.validate_junctions(plan['junctions'], rows)
    # Every changed Python source must be present in both actual import roots.
    for name in sources:
        if name.startswith((OVERLAY + 'deeptutor/', PYTHON + 'deeptutor/')):
            partner = (PYTHON + name.removeprefix(OVERLAY) if name.startswith(OVERLAY)
                       else OVERLAY + name.removeprefix(PYTHON))
            if rows.get(partner, {}).get('sha256') != rows[name]['sha256']:
                raise RuntimeError('Python primary/overlay disagreement: ' + name)
    for module in ('services/config/provider_runtime.py', 'services/model_selection/llm.py'):
        primary, overlay = PYTHON + 'deeptutor/' + module, OVERLAY + 'deeptutor/' + module
        expected = h.digest(ROOT / 'upstream/DeepTutor/deeptutor' / module)
        if any(name not in sources or rows[name]['sha256'] != expected for name in (primary, overlay)):
            raise RuntimeError('Required model dependency patch missing: ' + module)
    for module in ('sidecar.mjs', 'workspaces.mjs', 'workspace_http.mjs'):
        primary, source = 'runtime/harness/' + module, 'integration/harness/' + module
        if any(name not in sources for name in (primary, source)) or rows[primary]['sha256'] != rows[source]['sha256']:
            raise RuntimeError('Required executable Harness source mapping missing: ' + module)
    if 'scripts/workspace_document_reader.py' in rows:
        contract = plan.get('document_runtime')
        if not isinstance(contract, dict):
            raise RuntimeError('Document releases require a frozen document runtime contract')
        for record in contract.values():
            h.checked_file(record)
        document = load_document_gate()
        document.check_rows(rows, h.checked_file(contract['dependency_manifest']))
        for name, key in [('scripts/check_document_runtime.py', 'probe'),
                          ('installer/document-runtime-requirements.txt', 'requirements'),
            ('installer/document-fixtures/scanned-en.png', 'scan_fixture')]:
            source = h.checked_file(contract[key])
            sources[name] = source
            rows[name] = h.file_row(name, source.read_bytes())
    return plan, baseline, metadata, rows, sources


def load_document_gate():
    specification = importlib.util.spec_from_file_location('release_document_runtime', ROOT / 'installer/document_runtime.py')
    document = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(document)
    return document


def build(args):
    started = time.monotonic()
    plan, baseline, metadata, rows, sources = load_plan(args.expected_spec_sha256)
    if args.validate_only:
        print(json.dumps({'spec_validated': True, 'files': len(rows), 'full_build_performed': False}), flush=True)
        return
    if ARTIFACT.exists():
        raise RuntimeError('A fresh candidate directory is required')
    ARTIFACT.mkdir()
    release = ARTIFACT / 'release'
    release.mkdir()
    csharp = ARTIFACT / 'DeepSteamSetup-r6.cs'
    text = h.checked_file(plan['installer_source']).read_text('utf8')
    anchor = 'internal const string Version = "2026.10.10-r3";'
    if text.count(anchor) != 1:
        raise RuntimeError('Installer version anchor differs')
    write_new(csharp, text.replace(anchor, f'internal const string Version = "{VERSION}";', 1).encode('utf8'))
    exe = release / f'DeepSteam-Setup-{VERSION}-x64.exe'
    h.compile_installer(csharp, h.checked_file(plan['windows_manifest']), exe)
    native = dict(plan['native'])
    native.update(root=NATIVE + native['build_id'], server=NATIVE + native['build_id'] + '/server.js')
    generated = {'DeepSteam.exe': exe.read_bytes(), 'installer/DeepSteamSetup.cs': csharp.read_bytes(),
                 'installer/DeepSteam.manifest': h.checked_file(plan['windows_manifest']).read_bytes(),
                 'installer/junctions.json': h.json_bytes(plan['junctions']),
                 'runtime/native-frontend.json': h.json_bytes(native)}
    if plan.get('document_runtime'):
        generated['installer/document-runtime-lock.json'] = h.json_bytes(load_document_gate().check_rows(rows))
    for name in (native['server'], OM + 'server.js'):
        generated[name] = h.server_entry_policy(sources[name].read_bytes())
    for name, blob in generated.items():
        rows[name] = h.file_row(name, blob)
    frontend = dict(metadata['installer/frontend-payload-manifest.json'])
    # This OM build receipt identifies the actual Next build, not a timestamp.
    frontend.pop('openmaic_build_id', None)
    frontend.update(version=VERSION, native_build_id=native['build_id'],
                    openmaic_next_build_id=plan['openmaic_next_build_id'], tzdata_version='2026.5',
                    credentials_and_user_data_copied=False,
                    components=[h.component_inventory(prefix, rows) for prefix in (
                        native['root'], OM.rstrip('/'), 'runtime/render-service', 'runtime/desktop', 'runtime/harness')])
    generated['installer/frontend-payload-manifest.json'] = h.json_bytes(frontend)
    rows['installer/frontend-payload-manifest.json'] = h.file_row('installer/frontend-payload-manifest.json', generated['installer/frontend-payload-manifest.json'])
    manifest = {'version': VERSION, 'platform': 'win-x64', 'file_count': len(rows),
                'uncompressed_bytes': sum(r['bytes'] for r in rows.values()),
                'files': sorted(rows.values(), key=lambda r: r['path'])}
    generated[h.MANIFEST_NAME] = h.json_bytes(manifest)
    replacements = {name: source for name, source in sources.items() if rows[name] != baseline.get(name)}
    replacements.update(generated)
    removed = set(baseline) - set(rows)
    archive = ARTIFACT / 'payload-r6.zip'
    print(json.dumps({'phase': 'repackage', 'replacement_files': len(replacements), 'removed_files': len(removed)}), flush=True)
    reuse = h.repackage(BASELINE, archive, replacements, removed)
    verified = h.verify_archive(archive, rows, generated[h.MANIFEST_NAME])
    length, digest = archive.stat().st_size, h.digest(archive)
    payload = exe.with_suffix('.payload.dat')
    # Only this fresh candidate's temporary archive is renamed, never a prior package.
    if archive.resolve().parent != ARTIFACT.resolve() or payload.exists():
        raise RuntimeError('Unexpected temporary archive promotion path')
    os.rename(archive, payload)
    with payload.open('ab') as stream:
        stream.write(struct.pack('<16sQQ32s', h.TRAILER_MAGIC, 0, length, bytes.fromhex(digest)))
    self_test = ARTIFACT / 'actual-windows-container-self-test.txt'
    subprocess.run([str(exe), '--self-test', str(self_test)], check=True, timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
    document_acceptance = None
    if plan.get('document_runtime'):
        document_report = ARTIFACT / 'packaged-document-runtime-acceptance.json'
        load_document_gate().verify_archive_runtime(payload, ROOT / 'runtime', document_report)
        document_acceptance = descriptor(document_report)
    write_new(ARTIFACT / 'payload-manifest.json', generated[h.MANIFEST_NAME])
    write_new(ARTIFACT / 'spec.json', SPEC.read_bytes())
    report = {'kind': 'deepsteam-r6-models-build', 'version': VERSION,
              'native_build_id': native['build_id'], 'openmaic_next_build_id': plan['openmaic_next_build_id'],
              'tzdata_version': '2026.5', 'spec': descriptor(SPEC),
              'distribution_files': [descriptor(exe), descriptor(payload)],
              'payload_container': {'bytes': length, 'sha256': digest, 'trailer_bytes': 64},
              'raw_archive_reuse': reuse, 'files_sha_verified': verified,
              'all_file_sha_passed': True, 'crc_passed': True, 'actual_exe_self_test_passed': True,
              'packaged_document_runtime_acceptance': document_acceptance,
              'feature_acceptance': plan['feature_acceptance'], 'deferred_validation': plan['deferred_validation'],
              'user_data_copied': False, 'credentials_copied': False, 'models_downloaded': False,
              'duplicate_raw_archive_retained': False, 'written_to_e': False,
              'elapsed_seconds': round(time.monotonic() - started, 2)}
    write_new(ARTIFACT / 'build-report.json', report)
    print(json.dumps({'build_report': descriptor(ARTIFACT / 'build-report.json'), 'distribution': report['distribution_files']}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--prepare-timezone', action='store_true')
    parser.add_argument('--program-manifest', default='reports/local-management-program-manifest.json')
    parser.add_argument('--dependency-manifest', default='reports/local-management-dependency-patch.json')
    parser.add_argument('--extra-manifest', action='append', default=[])
    parser.add_argument('--native-receipt')
    parser.add_argument('--acceptance', default='reports/local-management-runtime-acceptance.json')
    parser.add_argument('--expected-spec-sha256')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if args.prepare_timezone:
        rows = prepare_timezone()
        print(json.dumps({'tzdata_files': len(rows), 'tzdata_bytes': sum(r['bytes'] for r in rows.values()), 'wheel': descriptor(WHEEL)}), flush=True)
    elif args.prepare:
        if not args.native_receipt:
            parser.error('--prepare needs the final --native-receipt')
        prepare(args)
    else:
        if not args.expected_spec_sha256:
            parser.error('Build/validation needs --expected-spec-sha256')
        build(args)


if __name__ == '__main__':
    main()
