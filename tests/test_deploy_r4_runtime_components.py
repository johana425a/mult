"""Deployment safety regression fixtures; no real runtime, port, model or service changes."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deploy_r4_test_subject', ROOT / 'reports/deploy_r4_runtime_components.py')
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeploymentFixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='r4-deployment-fixture-', dir=ROOT / 'reports')
        self.base = Path(self.temporary.name)
        self.workspace = self.base / 'source'
        self.program = self.base / 'run-cache'
        self.workspace.mkdir()
        self.program.mkdir()
        self.patch_workspace = patch.object(subject, 'WORKSPACE', self.workspace)
        self.patch_program = patch.object(subject, 'PROGRAM_ROOT', self.program)
        self.patch_workspace.start()
        self.patch_program.start()
        self.addCleanup(self.patch_workspace.stop)
        self.addCleanup(self.patch_program.stop)
        self.addCleanup(self.temporary.cleanup)
        self.report_pairs = []
        self.frozen_pairs = []
        self.native_sha = ''
        write(self.program / 'runtime/openmaic-standalone/stale.js', b'old complete OM tree')
        write(self.program / 'runtime/render-service/stale.js', b'old complete renderer')
        write(self.program / 'runtime/native-frontend.json', {'root': 'runtime/old-native', 'server': 'runtime/old-native/server.js'})
        write(self.program / 'installer/payload-manifest.json', {'factory': 'original-r3'})
        write(self.program / 'deepsteam-storage.json', {'state_root': 'D:\\Fixture-Data'})
        for name in subject.FROZEN_FILES:
            write(self.program / name, b'old app file')
            sha = write(self.workspace / name, b'frozen new app file: ' + name.encode())
            self.frozen_pairs.append([str(self.workspace / name), sha])
        write(self.program / 'installer/junctions.json', [])
        self.prepare('native', 'runtime/native-frontends/20261011-084654', {'server.js': b'new native server'})
        self.prepare('openmaic', 'runtime/openmaic-standalone', {'server.js': b'new OM server', '.next/BUILD_ID': b'fixture-next-id'})
        self.prepare('render', 'runtime/render-service', {'src/preview-renderer.ts': b'new offline renderer'})

    def prepare(self, name, target, files):
        artifact = self.workspace / 'installer' / ('r4-components-' + name)
        source = artifact / target
        rows = []
        for path, value in files.items():
            sha = write(source / path, value)
            rows.append({'path': path, 'sha256': sha, 'bytes': len(value)})
        source_relative = source.relative_to(self.workspace).as_posix()
        inventory = {'source': source_relative, 'target': target, 'files': rows,
                     'file_count': len(rows), 'uncompressed_bytes': sum(row['bytes'] for row in rows)}
        inventory_path = artifact / (name + '-inventory.json')
        inventory_sha = write(inventory_path, inventory)
        links_path = artifact / 'installer/junctions.json'
        links_sha = write(links_path, [])
        descriptor = lambda path, sha: {'source': path.relative_to(self.workspace).as_posix(),
                                       'sha256': sha, 'bytes': path.stat().st_size}
        component = {'name': name, 'source': source_relative, 'target': target,
                     'inventory': descriptor(inventory_path, inventory_sha), 'file_count': len(rows),
                     'build_id': '20261011-084654' if name == 'native' else None,
                     'next_build_id': 'fixture-next-id' if name == 'openmaic' else None}
        report = {'artifact': str(artifact), 'components': [component], 'junctions': descriptor(links_path, links_sha),
                  'user_data_copied': False, 'credentials_copied': False, 'models_called': False,
                  'services_started': False, 'written_to_e': False}
        report_path = artifact / 'prepare-report.json'
        report_sha = write(report_path, report)
        self.report_pairs.append([str(report_path), report_sha])
        if name == 'native':
            self.native_sha = write(artifact / 'runtime/native-frontend.json',
                                    {'root': target, 'server': target + '/server.js', 'build_id': '20261011-084654'})

    def plan(self):
        return subject.load_plan(self.report_pairs, self.frozen_pairs, self.native_sha)

    def test_full_verified_deployment_retains_old_trees_and_factory_records(self):
        plan = self.plan()
        factory = (self.program / 'installer/payload-manifest.json').read_bytes()
        state_config = (self.program / 'deepsteam-storage.json').read_bytes()
        with patch.object(subject, 'assert_services_stopped', return_value={'six_ports_stopped': True, 'owned_processes_active': False}), \
             patch.object(subject, 'repair_links', return_value={'dependency_links': 0, 'repaired': 0}) as repair:
            receipt = subject.deploy(plan)
        self.assertEqual(receipt['status'], 'package_pending')
        self.assertEqual(receipt['deployment_phase'], 'components_verified')
        self.assertFalse(receipt['installed_factory_verification_claimed'])
        self.assertFalse(receipt['state_root_mutated'])
        history = Path(receipt['history'])
        self.assertEqual((history / 'runtime/openmaic-standalone/stale.js').read_bytes(), b'old complete OM tree')
        self.assertEqual((history / 'runtime/render-service/stale.js').read_bytes(), b'old complete renderer')
        self.assertFalse((self.program / 'runtime/openmaic-standalone/stale.js').exists())
        self.assertEqual((self.program / 'installer/payload-manifest.json').read_bytes(), factory)
        self.assertEqual((self.program / 'deepsteam-storage.json').read_bytes(), state_config)
        self.assertEqual(json.loads((self.program / 'runtime/native-frontend.json').read_text())['root'],
                         'runtime/native-frontends/20261011-084654')
        self.assertTrue((self.program / 'reports/r4-runtime-deployment-latest.json').is_file())
        repair.assert_called_once_with(self.program.resolve(), [])
        for row in plan['frozen']:
            self.assertEqual(subject.digest(self.program / row['target']), row['sha256'])

    def test_active_service_rejection_writes_nothing_and_preserves_old_tree(self):
        plan = self.plan()
        with patch.object(subject, 'assert_services_stopped', side_effect=RuntimeError('port 8011 active')):
            with self.assertRaisesRegex(RuntimeError, '8011'):
                subject.deploy(plan)
        self.assertFalse((self.program / 'reports').exists())
        self.assertEqual((self.program / 'runtime/openmaic-standalone/stale.js').read_bytes(), b'old complete OM tree')

    def test_changed_source_after_preflight_fails_with_explicit_preserved_receipt(self):
        plan = self.plan()
        row = plan['components'][0]['rows'][0]
        write(plan['components'][0]['source_path'] / row['path'], b'changed after frozen preflight')
        with patch.object(subject, 'assert_services_stopped', return_value={'six_ports_stopped': True, 'owned_processes_active': False}):
            with self.assertRaisesRegex(RuntimeError, 'Frozen file changed'):
                subject.deploy(plan)
        receipt = json.loads((self.program / 'reports/r4-runtime-deployment-latest.json').read_text())
        self.assertEqual(receipt['status'], 'package_pending')
        self.assertEqual(receipt['deployment_phase'], 'failed_preserved_for_review')
        self.assertFalse(receipt['installed_factory_verification_claimed'])
        self.assertEqual((self.program / 'runtime/openmaic-standalone/stale.js').read_bytes(), b'old complete OM tree')

    def test_tampered_or_incomplete_inventory_rejected_before_deployment(self):
        source = self.workspace / 'installer/r4-components-openmaic/runtime/openmaic-standalone'
        write(source / 'server.js', b'tampered')
        with self.assertRaisesRegex(RuntimeError, 'Frozen file changed'):
            self.plan()
        write(source / 'server.js', b'new OM server')
        write(source / 'extra-private-state.json', b'not inventoried')
        with self.assertRaisesRegex(RuntimeError, 'complete frozen tree'):
            self.plan()
        self.assertFalse((self.program / 'reports').exists())

    def test_unsafe_paths_descriptor_and_existing_native_root_fail_closed(self):
        for value in ('../DeepSteam-Data/file', '/absolute', 'runtime/a:b', 'runtime\\ambiguous', 'runtime//empty'):
            with self.assertRaises(RuntimeError):
                subject.relative_name(value)
        descriptor = self.workspace / 'installer/r4-components-native/runtime/native-frontend.json'
        self.native_sha = write(descriptor, {'root': 'D:\\Fixture-Data', 'server': 'outside', 'build_id': '20261011-084654'})
        with self.assertRaisesRegex(RuntimeError, 'relative root'):
            self.plan()
        target = 'runtime/native-frontends/20261011-084654'
        self.native_sha = write(descriptor, {'root': target, 'server': target + '/server.js', 'build_id': '20261011-084654'})
        (self.program / target).mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'immutable'):
            self.plan()

    def test_owned_process_identity_rejection_does_not_print_arguments(self):
        import psutil
        process = SimpleNamespace(pid=919191, info={'exe': str(self.program / 'runtime/node/node.exe'),
          'cwd': str(self.program), 'cmdline': ['node', 'server.js', '--secret=DO_NOT_OUTPUT']})
        socket_mock = MagicMock()
        socket_mock.__enter__.return_value.connect_ex.return_value = 1
        with patch.object(psutil, 'net_connections', return_value=[]), \
             patch.object(psutil, 'Process') as current, patch.object(psutil, 'process_iter', return_value=[process]), \
             patch.object(subject.socket, 'socket', return_value=socket_mock):
            current.return_value.parents.return_value = []
            with self.assertRaises(RuntimeError) as raised:
                subject.assert_services_stopped(self.program)
        self.assertIn('919191', str(raised.exception))
        self.assertNotIn('DO_NOT_OUTPUT', str(raised.exception))

    def test_port_identity_guard_detects_any_of_the_six_listeners(self):
        import psutil
        listener = SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=3794), pid=4242)
        with patch.object(psutil, 'net_connections', return_value=[listener]):
            with self.assertRaisesRegex(RuntimeError, '3794'):
                subject.assert_services_stopped(self.program)

    def test_contained_dependency_rows_reject_escapes_duplicates_and_self_cycles(self):
        for rows in ([{'path': 'runtime/node_modules/a', 'target': '../DeepSteam-Data'}],
                     [{'path': 'runtime/a', 'target': 'runtime/a/subdir'}],
                     [{'path': 'runtime/a', 'target': 'runtime/b'}, {'path': 'runtime/A', 'target': 'runtime/c'}]):
            with self.assertRaises(RuntimeError):
                subject.validated_links(rows)


if __name__ == '__main__':
    unittest.main()
