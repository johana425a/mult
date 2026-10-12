"""Deterministic distribution/lifecycle checks; no accounts or model calls."""
from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import portal_runtime


def load(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


build = load('harness_delivery_test_builder', BASE / 'build_r5_candidate.py')
overlay = load('harness_delivery_test_overlay', BASE / 'deploy_harness_overlay.py')
handoff = load('harness_delivery_test_handoff', ROOT / 'scripts/package_handoff.py')
source_stage = load('harness_delivery_test_source_stage', BASE / 'stage_harness_sources.py')
delivery = load('harness_delivery_test_inventory', BASE / 'prepare_harness_delivery.py')


class HarnessDeliveryTests(unittest.TestCase):
    def test_private_account_and_desktop_state_rejected(self):
        for path in ('runtime/harness/.dsh/accounts.json', 'runtime/harness/profile/account.json',
                     'runtime/harness/control-token', 'runtime/harness/credentials.json',
                     'runtime/desktop/userData/Cookies', 'runtime/harness/sessions/test.json',
                     'data/learning.sqlite3', 'deepsteam-storage.json'):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                build.safe_name(path)

    def test_portable_code_and_dependencies_allowed(self):
        for path in ('runtime/harness/sidecar.mjs', 'runtime/harness/node_modules/credential/index.js',
                     'runtime/desktop/resources/app/main.cjs', 'integration/harness/package-lock.json'):
            self.assertEqual(build.safe_name(path), path)

    def test_unsafe_relative_paths_rejected(self):
        for path in ('../auth.json', 'runtime/../data/state.json', 'C:/auth.json', 'runtime\\token'):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                build.safe_name(path)

    def test_pending_live_gates_are_not_reported_ready(self):
        receipt = {'kind': 'deepsteam-desktop-harness-acceptance', 'credentials_included': False,
                   'user_data_included': False, 'distribution_ready': True,
                   **{key: True for key in build.REQUIRED_GATES}}
        actual = build.receipt_status(receipt)
        self.assertFalse(actual['distribution_ready'])
        self.assertEqual(actual['missing_gates'], list(build.LIVE_GATES))

    def test_all_live_gates_and_explicit_distribution_required(self):
        receipt = {'kind': 'deepsteam-desktop-harness-acceptance', 'credentials_included': False,
                   'user_data_included': False,
                   **{key: True for key in (*build.REQUIRED_GATES, *build.LIVE_GATES)}}
        self.assertFalse(build.receipt_status(receipt)['distribution_ready'])
        receipt['distribution_ready'] = True
        self.assertTrue(build.receipt_status(receipt)['distribution_ready'])

    def test_preview_version_changes_generated_source_only(self):
        original = 'internal const string Version = "2026.10.10-r3";'
        changed = build.versioned_source(original, '2026.10.11-r5-preview')
        self.assertIn('2026.10.11-r5-preview', changed)
        self.assertIn('2026.10.10-r3', original)
        with self.assertRaises(RuntimeError):
            build.versioned_source('unexpected installer source')

    def test_clean_source_bundle_excludes_accounts(self):
        for path in ('desktop/.dsh/accounts.json', 'integration/harness/auth.json',
                     'integration/harness/control-token', 'desktop/userData/Preferences'):
            with self.subTest(path=path):
                self.assertFalse(handoff.allowed(Path(path)))

    def test_overlay_cannot_target_settings(self):
        descriptor = {'files': [{'path': 'data/settings.json', 'source': 'README.md', 'sha256': '0' * 64}]}
        with self.assertRaises(RuntimeError):
            overlay.selected_files(descriptor)

    def test_overlay_includes_required_python_bridge(self):
        source = ROOT / 'integration/harness_bridge.py'
        descriptor = {'files': [{'path': 'integration/harness_bridge.py',
                                'source': 'integration/harness_bridge.py',
                                'sha256': build.helpers.digest(source)}]}
        selected = overlay.selected_files(descriptor)
        self.assertEqual(selected[0][0], 'integration/harness_bridge.py')
        self.assertEqual(selected[0][1], source.resolve())

    def test_startup_identity_helper_is_frozen_and_deployable(self):
        name = 'scripts/installation_identity.py'
        self.assertIn(name, delivery.OVERLAY_FILES)
        source = ROOT / name
        selected = overlay.selected_files({'files': [{'path': name, 'source': name,
            'sha256': build.helpers.digest(source)}]})
        self.assertEqual(selected[0][0], name)
        self.assertEqual(selected[0][1], source.resolve())

    def test_native_overlay_requires_matching_portable_manifest_and_fresh_build(self):
        with tempfile.TemporaryDirectory(prefix='harness-native-overlay-fixture-', dir=BASE) as folder:
            fixture = Path(folder)
            self.assertTrue(fixture.resolve().is_relative_to(BASE.resolve()))
            install = fixture / 'install'
            install.mkdir()
            source = fixture / 'server.js'
            source.write_bytes(b'// deterministic overlay fixture')
            manifest = fixture / 'native-frontend.json'
            manifest.write_text(json.dumps({'build_id': '20261011-200054',
                'root': 'runtime/native-frontends/20261011-200054',
                'server': 'runtime/native-frontends/20261011-200054/server.js'}), 'utf-8')
            selected = [('runtime/native-frontends/20261011-200054/server.js', source, 'fixture'),
                        ('runtime/native-frontend.json', manifest, 'fixture')]
            overlay.check_native(selected, install)
            manifest.write_text(json.dumps({'build_id': '20261011-200054',
                'root': str(fixture), 'server': str(source)}), 'utf-8')
            with self.assertRaises(RuntimeError):
                overlay.check_native(selected, install)
            with self.assertRaises(RuntimeError):
                overlay.check_native(selected[:1], install)

    def test_native_overlay_never_overwrites_existing_immutable_build(self):
        with tempfile.TemporaryDirectory(prefix='harness-native-immutable-fixture-', dir=BASE) as folder:
            fixture = Path(folder)
            self.assertTrue(fixture.resolve().is_relative_to(BASE.resolve()))
            destination = fixture / 'runtime/native-frontends/20261011-200054'
            destination.mkdir(parents=True)
            (destination / 'server.js').write_bytes(b'existing immutable software fixture')
            manifest = fixture / 'manifest.json'
            manifest.write_text(json.dumps({'build_id': '20261011-200054',
                'root': 'runtime/native-frontends/20261011-200054',
                'server': 'runtime/native-frontends/20261011-200054/server.js'}), 'utf-8')
            with self.assertRaises(RuntimeError):
                overlay.check_native([('runtime/native-frontends/20261011-200054/server.js',
                    destination / 'server.js', 'fixture'), ('runtime/native-frontend.json', manifest, 'fixture')], fixture)

    def test_complete_source_stage_excludes_dependencies_and_private_state(self):
        with tempfile.TemporaryDirectory(prefix='harness-source-fixture-', dir=BASE) as folder:
            fixture = Path(folder)
            self.assertTrue(fixture.resolve().is_relative_to(BASE.resolve()))
            for relative in ('harness_bridge.py', 'harness/sidecar.mjs', 'harness/node_modules/pkg/file.js',
                             'harness/profile/state.json', 'local_qwen/downloads/model.part', 'harness/control-token'):
                path = fixture / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'deterministic source staging fixture')
            files, excluded = source_stage.source_files(fixture, 'integration')
            self.assertEqual([row[0] for row in files], ['harness_bridge.py', 'harness/sidecar.mjs'])
            self.assertEqual(len(excluded), 4)

    def test_reviewed_publisher_document_example_allowance_is_exact(self):
        target = next(iter(delivery.PUBLIC_DEPENDENCY_EXAMPLES))
        original = ROOT / target
        delivery.scan_public(original, target)
        with tempfile.TemporaryDirectory(prefix='harness-publisher-example-fixture-', dir=BASE) as folder:
            fixture = Path(folder)
            self.assertTrue(fixture.resolve().is_relative_to(BASE.resolve()))
            altered = fixture / 'changed.d.ts'
            altered.write_bytes(original.read_bytes() + b'\n// changed documentation fixture')
            with self.assertRaises(RuntimeError):
                delivery.scan_public(altered, target)
            with self.assertRaises(RuntimeError):
                delivery.scan_public(original, 'runtime/harness/changed-documentation.d.ts')

    def test_harness_is_required_for_new_headless_install(self):
        result = {'healthy': True,
                  'services': {'services': {name: {'ok': True} for name in ('deeptutor', 'openmaic', 'local_model')}},
                  'listeners': [{'port': port, 'host': '127.0.0.1'} for port in portal_runtime.EXPECTED_PORTS],
                  'auxiliary_http': {'deeptutor_ui': True, 'renderer': True}}
        with patch.object(portal_runtime, 'harness_installed', return_value=False):
            self.assertTrue(portal_runtime.startup_ready(result))
        with patch.object(portal_runtime, 'harness_installed', return_value=True):
            self.assertFalse(portal_runtime.startup_ready(result))
            result['listeners'].append({'port': 3796, 'host': '127.0.0.1'})
            result['auxiliary_http']['harness'] = True
            self.assertTrue(portal_runtime.startup_ready(result))
            result['auxiliary_http']['harness'] = False
            self.assertFalse(portal_runtime.startup_ready(result))

    def test_external_listener_remains_rejected(self):
        result = {'healthy': True,
                  'services': {'services': {name: {'ok': True} for name in ('deeptutor', 'openmaic', 'local_model')}},
                  'listeners': [{'port': port, 'host': '127.0.0.1'} for port in portal_runtime.EXPECTED_PORTS],
                  'auxiliary_http': {'deeptutor_ui': True, 'renderer': True}}
        result['listeners'][0]['host'] = '0.0.0.0'
        with patch.object(portal_runtime, 'harness_installed', return_value=False):
            self.assertFalse(portal_runtime.startup_ready(result))

    def test_complete_frozen_overlay_plan_and_changed_file_rejection(self):
        with tempfile.TemporaryDirectory(prefix='harness-delivery-fixture-', dir=BASE) as folder:
            fixture = Path(folder)
            self.assertTrue(fixture.resolve().is_relative_to(BASE.resolve()))

            def new_file(relative, blob):
                path = fixture / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(blob)
                return {'source': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(blob).hexdigest()}

            old_files = {
                'runtime/native-frontend.json': json.dumps({'build_id': '20261011-111852',
                    'root': 'runtime/native-frontends/20261011-111852',
                    'server': 'runtime/native-frontends/20261011-111852/server.js'}).encode(),
                'installer/frontend-payload-manifest.json': b'{}',
                'installer/junctions.json': b'[]',
                'installer/Start-DeepSteam.ps1': b'# software fixture',
                'installer/Stop-DeepSteam.ps1': b'# software fixture',
                'runtime/native-frontends/20261011-111852/server.js':
                    b'const nextConfig = {}\nprocess.env.__NEXT_PRIVATE_STANDALONE_CONFIG = JSON.stringify(nextConfig)\n',
                'runtime/openmaic-standalone/server.js':
                    b'const nextConfig = {}\nprocess.env.__NEXT_PRIVATE_STANDALONE_CONFIG = JSON.stringify(nextConfig)\n',
            }
            old_rows = [build.helpers.file_row(name, blob) for name, blob in old_files.items()]
            manifest = {'version': '2026.10.11-r4', 'file_count': len(old_rows),
                        'uncompressed_bytes': sum(row['bytes'] for row in old_rows), 'files': old_rows}
            manifest_blob = build.helpers.json_bytes(manifest)
            archive_path = fixture / 'baseline.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                for name, blob in old_files.items():
                    archive.writestr(name, blob)
                archive.writestr(build.MANIFEST_NAME, manifest_blob)
            baseline = {'source': archive_path.relative_to(ROOT).as_posix(),
                        'sha256': build.helpers.digest(archive_path),
                        'manifest_sha256': hashlib.sha256(manifest_blob).hexdigest()}
            definitions = {
                'harness': {'sidecar.mjs': b'// deterministic software fixture',
                    'DEEPSEEK-HARNESS-LICENSE.txt': b'deterministic license fixture'},
                'desktop_runtime': {'DeepSteam Desktop.exe': b'deterministic software fixture',
                    'resources/app/main.cjs': b'// deterministic software fixture',
                    'resources/app/preload.cjs': b'// deterministic software fixture',
                    'LICENSE': b'deterministic license fixture',
                    'LICENSES.chromium.html': b'deterministic license fixture'},
                'scripts': {'harness_runtime.py': b'# deterministic software fixture',
                    'desktop_runtime.py': b'# deterministic software fixture'},
                'integration': {'harness/bridge.mjs': b'// deterministic software fixture',
                    'harness_bridge.py': b'# deterministic software fixture'},
            }
            components = []
            for name, files in definitions.items():
                source = fixture / 'components' / name
                for relative, blob in files.items():
                    new_file('components/' + name + '/' + relative, blob)
                target = build.TARGETS[name]
                rows = build.helpers.collect_tree(source, target)
                inventory = {'source': source.relative_to(ROOT).as_posix(), 'target': target,
                             'file_count': len(rows), 'uncompressed_bytes': sum(row['bytes'] for row in rows),
                             'files': rows}
                descriptor = new_file('inventories/' + name + '.json', build.helpers.json_bytes(inventory))
                components.append({'name': name, 'source': source.relative_to(ROOT).as_posix(),
                                   'target': target, 'inventory': descriptor})
            receipt = {'kind': 'deepsteam-desktop-harness-acceptance', 'credentials_included': False,
                       'user_data_included': False, 'status': 'development-preview',
                       'pending_live_reason': 'No actual cloud account used by this software fixture.',
                       **{key: True for key in build.REQUIRED_GATES}}
            specification = {'version': build.VERSION, 'artifact_name': 'r5-fixture-unused',
                             'baseline': baseline, 'components': components,
                             'feature_acceptance': new_file('receipt.json', build.helpers.json_bytes(receipt)),
                             'installer_source': new_file('source.cs', b'internal const string Version = "2026.10.10-r3";'),
                             'windows_manifest': new_file('windows.manifest', b'<fixture/>')}
            actual = build.load_plan(specification)
            self.assertFalse(actual['readiness']['distribution_ready'])
            self.assertEqual(len(actual['components']), 4)
            (fixture / 'components/harness/sidecar.mjs').write_bytes(b'changed after freeze')
            with self.assertRaises(RuntimeError):
                build.load_plan(specification)


if __name__ == '__main__':
    unittest.main(verbosity=2)
