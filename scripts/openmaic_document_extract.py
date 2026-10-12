"""DeepSteam native OpenMAIC reader with owner-scoped retained source copies.

Launched by the server with its fixed installation Python in isolated mode.
No client path, provider credential, network endpoint or executable is accepted.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_BYTES = 200 * 1024 * 1024
MAX_OUTPUT_BYTES = 128 * 1024 * 1024


def extract(request: dict) -> dict:
    if not isinstance(request, dict) or set(request) - {'source', 'include_assets', 'owner_scope', 'ingestion_id', 'action'}:
        raise ValueError('Invalid local document request')
    if not isinstance(request.get('source'), str) or type(request.get('include_assets', True)) is not bool:
        raise ValueError('Invalid local document request')
    temporary = Path(os.environ['DEEPSTEAM_DOCUMENT_TEMP_ROOT']).resolve(strict=True)
    supplied = Path(request['source'])
    source = supplied.resolve(strict=True)
    if (not supplied.is_absolute() or supplied != source or source.parent.parent != temporary
            or not source.parent.name.startswith('extract-') or source.stem != 'source'
            or source.is_symlink() or source.parent.is_symlink()
            or not source.is_file() or source.stat().st_size > MAX_SOURCE_BYTES):
        raise ValueError('The document copy is outside the owned extraction directory')
    sys.path.insert(0, str(ROOT))
    from integration.document_ingestion_jobs import DocumentIngestions
    service = DocumentIngestions(test_root=os.environ.get('DEEPSTEAM_HARNESS_TEST_ROOT'), python=sys.executable)
    identity = service.prepare(source, request.get('owner_scope', 'standalone-openmaic'),
                               request.get('include_assets', True), request.get('ingestion_id'))
    with contextlib.redirect_stdout(sys.stderr):
        if request.get('action', 'read') == 'cancel':
            if not request.get('ingestion_id'):
                raise ValueError('Cancellation needs the issued ingestion id')
            return service.cancel(identity)
        if request.get('action', 'read') != 'read':
            raise ValueError('Invalid document action')
        return service.wait(identity)


def main() -> int:
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('--ingest')
        parser.add_argument('--test-root')
        args = parser.parse_args()
        test_root = args.test_root or os.environ.get('DEEPSTEAM_HARNESS_TEST_ROOT')
        if test_root:
            target = Path(test_root).resolve()
            if not target.is_relative_to((ROOT / 'runtime').resolve()):
                raise ValueError('Test state must stay in the fixture directory')
            os.environ['DEEPSTEAM_HARNESS_TEST_ROOT'] = str(target)
        if args.ingest:
            sys.path.insert(0, str(ROOT))
            from integration.document_ingestion_jobs import DocumentIngestions
            service = DocumentIngestions(test_root=test_root, python=sys.executable)
            service._row(args.ingest)
            service.drain()
            return 0
        request_bytes = sys.stdin.buffer.read(65537)
        if len(request_bytes) > 65536:
            raise ValueError('Local document request is too large')
        result = extract(json.loads(request_bytes))
        encoded = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(encoded) > MAX_OUTPUT_BYTES:
            raise ValueError('Local document output exceeds the application limit')
        sys.stdout.buffer.write(encoded)
        return 0 if result.get('ok') or result.get('status') in {'queued', 'running', 'cancelled'} else 1
    except Exception as error:
        # No traceback, local source path or child stderr goes to the client.
        message = str(error) if error.__class__.__name__ == 'SharedDocumentError' else 'Local document reading failed. Check the format or repair the installation.'
        sys.stdout.buffer.write(json.dumps({'ok': False, 'error': message}, ensure_ascii=False).encode('utf-8'))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
