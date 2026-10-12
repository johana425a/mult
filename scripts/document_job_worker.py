"""Fixed-runtime broker/dispatcher entrypoint; stdin and stdout are JSON only."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integration.document_jobs import DocumentJobs, handle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--drain', action='store_true')
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
    raw = sys.stdin.buffer.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        return 2
    result = handle(json.loads(raw.decode('utf-8')), test_root=args.test_root, python=sys.executable)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
