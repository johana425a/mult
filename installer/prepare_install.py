"""Verify installed payload, rebuild contained junctions, and initialize new data."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import _winapi

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repair_install_paths import repair
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from offline_tokenizer import configure_tokenizer_cache

ROOT = Path(sys.argv[1]).resolve()


def native(path: Path) -> str:
    value = str(path)
    return value if value.startswith('\\\\?\\') else '\\\\?\\' + value


def contained(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or '..' in relative.parts or ':' in value:
        raise ValueError('Unsafe installation path')
    return ROOT / relative


def main():
    manifest = json.loads((ROOT / 'installer' / 'payload-manifest.json').read_text('utf-8'))
    files = manifest['files']
    for index, row in enumerate(files):
        path = contained(row['path'])
        with open(native(path), 'rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != row['sha256']:
            raise RuntimeError('Package integrity check failed: ' + row['path'])
        if index % 3000 == 0:
            print(f'Integrity: {index}/{len(files)}', flush=True)
    links_report = repair(ROOT)
    print(f'Local dependency links: {links_report["dependency_links"]}', flush=True)
    for name in ('data', 'logs', 'cache', 'runtime/temp', 'reports'):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    configure_tokenizer_cache(ROOT)
    node = ROOT / 'runtime' / 'node' / 'node.exe'
    subprocess.run([str(node), '--version'], check=True)
    desktop = ROOT / 'runtime/desktop/DeepSteam Desktop.exe'
    harness = ROOT / 'runtime/harness/sidecar.mjs'
    desktop_harness = desktop.is_file() or harness.is_file()
    if desktop_harness:
        required = (desktop, harness, ROOT / 'runtime/desktop/resources/app/main.cjs',
                    ROOT / 'runtime/desktop/resources/app/preload.cjs',
                    ROOT / 'scripts/harness_runtime.py', ROOT / 'scripts/desktop_runtime.py')
        if not all(path.is_file() for path in required):
            raise RuntimeError('Desktop/Harness package is incomplete; no account login was attempted')
        node_version = subprocess.check_output([str(node), '--version'], text=True).strip()
        if int(node_version.lstrip('v').split('.')[0]) < 22:
            raise RuntimeError('The pinned Harness Host requires bundled Node 22 or newer')
        subprocess.run([str(node), '--check', str(harness)], check=True, timeout=30)
        subprocess.run([str(node), '--check', str(ROOT / 'runtime/desktop/resources/app/main.cjs')], check=True, timeout=30)
        subprocess.run([str(node), '--check', str(ROOT / 'runtime/desktop/resources/app/preload.cjs')], check=True, timeout=30)
    subprocess.run([str(node), '-e', 'require.resolve("next"); console.log("OpenMAIC dependencies OK")'],
                   cwd=ROOT / 'runtime/openmaic-standalone', check=True)
    subprocess.run([str(node), str(ROOT / 'installer/test_sharp_runtime.js'), str(ROOT)], check=True, timeout=30)
    subprocess.run([str(node), str(ROOT / 'installer/test_next_image_cache.js'), str(ROOT)], check=True, timeout=30)
    if not (ROOT / 'runtime/render-service/node_modules/tsx/dist/cli.mjs').is_file():
        raise RuntimeError('Video renderer dependency link is not readable')
    # Connection setup must work before a user chooses any teaching model.
    # Document parsing has a separate, installation-owned offline runtime.
    mineru_python = ROOT / 'runtime/mineru/python.exe'
    mineru_worker = ROOT / 'scripts/mineru_document_worker.py'
    mineru_verified = False
    if mineru_python.is_file() or mineru_worker.is_file():
        if not mineru_python.is_file() or not mineru_worker.is_file():
            raise RuntimeError('Local document tool runtime is incomplete; repair this installation.')
        subprocess.run([str(mineru_python), '-I', '-B', str(mineru_worker), '--health'],
                       check=True, timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        mineru_verified = True
    subprocess.run([sys.executable, '-I', '-B', '-c', 'import deeptutor, fastapi, uvicorn, psutil, PIL, pymupdf, faiss; print("Python application dependencies OK")'], check=True)
    subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'scripts/verify_timezone_runtime.py')], check=True)
    # Test the shipped parser/OCR closure on the recipient's machine as well as
    # at build time. No workspace, account or language model is involved.
    document_reader = ROOT / 'scripts/workspace_document_reader.py'
    document_verified = False
    if document_reader.is_file():
        document_probe = ROOT / 'scripts/check_document_runtime.py'
        if not document_probe.is_file():
            raise RuntimeError('Document runtime self-check is missing; obtain the complete current installer.')
        subprocess.run([sys.executable, '-I', '-B', str(document_probe)], check=True, timeout=150)
        document_verified = True
    subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'installer/test_offline_tokenizer.py'), str(ROOT)], check=True)
    subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'scripts' / 'initialize_deepsteam.py')], cwd=ROOT, check=True)
    report = {'files_verified': len(files), 'junctions_created_or_verified': links_report['dependency_links'],
              'standalone_install': True, 'network_required_for_install': False,
              'bundled_local_model': False, 'mineru_document_tool_verified': mineru_verified,
              'offline_tokenizer_verified_without_network': True,
              'packaged_timezone_database_verified': True,
              'packaged_document_imports_offline_ocr_and_source_images_verified': document_verified,
              'sharp_native_dll_and_exact_pixel_test_passed': True,
              'next_image_cache_separate_mode_no_disk_io_test_passed': True,
              'desktop_harness_program_entries_verified': desktop_harness,
              'desktop_harness_accounts_or_cloud_calls_tested': False,
              'models_called': False, 'source_machine_credentials_copied': False}
    (ROOT / 'reports' / 'installed-runtime-check.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Installed package verification passed.', flush=True)


if __name__ == '__main__':
    main()
