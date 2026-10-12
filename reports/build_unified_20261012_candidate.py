"""Build the 2026-10-12 update using frozen public code overrides.

Preserves the earlier builder and its full archive/inventory checks.  Only
ordinary Python modules in the bundled DeepTutor package and top-level Harness
code modules extend the earlier source-file allowlist; no runtime state is a
valid override.  No build runs on import.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location(
    "unified_20261012_base", ROOT / "reports/build_unified_r5_candidate.py")
base = importlib.util.module_from_spec(specification)
specification.loader.exec_module(base)
VERSION = "2026.10.12-r5-unified"
builder = base.builder
REQUIRED_GATES = base.REQUIRED_GATES
DEFERRED_VALIDATION = base.DEFERRED_VALIDATION
EXTRA_PREFIXES = ("runtime/deeptutor-packages/deeptutor/", "runtime/harness/")
original_load_plan = builder.load_plan


def receipt_status(receipt):
    if receipt.get("release_version") != VERSION:
        raise RuntimeError("Acceptance must identify this exact 2026-10-12 release")
    return base.receipt_status(receipt)


def public_runtime_code(name: str) -> bool:
    builder.safe_name(name)
    path = PurePosixPath(name)
    if name.startswith(EXTRA_PREFIXES[0]):
        return path.suffix == ".py" and len(path.parts) > 3
    if name.startswith(EXTRA_PREFIXES[1]):
        return len(path.parts) == 3 and path.suffix in {".py", ".mjs"}
    return False


def load_plan(plan):
    if not {"README.md", "GUIDE.md", "USER-GUIDE.txt"}.issubset({row["path"] for row in plan.get("files", [])}):
        raise RuntimeError("Current desktop README, handoff, and installation instructions must be frozen")
    for row in plan.get("files", []):
        if row["path"].startswith("runtime/") and not public_runtime_code(row["path"]):
            raise RuntimeError("Only explicitly frozen public runtime code is an override")
    result = original_load_plan(plan)
    # A prior runtime acceptance cannot silently certify this newer update.
    accepted = result["acceptance"]
    if accepted.get("release_version") != VERSION:
        raise RuntimeError("Acceptance must identify this exact 2026-10-12 release")
    return result


base.VERSION = VERSION
builder.VERSION = VERSION
builder.ALLOWED_PREFIXES = (*builder.ALLOWED_PREFIXES, *EXTRA_PREFIXES)
builder.load_plan = load_plan
builder.receipt_status = receipt_status


def main():
    base.main()
    if "--validate-only" in sys.argv:
        return
    arguments = sys.argv[1:]
    plan = json.loads((ROOT / arguments[arguments.index("--spec") + 1]).read_text("utf-8"))
    instructions = next((row for row in plan.get("files", []) if row["path"] == "USER-GUIDE.txt"), None)
    if instructions is None:
        raise RuntimeError("Current user installation instructions must be explicitly frozen")
    source = builder.helpers.checked_file(instructions)
    artifact = ROOT / "installer" / plan["artifact_name"]
    destination = artifact / "release/DeepSteam-Installation-Guide.txt"
    if destination.exists():
        raise RuntimeError("New release instructions must not overwrite an earlier file")
    shutil.copy2(source, destination)
    doc = {"path": str(destination), "bytes": destination.stat().st_size, "sha256": builder.helpers.digest(destination)}
    for path in (artifact / "build-report.json", artifact / "release/DeepSteam-Package-Manifest.json"):
        report = json.loads(path.read_text("utf-8"))
        report["distribution_files"].append(doc)
        report["desktop_user_instructions_included"] = True
        path.write_bytes(builder.helpers.json_bytes(report))
    print(json.dumps({"desktop_instructions": doc, "version": VERSION,
                      "build_report_sha256": builder.helpers.digest(artifact / "build-report.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
