"""Run the shipping shortcut cleanup against isolated Chinese/English links."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CSC = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')

class InstallerShortcutsTests(unittest.TestCase):
    def test_owned_chinese_english_and_uninstall_links_removed_others_retained(self):
        with tempfile.TemporaryDirectory(prefix='DS shortcuts fixture ') as directory:
            root = Path(directory)
            exe = root / 'shortcuts.exe'
            compile_result = subprocess.run([str(CSC), '/nologo', '/target:exe', '/platform:x64', '/codepage:65001',
                '/main:DeepSteamInstaller.InstallerShortcutTests', '/out:' + str(exe),
                '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                '/reference:System.Runtime.Serialization.dll', str(ROOT / 'installer/DeepSteamSetup.cs'),
                str(ROOT / 'tests/release/InstallerShortcutTests.cs')], capture_output=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout.decode('utf-8', 'replace'))
            result = subprocess.run([str(exe), str(root)], capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
            self.assertIn(b'PASS 7 assertions', result.stdout)

if __name__ == '__main__':
    unittest.main(verbosity=2)
