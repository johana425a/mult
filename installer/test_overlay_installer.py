"""Exercise the real C# installer with Zip64 and >2 GiB overlay offsets.

Fixtures are explicitly software tests; they contain no actual model or course.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import msvcrt
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_installer as build

BASE = Path(__file__).resolve().parent
FIXTURES = BASE / 'overlay-fixtures'


def sparse_extend(path: Path, length: int) -> None:
    with path.open('r+b') as stream:
        returned = ctypes.c_ulong()
        handle = msvcrt.get_osfhandle(stream.fileno())
        ok = ctypes.windll.kernel32.DeviceIoControl(ctypes.c_void_p(handle), 0x000900C4,
            None, 0, None, 0, ctypes.byref(returned), None)
        if not ok:
            raise ctypes.WinError()
        stream.truncate(length)


def zip64_eocd(path: Path) -> None:
    content = path.read_bytes()
    eocd = content[-22:]
    signature, disk, cd_disk, n_disk, n_total, cd_size, cd_offset, comment = struct.unpack('<4s4H2IH', eocd)
    assert signature == b'PK\x05\x06' and not comment
    offset = len(content) - 22
    record = struct.pack('<4sQ2H2I4Q', b'PK\x06\x06', 44, 45, 45, 0, 0,
                         n_disk, n_total, cd_size, cd_offset)
    locator = struct.pack('<4sIQI', b'PK\x06\x07', 0, offset, 1)
    legacy = struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, 65535, 65535,
                         0xffffffff, 0xffffffff, 0)
    path.write_bytes(content[:-22] + record + locator + legacy)


def run_test(exe: Path, expected_success: bool, name: str) -> dict:
    report = FIXTURES / (name + '.txt')
    process = subprocess.run([str(exe), '--self-test', str(report)], timeout=40,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    text = report.read_text('utf-8')
    success = process.returncode == 0
    if success != expected_success:
        raise AssertionError(name + ': ' + text)
    return {'case': name, 'exit_code': process.returncode, 'report': text.strip()}


def main():
    FIXTURES.mkdir(exist_ok=True)
    stub = FIXTURES / 'bare.exe'
    build.compile_exe(stub)
    archive = FIXTURES / 'fixture.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as package:
        for name in ('Install-DeepSteam.ps1', 'Start-DeepSteam.ps1', 'Stop-DeepSteam.ps1'):
            package.writestr('installer/' + name, 'param([string]$InstallRoot)\nWrite-Output "SOFTWARE TEST fixture"\n')
        package.write(stub, 'DeepSteam.exe')
        info = zipfile.ZipInfo('fixture.txt')
        with package.open(info, 'w', force_zip64=True) as stream:
            stream.write(b'DeepSteam installer fixture; no model call.\n')
    zip64_eocd(archive)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
    normal = FIXTURES / 'valid.exe'
    shutil.copy2(stub, normal)
    normal_overlay = build.append_payload(normal, archive)
    large = FIXTURES / 'large-offset.exe'
    shutil.copy2(stub, large)
    sparse_extend(large, 2 * 1024**3 + 12345)
    large_overlay = build.append_payload(large, archive)
    cases = [run_test(normal, True, 'zip64'), run_test(large, True, 'offset_above_2gib')]
    external = FIXTURES / 'external.exe'
    shutil.copy2(stub, external)
    external_payload = external.with_suffix('.payload.dat')
    external_payload.write_bytes(b'')
    external_overlay = build.append_payload(external_payload, archive)
    assert external_overlay['offset'] == 0
    cases.append(run_test(external, True, 'companion_zip64'))
    missing = FIXTURES / 'missing-companion.exe'
    shutil.copy2(stub, missing)
    cases.append(run_test(missing, False, 'missing_companion'))
    corrupt = FIXTURES / 'corrupt.exe'
    shutil.copy2(normal, corrupt)
    with corrupt.open('r+b') as stream:
        stream.seek(normal_overlay['offset'])
        stream.write(b'FAIL')
    cases.append(run_test(corrupt, False, 'hash_corruption'))
    invalid = FIXTURES / 'invalid-offset.exe'
    shutil.copy2(normal, invalid)
    with invalid.open('r+b') as stream:
        stream.seek(-48, 2)
        stream.write(struct.pack('<Q', 2**63 - 1))
    cases.append(run_test(invalid, False, 'invalid_bounds'))
    unsafe_zip = FIXTURES / 'unsafe.zip'
    with zipfile.ZipFile(unsafe_zip, 'w') as package:
        package.writestr('../escape.txt', 'must be rejected')
    unsafe = FIXTURES / 'unsafe.exe'
    shutil.copy2(stub, unsafe)
    build.append_payload(unsafe, unsafe_zip)
    cases.append(run_test(unsafe, False, 'path_traversal'))
    target = FIXTURES / ('installed-' + uuid.uuid4().hex[:8])
    if target.exists():
        raise RuntimeError('Use a fresh fixture directory; never overwrite test installation')
    process = subprocess.run([str(normal), '--install-to', str(target), '--no-launch'],
                             timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode == 0
    assert (target / 'fixture.txt').read_bytes().startswith(b'DeepSteam installer fixture')
    assert (target / '.deepsteam-installed').is_file()
    cases.append({'case': 'extract_and_install', 'exit_code': 0,
                  'fixture_preserved': True, 'installed_marker': True})
    report = {'format': 'pe-overlay-zip64-v1', 'cases': cases,
              'large_exe_bytes': large.stat().st_size, 'large_overlay': large_overlay,
              'model_calls': False, 'fixtures_only': True}
    (BASE / 'overlay-fixture-test-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
