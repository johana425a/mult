"""Verify raw compressed model reuse with forced Zip64 and real C# reading."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_installer as build


def main():
    base = build.BASE / 'model-cache-fixtures' / uuid.uuid4().hex[:8]
    base.mkdir(parents=True)
    content = {
        'models/local-qwen/Qwen3.5-4B-Q4_K_M.gguf': b'GGUF MODEL FIXTURE ONLY\n' * 20000,
        'models/local-qwen/mmproj-F16.gguf': bytes(range(256)) * 2000,
    }
    rows = [{'path': name, 'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
            for name, value in content.items()]
    cache = base / 'models.zip'
    with zipfile.ZipFile(cache, 'w', zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as source:
        for name, value in content.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            with source.open(info, 'w', force_zip64=True) as output:
                output.write(value)
    metadata = base / 'models.json'
    metadata.write_text(json.dumps({'model_files': rows, 'archive_sha256': hashlib.sha256(cache.read_bytes()).hexdigest()}), 'utf-8')
    archive = base / 'combined.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as target:
        seeded = build.seed_cached_models(target, rows, cache, metadata)
        assert seeded == set(content)
        for name in ('Install-DeepSteam.ps1', 'Start-DeepSteam.ps1', 'Stop-DeepSteam.ps1'):
            target.writestr('installer/' + name, 'param([string]$InstallRoot)\nWrite-Output "FIXTURE only"\n')
        target.writestr('fixture.txt', 'Appended after copied Zip64 models')
    with zipfile.ZipFile(archive) as target:
        assert target.testzip() is None
        for name, value in content.items():
            assert target.read(name) == value
        assert target.read('fixture.txt') == b'Appended after copied Zip64 models'
    exe = base / 'fixture.exe'
    build.compile_exe(exe)
    build.append_payload(exe, archive)
    report = base / 'csharp-self-test.txt'
    subprocess.run([str(exe), '--self-test', str(report)], timeout=40, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    result = {'fixture_root': str(base), 'forced_zip64_local_headers': True,
              'reused_model_entries': 2, 'crc_and_exact_content_passed': True,
              'actual_csharp_self_test': report.read_text('utf-8').strip(), 'models_called': False}
    (build.BASE / 'model-cache-fixture-test-report.json').write_text(json.dumps(result, indent=2), 'utf-8')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
