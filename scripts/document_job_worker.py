"""Fixed-runtime broker/dispatcher entrypoint; stdin and stdout are JSON only."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integration.document_jobs import DocumentJobs, handle


def emit(value):
    """Write one UTF-8 JSON document, independent of the console code page.

    ``-I`` also ignores PYTHONUTF8, so on Windows a text-mode stdout would fall
    back to the ANSI code page and raise on any character outside it (an OCR'd
    '・', '≤' or a non-Chinese script). The caller parses UTF-8 bytes.
    """
    payload = json.dumps(value, ensure_ascii=False).encode('utf-8')
    stream = getattr(sys.stdout, 'buffer', None)
    if stream is None:
        sys.stdout.write(payload.decode('utf-8', 'replace'))
        return
    stream.write(payload)
    stream.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--drain', action='store_true')
    parser.add_argument('--drain-parses', action='store_true')
    parser.add_argument('--test-root')
    args = parser.parse_args()
    if args.test_root:
        target = Path(args.test_root).resolve()
        allowed = [ROOT / 'runtime']
        if not any(target.is_relative_to(root.resolve()) for root in allowed):
            raise ValueError('test_root_outside_fixture_area')
    if args.drain:
        DocumentJobs(test_root=args.test_root, python=sys.executable).drain()
        return 0
    if args.drain_parses:
        DocumentJobs(test_root=args.test_root, python=sys.executable).drain_parses()
        return 0
    raw = sys.stdin.buffer.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        return 2
    result = handle(json.loads(raw.decode('utf-8')), test_root=args.test_root, python=sys.executable)
    emit(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
