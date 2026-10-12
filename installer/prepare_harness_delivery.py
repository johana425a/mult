"""Freeze public desktop/Harness component and overlay inventories on D.

No build, deployment, service start or account access occurs. Give complete
ordinary dependency trees; symlinks/junctions and credential-state files fail.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
module_spec = importlib.util.spec_from_file_location('harness_delivery_builder', BASE / 'build_r5_candidate.py')
build = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(build)
TEXT_SUFFIXES = {'.py', '.js', '.cjs', '.mjs', '.ts', '.tsx', '.json', '.jsonc', '.yaml',
                 '.yml', '.toml', '.md', '.txt', '.ps1', '.cmd', '.html', '.css'}
SECRET_PATTERNS = {
    'private_key': rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'api_key': rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b',
    'github_token': rb'\bgh[pousr]_[A-Za-z0-9]{30,}\b',
    'aws_access_key': rb'\bAKIA[0-9A-Z]{16}\b',
}
# Reviewed publisher documentation examples in the pinned AWS SDK dependency.
# An edit, a different path or any additional secret category still blocks.
# No actual credential value is stored or emitted by this exception list.
PUBLIC_DEPENDENCY_EXAMPLES = {
    'runtime/harness/node_modules/@aws-sdk/nested-clients/dist-types/submodules/sts/commands/AssumeRoleCommand.d.ts':
        'd6b5f96e31cdfcf6955ca63778db40cbf392b87934b6c0db399b5b71206ff609',
    'runtime/harness/node_modules/@aws-sdk/nested-clients/dist-types/submodules/sts/commands/AssumeRoleWithWebIdentityCommand.d.ts':
        '93271217ff1125ad4250d78a14941f3cc59aa477eb10207bc72c709e82790bbe',
}
REVIEWED_DEPENDENCY_EXAMPLES_USED = set()
OVERLAY_COMPONENTS = {'harness', 'desktop_runtime', 'desktop_source', 'portal', 'harness_bridge'}
OVERLAY_FILES = {'scripts/harness_runtime.py', 'scripts/desktop_runtime.py', 'scripts/portal_runtime.py',
                 'scripts/installation_identity.py',
                 'integration/harness_bridge.py',
                 'installer/Start-DeepSteam.ps1', 'installer/Stop-DeepSteam.ps1',
                 'README.md', 'HANDOFF.md'}


def scan_public(source, target):
    build.safe_name(target)
    if source.suffix.casefold() in TEXT_SUFFIXES:
        blob = source.read_bytes()
        matches = [kind for kind, pattern in SECRET_PATTERNS.items() if re.search(pattern, blob)]
        if (matches == ['aws_access_key'] and target in PUBLIC_DEPENDENCY_EXAMPLES
                and hashlib.sha256(blob).hexdigest() == PUBLIC_DEPENDENCY_EXAMPLES[target]):
            REVIEWED_DEPENDENCY_EXAMPLES_USED.add(target)
            matches = []
        if matches:
            raise RuntimeError('Credential-pattern review required: ' + target + ' (' + ', '.join(matches) + ')')


def write_new(path, value):
    if path.exists() or not path.resolve().is_relative_to((ROOT / 'reports').resolve()):
        raise RuntimeError('A new inventory path under reports is required')
    blob = build.helpers.json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(blob)
    return {'source': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(blob).hexdigest(), 'bytes': len(blob)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', required=True, help='Unique lowercase inventory filename prefix')
    parser.add_argument('--component', action='append', default=[], help='Fixed component_name=workspace-relative source tree')
    parser.add_argument('--file', action='append', default=[], help='Workspace-relative public program file')
    parser.add_argument('--overlay-output', required=True, help='New workspace-relative reports JSON')
    parser.add_argument('--output', required=True, help='New workspace-relative component descriptor JSON')
    parser.add_argument('--native-prepare-report', help='Frozen sanitized native preparation report')
    parser.add_argument('--expected-native-prepare-report-sha256')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9-]+', args.prefix):
        raise RuntimeError('A plain unique inventory prefix is required')
    components, overlay, explicit, seen = [], [], [], set()
    native_manifest = None
    if args.native_prepare_report:
        report_path = build.helpers.checked_file({'source': args.native_prepare_report,
            'sha256': args.expected_native_prepare_report_sha256 or ''})
        prepared = json.loads(report_path.read_text('utf-8'))
        if any(prepared.get(name) is not False for name in
               ('user_data_copied', 'credentials_copied', 'services_started', 'written_to_e')):
            raise RuntimeError('A sanitized, data-free native preparation report is required')
        selected = [row for row in prepared['components'] if row['name'] == 'native']
        if len(selected) != 1:
            raise RuntimeError('Exactly one complete native component is required')
        component = selected[0]
        source = build.helpers.workspace_path(component['source'])
        target = build.safe_name(component['target'])
        if (not re.fullmatch(r'\d{8}-\d{6}', component.get('build_id', ''))
                or target != 'runtime/native-frontends/' + component['build_id']):
            raise RuntimeError('Native preparation target and build identity differ')
        inventory = json.loads(build.helpers.checked_file(component['inventory']).read_text('utf-8'))
        rows = build.helpers.collect_tree(source, target)
        if (rows != inventory['files'] or inventory.get('source') != component['source']
                or inventory.get('target') != target or inventory.get('file_count') != len(rows)):
            raise RuntimeError('Prepared native runtime changed after its frozen inventory')
        for row in rows:
            absolute = source / row['path']
            name = target + '/' + row['path']
            delivery_source = absolute.relative_to(ROOT).as_posix()
            build.safe_name(name)
            overlay.append({'path': name, 'source': delivery_source,
                            'bytes': row['bytes'], 'sha256': row['sha256']})
        artifact = Path(prepared['artifact']).resolve()
        if not artifact.is_relative_to((ROOT / 'installer').resolve()):
            raise RuntimeError('Native preparation stage escaped the installer workspace')
        portable = artifact / 'runtime/native-frontend.json'
        manifest = json.loads(portable.read_text('utf-8'))
        if (manifest.get('root') != target or manifest.get('server') != target + '/server.js'
                or manifest.get('build_id') != component['build_id']):
            raise RuntimeError('Native preparation manifest is not portable')
        native_manifest = {'path': 'runtime/native-frontend.json',
                           'source': portable.relative_to(ROOT).as_posix(),
                           'bytes': portable.stat().st_size, 'sha256': build.helpers.digest(portable)}
        overlay.append(native_manifest)
        components.append({key: component[key] for key in ('name', 'source', 'target', 'inventory')})
        seen.add('native')
    for option in args.component:
        name, separator, relative = option.partition('=')
        if not separator or name in seen or name not in build.TARGETS:
            raise RuntimeError('An unrepeated fixed component name is required')
        seen.add(name)
        source = build.helpers.workspace_path(relative)
        target = build.TARGETS[name]
        rows = build.helpers.collect_tree(source, target)
        if not rows:
            raise RuntimeError('Empty component: ' + name)
        for row in rows:
            absolute = source / row['path']
            output_name = target + '/' + row['path']
            scan_public(absolute, output_name)
            if name in OVERLAY_COMPONENTS:
                overlay.append({'path': output_name, 'source': absolute.relative_to(ROOT).as_posix(),
                                'bytes': row['bytes'], 'sha256': row['sha256']})
            elif name == 'integration' and (row['path'].startswith('harness/') or output_name in OVERLAY_FILES):
                overlay.append({'path': output_name, 'source': absolute.relative_to(ROOT).as_posix(),
                                'bytes': row['bytes'], 'sha256': row['sha256']})
            elif name == 'scripts' and output_name in OVERLAY_FILES:
                overlay.append({'path': output_name, 'source': absolute.relative_to(ROOT).as_posix(),
                                'bytes': row['bytes'], 'sha256': row['sha256']})
        inventory = {'source': relative, 'target': target, 'file_count': len(rows),
                     'uncompressed_bytes': sum(row['bytes'] for row in rows), 'files': rows,
                     'credentials_copied': False, 'user_data_copied': False}
        descriptor = write_new(ROOT / 'reports' / (args.prefix + '-' + name + '-inventory.json'), inventory)
        components.append({'name': name, 'source': relative, 'target': target, 'inventory': descriptor})
    for relative in args.file:
        name = build.safe_name(relative)
        source = build.helpers.workspace_path(relative)
        if not source.is_file() or source.is_symlink() or source.is_junction():
            raise RuntimeError('Explicit public file must be an ordinary contained file')
        scan_public(source, name)
        row = {'path': name, 'source': relative, 'bytes': source.stat().st_size, 'sha256': build.helpers.digest(source)}
        explicit.append(row)
        if name in OVERLAY_FILES and not any(item['path'] == name for item in overlay):
            overlay.append(row)
    overlay = sorted(overlay, key=lambda row: row['path'])
    if len({row['path'] for row in overlay}) != len(overlay):
        raise RuntimeError('Duplicate public overlay targets')
    overlay_descriptor = write_new(build.helpers.workspace_path(args.overlay_output), {
        'kind': 'deepsteam-harness-program-overlay', 'files': overlay,
        'credentials_copied': False, 'user_data_copied': False})
    result = {'components': components, 'files': explicit, 'overlay': overlay_descriptor,
              'native_portable_manifest': native_manifest,
              'credential_pattern_findings': 0, 'models_called': False, 'services_started': False,
              'reviewed_publisher_documentation_examples': sorted(REVIEWED_DEPENDENCY_EXAMPLES_USED),
              'native_runtime_sha_inventory_verified': native_manifest is not None,
              'native_runtime_credential_pattern_scan_performed': False,
              'production_changed': False, 'published_to_e': False}
    descriptor = write_new(build.helpers.workspace_path(args.output), result)
    print(json.dumps({'descriptor': descriptor, 'overlay': overlay_descriptor,
                      'components': [row['name'] for row in components],
                      'overlay_files': len(overlay), 'source_changed': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
