"""Build a new D-only r4 candidate from a frozen, corrected r3 archive.

Never invokes the legacy builder's main(), overwrites r3 artifacts, installs,
starts services, accesses user state, downloads, or publishes to E. Root must
freeze a SHA-pinned spec and feature acceptance before invoking this entry.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import time
import zipfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
VERSION = '2026.10.11-r4'
MANIFEST_NAME = 'installer/payload-manifest.json'
BLOCK = 8 * 1024 * 1024
CSC = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
TRAILER_MAGIC = b'DeepSteamZip64v1'
COMPONENT_TARGETS = {
    'openmaic': 'runtime/openmaic-standalone', 'render': 'runtime/render-service',
    'ffmpeg': 'runtime/ffmpeg', 'tts': 'runtime/tts', 'fonts': 'runtime/fonts',
    'portal': 'portal', 'integration': 'integration', 'scripts': 'scripts',
    'demo': 'demo', 'licenses': 'licenses',
}
SOURCE_FILE_PREFIXES = ('portal/', 'integration/', 'scripts/', 'demo/', 'licenses/', 'installer/')
SOURCE_FILE_NAMES = {'README.md', 'HANDOFF.md', 'requirements-demo.txt', 'INSTALLATION.txt',
                     'reports/demo-lesson-video.mp4', 'reports/demo-lesson-video.json'}
GENERATED_NAMES = {MANIFEST_NAME, 'DeepSteam.exe', 'installer/DeepSteamSetup.cs',
                   'installer/DeepSteam.manifest', 'installer/frontend-payload-manifest.json',
                   'installer/junctions.json', 'runtime/native-frontend.json'}


def native_path(path):
    value = str(path)
    return value if os.name != 'nt' or value.startswith('\\\\?\\') else '\\\\?\\' + value


def digest(path):
    with open(native_path(path), 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def safe_name(name):
    if not isinstance(name, str):
        raise RuntimeError('Payload path must be text')
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name
            or path.is_absolute() or '..' in path.parts or path.as_posix() != name):
        raise RuntimeError('Unsafe payload-relative path: ' + str(name))
    if (name.startswith(('data/', 'logs/', 'cache/', 'runtime/deeptutor-home/', 'runtime/temp/',
                         'runtime/openmaic-standalone/data/', 'runtime/render-service/.local/',
                         'integration/local_qwen/downloads/'))
            or name in {'deepsteam-storage.json', 'runtime/local-qwen/process.json'}
            or any(part == '.env' or part.startswith('.env.') for part in path.parts)
            or name.endswith(('.partial', '.pyc', '.pyo'))):
        raise RuntimeError('Private, mutable, or incomplete file forbidden: ' + name)
    return name


def workspace_path(name):
    safe_name(name)
    path = ROOT / name
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT.resolve()) or resolved.drive.upper() != 'D:':
        raise RuntimeError('Frozen source must remain within the D workspace: ' + name)
    return path


def checked_file(row):
    source = workspace_path(row['source'])
    if (not re.fullmatch(r'[0-9a-f]{64}', row['sha256']) or not source.is_file()
            or source.is_symlink() or source.is_junction()
            or digest(source) != row['sha256']):
        raise RuntimeError('Frozen source SHA changed: ' + str(source))
    if 'bytes' in row and source.stat().st_size != row['bytes']:
        raise RuntimeError('Frozen source length changed: ' + str(source))
    return source


def file_row(name, contents):
    safe_name(name)
    return {'path': name, 'bytes': len(contents), 'sha256': hashlib.sha256(contents).hexdigest()}


def rows_by_path(manifest):
    rows = {}
    for row in manifest['files']:
        safe_name(row['path'])
        if row['path'] == MANIFEST_NAME or row['path'] in rows:
            raise RuntimeError('Manifest has a self-entry or duplicate path')
        if not isinstance(row['bytes'], int) or row['bytes'] < 0 or not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
            raise RuntimeError('Invalid manifest file row')
        rows[row['path']] = dict(row)
    if (manifest['file_count'] != len(rows)
            or manifest['uncompressed_bytes'] != sum(row['bytes'] for row in rows.values())):
        raise RuntimeError('Manifest totals disagree with its entries')
    return rows


def collect_tree(source, target=None):
    """Only staged regular files; no implicit traversal of pnpm junctions."""
    rows = []
    for directory, dirs, files in os.walk(native_path(source), followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in {'__pycache__', '.pytest_cache', '.git'})
        for name in dirs + files:
            path = Path(directory) / name
            if os.path.islink(str(path)) or os.path.isjunction(str(path)):
                raise RuntimeError('Stage contains a reparse point: ' + str(path))
        for name in sorted(files):
            if name.endswith(('.pyc', '.pyo')):
                continue
            path = Path(directory) / name
            relative = os.path.relpath(str(path), native_path(source)).replace('\\', '/')
            safe_name(relative)
            if target:
                safe_name(target + '/' + relative)
            rows.append({'path': relative, 'bytes': os.stat(str(path)).st_size, 'sha256': digest(path)})
    return sorted(rows, key=lambda row: row['path'])


def component_prefix(component, native_build_id):
    name, target = component['name'], component['target']
    safe_name(target)
    if name == 'native':
        if target != 'runtime/native-frontends/' + native_build_id:
            raise RuntimeError('Native component target differs from frozen build ID')
        return 'runtime/native-frontends/'
    if name not in COMPONENT_TARGETS or target != COMPONENT_TARGETS[name]:
        raise RuntimeError('Component outside the fixed distributable scope: ' + name)
    return target + '/'


def merge_rows(baseline, components, explicit_rows, native_build_id):
    """Authoritative component inventories remove obsolete chunks and assets."""
    rows = {name: dict(row) for name, row in baseline.items()}
    prefixes, removed = [], []
    for component in components:
        prefix = component_prefix(component, native_build_id)
        if any(prefix.startswith(other) or other.startswith(prefix) for other in prefixes):
            raise RuntimeError('Overlapping component replacement prefixes')
        prefixes.append(prefix)
        obsolete = [name for name in rows if name.startswith(prefix)]
        removed.extend(obsolete)
        for name in obsolete:
            del rows[name]
        inventory = component['rows']
        seen = set()
        for row in inventory:
            relative = safe_name(row['path'])
            target = safe_name(component['target'] + '/' + relative)
            if relative in seen:
                raise RuntimeError('Duplicate component inventory path')
            seen.add(relative)
            rows[target] = {**row, 'path': target}
        if not inventory:
            raise RuntimeError('Empty authoritative component inventory')
    seen = set()
    for row in explicit_rows:
        name = safe_name(row['path'])
        if name in seen:
            raise RuntimeError('Duplicate explicit replacement')
        seen.add(name)
        rows[name] = dict(row)
    return rows, sorted(set(removed) - set(rows))


def validate_junctions(links, rows):
    directories = set()
    for name in rows:
        parent = PurePosixPath(name).parent
        while parent.as_posix() != '.':
            directories.add(parent.as_posix())
            parent = parent.parent
    seen = set()
    for row in links:
        name, target = safe_name(row['path']), safe_name(row['target'])
        if name in seen or name in rows or name in directories:
            raise RuntimeError('Duplicate junction or junction collides with regular staged path')
        seen.add(name)
        if not name.startswith(('runtime/native-frontends/', 'runtime/openmaic-standalone/', 'runtime/render-service/')):
            raise RuntimeError('Junction outside the frontend dependency scope')
        if target not in directories:
            raise RuntimeError('Junction target is absent from the complete candidate: ' + target)


def versioned_installer_source(source):
    anchor = 'internal const string Version = "2026.10.10-r3";'
    if source.count(anchor) != 1:
        raise RuntimeError('Unexpected installer version structure; no speculative patch')
    return source.replace(anchor, 'internal const string Version = "' + VERSION + '";', 1)


def server_entry_policy(contents):
    source = contents.decode('utf-8')
    marker = '// DeepSteam modification 2026-10-11: separate-storage image disk cache policy.'
    anchor = 'process.env.__NEXT_PRIVATE_STANDALONE_CONFIG = JSON.stringify(nextConfig)'
    injection = (marker + '\n' + "if (process.env.DEEPSTEAM_SEPARATE_STORAGE === '1') {\n"
                 '  nextConfig.images = { ...nextConfig.images, maximumDiskCacheSize: 0 };\n}\n\n')
    if source.count(anchor) != 1 or source.count('const nextConfig = ') != 1:
        raise RuntimeError('Unexpected generated standalone entry structure')
    if marker in source:
        if source.count(marker) != 1 or injection not in source:
            raise RuntimeError('Existing Next image cache policy differs from reviewed injection')
        return contents
    return source.replace(anchor, injection + anchor, 1).encode('utf-8')


def next_dist_dir(contents):
    source = contents.decode('utf-8')
    anchor = 'const nextConfig = '
    if source.count(anchor) != 1:
        raise RuntimeError('Unexpected standalone Next configuration')
    configuration, end = json.JSONDecoder().raw_decode(source.split(anchor, 1)[1])
    value = configuration.get('distDir', '.next')
    value = value[2:] if value.startswith('./') else value
    if value not in {'.next', '.next-contest-native'}:
        raise RuntimeError('Unexpected standalone Next dist directory')
    return value


def compile_installer(source, manifest, destination):
    command = [str(CSC), '/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/codepage:65001',
               '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
               '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
               '/win32manifest:' + str(manifest), '/resource:' + str(source) + ',DeepSteamSetup.cs',
               '/out:' + str(destination), str(source)]
    subprocess.run(command, check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def without_zip64_extra(extra):
    result, offset = bytearray(), 0
    while offset < len(extra):
        if len(extra) - offset < 4:
            raise RuntimeError('Truncated ZIP extra field')
        identifier, length = struct.unpack_from('<HH', extra, offset)
        end = offset + 4 + length
        if end > len(extra):
            raise RuntimeError('ZIP extra field exceeds bounds')
        if identifier != 1:
            result.extend(extra[offset:end])
        offset = end
    return bytes(result)


def repackage(source_path, target_path, replacements, removed):
    copied_count = copied_bytes = 0
    removed = set(removed)
    if removed.intersection(replacements):
        raise RuntimeError('Replacement also marked for removal')
    with zipfile.ZipFile(source_path) as source:
        entries = source.infolist()
        names = {entry.filename for entry in entries}
        if len(names) != len(entries) or not removed.issubset(names):
            raise RuntimeError('Duplicate source entries or unknown removal')
        ordered = sorted(entries, key=lambda entry: entry.header_offset)
        if not ordered or ordered[0].header_offset != 0:
            raise RuntimeError('Only reviewed zero-prefix ZIP payloads supported')
        for entry in entries:
            safe_name(entry.filename)
            if entry.flag_bits & 1 or (entry.external_attr >> 16 & 0xF000) == 0xA000:
                raise RuntimeError('Encrypted/symbolic ZIP entry forbidden')
        with zipfile.ZipFile(target_path, 'x', zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as target:
            for index, entry in enumerate(ordered):
                end = ordered[index + 1].header_offset if index + 1 < len(ordered) else source.start_dir
                length = end - entry.header_offset
                if length < 30 or end > source.start_dir:
                    raise RuntimeError('Invalid local ZIP record bounds')
                if entry.filename in replacements or entry.filename in removed:
                    continue
                source.fp.seek(entry.header_offset)
                if source.fp.read(4) != b'PK\x03\x04':
                    raise RuntimeError('Invalid local ZIP header')
                source.fp.seek(entry.header_offset)
                copied = copy.copy(entry)
                copied.header_offset = target.fp.tell()
                remaining = length
                while remaining:
                    block = source.fp.read(min(BLOCK, remaining))
                    if not block:
                        raise RuntimeError('Truncated raw ZIP record')
                    target.fp.write(block)
                    remaining -= len(block)
                target.filelist.append(copied)
                target.NameToInfo[copied.filename] = copied
                target.start_dir = target.fp.tell()
                target._didModify = True
                copied_count += 1
                copied_bytes += length
            for name, value in sorted(replacements.items()):
                safe_name(name)
                if isinstance(value, Path):
                    target.write(native_path(value), name, compress_type=zipfile.ZIP_DEFLATED, compresslevel=3)
                else:
                    updated = copy.copy(source.getinfo(name)) if name in names else zipfile.ZipInfo(name)
                    updated.flag_bits &= ~8
                    updated.extra = without_zip64_extra(updated.extra)
                    target.writestr(updated, value, compress_type=zipfile.ZIP_DEFLATED, compresslevel=3)
    return {'unchanged_raw_records_reused': copied_count, 'unchanged_raw_bytes_reused': copied_bytes,
            'replaced_or_added_paths': sorted(replacements), 'removed_paths': sorted(removed),
            'models_recompressed': False}


def append_companion(path, archive):
    actual, length = hashlib.sha256(), 0
    with path.open('xb') as output, archive.open('rb') as source:
        while block := source.read(BLOCK):
            output.write(block)
            actual.update(block)
            length += len(block)
        output.write(struct.pack('<16sQQ32s', TRAILER_MAGIC, 0, length, actual.digest()))
    return {'format': 'companion-zip64-v1', 'offset': 0, 'bytes': length,
            'sha256': actual.hexdigest(), 'trailer_bytes': 64, 'filename': path.name}


def verify_archive(archive, rows, manifest_bytes):
    """Read every entry to EOF: ZipFile checks CRC, then compare full SHA256."""
    with zipfile.ZipFile(archive) as checked:
        if len(checked.infolist()) != len(rows) + 1 or set(checked.namelist()) != set(rows) | {MANIFEST_NAME}:
            raise RuntimeError('Final archive entries differ from authoritative complete manifest')
        for name, row in sorted(rows.items()):
            if checked.getinfo(name).file_size != row['bytes']:
                raise RuntimeError('Final file length differs from complete manifest: ' + name)
            with checked.open(name) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != row['sha256']:
                    raise RuntimeError('Final file SHA differs from complete manifest: ' + name)
        if checked.read(MANIFEST_NAME) != manifest_bytes:
            raise RuntimeError('Final archive factory manifest differs')
    return len(rows)


def validate_feature_receipt(receipt):
    if any(receipt.get(name) is not True for name in (
            'slides_layout_passed', 'explanations_complete', 'full_narrated_video_passed')):
        raise RuntimeError('Root must confirm all three complete classroom/video gates')
    coverage = receipt.get('narration_coverage', {})
    if (not isinstance(coverage.get('total'), int) or coverage['total'] <= 0
            or coverage.get('written') != coverage['total']):
        raise RuntimeError('Full narration requires positive 100 percent action coverage')
    if receipt.get('video_has_audio') is not True or not receipt.get('video_duration_seconds', 0) > 0:
        raise RuntimeError('A real completed narrated media result is required')


def component_inventory(target, rows):
    selected = [row for row in rows.values() if row['path'].startswith(target + '/')]
    actual = hashlib.sha256()
    for row in sorted(selected, key=lambda item: item['path']):
        actual.update(row['path'][len(target) + 1:].encode('utf-8'))
        actual.update(bytes.fromhex(row['sha256']))
    return {'path': target, 'files': len(selected), 'bytes': sum(row['bytes'] for row in selected),
            'inventory_sha256': actual.hexdigest(), 'inventory_order': 'sorted-relative-path'}


def load_plan(spec):
    if spec.get('version') != VERSION or not re.fullmatch(r'r4-[a-z0-9-]+', spec['artifact_name']):
        raise RuntimeError('A fresh r4 installer-child artifact and exact version required')
    baseline_path = checked_file(spec['baseline'])
    with zipfile.ZipFile(baseline_path) as archive:
        manifest_bytes = archive.read(MANIFEST_NAME)
        if hashlib.sha256(manifest_bytes).hexdigest() != spec['baseline']['manifest_sha256']:
            raise RuntimeError('Frozen baseline factory manifest changed')
        manifest = json.loads(manifest_bytes)
        baseline = rows_by_path(manifest)
        if set(archive.namelist()) != set(baseline) | {MANIFEST_NAME}:
            raise RuntimeError('Baseline ZIP entries differ from complete manifest')
        old_native = json.loads(archive.read('runtime/native-frontend.json'))
    if manifest['version'] != '2026.10.10-r3':
        raise RuntimeError('Expected the preserved corrected r3 baseline')
    native_id = spec['builds']['native']['build_id']
    om_id = spec['builds']['openmaic']['build_id']
    if not all(re.fullmatch(r'\d{8}-\d{6}', value) for value in (native_id, om_id)):
        raise RuntimeError('Explicit native/OpenMAIC immutable build IDs required')
    components, sources, explicit = [], {}, []
    seen = set()
    for original in spec['components']:
        component = dict(original)
        if component['name'] in seen:
            raise RuntimeError('Repeated component name')
        seen.add(component['name'])
        component_prefix(component, native_id)
        source = workspace_path(component['source'])
        inventory_path = checked_file(component['inventory'])
        inventory = json.loads(inventory_path.read_text('utf-8'))
        if inventory.get('source') != component['source'] or inventory.get('target') != component['target']:
            raise RuntimeError('Inventory source/target identity differs from spec')
        actual_rows = collect_tree(source, component['target'])
        if actual_rows != inventory['files']:
            raise RuntimeError('Staged component changed since its frozen complete inventory')
        if (inventory.get('file_count') != len(actual_rows)
                or inventory.get('uncompressed_bytes') != sum(row['bytes'] for row in actual_rows)):
            raise RuntimeError('Component inventory totals disagree')
        component['rows'] = actual_rows
        components.append(component)
        for row in actual_rows:
            sources[component['target'] + '/' + row['path']] = source / row['path']
    if native_id != old_native['build_id'] and 'native' not in seen:
        raise RuntimeError('New native build lacks complete replacement inventory')
    if 'native' in seen and native_id == old_native['build_id']:
        raise RuntimeError('Modified native component must use a new immutable build ID')
    if 'openmaic' not in seen:
        raise RuntimeError('r4 classroom change requires its new complete OpenMAIC inventory')
    om_source = workspace_path(next(item['source'] for item in components if item['name'] == 'openmaic'))
    if ((om_source / '.next/BUILD_ID').read_text('utf-8').strip() != spec['builds']['openmaic']['next_build_id']
            or not (om_source / 'server.js').is_file()):
        raise RuntimeError('Actual OpenMAIC standalone identity differs')
    if 'native' in seen:
        native_source = workspace_path(next(item['source'] for item in components if item['name'] == 'native'))
        if not (native_source / 'server.js').is_file():
            raise RuntimeError('New native standalone is incomplete')
        native_dist = next_dist_dir((native_source / 'server.js').read_bytes())
        if not (native_source / native_dist / 'BUILD_ID').is_file():
            raise RuntimeError('New native standalone lacks its configured BUILD_ID')
    for row in spec.get('files', []):
        name = safe_name(row['path'])
        if name in GENERATED_NAMES or not (name.startswith(SOURCE_FILE_PREFIXES) or name in SOURCE_FILE_NAMES):
            raise RuntimeError('Explicit source file outside the frozen code/public-assets scope')
        source = checked_file(row)
        explicit.append({'path': name, 'bytes': source.stat().st_size, 'sha256': row['sha256']})
        sources[name] = source
    rows, removed = merge_rows(baseline, components, explicit, native_id)
    native_receipt = None
    if 'receipt' in spec['builds']['native']:
        receipt_path = checked_file(spec['builds']['native']['receipt'])
        native_receipt = json.loads(receipt_path.read_text('utf-8'))
        if native_receipt.get('build_id') != native_id:
            raise RuntimeError('Native receipt identity changed')
        if not set(old_native.get('source_pages', [])).issubset(native_receipt.get('source_pages', [])):
            raise RuntimeError('An existing DeepTutor page was removed from the new native build')
    elif native_id != old_native['build_id']:
        raise RuntimeError('Changed native build requires its frozen source/page receipt')
    links_path = checked_file(spec['junctions'])
    links = json.loads(links_path.read_text('utf-8'))
    validate_junctions(links, rows)
    acceptance_path = checked_file(spec['feature_acceptance'])
    acceptance = json.loads(acceptance_path.read_text('utf-8'))
    validate_feature_receipt(acceptance)
    csharp_source = checked_file(spec['installer_source'])
    win_manifest = checked_file(spec['windows_manifest'])
    launch_page = checked_file(spec['launch_page'])
    versioned_installer_source(csharp_source.read_text('utf-8'))
    om_rows = [name for name in rows if name.startswith('runtime/openmaic-standalone/')]
    if not all(any(name.endswith('/' + dll) for name in om_rows)
               for dll in ('libvips-42.dll', 'libvips-cpp-8.18.6.dll', 'sharp-win32-x64-0.35.4.node')):
        raise RuntimeError('Pinned OpenMAIC Sharp native addon and companion DLLs must remain complete')
    server_entries = {}
    with zipfile.ZipFile(baseline_path) as baseline_zip:
        for name in ('runtime/native-frontends/' + native_id + '/server.js',
                     'runtime/openmaic-standalone/server.js'):
            if name in sources:
                with open(native_path(sources[name]), 'rb') as stream:
                    original_entry = stream.read()
            else:
                original_entry = baseline_zip.read(name)
            server_entries[name] = server_entry_policy(original_entry)
    return {'baseline_path': baseline_path, 'baseline': baseline, 'old_native': old_native,
            'components': components, 'sources': sources, 'rows': rows, 'removed': removed,
            'links': links, 'acceptance': acceptance, 'csharp_source': csharp_source,
            'windows_manifest': win_manifest, 'launch_page': launch_page,
            'native_receipt': native_receipt, 'server_entries': server_entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True, help='D-workspace-relative frozen JSON spec')
    parser.add_argument('--expected-spec-sha256', required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    started = time.monotonic()
    spec_path = checked_file({'source': args.spec, 'sha256': args.expected_spec_sha256.lower()})
    spec = json.loads(spec_path.read_text('utf-8'))
    plan = load_plan(spec)
    artifact = BASE / spec['artifact_name']
    if artifact.exists():
        raise RuntimeError('Existing r4 candidate retained; choose a new artifact name')
    if args.validate_only:
        print(json.dumps({'spec_validated': True, 'version': VERSION, 'candidate': str(artifact),
                          'complete_components': [item['name'] for item in plan['components']],
                          'obsolete_paths_to_remove': len(plan['removed']), 'build_performed': False}, indent=2))
        return
    artifact.mkdir()
    history = artifact / 'frozen-inputs'
    history.mkdir()
    (history / 'spec.json').write_bytes(spec_path.read_bytes())
    (history / 'baseline-manifest.json').write_bytes(json_bytes({
        'version': '2026.10.10-r3', 'file_count': len(plan['baseline']),
        'uncompressed_bytes': sum(row['bytes'] for row in plan['baseline'].values()),
        'files': sorted(plan['baseline'].values(), key=lambda row: row['path'])}))
    generated_source = artifact / 'DeepSteamSetup-r4.cs'
    generated_source.write_text(versioned_installer_source(plan['csharp_source'].read_text('utf-8')), 'utf-8')
    stub = artifact / 'DeepSteam-r4-stub.exe'
    compile_installer(generated_source, plan['windows_manifest'], stub)
    rows = plan['rows']
    native = dict(plan['old_native'])
    native_target = 'runtime/native-frontends/' + spec['builds']['native']['build_id']
    native.update(build_id=spec['builds']['native']['build_id'], root=native_target, server=native_target + '/server.js')
    if plan['native_receipt'] is not None:
        receipt = plan['native_receipt']
        for key in ('package_lock_sha256', 'source_sha256', 'source_page_count', 'source_pages', 'build_auth_enabled'):
            if key in receipt:
                native[key] = receipt[key]
    generated = {'DeepSteam.exe': stub.read_bytes(), 'installer/DeepSteamSetup.cs': generated_source.read_bytes(),
                 'installer/DeepSteam.manifest': plan['windows_manifest'].read_bytes(),
                 'runtime/native-frontend.json': json_bytes(native),
                 'installer/junctions.json': json_bytes(plan['links'])}
    # Installer-owned launcher remains present when a new native tree replaces
    # the old one; it contains no machine path or private browser state.
    launch_name = native_target + '/public/deepsteam-start.html'
    if launch_name not in rows:
        generated[launch_name] = plan['launch_page'].read_bytes()
    generated.update(plan['server_entries'])
    for name, contents in generated.items():
        rows[name] = file_row(name, contents)
    frontend_targets = (native_target, 'runtime/openmaic-standalone', 'runtime/render-service', 'runtime/ffmpeg')
    frontend = {'version': VERSION, 'native_build_id': native['build_id'],
                'openmaic_build_id': spec['builds']['openmaic']['build_id'],
                'openmaic_next_build_id': spec['builds']['openmaic']['next_build_id'],
                'components': [component_inventory(target, rows) for target in frontend_targets],
                'junctions': len(plan['links']), 'junction_manifest': 'installer/junctions.json',
                'staged_reparse_points': 0, 'credentials_and_user_data_copied': False,
                'installer_launch_page_included': True,
                'generated_entry_modification_required': 'separate-storage images.maximumDiskCacheSize=0; optimizer retained'}
    generated['installer/frontend-payload-manifest.json'] = json_bytes(frontend)
    rows['installer/frontend-payload-manifest.json'] = file_row('installer/frontend-payload-manifest.json', generated['installer/frontend-payload-manifest.json'])
    manifest = {'version': VERSION, 'platform': 'win-x64', 'file_count': len(rows),
                'uncompressed_bytes': sum(row['bytes'] for row in rows.values()),
                'files': sorted(rows.values(), key=lambda row: row['path'])}
    generated[MANIFEST_NAME] = json_bytes(manifest)
    replacements = {name: source for name, source in plan['sources'].items()
                    if name not in plan['baseline'] or rows[name] != plan['baseline'][name]}
    replacements.update(generated)
    removed = set(plan['baseline']) - set(rows)
    archive = artifact / 'payload-r4.zip'
    print('Assembling r4 from frozen inventories; original r3 archive retained.', flush=True)
    raw = repackage(plan['baseline_path'], archive, replacements, removed)
    verified_files = verify_archive(archive, rows, generated[MANIFEST_NAME])
    print('Complete r4 CRC and SHA256 of every manifest file passed.', flush=True)
    release = artifact / 'release'
    release.mkdir()
    exe = release / ('DeepSteam-Setup-' + VERSION + '-x64.exe')
    exe.write_bytes(stub.read_bytes())
    companion = exe.with_suffix('.payload.dat')
    overlay = append_companion(companion, archive)
    tested = artifact / 'actual-windows-container-self-test.txt'
    subprocess.run([str(exe), '--self-test', str(tested)], check=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    distribution = [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}
                    for path in (exe, companion)]
    for row in distribution:
        path = Path(row['path'])
        path.with_suffix(path.suffix + '.sha256').write_text(row['sha256'] + '  ' + path.name + '\n', 'utf-8')
    result = {'version': VERSION, 'exe': str(exe), 'sha256': distribution[0]['sha256'], 'bytes': distribution[0]['bytes'],
              'native_build_id': native['build_id'], 'openmaic_build_id': frontend['openmaic_build_id'],
              'openmaic_next_build_id': frontend['openmaic_next_build_id'], 'distribution_files': distribution,
              'payload_container': overlay, 'single_file_exe': False, 'payload_files': len(rows) + 1,
              'payload_bytes': manifest['uncompressed_bytes'], 'payload_zip_bytes': archive.stat().st_size,
              'manifest_sha256': hashlib.sha256(generated[MANIFEST_NAME]).hexdigest(),
              'crc_passed': True, 'changed_file_sha_passed': True, 'all_file_sha_passed': True,
              'files_sha_verified': verified_files, 'actual_exe_self_test_passed': True,
              'self_test_report': str(tested), 'frozen_spec': str(spec_path), 'frozen_spec_sha256': args.expected_spec_sha256.lower(),
              'raw_archive_reuse': raw, 'feature_acceptance': {key: plan['acceptance'][key] for key in (
                  'slides_layout_passed', 'explanations_complete', 'full_narrated_video_passed',
                  'narration_coverage', 'video_has_audio', 'video_duration_seconds')},
              'cold_start_validated': False, 'published_to_e': False, 'machine_state_bundled': False,
              'models_called_by_builder': False, 'downloads_performed': False,
              'prior_r3_artifacts_unchanged': True, 'elapsed_seconds': round(time.monotonic() - started, 3)}
    (artifact / 'payload-manifest.json').write_bytes(generated[MANIFEST_NAME])
    (artifact / 'frontend-payload-manifest.json').write_bytes(generated['installer/frontend-payload-manifest.json'])
    (artifact / 'build-report.json').write_bytes(json_bytes(result))
    (release / 'DeepSteam-Package-Manifest.json').write_bytes(json_bytes(result))
    print(json.dumps({'version': VERSION, 'build_report': str(artifact / 'build-report.json'),
                      'distribution_files': distribution, 'payload_files': len(rows) + 1,
                      'all_file_sha_passed': True, 'files_sha_verified': verified_files,
                      'actual_exe_self_test_passed': True,
                      'unchanged_raw_records_reused': raw['unchanged_raw_records_reused'],
                      'removed_path_count': len(removed), 'published_to_e': False,
                      'cold_start_validated': False, 'elapsed_seconds': result['elapsed_seconds']},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
