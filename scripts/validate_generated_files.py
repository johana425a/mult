"""Parse generated artifacts with packaged libraries before delivery."""
import json, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root/'runtime/deeptutor-packages')]
from integration.harness_turn import validate_file
if __name__ == '__main__':
    try:
        files = json.loads(sys.stdin.read())
        print(json.dumps({'ok': True, 'files': [validate_file(p) for p in files]}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
