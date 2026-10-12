"""Hash the complete locked, application-owned Harness dependency tree."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = Path(__file__).resolve().parent
DENIED = {'.cache', '__pycache__', '.dsh', '.git'}
DENIED_FILES = {'control-token', 'auth.json', 'cookies.json', 'account-state.json', '.env'}


def main():
    sources = [HOST / 'package.json', HOST / 'package-lock.json']
    sources.extend(path for path in (HOST / 'node_modules').rglob('*') if path.is_file())
    rows = []
    for source in sorted(sources):
        relative = source.relative_to(HOST)
        if set(relative.parts) & DENIED or source.name in DENIED_FILES:
            continue
        if not source.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f'Dependency escapes project: {source}')
        rows.append({'source': str(source.resolve()), 'target': 'runtime/harness/' + relative.as_posix(),
                     'bytes': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    report = {'schema': 'deepsteam-harness-runtime-v1',
              'engine_version': '0.2.1-alpha.2+d743267388641bc76f17c45ce8b4c231aed1d32c',
              'tool_only': True, 'files': rows}
    output = ROOT / 'reports' / 'harness-runtime-files.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'manifest': str(output), 'files': len(rows), 'bytes': sum(row['bytes'] for row in rows)}))


if __name__ == '__main__':
    main()
