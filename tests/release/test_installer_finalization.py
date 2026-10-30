"""Exercise actual >2 GiB installer finalization, factory ownership and rollback."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CSC = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')

class InstallerFinalizationTests(unittest.TestCase):
    def test_large_launcher_and_owned_factory_files_are_removed_and_rollback_is_bounded(self):
        with tempfile.TemporaryDirectory(prefix='DS large uninstall ') as directory:
            root = Path(directory)
            exe = root / 'large-uninstall.exe'
            compile_result = subprocess.run([str(CSC), '/nologo', '/target:exe', '/platform:x64', '/codepage:65001',
                '/main:DeepSteamInstaller.InstallerFinalizationTests', '/out:' + str(exe),
                '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                '/reference:System.Runtime.Serialization.dll', str(ROOT / 'installer/DeepSteamSetup.cs'),
                str(ROOT / 'tests/release/InstallerFinalizationTests.cs')], capture_output=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout.decode('utf-8', 'replace'))
            result = subprocess.run([str(exe), str(root / 'isolated app')], capture_output=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
            self.assertIn(b'PASS 15 assertions', result.stdout)
            print(result.stdout.decode('utf-8', 'replace').strip())

if __name__ == '__main__':
    unittest.main(verbosity=2)
