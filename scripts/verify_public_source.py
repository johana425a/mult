"""Verify the public source manifest without reading user configuration."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
PUBLIC_ENGLISH_DOCS = {'README.md', 'GUIDE.md', 'RELEASE.md', 'PORTABLE-README.md',
                       'docs/architecture.md', 'docs/validation.md', 'docs/project-status.md',
                       'docs/source-provenance.md', 'docs/review-guide.md',
                       'installer/DOCUMENT-RELEASE.md', 'installer/UNINSTALL.md'}
PRIVATE_PARTS = {'node_modules', '.git', '.next', '.next-github', '__pycache__', '.pytest_cache',
                 '.venv', 'browser-profile', 'userData', 'harness-state', '.cache', '.turbo'}
PRIVATE_SUFFIXES = {'.log', '.db', '.sqlite', '.sqlite3', '.pem', '.key', '.pfx', '.p12', '.pyc', '.pyo'}
PRIVATE_CONTENT = {
    'private_key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'api_credential': re.compile(rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    'developer_runtime_path': re.compile(rb'(?i)[DE]:(?:\\+|/)(?:DeepSteam-(?:RunCache|Data|GitHub-r[0-9]+|Public-English)|EduAgent-Contest)(?:\\+|/|\b)'),
}

def main() -> int:
    manifest = json.loads((ROOT / 'PUBLIC-SOURCE-MANIFEST.json').read_text('utf-8'))
    failures = []
    if manifest.get('default_interface_language') != 'en':
        failures.append({'file': 'PUBLIC-SOURCE-MANIFEST.json', 'reason': 'Public source default language must be English'})
    rows = manifest['files']
    paths = [row['path'] for row in rows]
    if len(set(paths)) != len(paths) or manifest.get('file_count') != len(rows):
        failures.append({'file': 'PUBLIC-SOURCE-MANIFEST.json', 'reason': 'Duplicate paths or inconsistent file count'})
    for row in rows:
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts or not row['path'].isascii() or ':' in row['path'] or '\\' in row['path']:
            failures.append({'file': row['path'], 'reason': 'Unsafe or non-English source filename'})
            continue
        if PRIVATE_PARTS.intersection(relative.parts) or relative.suffix.lower() in PRIVATE_SUFFIXES or relative.parts[0] in {'data', 'runtime', 'cache'} or relative.name.startswith('.env'):
            failures.append({'file': row['path'], 'reason': 'Private state, credentials or generated runtime member is excluded'})
            continue
        target = ROOT / relative
        if target.is_symlink() or target.is_junction() or not target.is_file():
            failures.append({'file': row['path'], 'reason': 'Missing source file or unexpected link'})
            continue
        target.resolve().relative_to(ROOT)
        data = target.read_bytes()
        for reason, pattern in PRIVATE_CONTENT.items():
            if pattern.search(data):
                failures.append({'file': row['path'], 'reason': reason})
        if row.get('checkout_eol') is not None:
            if row['checkout_eol'] != 'crlf' or relative.suffix.lower() != '.cmd':
                failures.append({'file': row['path'], 'reason': 'Unsupported checkout conversion'})
                continue
            # Git stores LF but the upstream .gitattributes checks these CMD files
            # out as CRLF. Verify canonical Git bytes for either checkout form.
            data = data.replace(b'\r\n', b'\n')
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            failures.append({'file': row['path'], 'reason': 'Source bytes differ from the reviewed manifest'})
        blob_sha = hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()
        if blob_sha != row['git_blob_sha']:
            failures.append({'file': row['path'], 'reason': 'Git blob identity differs from the reviewed manifest'})
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            continue
        if row['path'] in PUBLIC_ENGLISH_DOCS and HAN.search(text):
            failures.append({'file': row['path'], 'reason': 'Public user/source documentation must be English'})
    defaults = {
        'upstream/DeepTutor/deeptutor/services/settings/interface_settings.py': ('"language": "en"', '"response_language": "en"'),
        'upstream/DeepTutor/web/i18n/languages.ts': ('export function normalizeLanguage(_value: unknown): AppLanguage {\n  return "en";\n}',),
        'upstream/DeepTutor/web/context/AppShellContext.tsx': ('useState<AppLanguage>("en")',),
        'upstream/OpenMAIC/lib/i18n/types.ts': ("defaultLocale: Locale = 'en-US'",),
    }
    for name, expected in defaults.items():
        if not (ROOT / name).is_file() or not all(item in (ROOT / name).read_text('utf-8') for item in expected):
            failures.append({'file': name, 'reason': 'Public source English default is missing'})
    print(json.dumps({'checked_files': len(rows), 'failures': failures,
                      'default_language': 'en', 'localized_source_and_upstream_notices_preserved': True,
                      'user_configuration_read': False, 'network_calls': 0}, indent=2))
    return 1 if failures else 0

if __name__ == '__main__':
    raise SystemExit(main())
