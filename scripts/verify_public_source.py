"""Verify the public source manifest without reading user configuration."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')

def main() -> int:
    manifest = json.loads((ROOT / 'PUBLIC-SOURCE-MANIFEST.json').read_text('utf-8'))
    failures = []
    rows = manifest['files']
    for row in rows:
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts or not row['path'].isascii():
            failures.append({'file': row['path'], 'reason': 'Unsafe or non-English source filename'})
            continue
        target = ROOT / relative
        if target.is_symlink() or not target.is_file():
            failures.append({'file': row['path'], 'reason': 'Missing source file or unexpected link'})
            continue
        target.resolve().relative_to(ROOT)
        data = target.read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            failures.append({'file': row['path'], 'reason': 'Source bytes differ from the reviewed manifest'})
        blob_sha = hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()
        if blob_sha != row['git_blob_sha']:
            failures.append({'file': row['path'], 'reason': 'Git blob identity differs from the reviewed manifest'})
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            continue
        if HAN.search(text):
            failures.append({'file': row['path'], 'reason': 'Non-English text found in source'})
    print(json.dumps({'checked_files': len(rows), 'failures': failures,
                      'user_configuration_read': False, 'network_calls': 0}, indent=2))
    return 1 if failures else 0

if __name__ == '__main__':
    raise SystemExit(main())
