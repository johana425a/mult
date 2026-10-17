"""Regenerate source manifests from the current public Git working tree.

Run only after reviewing the Git diff. Excluded metadata refers to the resulting
manifest hash; including it in its own hash list would create a circular digest.
No runtime configuration or credential store is read by this script.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'PUBLIC-SOURCE-MANIFEST.json', 'PACKAGE-MANIFEST.json', 'LOCAL-BUILD-INFO.json'}


def write(name: str, value: dict) -> None:
    (ROOT / name).write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8', newline='\n')


def main() -> int:
    identity = json.loads((ROOT / 'RELEASE-IDENTITY.json').read_text('utf-8-sig'))
    raw = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    names = sorted(set(filter(None, raw.decode('utf-8').split('\0'))))
    rows = []
    normalized = 0
    for name in names:
        if name in EXCLUDED:
            continue
        target = ROOT / name
        if not target.exists():  # staged/tracked deletion
            continue
        if not name.isascii() or target.is_symlink() or target.is_junction():
            raise ValueError('Unexpected source path or link: ' + name)
        target.resolve().relative_to(ROOT)
        data = target.read_bytes()
        # Match .gitattributes for UTF-8 source, keeping binary bytes untouched.
        if b'\x00' not in data and b'\r\n' in data:
            try:
                data.decode('utf-8-sig')
            except UnicodeDecodeError:
                pass
            else:
                data = data.replace(b'\r\n', b'\n')
                target.write_bytes(data)
                normalized += 1
        rows.append({'path': name, 'bytes': len(data),
                     'sha256': hashlib.sha256(data).hexdigest(),
                     'git_blob_sha': hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()})
    manifest = {
        'product': 'DeepSteam', 'edition': 'public-english-source',
        'version': identity['version'], 'source_base_commit': identity['source_base_commit'],
        'default_interface_language': 'en', 'paired_binary_default_interface_language': 'zh',
        'timezone_policy': 'detect_at_runtime',
        'scope': 'Reviewed source, licenses, tests and sanitized records; excludes installed dependencies, private state and credentials.',
        'manifest_files_excluded_from_own_hash_list': sorted(EXCLUDED),
        'file_count': len(rows), 'files': rows,
    }
    write('PUBLIC-SOURCE-MANIFEST.json', manifest)
    digest = hashlib.sha256((ROOT / 'PUBLIC-SOURCE-MANIFEST.json').read_bytes()).hexdigest()
    write('PACKAGE-MANIFEST.json', {
        'product': 'DeepSteam', 'edition': 'public-english-source', 'version': identity['version'],
        'default_language': 'en', 'paired_binary_default_language': 'zh', 'default_timezone': 'runtime_local',
        'scope': 'source_tests_notices_and_sanitized_records', 'file_manifest': 'PUBLIC-SOURCE-MANIFEST.json',
        'source_files_hashed': len(rows), 'source_manifest_sha256': digest,
        'runtime_binaries_included': False, 'model_weights_included': False,
        'user_data_included': False, 'credentials_included': False,
        'machine_configuration_included': False, 'installed_application_included': False,
        'new_binary_release': False,
    })
    write('LOCAL-BUILD-INFO.json', {
        'product': 'DeepSteam', 'version': identity['version'], 'edition': 'public-english-source',
        'source_repository': identity['source_repository'], 'source_base_commit': identity['source_base_commit'],
        'source_manifest': 'PUBLIC-SOURCE-MANIFEST.json', 'source_manifest_sha256': digest,
        'paired_installed_version': identity['paired_installed_version'],
        'paired_openmaic_build': identity['paired_openmaic_build'],
        'default_interface_language': 'en', 'timezone_policy': 'runtime_local',
        'execution_core': 'official-harness', 'full_clean_installer_rebuild_verified': False,
        'publication_scope': 'Current reviewed source snapshot; not a new installer build',
        'documentation': ['docs/architecture.md', 'docs/validation.md', 'docs/project-status.md', 'docs/source-provenance.md'],
    })
    print(json.dumps({'files': len(rows), 'normalized_text_files': normalized, 'manifest_sha256': digest}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
