"""Exercise the actual same-version atomic resume entry point with tiny files."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import build_installer as build


def main():
    directory = BASE / 'resume-fixtures' / uuid.uuid4().hex[:8]
    directory.mkdir(parents=True)
    content = b'Completed atomic file retained and verified.\n'
    expected = hashlib.sha256(content).hexdigest()
    check = ('param([string]$InstallRoot)\n'
             '$ErrorActionPreference="Stop"\n'
             '$bytes=[IO.File]::ReadAllBytes((Join-Path $InstallRoot "existing.txt"))\n'
             '$hash=[Security.Cryptography.SHA256]::Create().ComputeHash($bytes)\n'
             '$actual=[BitConverter]::ToString($hash).Replace("-", "").ToLower()\n'
             f'if($actual -ne "{expected}"){{throw "Fixture SHA mismatch"}}\n'
             'if(!(Test-Path -LiteralPath (Join-Path $InstallRoot "missing.txt"))){throw "Missing file"}\n')
    archive = directory / 'fixture.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
        package.writestr('existing.txt', content)
        package.writestr('missing.txt', 'Restored after interruption')
        package.writestr('installer/Install-DeepSteam.ps1', check)
        for name in ('Start-DeepSteam.ps1', 'Stop-DeepSteam.ps1'):
            package.writestr('installer/' + name, 'param([string]$InstallRoot)\n')
    exe = directory / 'fixture.exe'
    build.compile_exe(exe)
    build.append_payload(exe, archive)
    results = []
    for label, marker, complete, valid, tampered in (
            ('same_version_partial', 'DeepSteam 2026.10.10-r3', False, True, False),
            ('ordinary_directory', None, False, False, False),
            ('wrong_version', 'DeepSteam 2026.10.10-r2', False, False, False),
            ('already_complete', 'DeepSteam 2026.10.10-r3', True, False, False),
            ('same_version_changed_file', 'DeepSteam 2026.10.10-r3', False, False, True)):
        target = directory / label
        target.mkdir()
        original = b'Changed content must be retained and rejected by SHA.' if tampered else content
        (target / 'existing.txt').write_bytes(original)
        if marker:
            (target / '.deepsteam-installing').write_text(marker, 'utf-8')
        if complete:
            (target / '.deepsteam-installed').write_text('Fixture prior completion', 'utf-8')
        before = (target / 'existing.txt').stat().st_mtime_ns
        proc = subprocess.run([str(exe), '--resume-install-to', str(target), '--no-launch'],
                              capture_output=True, text=True, timeout=40,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        assert (proc.returncode == 0) == valid, (label, proc.stdout, proc.stderr)
        assert (target / 'existing.txt').read_bytes() == original
        assert (target / 'existing.txt').stat().st_mtime_ns == before
        if valid:
            assert (target / 'missing.txt').is_file()
            assert (target / '.deepsteam-installed').is_file()
            assert not (target / '.deepsteam-installing').exists()
        elif not tampered:
            assert not (target / 'missing.txt').exists()
        else:
            assert not (target / '.deepsteam-installed').exists()
            assert (target / '.deepsteam-installing').is_file()
        results.append({'case': label, 'passed': True, 'completed_file_preserved': True})
    report = {'fixture_root': str(directory), 'actual_windows_exe': True,
              'cases': results, 'services_started': False, 'models_called': False}
    (BASE / 'resume-fixture-test-report.json').write_text(json.dumps(report, indent=2), 'utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
