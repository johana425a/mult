"""Freeze a desktop/Harness candidate specification after root acceptance.

The source inventories and receipt are SHA-pinned; no receipt is invented or
modified. This only writes a new D-workspace report and never builds, installs,
starts services, accesses account credentials or publishes to E.
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
module_spec = importlib.util.spec_from_file_location('r5_spec_assembler_builder', BASE / 'build_r5_candidate.py')
build = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(build)
BASELINE = {'source': 'installer/r4-technical-20261011-final/payload-r4.zip',
            'sha256': '27eaf815734dd750bd21157b0e1755c63fe5ed5827325f784111e6dcd1903b95',
            'manifest_sha256': '9a563eb29a92ee9416eca0ab3aaf24760f22315eb95c8057bbc76735a665e94b'}


def pinned(source, digest):
    descriptor = {'source': source, 'sha256': digest}
    path = build.helpers.checked_file(descriptor)
    return descriptor, json.loads(path.read_text('utf-8'))


def public_file(source):
    path = build.helpers.workspace_path(source)
    return {'source': source, 'sha256': build.helpers.digest(path), 'bytes': path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-name', required=True)
    parser.add_argument('--components-report', required=True)
    parser.add_argument('--expected-components-report-sha256', required=True)
    parser.add_argument('--native-receipt', required=True)
    parser.add_argument('--expected-native-receipt-sha256', required=True)
    parser.add_argument('--junctions', required=True)
    parser.add_argument('--expected-junctions-sha256', required=True)
    parser.add_argument('--feature-receipt', required=True)
    parser.add_argument('--expected-feature-receipt-sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'r5-[a-z0-9-]+', args.artifact_name) or (BASE / args.artifact_name).exists():
        raise RuntimeError('A fresh dedicated r5-* candidate name is required')
    _, components = pinned(args.components_report, args.expected_components_report_sha256)
    if components.get('production_changed') is not False or components.get('published_to_e') is not False:
        raise RuntimeError('A clean public source inventory report is required')
    native_descriptor, native = pinned(args.native_receipt, args.expected_native_receipt_sha256)
    native_rows = [row for row in components['components'] if row['name'] == 'native']
    if len(native_rows) != 1 or native_rows[0]['target'] != 'runtime/native-frontends/' + native['build_id']:
        raise RuntimeError('Native source receipt and complete component disagree')
    junction_descriptor, _ = pinned(args.junctions, args.expected_junctions_sha256)
    acceptance_descriptor, acceptance = pinned(args.feature_receipt, args.expected_feature_receipt_sha256)
    readiness = build.receipt_status(acceptance)
    result = {'version': build.VERSION, 'artifact_name': args.artifact_name,
              'baseline': BASELINE,
              'builds': {'native': {'build_id': native['build_id'], 'receipt': native_descriptor}},
              'components': components['components'], 'files': components['files'],
              'junctions': junction_descriptor, 'feature_acceptance': acceptance_descriptor,
              'installer_source': public_file('installer/DeepSteamSetup.cs'),
              'windows_manifest': public_file('installer/DeepSteam.manifest')}
    # Validate every component/file against the frozen complete specification.
    # Pending live evidence remains pending; the builder controls preview policy.
    build.load_plan(result)
    output = build.helpers.workspace_path(args.output)
    if output.exists() or not output.resolve().is_relative_to((ROOT / 'reports').resolve()):
        raise RuntimeError('A fresh specification file under reports is required')
    blob = build.helpers.json_bytes(result)
    with output.open('xb') as stream:
        stream.write(blob)
    print(json.dumps({'spec': output.relative_to(ROOT).as_posix(),
                      'sha256': hashlib.sha256(blob).hexdigest(),
                      'complete_components': [row['name'] for row in result['components']],
                      'receipt_written': False, 'build_performed': False,
                      'published_to_e': False, **readiness}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
