"""Controlled local fixtures: no services, model requests or user data."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portal_runtime as runtime
from test_portal_startup import healthy_status, owned_processes


ORDER = ['harness_runtime.py', 'deeptutor_runtime.py',
         'openmaic_runtime.py', 'render_runtime.py']


class ParallelLauncherTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.object(runtime, 'harness_installed', return_value=True),
                        patch.object(Path, 'exists', return_value=True),
                        patch.object(runtime, '_write_startup_timings'),
                        patch.object(runtime.subprocess, 'Popen', side_effect=AssertionError('No real spawn'))]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def test_all_required_launchers_enter_concurrently_and_results_remain_ordered(self):
        barrier = threading.Barrier(len(ORDER), timeout=5)
        lock = threading.Lock()
        active = 0
        peak = 0
        finished = []
        # Each launcher waits until its successor completes: completion is
        # deliberately opposite to the stable public diagnostic order.
        done = [threading.Event() for _ in ORDER]

        def launch(args, **kwargs):
            nonlocal active, peak
            name = Path(args[-2]).name
            index = ORDER.index(name)
            self.assertEqual(args[-1], 'start')
            self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
            self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait()
            if index + 1 < len(ORDER):
                self.assertTrue(done[index + 1].wait(5))
            with lock:
                finished.append(name)
                active -= 1
            done[index].set()
            return SimpleNamespace(returncode=index)

        with patch.object(runtime.subprocess, 'run', side_effect=launch):
            results = runtime.upstream('start')
        self.assertEqual(peak, len(ORDER))
        self.assertEqual(finished, list(reversed(ORDER)))
        self.assertEqual([item['service'] for item in results], ORDER)
        self.assertEqual([item['exit_code'] for item in results], list(range(len(ORDER))))
        self.assertTrue(all(item['timing']['elapsed_seconds'] >= 0 for item in results))

    def run_held_launchers(self, invoke, first_error=False, cancel=None):
        entered = threading.Barrier(len(ORDER) + 1, timeout=5)
        release = threading.Event()
        completed = set()
        lock = threading.Lock()

        def launch(args, **kwargs):
            name = Path(args[-2]).name
            entered.wait()
            if first_error and name == ORDER[0]:
                raise OSError('SECRET-fixture-command-key')
            self.assertTrue(release.wait(5))
            with lock:
                completed.add(name)
            return SimpleNamespace(returncode=0)

        with patch.object(runtime.subprocess, 'run', side_effect=launch), \
             ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(invoke, completed)
            try:
                entered.wait()
                if cancel is not None:
                    cancel.set()
                self.assertFalse(future.done(), 'Must join all in-flight launchers before returning')
            finally:
                release.set()
            if cancel is not None:
                with self.assertRaises(KeyboardInterrupt):
                    future.result(timeout=5)
                return completed
            return future.result(timeout=5), completed

    def test_failed_launcher_keeps_every_exit_and_waits_for_inflight_launchers(self):
        results, completed = self.run_held_launchers(lambda _: runtime.upstream('start'), first_error=True)
        self.assertEqual(completed, set(ORDER[1:]))
        self.assertEqual(results[0]['status'], 'launcher_failed')
        self.assertIsNone(results[0]['exit_code'])
        self.assertEqual([item['exit_code'] for item in results[1:]], [0] * (len(ORDER) - 1))
        self.assertNotIn('SECRET', json.dumps(results))

    def test_cancellation_joins_running_launchers_and_does_not_launch_portal(self):
        cancel = threading.Event()
        with patch.object(runtime, 'start_portal') as portal:
            completed = self.run_held_launchers(
                lambda _: runtime.start_services(cancelled=cancel.is_set), cancel=cancel)
        self.assertEqual(completed, set(ORDER))
        portal.assert_not_called()

    def test_portal_starts_only_after_all_launchers_complete_then_checks_all_services(self):
        def invoke(completed):
            def portal():
                self.assertEqual(completed, set(ORDER))
                return healthy_status()
            with patch.object(runtime, 'start_portal', side_effect=portal) as start_portal, \
                 patch.object(runtime, 'status', return_value=healthy_status()), \
                 patch.object(runtime, 'recorded_processes', return_value=(owned_processes(), set())):
                report = runtime.start_services(timeout=2)
            start_portal.assert_called_once()
            return report
        report, _ = self.run_held_launchers(invoke)
        self.assertTrue(report['startup']['ready'])
        self.assertEqual([event['service'] for event in report['timings']],
                         ORDER + ['portal', 'all_services', 'all_services'])
        self.assertEqual([event['phase'] for event in report['timings'][-3:]],
                         ['launch', 'readiness', 'total'])
        self.assertEqual(report['timings'][-1]['exit_code'], 0)

    def test_stop_is_still_serial_and_in_original_reverse_order(self):
        calls = []
        def stop(args, **kwargs):
            calls.append(Path(args[-2]).name)
            self.assertEqual(args[-1], 'stop')
            self.assertNotIn('stdout', kwargs)
            return SimpleNamespace(returncode=len(calls))
        with patch.object(runtime.subprocess, 'run', side_effect=stop), \
             patch.object(runtime, 'ThreadPoolExecutor', side_effect=AssertionError('Stop must stay serial')):
            results = runtime.upstream('stop')
        self.assertEqual(calls, list(reversed(ORDER)))
        self.assertEqual([row['exit_code'] for row in results], list(range(1, len(ORDER) + 1)))

    def test_pre_cancelled_launch_spawns_nothing(self):
        with patch.object(runtime.subprocess, 'run') as child, \
             patch.object(runtime, 'ThreadPoolExecutor') as executor:
            with self.assertRaises(KeyboardInterrupt):
                runtime.upstream('start', cancelled=lambda: True)
        child.assert_not_called()
        executor.assert_not_called()

    def test_missing_optional_harness_is_not_submitted(self):
        with patch.object(runtime, 'harness_installed', return_value=False), \
             patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as child:
            results = runtime.upstream('start')
        self.assertEqual([row['service'] for row in results], [name for name in ORDER if name != 'harness_runtime.py'])
        self.assertEqual(child.call_count, len(ORDER) - 1)

    def test_missing_script_is_reported_without_subprocess(self):
        with patch.object(Path, 'exists', side_effect=lambda: False), \
             patch.object(runtime.subprocess, 'run') as child:
            results = runtime.upstream('start')
        self.assertTrue(all(row['status'] == 'not_installed' for row in results))
        child.assert_not_called()

    def test_wrapper_timeout_is_retained_as_safe_failure_and_does_not_drop_peers(self):
        def launch(args, **kwargs):
            if Path(args[-2]).name == ORDER[0]:
                raise subprocess.TimeoutExpired('SECRET-fixture-command', 180)
            return SimpleNamespace(returncode=0)
        with patch.object(runtime.subprocess, 'run', side_effect=launch):
            results = runtime.upstream('start')
        self.assertEqual(len(results), len(ORDER))
        self.assertEqual(results[0]['status'], 'launcher_failed')
        self.assertNotIn('SECRET', json.dumps(results))


class StartupTimingTests(unittest.TestCase):
    def test_monotonic_service_and_total_durations(self):
        clock = [10.0]
        def upstream(*args, **kwargs):
            clock[0] += 8
            return []
        def portal():
            clock[0] += 2
        def readiness(*args):
            clock[0] += 1
            return {'ready': True, 'reason': 'ready', 'missing': []}
        with patch.object(runtime.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(runtime, 'upstream', side_effect=upstream), \
             patch.object(runtime, 'start_portal', side_effect=portal), \
             patch.object(runtime, 'wait_for_startup', side_effect=readiness) as wait, \
             patch.object(runtime, '_write_startup_timings') as write:
            report = runtime.start_services(timeout=37)
        wait.assert_called_once_with(37, None)
        self.assertEqual([item['elapsed_seconds'] for item in report['timings']], [2, 1, 11])
        self.assertEqual([item['started_after_seconds'] for item in report['timings']], [8, 10, 0])
        write.assert_called_once_with(report['timings'])

    def test_timing_log_failure_does_not_change_startup(self):
        with patch.object(runtime, 'upstream', return_value=[]), \
             patch.object(runtime, 'start_portal', return_value={}), \
             patch.object(runtime, 'wait_for_startup', return_value={'ready': True, 'reason': 'ready'}), \
             patch.object(Path, 'mkdir', side_effect=OSError('fixture disk failure')):
            self.assertTrue(runtime.start_services()['startup']['ready'])

    def test_timings_append_only_safe_metadata_and_keep_prior_entry(self):
        events = [{'service': 'portal', 'phase': 'launch', 'started_after_seconds': 1,
                   'elapsed_seconds': 2, 'exit_code': 0}]
        with tempfile.TemporaryDirectory(prefix='deepsteam-startup-timing-') as directory:
            with patch.object(runtime, 'STORAGE', SimpleNamespace(logs=Path(directory))):
                runtime._write_startup_timings(events)
                runtime._write_startup_timings(events)
            lines = (Path(directory) / 'startup-timings.jsonl').read_text('utf-8').splitlines()
        self.assertEqual([json.loads(line) for line in lines], [{'timings': events}, {'timings': events}])


if __name__ == '__main__':
    unittest.main()
