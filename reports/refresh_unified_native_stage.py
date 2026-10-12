"""Refresh only the frozen native frontend in an existing public candidate.

The original complete stage and all unchanged components stay pinned. Produce
a small native-only overlay for root deployment plus an updated full candidate
descriptor for later spec assembly. No deploy/build/model/service/E operation.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location("unified_native_refresh_helpers", ROOT / "reports/prepare_unified_public_stage.py")
stage_helpers = importlib.util.module_from_spec(specification)
specification.loader.exec_module(stage_helpers)
helpers = stage_helpers.helpers
build = stage_helpers.build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-overlay", required=True)
    parser.add_argument("--expected-previous-overlay-sha256", required=True)
    parser.add_argument("--native-component-report", required=True)
    parser.add_argument("--expected-native-component-report-sha256", required=True)
    parser.add_argument("--native-receipt", required=True)
    parser.add_argument("--expected-native-receipt-sha256", required=True)
    parser.add_argument("--artifact-name", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    if not re.fullmatch(r"r5-unified-native-[a-z0-9-]+", args.artifact_name):
        raise RuntimeError("Fresh installer/r5-unified-native-* artifact required")
    output = ROOT / "installer" / args.artifact_name
    if output.exists():
        raise RuntimeError("Previous public stages are immutable")
    previous_path = helpers.checked_file({"source": args.previous_overlay, "sha256": args.expected_previous_overlay_sha256})
    previous = json.loads(previous_path.read_text("utf-8"))
    report_path = helpers.checked_file({"source": args.native_component_report, "sha256": args.expected_native_component_report_sha256})
    component_report = json.loads(report_path.read_text("utf-8"))
    receipt_path = helpers.checked_file({"source": args.native_receipt, "sha256": args.expected_native_receipt_sha256})
    receipt = json.loads(receipt_path.read_text("utf-8"))
    for value in (previous, component_report):
        if value.get("credentials_copied") is not False or value.get("user_data_copied") is not False:
            raise RuntimeError("Both public stages require explicit private-state exclusions")
    if len(component_report["components"]) != 1 or component_report["components"][0]["name"] != "native":
        raise RuntimeError("Only the native component may be refreshed")
    native_component = component_report["components"][0]
    native_inventory = json.loads(helpers.checked_file(native_component["inventory"]).read_text("utf-8"))
    actual = helpers.collect_tree(helpers.workspace_path(native_component["source"]), native_component["target"])
    if actual != native_inventory["files"] or len(actual) != native_inventory["file_count"]:
        raise RuntimeError("New native complete inventory changed")
    old_native = next(item for item in previous["components"] if item["name"] == "native")
    if native_component["build_id"] != receipt["build_id"] or native_component["build_id"] == old_native["build_id"]:
        raise RuntimeError("New native build identity is missing or mismatched")
    # Verify unchanged inventories by their frozen descriptor; the later full
    # builder checks every byte again. No expensive duplicate tree copies here.
    components = []
    for component in previous["components"]:
        selected = native_component if component["name"] == "native" else component
        helpers.checked_file(selected["inventory"])
        components.append(selected)
    portable_path = report_path.parent / "runtime/native-frontend.json"
    portable = json.loads(portable_path.read_text("utf-8"))
    if portable["root"] != native_component["target"] or portable["server"] != native_component["target"] + "/server.js":
        raise RuntimeError("Portable native paths differ from the complete component")
    old_portable = json.loads(helpers.checked_file(previous["generated"]["runtime/native-frontend.json"]).read_text("utf-8"))
    if not set(old_portable.get("source_pages", [])).issubset(portable.get("source_pages", [])):
        raise RuntimeError("An original frontend route was removed")
    links_descriptor = component_report["junctions"]
    links = json.loads(helpers.checked_file(links_descriptor).read_text("utf-8"))
    old_links = previous["junctions"]
    unchanged = lambda values: sorted((row for row in values if not row["path"].startswith("runtime/native-frontends/")), key=lambda row: row["path"])
    if unchanged(links) != unchanged(old_links):
        raise RuntimeError("Refresh must preserve all non-native dependency links")
    old_frontend = json.loads(helpers.checked_file(previous["generated"]["installer/frontend-payload-manifest.json"]).read_text("utf-8"))
    native_rows = {native_component["target"] + "/" + item["path"]: {**item, "path": native_component["target"] + "/" + item["path"]} for item in actual}
    summary = helpers.component_inventory(native_component["target"], native_rows)
    frontend = {**old_frontend, "native_build_id": portable["build_id"], "junctions": len(links),
                "components": [summary if item["path"].startswith("runtime/native-frontends/") else item for item in old_frontend["components"]]}
    output.mkdir()
    generated = {}
    incremental_files = [{**item, "path": native_component["target"] + "/" + item["path"],
                          "source": native_component["source"] + "/" + item["path"]} for item in actual]
    for name, value in (("runtime/native-frontend.json", portable), ("installer/junctions.json", links),
                        ("installer/frontend-payload-manifest.json", frontend)):
        descriptor = stage_helpers.write_new(output / name, value)
        generated[name] = descriptor
        incremental_files.append({"path": name, **descriptor})
    files = [row for row in previous["files"] if not row["path"].startswith("runtime/native-frontends/") and row["path"] not in generated]
    files += incremental_files
    files.sort(key=lambda row: row["path"])
    if len({row["path"] for row in files}) != len(files):
        raise RuntimeError("Duplicate updated candidate destination")
    # Spec assembler expects installer source beside the full overlay. Retain
    # exact original freeze, never recapture mutable C# or other public sources.
    for name in ("installer/DeepSteamSetup.cs", "installer/DeepSteam.manifest"):
        source_row = next(row for row in previous["public_source_files"] if row["path"] == name)
        stage_helpers.copy_file(helpers.checked_file(source_row), output / name)
    documentation = "reports/DeepSteam-Models-And-Workspaces.md"
    stage_helpers.copy_file(ROOT / documentation, output / documentation)
    stage_helpers.scan_public_text(output / documentation)
    documentation_row = {"path": documentation, "source": (output / documentation).relative_to(ROOT).as_posix(),
                         "bytes": (output / documentation).stat().st_size, "sha256": helpers.digest(output / documentation)}
    files = [row for row in files if row["path"] != documentation] + [documentation_row]
    files.sort(key=lambda row: row["path"])
    public_source_files = [row for row in previous["public_source_files"] if row["path"] != documentation] + [documentation_row]
    public_source_files.sort(key=lambda row: row["path"])
    full = {**previous, "kind": "deepsteam-unified-public-program-overlay",
            "files": files, "components": components, "generated": generated, "junctions": links,
            "public_source_files": public_source_files,
            "builds": {**previous["builds"], "native": {"build_id": receipt["build_id"],
                       "receipt": {"source": args.native_receipt, "sha256": args.expected_native_receipt_sha256}}},
            "derivation": {"previous_overlay": {"source": args.previous_overlay, "sha256": args.expected_previous_overlay_sha256},
                           "refresh": "native only", "unchanged_components_reused": [item["name"] for item in components if item["name"] != "native"]}}
    full_descriptor = stage_helpers.write_new(output / "public-overlay.json", full)
    incremental = {"kind": "deepsteam-unified-native-public-overlay", "files": sorted(incremental_files, key=lambda row: row["path"]),
                   "junctions": links, "credentials_copied": False, "user_data_copied": False,
                   "private_storage_configuration_changed": False, "deletions": [], "preserve_existing_public_files": True,
                   "derivation": {"full_overlay": full_descriptor, "previous_build_id": old_native["build_id"], "native_build_id": receipt["build_id"]}}
    runtime_descriptor = stage_helpers.write_new(output / "native-runtime-overlay.json", incremental)
    report = {"kind": "deepsteam-unified-native-refresh", "full_overlay": full_descriptor, "runtime_overlay": runtime_descriptor,
              "component": native_component, "incremental_file_count": len(incremental_files),
              "incremental_bytes": sum(row["bytes"] for row in incremental_files), "junction_count": len(links),
              "unchanged_components_reused": full["derivation"]["unchanged_components_reused"],
              "refreshed_public_document": documentation_row,
              "credentials_copied": False, "user_data_copied": False, "models_called": False,
              "services_started": False, "production_changed": False, "full_installer_built": False,
              "published_to_e": False, "elapsed_seconds": round(time.monotonic() - started, 3)}
    descriptor = stage_helpers.write_new(output / "prepare-report.json", report)
    print(json.dumps({"report": descriptor, "full_overlay": full_descriptor, "runtime_overlay": runtime_descriptor,
                      "files": len(incremental_files), "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
