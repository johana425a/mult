"""Relocation contracts; never starts or stops the developer's running app."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import deeptutor_runtime
import runtime_paths


class PortableRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="DeepSteam relocation ")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def file(self, relative):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"test placeholder")
        return target.resolve()

    def test_bundled_tools_win_over_machine_path(self):
        node = self.file("runtime/node/node.exe")
        python = self.file("runtime/python/python.exe")
        chrome = self.file("runtime/chromium/chrome-win64/chrome.exe")
        with patch.object(runtime_paths, "ROOT", self.root), patch.dict(
                runtime_paths.os.environ, {"DEEPSTEAM_NODE": "C:/missing/node.exe",
                                           "DEEPSTEAM_BROWSER": "C:/missing/chrome.exe"}):
            self.assertEqual(runtime_paths.node_executable(), node)
            self.assertEqual(runtime_paths.python_executable("portal"), python)
            self.assertEqual(runtime_paths.python_executable("deeptutor"), python)
            self.assertEqual(runtime_paths.browser_executable(), chrome)

    def test_missing_browser_reports_repair_without_download(self):
        with patch.object(runtime_paths, "ROOT", self.root), patch.dict(
                runtime_paths.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "bundled Chromium"):
                runtime_paths.browser_executable()

    def test_relative_frontend_manifest_uses_install_root(self):
        server = self.file("runtime/native-frontends/release/server.js")
        manifest = self.root / "runtime/native-frontend.json"
        manifest.write_text(json.dumps({"root": "runtime/native-frontends/release",
                                       "api_base": deeptutor_runtime.API}), encoding="utf-8")
        with patch.object(deeptutor_runtime, "ROOT", self.root):
            self.assertEqual(deeptutor_runtime.read_native_frontend(manifest)[1], server.parent)

    def test_frontend_manifest_cannot_escape_installation(self):
        self.file("outside/server.js")
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"root": "runtime/native-frontends/../../../outside",
                                       "api_base": deeptutor_runtime.API}), encoding="utf-8")
        with patch.object(deeptutor_runtime, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "inside this project"):
                deeptutor_runtime.read_native_frontend(manifest)

    def test_frontend_rejects_foreign_backend(self):
        self.file("runtime/native-frontends/release/server.js")
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"root": "runtime/native-frontends/release",
                                       "api_base": "https://example.invalid"}), encoding="utf-8")
        with patch.object(deeptutor_runtime, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "different backend"):
                deeptutor_runtime.read_native_frontend(manifest)


if __name__ == "__main__":
    unittest.main()
