"""Capture selected public-code deltas after owners declare source freeze.

Only repository public code, named user-facing docs, top-level Harness modules,
and SHA-verified paired DeepTutor modules are read. No runtime state is read.
This command does not stage, build, deploy, launch services or call models.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("freeze_update_20261012", ROOT / "reports/refresh_unified_release_20261012.py")
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)
helpers = update.helpers
SKIP_SOURCE_DIRECTORIES = {
    "node_modules", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "cache", "caches", "logs", "data", "state", "sessions", "session", "profiles", "profile",
    "browser-profile", "user-data", "userdata", "harness-state", ".dsh", ".deepseek", ".local",
    "downloads", "models", "runtime", "temp", "tmp", "dist", "build", ".next", ".venv", "venv",
}
SKIP_SOURCE_FILES = {
    "control-token", "account-state.json", "credentials.json", "credentials.yaml", ".credentials.yaml",
    "credentials.dpapi", "cookies.json", "auth.json", "runtime.json", "deepsteam-storage.json",
    "id_rsa", "id_ed25519",
}
SKIP_SOURCE_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".sqlite3", ".db", ".pem", ".pfx", ".p12", ".key", ".log", ".tsbuildinfo"}


def walk_public_sources(source):
    """Prune dependencies/private state before descent; never follow reparse points."""
    if source.is_symlink() or source.is_junction():
        raise RuntimeError("A public source root cannot be a reparse point")
    for directory, names, files in os.walk(source, topdown=True, followlinks=False):
        parent = Path(directory)
        kept = []
        for name in sorted(names):
            lower = name.casefold()
            if lower in SKIP_SOURCE_DIRECTORIES or lower.startswith((".next-", ".env")):
                continue
            child = parent / name
            if not child.is_symlink() and not child.is_junction():
                kept.append(name)
        names[:] = kept
        for name in sorted(files):
            lower = name.casefold()
            if lower in SKIP_SOURCE_FILES or lower.startswith(".env"):
                continue
            child = parent / name
            if child.suffix.casefold() in SKIP_SOURCE_SUFFIXES or child.is_symlink() or child.is_junction():
                continue
            if child.is_file():
                yield child


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-overlay", required=True)
    parser.add_argument("--expected-previous-overlay-sha256", required=True)
    parser.add_argument("--python-map", required=True)
    parser.add_argument("--expected-python-map-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    previous = json.loads(helpers.checked_file({"source": args.previous_overlay, "sha256": args.expected_previous_overlay_sha256}).read_text("utf-8"))
    mapping = json.loads(helpers.checked_file({"source": args.python_map, "sha256": args.expected_python_map_sha256}).read_text("utf-8"))
    if (mapping.get("kind") != "deepsteam-public-python-runtime-map" or mapping.get("public_only") is not True
            or mapping.get("credentials_included") is not False or mapping.get("user_data_included") is not False):
        raise RuntimeError("Explicit public upstream/runtime map required")
    prior = {row["path"]: row for row in previous["files"]}
    selected = {}
    for directory in ("portal", "scripts", "integration/harness"):
        for file in walk_public_sources(ROOT / directory):
            name = file.relative_to(ROOT).as_posix()
            selected[name] = file
    for file in (ROOT / "integration").glob("*.py"):
        selected[file.relative_to(ROOT).as_posix()] = file
    for file in (ROOT / "runtime/harness").iterdir():
        if file.is_file() and file.suffix in {".py", ".mjs"}:
            selected[file.relative_to(ROOT).as_posix()] = file
    for name in sorted(update.PUBLIC_EXACT):
        if name == "USER-GUIDE.txt":
            selected[name] = ROOT / "installer/USER-GUIDE.txt"
        else:
            selected[name] = ROOT / name
    rows = []
    for name, file in sorted(selected.items()):
        update.stage.ordinary(file)
        if not update.public_code_path(name):
            raise RuntimeError("Out-of-scope public file: " + name)
        update.stage.scan_public_text(file)
        size, digest = file.stat().st_size, helpers.digest(file)
        # Docs and launcher sources are always explicitly carried, even when
        # a baseline happens to have equal bytes. No stale root guide survives.
        if name not in update.PUBLIC_EXACT and prior.get(name, {}).get("sha256") == digest:
            continue
        rows.append({"path": name, "source": file.relative_to(ROOT).as_posix(), "sha256": digest, "bytes": size})
    for row in mapping["files"]:
        source = helpers.checked_file({"source": row["source"], "sha256": row["sha256"], "bytes": row["size"]})
        runtime = helpers.checked_file({"source": row["runtime"], "sha256": row["sha256"], "bytes": row["size"]})
        if not update.current.public_runtime_code(row["runtime"]):
            raise RuntimeError("Mapped runtime module is outside the approved Python package")
        rows.append({"path": row["runtime"], "source": runtime.relative_to(ROOT).as_posix(), "sha256": row["sha256"],
                     "bytes": row["size"], "paired_source": source.relative_to(ROOT).as_posix(), "paired_sha256": row["sha256"]})
    result = {"kind": "deepsteam-public-code-freeze", "credentials_copied": False, "user_data_copied": False,
              "files": sorted(rows, key=lambda row: row["path"]), "production_modified": False,
              "models_called": False, "services_started": False, "source_freeze_declared_by_coordinator": True,
              "derivation": {"previous_overlay": args.previous_overlay, "previous_overlay_sha256": args.expected_previous_overlay_sha256,
                             "python_map": args.python_map, "python_map_sha256": args.expected_python_map_sha256}}
    update.check_public_freeze(result)
    output = helpers.workspace_path(args.output)
    if not output.resolve().is_relative_to((ROOT / "reports").resolve()) or output.exists():
        raise RuntimeError("A fresh reports output is required")
    descriptor = update.stage.write_new(output, result)
    print(json.dumps({"freeze": descriptor, "files": len(rows), "services_started": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
