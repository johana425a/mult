"""Assemble reviewed components and publish a verified Windows installer."""
from __future__ import annotations
import hashlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
PAYLOAD = BASE / 'app-payload'
RELEASE = BASE / 'releases'
CSC = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
VERSION = '2026.10.10-r3'
EXPECTED_NATIVE_BUILD = '20261010-212012'
EXPECTED_OPENMAIC_BUILD = '20261011-000616'
EXPECTED_OPENMAIC_REPORT = 'openmaic-state-root-build-20261011-000616.json'
TRAILER_MAGIC = b'DeepSteamZip64v1'
MAX_PE_BYTES = 4 * 1024**3 - 65536


def lp(path):
    p = str(path)
    return p if p.startswith('\\\\?\\') else '\\\\?\\' + p


def copy_tree(source, target):
    for directory, dirs, files in os.walk(lp(source)):
        dirs[:] = [d for d in dirs if d not in {'__pycache__', '.pytest_cache'}]
        rel = os.path.relpath(directory, lp(source))
        if source == ROOT / 'integration' and rel.replace('\\', '/') == 'local_qwen':
            dirs[:] = [d for d in dirs if d != 'downloads']
        dest = target if rel == '.' else target / rel
        os.makedirs(lp(dest), exist_ok=True)
        for name in files:
            if name.endswith(('.pyc', '.pyo')):
                continue
            if name == '.env' or name.startswith('.env.'):
                continue
            if name.endswith('.partial'):
                continue
            if source == ROOT / 'integration' and rel.replace('\\', '/') == 'local_qwen' and name not in {
                    'manifest.json', 'README.md', 'SOURCE.md', 'NOTICE.md', 'ACCEPTANCE.md',
                    'acceptance-vulkan.json', 'acceptance-cpu-grounded.json'}:
                continue
            if source == ROOT / 'runtime/local-qwen' and (name == 'process.json' or name.endswith('.log')):
                continue
            shutil.copy2(os.path.join(directory, name), lp(dest / name))


