"""Deterministic lifecycle fixtures; these do not prove live model capability."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import desktop_runtime as runtime


class DesktopRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="desktop-test-", dir=runtime.ROOT / "runtime" / "temp")
        self.state = Path(self.folder.name)
        storage = SimpleNamespace(process_root=self.state, state_root=self.state, qwen_state=self.state / "local-qwen", prepare=lambda path: path.mkdir(parents=True, exist_ok=True), child_environment=lambda: {})
        self.patch = patch.object(runtime, "STORAGE", storage)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.folder.cleanup()

    def test_start_only_claims_new_processes(self):
        before = {55: {"pid": 55, "created": 1}}
        after = {**before, 66: {"pid": 66, "created": 2}}
        with patch.object(runtime, "snapshot", side_effect=[before, after]), patch.object(runtime.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            self.assertEqual(runtime.start_owned("123-456"), 0)
        state = json.loads(runtime.claim_file("123-456").read_text())
        self.assertEqual([item["pid"] for item in state["processes"]], [66])

    def test_failed_start_still_records_new_process(self):
        with patch.object(runtime, "snapshot", side_effect=[{}, {66: {"pid": 66, "created": 2}}]), patch.object(runtime.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            self.assertEqual(runtime.start_owned("123-456"), 1)
        self.assertEqual(json.loads(runtime.claim_file("123-456").read_text())["processes"][0]["pid"], 66)

    def test_claim_rejects_traversal_before_filesystem_write(self):
        for value in ["../other", "1-2.json", "abc", "1-2/3"]:
            with self.assertRaises(ValueError):
                runtime.claim_file(value)

    def test_stop_skips_a_reused_pid(self):
        item = {"pid": 66, "created": 2, "executable": "owned", "command_hash": "known"}
        filename = runtime.claim_file("123-456")
        filename.write_text(json.dumps({"processes": [item]}))
        process = MagicMock(pid=66)
        with patch("psutil.Process", return_value=process), patch.object(runtime, "identity", return_value={**item, "created": 9}), patch("psutil.wait_procs", return_value=([], [])):
            self.assertEqual(runtime.stop_owned("123-456"), 0)
        process.terminate.assert_not_called()

    def test_stop_targets_only_claimed_pid_and_descendants(self):
        item = {"pid": 66, "created": 2, "executable": "owned", "command_hash": "known"}
        filename = runtime.claim_file("123-456")
        filename.write_text(json.dumps({"processes": [item]}))
        process = MagicMock(pid=66)
        child = MagicMock(pid=67)
        process.children.return_value = [child]
        with patch("psutil.Process", return_value=process) as lookup, patch.object(runtime, "identity", return_value=item), patch("psutil.wait_procs", return_value=([], [])):
            self.assertEqual(runtime.stop_owned("123-456"), 0)
        lookup.assert_called_once_with(66)
        process.terminate.assert_called_once()
        child.terminate.assert_called_once()
        self.assertFalse(filename.exists())

    def test_owned_harness_graceful_shutdown_precedes_fallback(self):
        item = {"pid": 66, "created": 2, "executable": "owned", "command_hash": "known"}
        filename = runtime.claim_file("123-456")
        filename.write_text(json.dumps({"processes": [item]}))
        harness = self.state / "harness-state" / "runtime.json"
        harness.parent.mkdir()
        harness.write_text(json.dumps({"pid": 66, "created": 2}))
        process = MagicMock(pid=66)
        process.children.return_value = []
        events = []
        process.terminate.side_effect = lambda: events.append("fallback")
        with patch("psutil.Process", return_value=process), patch.object(runtime, "identity", return_value=item), patch("psutil.wait_procs", return_value=([], [])), patch.object(runtime.subprocess, "run", side_effect=lambda *args, **kwargs: events.append("graceful")):
            self.assertEqual(runtime.stop_owned("123-456"), 0)
        self.assertEqual(events, ["graceful", "fallback"])

    def test_failed_deeptutor_start_is_found_in_actual_plural_state_filename(self):
        state = self.state / "deeptutor-processes.json"
        state.write_text(json.dumps({"processes": [{"pid": 66, "created": 2, "name": "backend"}]}))
        process = MagicMock(pid=66)
        process.create_time.return_value = 2
        item = {"pid": 66, "created": 2, "executable": "owned", "command_hash": "known"}
        with patch("psutil.net_connections", return_value=[]), patch("psutil.Process", return_value=process), patch.object(runtime, "identity", return_value=item):
            self.assertEqual(runtime.snapshot(), {66: item})


if __name__ == "__main__":
    unittest.main()
