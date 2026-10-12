"""Apply friendly defaults once to a fresh DeepSteam installation.

Runs entirely locally using upstream settings/catalog services. It neither
starts servers nor exports model credentials. Later launches preserve choices.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deeptutor_runtime as runtime


def relocated_content_path(value: object, previous: Path, current: Path) -> str | None:
    """Map one absolute path beneath our old content root, never free text."""
    if not isinstance(value, str):
        return None
    path = Path(value)
    if not path.is_absolute():
        return None
    try:
        relative = path.relative_to(previous)
    except ValueError:
        return None
    if ".." in relative.parts:
        raise ValueError("Owned workspace path contains traversal")
    return str(current / relative)


def rebind_workspace(catalog, marker: dict) -> bool:
    """After an installation folder is moved, keep its workspace identity.

    The marker identifies the installer-owned root. Catalog paths for native
    system/general/private-chat registrations below that root follow the same
    copy while all IDs, credentials, unrelated registrations and free text are
    preserved. Nothing is copied or removed from the old location here.
    """
    previous = marker.get("workspace_path")
    workspace_id = marker.get("workspace_id")
    current = str(runtime.CONTENT.resolve())
    if not previous or not workspace_id or previous == current:
        return False
    if not Path(previous).as_posix().replace("\\", "/").lower().endswith("/data/deeptutor"):
        raise ValueError("Existing DeepSteam workspace marker has an unexpected content path")
    previous_root, current_root = Path(previous), runtime.CONTENT.resolve()
    if not previous_root.is_absolute():
        raise ValueError("Existing DeepSteam workspace marker must have an absolute content path")
    with catalog._catalog_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        record = conn.execute("SELECT payload FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
        row = json.loads(record[0]) if record else None
        if not row or row.get("kind") != "workspace" or row.get("path") != previous:
            raise ValueError("DeepSteam workspace registration does not match its relocation marker")
        for identity, raw in conn.execute("SELECT id,payload FROM workspaces").fetchall():
            saved = json.loads(raw)
            replacement = relocated_content_path(saved.get("path"), previous_root, current_root)
            if replacement is None:
                continue
            old_path = saved["path"]
            saved["path"] = replacement
            saved["previous_paths"] = [*saved.get("previous_paths", []), old_path]
            conn.execute("UPDATE workspaces SET payload=? WHERE id=?", (json.dumps(saved, ensure_ascii=False), identity))
        # Upstream's optional managed-root override is an exact JSON path.
        # It may be absent in older catalogs; never modify migration/history.
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone():
            record = conn.execute("SELECT value FROM metadata WHERE key='root'").fetchone()
            if record:
                replacement = relocated_content_path(json.loads(record[0]), previous_root, current_root)
                if replacement:
                    conn.execute("UPDATE metadata SET value=? WHERE key='root'", (json.dumps(replacement),))
    marker["workspace_path"] = current
    return True


def initialize() -> dict:
    marker = runtime.HOME / ".deepsteam-defaults-v1.json"
    runtime.initialize()
    from deeptutor.services.settings.interface_settings import update_ui_settings
    from deeptutor.services.workspace import get_content_workspace_service
    from integration.local_qwen_defaults import retire_native_local_model

    migration = retire_native_local_model()
    catalog = get_content_workspace_service()
    if marker.is_file():
        saved = json.loads(marker.read_text(encoding="utf-8"))
        relocated = rebind_workspace(catalog, saved)
        if relocated:
            marker.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"initialized": False, "reason": "Existing DeepSteam preferences preserved",
                "workspace_relocated": relocated, "workspace_id": saved.get("workspace_id"),
                "model_migration": migration}

    # This service patches only the supplied UI fields, leaving other settings
    # such as API providers and optional tools to DeepTutor's own defaults.
    update_ui_settings({"theme": "dark", "language": "zh", "response_language": "zh"})
    # create_workspace reuses the registered identity for an existing folder.
    # No SQLite internals or generated workspace IDs are written here.
    workspace = catalog.create_workspace("DeepSteam", path=str(runtime.CONTENT))
    result = {"initialized": True, "version": 1, "theme": "dark",
              "language": "zh", "response_language": "zh",
              "workspace_id": workspace["workspace_id"],
              "workspace_name": workspace["display_name"],
              "workspace_path": workspace["path"], "model_migration": migration}
    marker.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(initialize(), ensure_ascii=False, indent=2))
