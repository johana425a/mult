"""Check installer layout, measured progress and uninstall root hand-off without showing UI."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
CSC=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')

class InstallerPresentationTests(unittest.TestCase):
    def test_hidden_layout_progress_and_desktop_entry(self):
        with tempfile.TemporaryDirectory(prefix='DeepSteam presentation fixture ') as temporary:
            directory=Path(temporary).resolve(strict=True)
            print('Owned disposable test directory:',directory,flush=True)
            exe=directory/'presentation.exe'
            args=[str(CSC),'/nologo','/target:exe','/platform:x64','/codepage:65001',
                '/main:DeepSteamInstaller.InstallerPresentationTests','/out:'+str(exe),
                '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
                '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
                '/reference:System.Runtime.Serialization.dll',str(ROOT/'installer/DeepSteamSetup.cs'),
                str(ROOT/'tests/release/InstallerPresentationTests.cs')]
            build=subprocess.run(args,capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(build.returncode,0,build.stdout.decode('utf-8','replace'))
            result=subprocess.run([str(exe),str(directory/'隔离 install')],capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace'))
            print(result.stdout.decode('utf-8','replace').strip())

if __name__=='__main__':unittest.main(verbosity=2)
