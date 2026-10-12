"""Deterministic startup fixtures; no real services or model calls are made."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portal_runtime as runtime


def healthy_status():
    return {'healthy': True,
            'services': {'services': {name: {'ok': True} for name in ('deeptutor', 'openmaic')}},
            'auxiliary_http': {name: True for name in ('deeptutor_ui', 'renderer', 'harness')},
            'listeners': [{'host': '127.0.0.1', 'port': port, 'pid': port + 10000}
                          for port in runtime.SERVICE_PORTS.values()]}


def owned_processes():
    return {port: {port + 10000} for port in runtime.SERVICE_PORTS.values()}


class StartupReadinessTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0.0
        self.patches = [patch.object(runtime, 'harness_installed', return_value=True),
                        patch.object(runtime, '_write_startup_timings'),
                        patch.object(runtime.time, 'monotonic', side_effect=lambda: self.clock),
                        patch.object(runtime.time, 'sleep', side_effect=self.sleep),
                        patch.object(runtime, 'recorded_processes', return_value=(owned_processes(), set())),
                        patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('No real spawn in fixture')),
                        patch.object(runtime.subprocess, 'run', side_effect=AssertionError('No real subprocess in fixture'))]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def sleep(self, seconds):
        self.clock += seconds

    def test_early_nonzero_launcher_can_finish_ready_without_relaunch(self):
        early = healthy_status()
        early['services']['services']['openmaic']['ok'] = False
        with patch.object(runtime, 'upstream', return_value=[{'service': 'openmaic_runtime.py', 'exit_code': 1}]) as upstream, \
             patch.object(runtime, 'start_portal', return_value=early) as portal, \
             patch.object(runtime, 'status', side_effect=[early, healthy_status()]) as probe:
            report = runtime.start_services(timeout=2)
        self.assertTrue(report['startup']['ready'])
        self.assertEqual(report['services'][0]['exit_code'], 1)
        upstream.assert_called_once()
        portal.assert_called_once()
        self.assertEqual(probe.call_count, 2)

    def test_late_portal_readiness_recovers_its_fixed_window_timeout(self):
        early = healthy_status()
        early['healthy'] = False
        with patch.object(runtime, 'upstream', return_value=[]), \
             patch.object(runtime, 'start_portal', side_effect=RuntimeError('fixed window expired')) as portal, \
             patch.object(runtime, 'status', side_effect=[early, healthy_status()]):
            report = runtime.start_services(timeout=2)
        self.assertTrue(report['startup']['ready'])
        portal.assert_called_once()

    def test_continually_missing_service_times_out(self):
        value = healthy_status()
        value['auxiliary_http']['renderer'] = False
        with patch.object(runtime, 'status', return_value=value):
            report = runtime.wait_for_startup(timeout=1)
        self.assertFalse(report['ready'])
        self.assertEqual(report['reason'], 'timeout')
        self.assertEqual(report['missing'], [{'service': 'renderer', 'port': 3794}])
        self.assertEqual(self.clock, 1)

    def test_portal_http_200_is_not_success(self):
        with patch.object(runtime, 'status', return_value={'healthy': True, 'listeners': []}):
            report = runtime.wait_for_startup(timeout=.5)
        self.assertEqual(report['reason'], 'timeout')
        self.assertEqual(len(report['missing']), 6)

    def test_each_original_requirement_still_blocks_success(self):
        values = []
        for service in ('deeptutor', 'openmaic'):
            value = healthy_status()
            value['services']['services'][service]['ok'] = False
            values.append(value)
        for service in ('deeptutor_ui', 'renderer', 'harness'):
            value = healthy_status()
            value['auxiliary_http'][service] = False
            values.append(value)
        value = healthy_status()
        value['listeners'].pop()
        values.append(value)
        for value in values:
            self.clock = 0
            with patch.object(runtime, 'status', return_value=value):
                self.assertFalse(runtime.wait_for_startup(timeout=.1)['ready'])

    def test_foreign_listener_cannot_be_adopted_despite_healthy_http(self):
        value = healthy_status()
        value['listeners'][0]['pid'] = 99999
        with patch.object(runtime, 'status', return_value=value):
            report = runtime.wait_for_startup(timeout=2)
        self.assertEqual(report['reason'], 'unverified_listener')
        self.assertFalse(report['ready'])
        self.assertEqual(report['missing'], [{'service': 'portal', 'port': 3791}])

    def test_non_loopback_listener_cannot_be_accepted(self):
        value = healthy_status()
        value['listeners'][0]['host'] = '0.0.0.0'
        with patch.object(runtime, 'status', return_value=value):
            report = runtime.wait_for_startup(timeout=.1)
        self.assertFalse(report['ready'])

    def test_known_dead_service_fails_without_waiting_out_timeout(self):
        value = healthy_status()
        value['listeners'] = [item for item in value['listeners'] if item['port'] != 3794]
        with patch.object(runtime, 'status', return_value=value), \
             patch.object(runtime, 'recorded_processes', return_value=(owned_processes(), {3794})):
            report = runtime.wait_for_startup(timeout=180)
        self.assertEqual(report['reason'], 'service_exited')
        self.assertEqual(self.clock, 0)

    def test_cancelled_wait_does_not_probe_or_spawn(self):
        with patch.object(runtime, 'status') as probe:
            report = runtime.wait_for_startup(cancelled=lambda: True)
        self.assertEqual(report['reason'], 'cancelled')
        probe.assert_not_called()

    def test_cancelled_result_is_not_overridden_by_late_health(self):
        with patch.object(runtime, 'status', return_value=healthy_status()), \
             patch.object(runtime, 'recorded_processes', return_value=(owned_processes(), set())):
            checks = iter([False, True])
            report = runtime.wait_for_startup(cancelled=lambda: next(checks))
        self.assertEqual(report['reason'], 'cancelled')

    def test_cancelled_upstream_does_not_spawn(self):
        with self.assertRaises(KeyboardInterrupt):
            runtime.upstream('start', cancelled=lambda: True)

    def test_keyboard_interrupt_has_cancel_code_and_no_extra_launch(self):
        output = io.StringIO()
        with patch.object(runtime, 'upstream', return_value=[]) as launch, \
             patch.object(runtime, 'start_portal', return_value={}) as portal, \
             patch.object(runtime, 'status', side_effect=KeyboardInterrupt), redirect_stdout(output):
            code = runtime.main(['start'])
        self.assertEqual(code, 130)
        launch.assert_called_once()
        portal.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())['startup']['reason'], 'cancelled')

    def test_cli_timeout_is_nonzero_and_diagnostics_never_copy_logs(self):
        output = io.StringIO()
        with patch.object(runtime, 'start_services', return_value={'services': [], 'startup': {
                'ready': False, 'reason': 'timeout', 'missing': [{'service': 'renderer', 'port': 3794}]}}), \
             redirect_stdout(output):
            code = runtime.main(['start'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['startup']['missing'][0]['port'], 3794)
        output = io.StringIO()
        with patch.object(runtime, 'start_services', side_effect=RuntimeError('SECRET-TEST-value')), redirect_stdout(output):
            self.assertEqual(runtime.main(['start']), 1)
        self.assertNotIn('SECRET-TEST-value', output.getvalue())

    def test_startup_success_return_code_ignores_early_exit_code(self):
        with patch.object(runtime, 'start_services', return_value={'services': [{'exit_code': 1}],
                'startup': {'ready': True, 'reason': 'ready', 'missing': []}}), redirect_stdout(io.StringIO()):
            self.assertEqual(runtime.main(['start']), 0)


class RecordedProcessTests(unittest.TestCase):
    def setUp(self):
        self.storage = SimpleNamespace(process_root=Path('X:/fixture/runtime'),
                                       qwen_state=Path('X:/fixture/runtime/local-qwen'),
                                       render_local=lambda _: Path('X:/fixture/renderer'))
        self.value = {'pid': 123, 'created': 50}
        self.process = MagicMock(pid=123)
        self.process.create_time.return_value = 50
        self.process.cmdline.return_value = [str(runtime.ROOT / 'runtime' / 'node.exe')]
        self.process.is_running.return_value = True
        self.process.status.return_value = 'running'
        self.process.children.return_value = []

    def read_record(self, path, *args, **kwargs):
        if path == runtime.STATE:
            return json.dumps(self.value)
        raise FileNotFoundError

    def inspect(self, lookup=None):
        with patch.object(runtime, 'STORAGE', self.storage), \
             patch.object(Path, 'read_text', autospec=True, side_effect=self.read_record), \
             patch('psutil.Process', side_effect=lookup) if lookup else patch('psutil.Process', return_value=self.process):
            return runtime.recorded_processes()

    def test_record_creation_time_and_install_path_required(self):
        self.assertEqual(self.inspect(), ({3791: {123}}, set()))
        self.process.create_time.return_value = 99
        self.assertEqual(self.inspect(), ({}, set()))
        self.process.create_time.return_value = 50
        self.process.cmdline.return_value = ['X:/unrelated/node.exe']
        self.assertEqual(self.inspect(), ({}, set()))

    def test_recorded_child_listener_is_allowed(self):
        child = MagicMock(pid=124)
        child.cmdline.return_value = [str(runtime.ROOT / 'runtime' / 'renderer' / 'src' / 'main.ts')]
        self.process.children.return_value = [child]
        self.assertEqual(self.inspect(), ({3791: {123, 124}}, set()))

    def test_sibling_install_cannot_own_a_recorded_listener(self):
        self.process.cmdline.return_value = [str(runtime.ROOT) + '-Other\\runtime\\node.exe']
        self.assertEqual(self.inspect(), ({}, set()))

    def test_sibling_child_is_not_adopted(self):
        child = MagicMock(pid=124)
        child.cmdline.return_value = [str(runtime.ROOT) + '-Other\\runtime\\node.exe']
        self.process.children.return_value = [child]
        self.assertEqual(self.inspect(), ({3791: {123}}, set()))

    def test_repr_root_portal_with_external_interpreter_is_recognized(self):
        code = 'import sys; sys.path.insert(0, ' + repr(str(runtime.ROOT)) + ')'
        self.process.cmdline.return_value = ['C:\\ExternalPython\\python.exe', '-c', code]
        self.assertEqual(self.inspect(), ({3791: {123}}, set()))

    def test_start_portal_does_not_adopt_sibling_record(self):
        self.process.cmdline.return_value = [str(runtime.ROOT) + '-Other\\runtime\\node.exe']
        sock = MagicMock()
        sock.__enter__.return_value.connect_ex.return_value = 0
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'read_text', autospec=True, side_effect=self.read_record), \
             patch.object(runtime, 'configure_tokenizer_cache'), \
             patch('psutil.Process', return_value=self.process), \
             patch.object(runtime.socket, 'socket', return_value=sock), \
             patch.object(runtime.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, 'occupied'):
                runtime.start_portal()
        launch.assert_not_called()

    def test_stop_portal_does_not_terminate_sibling_record(self):
        self.process.cmdline.return_value = [str(runtime.ROOT) + '-Other\\runtime\\node.exe']
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'read_text', autospec=True, side_effect=self.read_record), \
             patch('psutil.Process', return_value=self.process):
            with self.assertRaises(RuntimeError):
                runtime.stop_portal()
        self.process.terminate.assert_not_called()

    def test_missing_recorded_process_is_reported_dead(self):
        import psutil
        self.assertEqual(self.inspect(psutil.NoSuchProcess(123)), ({}, {3791}))


if __name__ == '__main__':
    unittest.main()
