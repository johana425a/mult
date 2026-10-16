"""Stage sanitized r4 components on D before full bundle construction.

No full installer build, service start, model call, E write, or user-data import.
Root may deploy the resulting SHA inventories separately for feature acceptance.
Every invocation uses a fresh installer/r4-components-* directory.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import time
import zipfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


build = module('r4_component_builder', 'build_r4_candidate.py')
stage = module('r4_component_stage', 'stage_frontend_payload.py')
BASELINE = BASE / 'local-runtime-compat-fix/payload-r3-loopback.zip'
BASELINE_MANIFEST_SHA = '919615a0a80aed2909ed43bddb4a04421e0a46f5a7036276cabec9b2eb617f7d'


def guard_source_path(path):
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise RuntimeError('Component source escaped the D workspace')
    name = resolved.relative_to(ROOT.resolve()).as_posix()
    build.safe_name(name)
    if name.startswith(('upstream/OpenMAIC/data/', 'upstream/OpenMAIC/.next/standalone/data/',
                        'upstream/OpenMAIC/logs/', 'upstream/OpenMAIC/cache/',
                        'upstream/OpenMAIC/render-service/.local/')):
        raise RuntimeError('Private traced runtime state excluded from component stage')
    return resolved


def install_copy_guards(artifact):
    original_file, original_tree = stage.copy_file, stage.copy_regular_tree
    def guarded_file(source, target):
        guard_source_path(source)
        build.safe_name(target.absolute().relative_to(artifact.absolute()).as_posix())
        return original_file(source, target)
    def guarded_tree(source, target, mapping, **options):
        guard_source_path(source)
        build.safe_name(target.absolute().relative_to(artifact.absolute()).as_posix())
        return original_tree(source, target, mapping, **options)
    stage.copy_file = guarded_file
    stage.copy_regular_tree = guarded_tree


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = build.json_bytes(value)
    with path.open('xb') as stream:
        stream.write(contents)
    return {'source': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(contents).hexdigest(), 'bytes': len(contents)}


def copy_allowed_root(source, target, mapping, directories, files):
    target.mkdir(parents=True, exist_ok=True)
    present = {item.name for item in source.iterdir()}
    for name in sorted(present.intersection(directories)):
        stage.copy_regular_tree(source / name, target / name, mapping)
    for name in sorted(present.intersection(files)):
        stage.copy_file(source / name, target / name)
    return sorted(present - set(directories) - set(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-name', required=True)
    parser.add_argument('--native-receipt')
    parser.add_argument('--expected-native-receipt-sha256')
    parser.add_argument('--openmaic-build-id')
    parser.add_argument('--expected-openmaic-next-build-id')
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--junction-base')
    parser.add_argument('--expected-junction-base-sha256')
    args = parser.parse_args()
    started = time.monotonic()
    if not re.fullmatch(r'r[45]-components-[a-z0-9-]+', args.artifact_name):
        raise RuntimeError('A new r4-components-* or r5-components-* installer child required')
    artifact = BASE / args.artifact_name
    if artifact.exists() or not (args.native_receipt or args.openmaic_build_id or args.render):
        raise RuntimeError('Fresh component stage and at least one selected component required')
    with zipfile.ZipFile(BASELINE) as archive:
        manifest_bytes = archive.read(build.MANIFEST_NAME)
        if hashlib.sha256(manifest_bytes).hexdigest() != BASELINE_MANIFEST_SHA:
            raise RuntimeError('Preserved corrected r3 baseline manifest changed')
        links = json.loads(archive.read('installer/junctions.json'))
    if args.junction_base:
        link_path = build.checked_file({'source': args.junction_base, 'sha256': args.expected_junction_base_sha256 or ''})
        links = json.loads(link_path.read_text('utf-8'))
    native_receipt = None
    if args.native_receipt:
        receipt_path = build.checked_file({'source': args.native_receipt, 'sha256': args.expected_native_receipt_sha256 or ''})
        native_receipt = json.loads(receipt_path.read_text('utf-8'))
        native_source = Path(native_receipt['root'])
        if (not native_source.resolve().is_relative_to(ROOT.resolve())
                or not re.fullmatch(r'\d{8}-\d{6}', native_receipt['build_id'])
                or not (native_source / 'server.js').is_file()):
            raise RuntimeError('Frozen native receipt points outside the immutable D build')
        native_dist = build.next_dist_dir((native_source / 'server.js').read_bytes())
        if not (native_source / native_dist / 'BUILD_ID').is_file():
            raise RuntimeError('Native source lacks its configured Next BUILD_ID')
        links = [row for row in links if not row['path'].startswith('runtime/native-frontends/')]
    openmaic = ROOT / 'upstream/OpenMAIC'
    if args.openmaic_build_id:
        if (not re.fullmatch(r'\d{8}-\d{6}', args.openmaic_build_id)
                or not args.expected_openmaic_next_build_id
                or (openmaic / '.next/standalone/.next/BUILD_ID').read_text('utf-8').strip() != args.expected_openmaic_next_build_id
                or (openmaic / '.next/BUILD_ID').read_text('utf-8').strip() != args.expected_openmaic_next_build_id):
            raise RuntimeError('Exact completed OpenMAIC standalone build identity required')
        links = [row for row in links if not row['path'].startswith('runtime/openmaic-standalone/')]
    if args.render:
        links = [row for row in links if not row['path'].startswith('runtime/render-service/')]
    artifact.mkdir()
    stage.STAGE = artifact
    stage.LINKS = []
    stage.LINK_TARGETS = []
    install_copy_guards(artifact)
    selected, exclusions, mappings = [], {}, []
    if native_receipt:
        target = artifact / 'runtime/native-frontends' / native_receipt['build_id']
        skipped = copy_allowed_root(native_source, target, (native_source, target),
                                    {native_dist, 'node_modules', 'public', 'lib'}, {'server.js', 'package.json'})
        selected.append({'name': 'native', 'target': target, 'build_id': native_receipt['build_id']})
        exclusions['native_root_entries_not_distributed'] = skipped
        mappings.append((native_source, target))
        stage.copy_file(BASE / 'deepsteam-start.html', target / 'public/deepsteam-start.html')
        portable = dict(native_receipt)
        portable.update(root=target.relative_to(artifact).as_posix(),
                        server=(target / 'server.js').relative_to(artifact).as_posix())
        write_new(artifact / 'runtime/native-frontend.json', portable)
    if args.openmaic_build_id:
        target = artifact / 'runtime/openmaic-standalone'
        # Source app/config/test/data directories are not runtime payloads.
        # lib prompts, agent worker, skills and package targets are runtime-read
        # assets and must remain; the build bundles ordinary TS application code.
        skipped = copy_allowed_root(openmaic / '.next/standalone', target, (openmaic, target),
                                    {'node_modules', 'packages', 'lib', 'skills', 'assets', 'public'},
                                    {'server.js', 'package.json'})
        # A reused standalone trace may still contain yesterday's static/cache
        # tree. Take its runtime Next manifests/server, then only the current
        # canonical build's static tree so obsolete browser chunks cannot leak.
        stage.copy_regular_tree(openmaic / '.next/standalone/.next', target / '.next',
                                (openmaic, target), root_excludes={'static', 'cache', 'standalone'})
        stage.copy_regular_tree(openmaic / '.next/static', target / '.next/static', (openmaic, target))
        # The standalone public tree may be a trace subset. Fill each regular
        # public asset using the publisher's source, without copying user data.
        stage.copy_regular_tree(openmaic / 'public', target / 'public', (openmaic, target))
        stage.supplement_sharp_native_libs()
        selected.append({'name': 'openmaic', 'target': target, 'build_id': args.openmaic_build_id,
                         'next_build_id': args.expected_openmaic_next_build_id})
        exclusions['openmaic_root_entries_not_distributed'] = [name for name in skipped if name != '.next']
        exclusions['openmaic_trace_next_directories_not_distributed'] = ['static', 'cache', 'standalone']
        mappings.append((openmaic, target))
    if args.render:
        render = openmaic / 'render-service'
        target = artifact / 'runtime/render-service'
        skipped = copy_allowed_root(render, target, (render, target), {'src', 'scripts', 'node_modules'},
                                    {'package.json', 'package-lock.json', 'pnpm-lock.yaml', 'tsconfig.json',
                                     'README.md', 'WINDOWS-EDUAGENT.md', 'resource-config.example.json'})
        stage.copy_file(openmaic / 'LICENSE', target / 'LICENSE')
        selected.append({'name': 'render', 'target': target})
        exclusions['render_root_entries_not_distributed'] = skipped
        mappings.append((render, target))
    cursor = 0
    while cursor < len(stage.LINK_TARGETS):
        source, target = stage.LINK_TARGETS[cursor]
        cursor += 1
        if not target.exists():
            mapping = next((item for item in reversed(mappings) if source.is_relative_to(item[0])), None)
            if mapping is None:
                raise RuntimeError('Dependency target escaped selected distributable source')
            stage.copy_regular_tree(source, target, mapping)
    unique = {row['path']: row for row in links}
    for row in stage.LINKS:
        if row['path'] in unique:
            raise RuntimeError('Duplicate declared dependency link')
        target = artifact / row['target']
        if not target.is_dir() or not target.resolve().is_relative_to(artifact.resolve()):
            raise RuntimeError('New dependency target missing or outside component stage')
        unique[row['path']] = row
    junction_descriptor = write_new(artifact / 'installer/junctions.json', sorted(unique.values(), key=lambda row: row['path']))
    components = []
    for item in selected:
        if item['name'] in {'native', 'openmaic'}:
            stage.configure_next_image_cache(item['target'] / 'server.js')
        source_name = item['target'].relative_to(ROOT).as_posix()
        target_name = item['target'].relative_to(artifact).as_posix()
        rows = build.collect_tree(item['target'], target_name)
        inventory = {'source': source_name, 'target': target_name, 'file_count': len(rows),
                     'uncompressed_bytes': sum(row['bytes'] for row in rows), 'files': rows}
        descriptor = write_new(artifact / (item['name'] + '-inventory.json'), inventory)
        components.append({'name': item['name'], 'source': source_name, 'target': target_name,
                           'inventory': descriptor, 'file_count': len(rows),
                           'build_id': item.get('build_id'), 'next_build_id': item.get('next_build_id')})
    report = {'artifact': str(artifact), 'components': components, 'junctions': junction_descriptor,
              'exclusions': exclusions, 'user_data_copied': False, 'credentials_copied': False,
              'baseline_manifest_sha_verified': True, 'baseline_archive_complete_sha_rechecked': False,
              'full_installer_built': False, 'models_called': False, 'services_started': False,
              'written_to_e': False, 'elapsed_seconds': round(time.monotonic() - started, 3)}
    write_new(artifact / 'prepare-report.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
