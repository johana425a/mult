"""Freeze a fresh native/OpenMAIC plus public-code delta without full recopy.

Reuses unchanged complete components from the SHA-pinned previous stage.
The full candidate descriptor points to their immutable inventories and new
explicit code overrides.  Runtime deployment gets only new frontend files,
changed code, and generated public manifests.  No deployment, model calls,
service starts, EXE/payload build, user-state access, or E drive writes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


stage = module("update_20261012_stage", ROOT / "reports/prepare_unified_public_stage.py")
current = module("update_20261012_builder", ROOT / "reports/build_unified_20261012_candidate.py")
helpers = current.builder.helpers
FRONT_PREFIXES = ("runtime/native-frontends/", "runtime/openmaic-standalone/")
PUBLIC_PREFIXES = ("portal/", "scripts/", "integration/", "licenses/")
PUBLIC_EXACT = {"reports/DeepSteam-Models-And-Workspaces.md", "installer/UNINSTALL.md",
                "README.md", "GUIDE.md", "USER-GUIDE.txt", "installer/USER-GUIDE.txt",
                "installer/DeepSteamSetup.cs", "installer/Start-DeepSteam.ps1"}


def public_code_path(name):
    current.builder.safe_name(name)
    return name.startswith(PUBLIC_PREFIXES) or name in PUBLIC_EXACT or current.public_runtime_code(name)


def check_public_freeze(value):
    if (value.get("kind") != "deepsteam-public-code-freeze"
            or value.get("credentials_copied") is not False
            or value.get("user_data_copied") is not False):
        raise RuntimeError("An explicit public code freeze is required")
    seen = set()
    for row in value.get("files", []):
        if row["path"] in seen or not public_code_path(row["path"]):
            raise RuntimeError("Repeated or out-of-scope public code target")
        if "paired_source" in row and "paired_sha256" not in row:
            raise RuntimeError("An upstream pair requires its exact SHA")
        seen.add(row["path"])
    if not seen:
        raise RuntimeError("Public code freeze cannot be empty")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("previous-overlay", "frontend-report", "native-receipt", "openmaic-receipt", "desktop-receipt", "public-freeze"):
        parser.add_argument("--" + name, required=True)
        parser.add_argument("--expected-" + name + "-sha256", required=True)
    parser.add_argument("--artifact-name", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    if not re.fullmatch(r"r5-unified-update-20261012-[a-z0-9-]+", args.artifact_name):
        raise RuntimeError("Fresh 20261012 update stage required")
    output = ROOT / "installer" / args.artifact_name
    if output.exists():
        raise RuntimeError("All previous stages must remain immutable")
    descriptors, values, paths = {}, {}, {}
    for name in ("previous_overlay", "frontend_report", "native_receipt", "openmaic_receipt", "desktop_receipt", "public_freeze"):
        descriptors[name] = {"source": getattr(args, name), "sha256": getattr(args, "expected_" + name + "_sha256")}
        paths[name] = helpers.checked_file(descriptors[name])
        values[name] = json.loads(paths[name].read_text("utf-8"))
    previous, front, receipt = values["previous_overlay"], values["frontend_report"], values["native_receipt"]
    for value in (previous, front):
        if value.get("credentials_copied") is not False or value.get("user_data_copied") is not False:
            raise RuntimeError("Previous and new frontend stages must exclude all private state")
    check_public_freeze(values["public_freeze"])
    fresh = {entry["name"]: entry for entry in front["components"]}
    if len(front["components"]) != 2 or set(fresh) != {"native", "openmaic"}:
        raise RuntimeError("Exactly the newly built native and OpenMAIC components are required")
    if fresh["native"]["build_id"] != receipt["build_id"]:
        raise RuntimeError("Native receipt identity mismatch")
    if fresh["native"]["build_id"] == previous["builds"]["native"]["build_id"]:
        raise RuntimeError("A new immutable native build is required")
    if fresh["openmaic"]["build_id"] == previous["builds"]["openmaic"]["build_id"]:
        raise RuntimeError("A new immutable OpenMAIC build is required")
    om_receipt = values["openmaic_receipt"]
    if (om_receipt.get("build_id") != fresh["openmaic"]["build_id"]
            or om_receipt.get("excluded_user_data") is not True):
        raise RuntimeError("OpenMAIC build receipt identity or user-state exclusion differs")
    desktop = values["desktop_receipt"]
    if (desktop.get("kind") != "deepsteam-public-desktop-runtime"
            or desktop.get("credentials_or_private_profiles_copied") is not False
            or not all(desktop.get(key) is True for key in ("all_asar_entry_bytes_verified", "source_mirror_matches_archive", "node_syntax_checks_passed", "licenses_retained"))):
        raise RuntimeError("A verified public desktop runtime receipt is required")
    desktop_root = stage.contained(Path(desktop["runtime"]), ROOT / "installer")
    if helpers.digest(desktop_root / "resources/app.asar") != desktop["app_asar_sha256"]:
        raise RuntimeError("New desktop ASAR differs from its verified receipt")
    old_asar = next(row for row in previous["files"] if row["path"] == "runtime/desktop/resources/app.asar")
    if old_asar["sha256"] == desktop["app_asar_sha256"]:
        raise RuntimeError("This update requires the new desktop transport ASAR")
    for row in desktop["source_files"]:
        for path in (ROOT / "desktop" / row["path"], desktop_root / "resources/app" / row["path"]):
            if path.stat().st_size != row["bytes"] or helpers.digest(path) != row["sha256"]:
                raise RuntimeError("Desktop source, mirror, and ASAR receipt must agree")
    components, new_rows = [], []
    for old in previous["components"]:
        if old["name"] in {"desktop_runtime", "desktop_source"}:
            continue
        selected = fresh.get(old["name"], old)
        inventory = json.loads(helpers.checked_file(selected["inventory"]).read_text("utf-8"))
        if old["name"] in fresh:
            actual = helpers.collect_tree(helpers.workspace_path(selected["source"]), selected["target"])
            if actual != inventory["files"] or len(actual) != inventory["file_count"]:
                raise RuntimeError("New frontend complete inventory changed")
            for item in actual:
                new_rows.append({**item, "path": selected["target"] + "/" + item["path"],
                                 "source": selected["source"] + "/" + item["path"]})
        components.append(selected)
    links = json.loads(helpers.checked_file(front["junctions"]).read_text("utf-8"))
    unchanged = lambda rows: sorted((row for row in rows if not row["path"].startswith(FRONT_PREFIXES)), key=lambda row: row["path"])
    if unchanged(links) != unchanged(previous["junctions"]):
        raise RuntimeError("Non-frontend runtime dependency links changed")
    native = json.loads((paths["frontend_report"].parent / "runtime/native-frontend.json").read_text("utf-8"))
    if native["root"] != fresh["native"]["target"] or native["server"] != native["root"] + "/server.js":
        raise RuntimeError("Native portable runtime mapping differs")
    prior_native = json.loads(helpers.checked_file(previous["generated"]["runtime/native-frontend.json"]).read_text("utf-8"))
    if not set(prior_native.get("source_pages", [])).issubset(native.get("source_pages", [])):
        raise RuntimeError("An existing application route was removed")
    # Validate all code sources before writing the fresh stage. Never read state.
    checked = []
    for row in values["public_freeze"]["files"]:
        source = helpers.checked_file(row)
        if "paired_source" in row:
            pair = helpers.checked_file({"source": row["paired_source"], "sha256": row["paired_sha256"]})
            if helpers.digest(pair) != row["sha256"]:
                raise RuntimeError("Upstream and installed Python code are not synchronized")
        stage.scan_public_text(source)
        checked.append((row, source))
    output.mkdir()
    # The desktop builder already produced an immutable installer-stage runtime.
    # Reference it directly instead of copying the entire Electron runtime again.
    desktop_rows = helpers.collect_tree(desktop_root, "runtime/desktop")
    desktop_inventory = {"source": desktop_root.relative_to(ROOT).as_posix(), "target": "runtime/desktop",
                         "file_count": len(desktop_rows), "uncompressed_bytes": sum(row["bytes"] for row in desktop_rows),
                         "files": desktop_rows}
    inventory_descriptor = stage.write_new(output / "desktop_runtime-inventory.json", desktop_inventory)
    desktop_component = {"name": "desktop_runtime", "source": desktop_inventory["source"], "target": "runtime/desktop",
                         "inventory": inventory_descriptor, "file_count": len(desktop_rows)}
    source_component, source_rows = stage.component(output, "desktop_source", ROOT / "desktop", "desktop", source_only=True)
    components.extend((desktop_component, source_component))
    for component, rows in ((desktop_component, desktop_rows), (source_component, source_rows)):
        new_rows.extend({**item, "path": component["target"] + "/" + item["path"],
                         "source": component["source"] + "/" + item["path"]} for item in rows)
    explicit = {row["path"]: row for row in previous["public_source_files"]}
    overrides = []
    for row, source in checked:
        destination = output / row["path"]
        stage.copy_file(source, destination)
        frozen = {"path": row["path"], "source": destination.relative_to(ROOT).as_posix(),
                  "sha256": helpers.digest(destination), "bytes": destination.stat().st_size}
        overrides.append(frozen)
        explicit[row["path"]] = frozen
    for name in ("installer/DeepSteamSetup.cs", "installer/DeepSteam.manifest"):
        if not (output / name).exists():
            stage.copy_file(helpers.checked_file(explicit[name]), output / name)
    replaced_prefixes = FRONT_PREFIXES + ("runtime/desktop/", "desktop/")
    merged = {row["path"]: row for row in previous["files"] if not row["path"].startswith(replaced_prefixes)}
    merged.update({row["path"]: row for row in new_rows + overrides})
    old_frontend = json.loads(helpers.checked_file(previous["generated"]["installer/frontend-payload-manifest.json"]).read_text("utf-8"))
    row_map = {name: {key: row[key] for key in ("path", "sha256", "bytes")} for name, row in merged.items()}
    frontend = {**old_frontend, "version": current.VERSION, "native_build_id": native["build_id"],
                "openmaic_build_id": fresh["openmaic"]["build_id"],
                "openmaic_next_build_id": fresh["openmaic"]["next_build_id"], "junctions": len(links),
                "components": [helpers.component_inventory(native["root"] if entry["path"].startswith("runtime/native-frontends/") else entry["path"], row_map)
                               if entry["path"].startswith("runtime/native-frontends/") or entry["path"] in {"runtime/openmaic-standalone", "runtime/harness", "runtime/desktop"}
                               else entry for entry in old_frontend["components"]]}
    generated = {}
    for name, value in (("runtime/native-frontend.json", native), ("installer/junctions.json", links),
                        ("installer/frontend-payload-manifest.json", frontend)):
        descriptor = stage.write_new(output / name, value)
        generated[name] = descriptor
        merged[name] = {"path": name, **descriptor}
    full = {**previous, "files": sorted(merged.values(), key=lambda row: row["path"]), "components": components,
            "public_source_files": sorted(explicit.values(), key=lambda row: row["path"]), "generated": generated,
            "junctions": links, "builds": {"native": {"build_id": native["build_id"], "receipt": descriptors["native_receipt"]},
            "openmaic": {"build_id": fresh["openmaic"]["build_id"], "next_build_id": fresh["openmaic"]["next_build_id"],
                         "receipt": descriptors["openmaic_receipt"]}},
            "derivation": {"inputs": descriptors, "refresh": "native, OpenMAIC, desktop transport, explicitly frozen public code only",
                           "unchanged_components_reused": [item["name"] for item in components if item["name"] not in {*fresh, "desktop_runtime", "desktop_source"}]}}
    full_descriptor = stage.write_new(output / "public-overlay.json", full)
    runtime_rows = new_rows + [row for row in overrides if row["path"].startswith(("portal/", "scripts/", "integration/", "runtime/"))
                               or row["path"] in PUBLIC_EXACT] + [merged[name] for name in generated]
    incremental = {"kind": "deepsteam-unified-public-runtime-overlay", "files": sorted(runtime_rows, key=lambda row: row["path"]),
                   "junctions": links, "credentials_copied": False, "user_data_copied": False,
                   "private_storage_configuration_changed": False, "deletions": [], "preserve_existing_public_files": True,
                   "derivation": {"full_overlay": full_descriptor, "inputs": descriptors}}
    delta = stage.write_new(output / "runtime-overlay.json", incremental)
    report = {"kind": "deepsteam-unified-incremental-public-stage", "full_overlay": full_descriptor,
              "runtime_overlay": delta, "components": components, "overrides": overrides,
              "incremental_file_count": len(runtime_rows), "incremental_bytes": sum(row["bytes"] for row in runtime_rows),
              "credentials_copied": False, "user_data_copied": False, "models_called": False,
              "services_started": False, "production_changed": False, "full_installer_built": False,
              "published_to_e": False, "elapsed_seconds": round(time.monotonic() - started, 3)}
    receipt_out = stage.write_new(output / "prepare-report.json", report)
    print(json.dumps({"report": receipt_out, "full_overlay": full_descriptor, "runtime_overlay": delta,
                      "files": len(runtime_rows), "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