def compile_exe(dest):
    command = [str(CSC), '/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/codepage:65001',
               '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
               '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
               '/win32manifest:' + str(BASE / 'DeepSteam.manifest'),
               '/resource:' + str(BASE / 'DeepSteamSetup.cs') + ',DeepSteamSetup.cs', '/out:' + str(dest)]
    command.append(str(BASE / 'DeepSteamSetup.cs'))
    subprocess.run(command, check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def append_payload(exe, archive):
    """Append a Zip64 segment without loading it into PE/.NET resources or RAM."""
    with exe.open('ab') as output, archive.open('rb') as source:
        offset = output.tell()
        digest = hashlib.sha256()
        length = 0
        while block := source.read(8 * 1024 * 1024):
            output.write(block)
            digest.update(block)
            length += len(block)
        output.write(struct.pack('<16sQQ32s', TRAILER_MAGIC, offset, length, digest.digest()))
    return {'format': 'pe-overlay-zip64-v1', 'offset': offset, 'bytes': length,
            'sha256': digest.hexdigest(), 'trailer_bytes': 64}


def seed_cached_models(package, rows, cache=BASE / 'model-payload-r3.zip', metadata=BASE / 'model-payload-r3.json'):
    """Seed an empty archive with unchanged, already compressed model entries.

    Python's ZipFile does not expose raw-entry copying. This narrow adapter uses
    its actual central-directory bookkeeping; all entry offsets remain unchanged
    because the model archive is copied at offset zero. The final ZIP is CRC tested
    and the actual C# installer reads it before publication.
    """
    if not cache.is_file() or not metadata.is_file():
        return set()
    info = json.loads(metadata.read_text('utf-8'))
    expected = {row['path']: row for row in rows if row['path'].lower().endswith('.gguf')}
    cached = {row['path']: row for row in info['model_files']}
    if set(cached) != set(expected):
        raise RuntimeError('Compressed model cache does not match packaged model paths')
    for name, row in cached.items():
        if row['sha256'] != expected[name]['sha256'] or row['bytes'] != expected[name]['bytes']:
            raise RuntimeError('Compressed model cache no longer matches source: ' + name)
    with cache.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != info['archive_sha256']:
            raise RuntimeError('Compressed model cache integrity failed')
    if package.filelist or package.start_dir != 0:
        raise RuntimeError('Compressed model cache must be the first archive segment')
    with zipfile.ZipFile(cache, 'r') as source:
        if set(source.namelist()) != set(expected):
            raise RuntimeError('Compressed model archive includes unexpected files')
        entries = [copy.copy(entry) for entry in source.infolist()]
        for entry in entries:
            if entry.compress_type != zipfile.ZIP_DEFLATED or entry.flag_bits & 1:
                raise RuntimeError('Unsupported compressed model cache entry')
        source.fp.seek(0)
        package.fp.seek(0)
        remaining = source.start_dir
        while remaining:
            block = source.fp.read(min(8 * 1024 * 1024, remaining))
            if not block:
                raise RuntimeError('Compressed model cache is truncated')
            package.fp.write(block)
            remaining -= len(block)
        package.filelist.extend(entries)
        package.NameToInfo.update({entry.filename: entry for entry in entries})
        package.start_dir = source.start_dir
        package._didModify = True
    print('Reused verified compressed models: ' + str(len(entries)), flush=True)
    return set(expected)


def main():
    # Kept for historical raw-ZIP helper imports; this r3 assembly predates the
    # shared document reader and does not represent the current product closure.
    raise RuntimeError('This historical r3 entry point is retired. Use installer/build_document_release.py to freeze reviewed program files and verify the packaged document runtime.')
    # Historical implementation below is retained for provenance, not executed.
    exe = RELEASE / ('DeepSteam-Setup-' + VERSION + '-x64.exe')
    pending_exe = RELEASE / ('DeepSteam-Setup-' + VERSION + '-x64.building.exe')
    if exe.exists() or pending_exe.exists():
        raise RuntimeError('Existing release or interrupted build retained; use a fresh output before rebuilding.')
    for required in ('python-runtime-manifest.json', 'vendor-runtime-manifest.json', 'frontend-payload-manifest.json'):
        if not (BASE / required).is_file():
            raise RuntimeError('Missing verified component manifest: ' + required)
    frontend = json.loads((BASE / 'frontend-payload-manifest.json').read_text('utf-8'))
    if frontend.get('native_build_id') != EXPECTED_NATIVE_BUILD:
        raise RuntimeError('Stage the current DeepSteam UI before building r3; expected ' + EXPECTED_NATIVE_BUILD)
    om_report = json.loads((ROOT / 'reports' / EXPECTED_OPENMAIC_REPORT).read_text('utf-8'))
    if om_report.get('build_id') != EXPECTED_OPENMAIC_BUILD:
        raise RuntimeError('Unexpected OpenMAIC build identity')
    source_next_id = (Path(om_report.get('staged_root', om_report.get('standalone'))) / '.next/BUILD_ID').read_text('utf-8').strip()
    payload_next_id = (PAYLOAD / 'runtime/openmaic-standalone/.next/BUILD_ID').read_text('utf-8').strip()
    if source_next_id != payload_next_id:
        raise RuntimeError('Stage the verified source-grounding OpenMAIC build before packaging r3')
    for required in (ROOT / 'runtime/local-qwen', ROOT / 'models/local-qwen', ROOT / 'scripts/qwen_runtime.py'):
        if not required.exists():
            raise RuntimeError('Local model component not ready; refusing to build a model-less release: ' + str(required))
    for required in (ROOT / 'models/local-qwen/Qwen3.5-4B-Q4_K_M.gguf', ROOT / 'models/local-qwen/mmproj-F16.gguf', ROOT / 'integration/local_qwen/manifest.json'):
        if not required.is_file():
            raise RuntimeError('Verified local model files not ready: ' + str(required))
    components = [(BASE / 'runtime-python', PAYLOAD / 'runtime/python'),
                              (BASE / 'vendor-runtime/node', PAYLOAD / 'runtime/node'),
                              (BASE / 'vendor-runtime/chromium', PAYLOAD / 'runtime/chromium')]
    for component, target in ([] if '--reuse-runtimes' in sys.argv else components):
        copy_tree(component, target)
    for directory in ('portal', 'integration', 'scripts', 'demo'):
        copy_tree(ROOT / directory, PAYLOAD / directory)
    for directory in ('runtime/local-qwen', 'runtime/tiktoken-cache', 'models/local-qwen', 'licenses'):
        if not (ROOT / directory).is_dir():
            raise RuntimeError('Missing distributable component: ' + directory)
        copy_tree(ROOT / directory, PAYLOAD / directory)
    (PAYLOAD / 'reports').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'reports/demo-lesson-video.mp4', PAYLOAD / 'reports/demo-lesson-video.mp4')
    for name in ('requirements-demo.txt', 'README.md', 'HANDOFF.md'):
        shutil.copy2(ROOT / name, PAYLOAD / name)
    for name in ('Install-DeepSteam.ps1', 'Start-DeepSteam.ps1', 'Stop-DeepSteam.ps1', 'prepare_install.py', 'repair_install_paths.py', 'test_offline_tokenizer.py', 'test_sharp_runtime.js', 'test_next_image_cache.js'):
        shutil.copy2(BASE / name, PAYLOAD / 'installer' / name)
    shutil.copy2(BASE / 'INSTALLATION.txt', PAYLOAD / 'INSTALLATION.txt')
    shutil.copy2(BASE / 'DeepSteamSetup.cs', PAYLOAD / 'installer/DeepSteamSetup.cs')
    shutil.copy2(BASE / 'DeepSteam.manifest', PAYLOAD / 'installer/DeepSteam.manifest')
    for name in ('python-runtime-manifest.json', 'vendor-runtime-manifest.json', 'frontend-payload-manifest.json'):
        shutil.copy2(BASE / name, PAYLOAD / 'installer' / name)
    for name in ('python-runtime-freeze.txt', 'python-runtime-verification.json'):
        shutil.copy2(BASE / name, PAYLOAD / 'installer' / name)
    native = json.loads((PAYLOAD / 'runtime/native-frontend.json').read_text('utf-8'))
    shutil.copy2(BASE / 'deepsteam-start.html', PAYLOAD / native['root'] / 'public/deepsteam-start.html')
    # Include the installer launch page in the final native component inventory.
    # The standalone build itself does not contain this installer-owned asset.
    stage_spec = importlib.util.spec_from_file_location('deepsteam_stage', BASE / 'stage_frontend_payload.py')
    stage = importlib.util.module_from_spec(stage_spec)
    stage_spec.loader.exec_module(stage)
    stage.supplement_sharp_native_libs()
    stage.configure_next_image_cache(PAYLOAD / native['root'] / 'server.js')
    stage.configure_next_image_cache(PAYLOAD / 'runtime/openmaic-standalone/server.js')
    final_frontend = json.loads((BASE / 'frontend-payload-manifest.json').read_text('utf-8'))
    om_inventory = stage.inventory(PAYLOAD / 'runtime/openmaic-standalone')
    native_inventory = stage.inventory(PAYLOAD / native['root'])
    final_frontend['components'] = [native_inventory if item['path'] == native['root'] else
                                    om_inventory if item['path'] == 'runtime/openmaic-standalone' else item
                                    for item in final_frontend['components']]
    final_frontend['installer_launch_page_included'] = True
    final_frontend['openmaic_build_id'] = EXPECTED_OPENMAIC_BUILD
    final_frontend['openmaic_next_build_id'] = payload_next_id
    (BASE / 'frontend-payload-manifest.json').write_text(json.dumps(final_frontend, ensure_ascii=False, indent=2), 'utf-8')
    shutil.copy2(BASE / 'frontend-payload-manifest.json', PAYLOAD / 'installer/frontend-payload-manifest.json')
    compile_exe(PAYLOAD / 'DeepSteam.exe')
    # Compiled installer does not ship any developer machine state or source venv.
    rows = []
    for directory, dirs, files in os.walk(lp(PAYLOAD), followlinks=False):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in files:
            if name.endswith(('.pyc', '.pyo')):
                continue
            filename = Path(directory) / name
            rel = os.path.relpath(str(filename), lp(PAYLOAD)).replace('\\', '/')
            if rel == 'installer/payload-manifest.json':
                continue
            forbidden = ('data/', 'logs/', 'cache/', 'runtime/deeptutor-home/',
                         'runtime/temp/', 'integration/local_qwen/downloads/')
            if rel.startswith(forbidden) or rel in {'runtime/local-qwen/process.json', 'deepsteam-storage.json'}:
                raise RuntimeError('Runtime state or download scratch leaked into distributable payload: ' + rel)
            if rel.endswith('.partial') or rel.rsplit('/', 1)[-1] == '.env':
                raise RuntimeError('Incomplete component or credentials file leaked into payload: ' + rel)
            with open(str(filename), 'rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            rows.append({'path': rel, 'bytes': os.path.getsize(filename), 'sha256': digest})
    rows.sort(key=lambda r: r['path'])
    manifest = {'version': VERSION, 'platform': 'win-x64', 'file_count': len(rows),
                'uncompressed_bytes': sum(r['bytes'] for r in rows), 'files': rows}
    (PAYLOAD / 'installer/payload-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    RELEASE.mkdir(parents=True, exist_ok=True)
    archive = BASE / 'payload-r3.zip'
    print('Compressing ' + str(len(rows)) + ' files; bytes=' + str(manifest['uncompressed_bytes']), flush=True)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as package:
        seeded = seed_cached_models(package, rows)
        for row in rows:
            if row['path'] in seeded:
                continue
            # Measured Q4/F16 samples shrink enough to help stay below Windows'
            # 4-GiB PE limit. The final archive size decides single/two-file mode.
            level = 1 if row['path'].lower().endswith('.gguf') else 3
            package.write(lp(PAYLOAD / row['path']), row['path'],
                          compress_type=zipfile.ZIP_DEFLATED, compresslevel=level)
        package.write(PAYLOAD / 'installer/payload-manifest.json', 'installer/payload-manifest.json')
    with zipfile.ZipFile(archive) as package:
        corrupt = package.testzip()
        if corrupt:
            raise RuntimeError('Payload archive corruption: ' + corrupt)
    compile_exe(pending_exe)
    companion = None
    if pending_exe.stat().st_size + archive.stat().st_size + 64 <= MAX_PE_BYTES:
        overlay = append_payload(pending_exe, archive)
    else:
        companion = pending_exe.with_suffix('.payload.dat')
        if companion.exists():
            raise RuntimeError('Existing release companion retained; choose a new release output before rebuilding.')
        companion.touch(exist_ok=False)
        overlay = append_payload(companion, archive)
        overlay['format'] = 'companion-zip64-v1'
    self_test = BASE / 'installer-r3-self-test.txt'
    subprocess.run([str(pending_exe), '--self-test', str(self_test)], timeout=240,
                   check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if companion:
        final_companion = exe.with_suffix('.payload.dat')
        if final_companion.exists():
            raise RuntimeError('Existing release companion retained; refusing to overwrite it.')
        os.rename(companion, final_companion)
        companion = final_companion
        overlay['filename'] = companion.name
    os.rename(pending_exe, exe)
    with exe.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    exe.with_suffix('.exe.sha256').write_text(digest + '  ' + exe.name + '\n', encoding='utf-8')
    distribution = [{'path': str(exe), 'bytes': exe.stat().st_size, 'sha256': digest}]
    if companion:
        with companion.open('rb') as stream:
            companion_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        companion.with_suffix('.dat.sha256').write_text(companion_digest + '  ' + companion.name + '\n', encoding='utf-8')
        distribution.append({'path': str(companion), 'bytes': companion.stat().st_size, 'sha256': companion_digest})
    shutil.copy2(BASE / 'INSTALLATION.txt', RELEASE / 'DeepSteam-Installation.txt')
    result = {'exe': str(exe), 'bytes': exe.stat().st_size, 'sha256': digest,
              'payload_files': len(rows) + 1, 'payload_bytes': manifest['uncompressed_bytes'],
              'payload_zip_bytes': archive.stat().st_size, 'crc_passed': True,
              'version': VERSION, 'payload_container': overlay, 'bundled_local_model': True,
              'distribution_files': distribution, 'single_file_exe': companion is None,
              'actual_exe_self_test_passed': True, 'self_test_report': str(self_test),
                'native_build_id': EXPECTED_NATIVE_BUILD, 'openmaic_build_id': EXPECTED_OPENMAIC_BUILD,
              'machine_state_bundled': False, 'models_called': False}
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    (BASE / 'installer-build-report-r3.json').write_text(serialized, encoding='utf-8')
    (RELEASE / 'DeepSteam-Package-Manifest.json').write_text(serialized, encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    raise SystemExit('This historical r3 builder is retired. Use installer/build_document_release.py with current component manifests.')
