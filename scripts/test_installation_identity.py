"""No-spawn fixtures for Windows install boundaries and process identity."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from installation_identity import command_in_install, path_in_install
import desktop_runtime


class InstallationBoundaryTests(unittest.TestCase):
    root = 'D:\\DeepSteam-Fixture'

    def test_exact_root_and_descendant(self):
        self.assertTrue(path_in_install(self.root, self.root))
        self.assertTrue(path_in_install(self.root + '\\runtime\\node.exe', self.root))

    def test_sibling_prefix_does_not_count(self):
        self.assertFalse(path_in_install(self.root + '-Other\\runtime\\node.exe', self.root))
        self.assertFalse(command_in_install([self.root + '-Other\\runtime\\node.exe'], self.root))

    def test_case_forward_slash_and_trailing_slash(self):
        self.assertTrue(path_in_install('d:/deepsteam-fixture/runtime/node.exe', self.root + '\\'))
        self.assertFalse(path_in_install('d:/deepsteam-fixture-other/runtime/node.exe', self.root))

    def test_dot_parent_escape_is_rejected(self):
        self.assertFalse(path_in_install(self.root + '\\..\\other\\node.exe', self.root))
        self.assertFalse(path_in_install('runtime\\node.exe', self.root))

    def test_repr_root_in_python_c_accepts_external_interpreter(self):
        code = 'import sys; sys.path.insert(0, ' + repr(self.root) + '); import uvicorn'
        self.assertIn('\\\\', code)
        self.assertTrue(command_in_install(['C:\\Python\\python.exe', '-I', '-B', '-c', code], self.root))

    def test_sibling_literal_in_python_c_is_rejected(self):
        code = 'import sys; sys.path.insert(0, ' + repr(self.root + '-Other') + ')'
        self.assertFalse(command_in_install(['C:\\Python\\python.exe', '-c', code], self.root))

    def test_c_code_is_parsed_without_execution(self):
        code = 'raise RuntimeError("must not run"); root = ' + repr(self.root)
        self.assertTrue(command_in_install(['C:\\Python\\python.exe', '-c', code], self.root))
        self.assertFalse(command_in_install(['C:\\Python\\python.exe', '-c', 'invalid ('], self.root))

    def test_embedded_arbitrary_text_is_not_a_path(self):
        self.assertFalse(command_in_install(['C:\\Other\\tool.exe', 'text ' + self.root + '\\node.exe'], self.root))
        self.assertFalse(command_in_install(' '.join([self.root, '-Other']), self.root))

    def test_desktop_identity_rejects_sibling_but_keeps_contract(self):
        process = MagicMock(pid=42)
        process.create_time.return_value = 51
        process.exe.return_value = str(desktop_runtime.ROOT / 'runtime' / 'node.exe')
        command = [str(desktop_runtime.ROOT) + '-Other\\runtime\\node.exe']
        process.cmdline.return_value = command
        self.assertIsNone(desktop_runtime.identity(process))
        command = [str(desktop_runtime.ROOT / 'runtime' / 'node.exe')]
        process.cmdline.return_value = command
        item = desktop_runtime.identity(process)
        self.assertEqual(item['pid'], 42)
        self.assertEqual(item['created'], 51)
        self.assertEqual(len(item['command_hash']), 64)


if __name__ == '__main__':
    unittest.main()
