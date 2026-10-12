"""Two focused temporary-runtime regressions; no real deployment or service calls."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def imported(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = imported('full_deploy_fixture_library', ROOT / 'tests/test_deploy_r4_runtime_components.py')
subject = imported('om_only_deploy_test_subject', ROOT / 'reports/deploy_r4_openmaic_only.py')


class OpenMAICOnlyDeploymentTests(unittest.TestCase):
    # Reuse the real frozen-stage fixture builder without inheriting its other tests.
    prepare = fixtures.DeploymentFixtures.prepare

    def setUp(self):
        fixtures.DeploymentFixtures.setUp(self)
        self.shared_patch = patch.object(subject, 'shared', fixtures.subject)
        self.shared_patch.start()
        self.addCleanup(self.shared_patch.stop)
        native_root = 'runtime/native-frontends/20261011-084654'
        fixtures.write(self.program / 'runtime/native-frontend.json', {'root': native_root, 'server': native_root + '/server.js'})
        fixtures.write(self.program / native_root / 'server.js', b'current immutable native')
        fixtures.write(self.program / 'reports/r4-runtime-deployment-latest.json', {'old': 'whole-components-receipt'})
        fixtures.write(self.program / 'runtime/render-service/package.json', {'unchanged': True})
        self.report_path, self.report_sha = self.report_pairs[1]

    def test_only_om_replaced_old_tree_retained_and_other_components_records_preserved(self):
        original = subject.preserved_records(self.program)
        untouched = [{'path': 'runtime/render-service/node_modules/pkg', 'target': 'runtime/render-service/vendor/pkg'}]
        fixtures.write(self.program / 'installer/junctions.json', {'version': 7, 'junctions': untouched})
        plan = subject.load_plan(self.report_path, self.report_sha)
        with patch.object(subject.shared, 'assert_services_stopped', return_value={'six_ports_stopped': True, 'owned_processes_active': False}), \
             patch.object(subject, 'repair_openmaic_links', return_value={'dependency_links': 0, 'repaired': 0}) as repair:
            receipt = subject.deploy(plan)
        self.assertEqual(receipt['deployment_phase'], 'openmaic_verified')
        self.assertEqual(receipt['status'], 'package_pending')
        self.assertEqual(receipt['files_verified'], 2)
        self.assertFalse(receipt['native_portal_bridge_renderer_replaced'])
        self.assertEqual(subject.preserved_records(self.program), original)
        self.assertEqual((self.program / 'runtime/render-service/stale.js').read_bytes(), b'old complete renderer')
        self.assertEqual(json.loads((self.program / 'installer/junctions.json').read_text()), {'version': 7, 'junctions': untouched})
        self.assertFalse((self.program / 'runtime/openmaic-standalone/stale.js').exists())
        history = Path(receipt['history'])
        self.assertEqual((history / 'runtime/openmaic-standalone/stale.js').read_bytes(), b'old complete OM tree')
        self.assertTrue((history / 'frozen-prepare-report.json').is_file())
        repair.assert_called_once_with(self.program.resolve(), [])

    def test_stopped_guard_and_changed_extra_source_reject_before_archiving(self):
        plan = subject.load_plan(self.report_path, self.report_sha)
        with patch.object(subject.shared, 'assert_services_stopped', side_effect=RuntimeError('3794 active')):
            with self.assertRaisesRegex(RuntimeError, '3794'):
                subject.deploy(plan)
        self.assertEqual((self.program / 'runtime/openmaic-standalone/stale.js').read_bytes(), b'old complete OM tree')
        source = plan['component']['source_path']
        for name, content in [('server.js', b'changed after preflight'), ('unexpected.json', b'uninventoried')]:
            with self.subTest(name=name):
                fixtures.write(source / name, content)
                with patch.object(subject.shared, 'assert_services_stopped', return_value={'six_ports_stopped': True, 'owned_processes_active': False}):
                    with self.assertRaises(RuntimeError):
                        subject.deploy(plan)
                self.assertEqual((self.program / 'runtime/openmaic-standalone/stale.js').read_bytes(), b'old complete OM tree')
                self.assertFalse((self.program / 'reports/r4-runtime-history').exists())
                if name == 'server.js':
                    fixtures.write(source / name, b'new OM server')


if __name__ == '__main__':
    unittest.main(verbosity=2)
