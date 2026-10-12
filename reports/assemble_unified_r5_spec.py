"""Pin the public stage and current root acceptance into a fresh r5-unified spec.

No EXE/payload build, deployment, service/model operation, E write or deletion.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location("unified_spec_builder", ROOT / "reports/build_unified_r5_candidate.py")
wrapper = importlib.util.module_from_spec(specification)
specification.loader.exec_module(wrapper)
builder = wrapper.builder
helpers = builder.helpers


def record(source):
    name = source.relative_to(ROOT).as_posix()
    path = helpers.workspace_path(name)
    if not path.is_file() or path.is_symlink() or path.is_junction():
        raise RuntimeError("Ordinary contained frozen source required")
    return {"source": name, "sha256": helpers.digest(path), "bytes": path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", required=True)
    parser.add_argument("--expected-overlay-sha256", required=True)
    parser.add_argument("--acceptance", required=True)
    parser.add_argument("--expected-acceptance-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--artifact-name", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"r5-unified-[a-z0-9-]+", args.artifact_name):
        raise RuntimeError("Fresh r5-unified-* artifact name required")
    output = helpers.workspace_path(args.output)
    if output.exists() or not output.resolve().is_relative_to((ROOT / "reports").resolve()):
        raise RuntimeError("New reports output required")
    overlay_path = helpers.checked_file({"source": args.overlay, "sha256": args.expected_overlay_sha256})
    overlay = json.loads(overlay_path.read_text("utf-8"))
    if overlay.get("credentials_copied") is not False or overlay.get("user_data_copied") is not False:
        raise RuntimeError("Public stage exclusion contract required")
    acceptance_descriptor = {"source": args.acceptance, "sha256": args.expected_acceptance_sha256}
    acceptance_path = helpers.checked_file(acceptance_descriptor)
    acceptance = json.loads(acceptance_path.read_text("utf-8"))
    readiness = wrapper.receipt_status(acceptance)
    if not readiness["distribution_ready"]:
        raise RuntimeError("Root runtime acceptance is incomplete: " + ",".join(readiness["missing_gates"]))
    explicit = []
    for item in overlay["public_source_files"]:
        name = item["path"]
        if name in helpers.GENERATED_NAMES:
            continue
        row = dict(item)
        if name == "reports/DeepSteam-Models-And-Workspaces.md":
            row["path"] = "installer/UNIFIED-MODELS-WORKSPACES.md"
        explicit.append(row)
    # The selected component stage holds the exact C# and Windows manifest
    # checked before root runtime acceptance; never recapture mutable originals.
    stage_root = overlay_path.parent
    spec = {
        "version": wrapper.VERSION, "artifact_name": args.artifact_name,
        "baseline": overlay["baseline"], "components": overlay["components"],
        "builds": overlay["builds"], "files": explicit,
        "junctions": overlay["generated"]["installer/junctions.json"],
        "installer_source": record(stage_root / "installer/DeepSteamSetup.cs"),
        "windows_manifest": record(stage_root / "installer/DeepSteam.manifest"),
        "feature_acceptance": {**acceptance_descriptor, "bytes": acceptance_path.stat().st_size},
        "validation_scope": "current software/runtime/configuration; cloud and second-PC checks explicitly deferred",
        "deferred_validation": list(wrapper.DEFERRED_VALIDATION),
        "stage_overlay": {"source": args.overlay, "sha256": args.expected_overlay_sha256},
    }
    for item in explicit:
        helpers.checked_file(item)
    # Complete archive hashing and full load_plan verification are the root's
    # later --validate-only step; assembling the spec never implies acceptance.
    blob = helpers.json_bytes(spec)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(blob)
    print(json.dumps({"spec": output.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(blob).hexdigest(),
                      "bytes": len(blob), "components": len(spec["components"]),
                      "explicit_public_files": len(explicit), "exe_built": False,
                      "deferred_validation": list(wrapper.DEFERRED_VALIDATION)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
