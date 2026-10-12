"""Test dependency repair without moving or changing the developer checkout."""
from pathlib import Path
import json
import os
import sys
import uuid
import _winapi

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repair_install_paths import native, repair

base = Path(__file__).resolve().parent / 'relocation-fixtures' / uuid.uuid4().hex[:8]
root = base / 'new-root'
previous = base / 'old-root' / 'package'
expected = root / 'runtime/package'
expected.mkdir(parents=True)
previous.mkdir(parents=True)
(previous / 'kept.txt').write_text('Old target retained', 'utf-8')
(expected / 'current.txt').write_text('Current root target', 'utf-8')
link = root / 'runtime/node_modules/package'
link.parent.mkdir(parents=True)
_winapi.CreateJunction(str(previous), native(link))
(root / 'installer').mkdir()
(root / 'installer/junctions.json').write_text(json.dumps([
    {'path': 'runtime/node_modules/package', 'target': 'runtime/package'}]), 'utf-8')
result = repair(root)
assert result['repaired'] == 1
assert (link / 'current.txt').is_file()
assert (previous / 'kept.txt').is_file()
repeat = repair(root)
assert repeat['repaired'] == 0
report = {'junction_target_changed_to_current_root': True,
          'old_target_retained': True, 'second_start_idempotent': True,
          'first': result, 'second': repeat, 'fixtures_only': True}
(Path(__file__).resolve().parent / 'relocation-fixture-test-report.json').write_text(
    json.dumps(report, indent=2), 'utf-8')
print(json.dumps(report, indent=2))
