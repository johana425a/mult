"""Repair only declared bundled dependency junctions after a drive-letter change.

No recursive deletion is used. User data, ordinary directories, and paths outside
the current installation are never replaced. The manifest contains relative paths.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import _winapi


def native(path: Path) -> str:
    value = str(path)
    return value if value.startswith('\\\\?\\') else '\\\\?\\' + value


def contained(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or '..' in relative.parts or ':' in value:
        raise ValueError('Unsafe bundled dependency path')
    return root / relative


def ensure_parent_is_contained(root: Path, parent: Path) -> None:
    current = parent
    while not os.path.lexists(native(current)):
        current = current.parent
    resolved = Path(os.path.realpath(native(current)))
    root_normalized = os.path.normcase(os.path.realpath(native(root)))
    current_normalized = os.path.normcase(str(resolved))
    if os.path.commonpath([root_normalized, current_normalized]) != root_normalized:
        raise RuntimeError('Bundled dependency parent points outside this installation')


def repair(root: Path) -> dict:
    root = root.resolve()
    manifest = root / 'installer/junctions.json'
    data = json.loads(manifest.read_text('utf-8'))
    links = data if isinstance(data, list) else data['junctions']
    links = sorted(links, key=lambda row: (len(Path(row['path']).parts), row['path']))
    repaired = 0
    for row in links:
        link = contained(root, row['path'])
        target = contained(root, row['target'])
        ensure_parent_is_contained(root, link.parent)
        ensure_parent_is_contained(root, target)
        if not os.path.isdir(native(target)):
            raise RuntimeError('Missing bundled dependency: ' + row['target'])
        expected = os.path.normcase(os.path.realpath(native(target)))
        if os.path.lexists(native(link)):
            actual = os.path.normcase(os.path.realpath(native(link)))
            if actual == expected and os.path.isdir(native(link)):
                continue
            attributes = os.lstat(native(link)).st_file_attributes
            if not attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise RuntimeError('Ordinary dependency folder retained: ' + row['path'])
            # Remove the declared junction itself; never follow or recursively
            # remove its old target, even when its old drive is now unavailable.
            os.rmdir(native(link))
        os.makedirs(native(link.parent), exist_ok=True)
        _winapi.CreateJunction(str(target), native(link))
        if not os.path.isdir(native(link)):
            raise RuntimeError('Bundled dependency junction is not readable: ' + row['path'])
        repaired += 1
    return {'dependency_links': len(links), 'repaired': repaired,
            'install_root': str(root), 'relative_manifest': True}


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: repair_install_paths.py <install-root>')
    print(json.dumps(repair(Path(sys.argv[1])), ensure_ascii=False))
