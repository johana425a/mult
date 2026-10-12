"""Prepare a new SHA-pinned public overlay; never deploy or start the product.

The preserved r4 archive supplies unchanged models/runtimes to the later package.
This stage contains public replacements only, with installation-relative links.
No account state, local storage selection, model inference, E writes or deletion.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer"


def load_module(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(value)
    return value


build = load_module("unified_public_r5_builder", INSTALLER / "build_r5_candidate.py")
helpers = build.helpers
BASELINE = INSTALLER / "r4-technical-20261011-final/payload-r4.zip"
BASELINE_SHA = "27eaf815734dd750bd21157b0e1755c63fe5ed5827325f784111e6dcd1903b95"
BASELINE_MANIFEST_SHA = "9a563eb29a92ee9416eca0ab3aaf24760f22315eb95c8057bbc76735a665e94b"
DESKTOP_REPORT = INSTALLER / "r5-desktop-unified-workspace-20261011/desktop-build-report.json"
DESKTOP_REPORT_SHA = "8fa75cf93848c82e11449e1cb6428369b34531b2058f48975ecd197a49cbf292"
INSTALLER_SOURCE_SHA = "325e9a9d8f7d58d1c1eff59348db761516e044d9372b2cec5a8a7059c7f8ded7"
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
SECRET_PATTERNS = {
    "private-key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "openai-key": rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b",
    "github-token": rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
    "aws-access-key": rb"\bAKIA[0-9A-Z]{16}\b",
}


def contained(path, root=ROOT):
    path.resolve().relative_to(root.resolve())
    return path


def ordinary(path):
    contained(path)
    for item in [path, *path.parents]:
        if item == ROOT.parent:
            break
        if item.is_symlink() or item.is_junction():
            raise RuntimeError("Public source may not traverse a reparse point: " + str(path))
    if not path.is_file():
        raise RuntimeError("Missing public source: " + str(path))
    return path


def write_new(path, value):
    contained(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = helpers.json_bytes(value)
    with path.open("xb") as stream:
        stream.write(blob)
    return {"source": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}


def copy_file(source, target):
    ordinary(source)
    contained(target)
    if target.exists():
        raise RuntimeError("Fresh staged file already exists: " + str(target))
    before = helpers.digest(source)
    Path(helpers.native_path(target.parent)).mkdir(parents=True, exist_ok=True)
    shutil.copy2(helpers.native_path(source), helpers.native_path(target))
    if before != helpers.digest(source) or before != helpers.digest(target):
        raise RuntimeError("Source changed while staging: " + str(source))


def copy_tree(source, target, installed_target, source_only=False):
    contained(source)
    target.mkdir(parents=True, exist_ok=False)
    skipped = []
    for directory, names, files in os.walk(helpers.native_path(source), followlinks=False):
        parent = Path(directory)
        names[:] = sorted(name for name in names if name not in SKIP_DIRS and not (source_only and name == "node_modules"))
        for name in names:
            item = parent / name
            if item.is_symlink() or item.is_junction():
                raise RuntimeError("Source dependency link must be explicitly mapped: " + str(item))
        for name in sorted(files):
            item = parent / name
            relative = item.relative_to(Path(helpers.native_path(source)))
            if name.endswith((".pyc", ".pyo")):
                continue
            build.safe_name(installed_target + "/" + relative.as_posix())
            copy_file(Path(str(item).removeprefix("\\\\?\\")), target / relative)
    return skipped


def component(stage, name, source, target, *, source_only=False):
    destination = stage / target
    copy_tree(source, destination, target, source_only=source_only)
    rows = helpers.collect_tree(destination, target)
    inventory = {"source": destination.relative_to(ROOT).as_posix(), "target": target,
                 "file_count": len(rows), "uncompressed_bytes": sum(item["bytes"] for item in rows), "files": rows}
    descriptor = write_new(stage / (name + "-inventory.json"), inventory)
    return {"name": name, "source": inventory["source"], "target": target,
            "inventory": descriptor, "file_count": len(rows)}, rows


def scan_public_text(path):
    if path.suffix.lower() not in {".py", ".mjs", ".cjs", ".js", ".ts", ".tsx", ".cs", ".json", ".md", ".txt", ".html", ".css", ".ps1"}:
        return
    findings = [name for name, pattern in SECRET_PATTERNS.items() if re.search(pattern, path.read_bytes())]
    if findings:
        raise RuntimeError("Public text requires credential-pattern review: " + str(path) + " " + ",".join(findings))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--frontend-stage", required=True)
    parser.add_argument("--expected-frontend-report-sha256", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    if not re.fullmatch(r"r5-unified-[a-z0-9-]+", args.artifact_name):
        raise RuntimeError("Fresh installer/r5-unified-* stage required")
    stage = INSTALLER / args.artifact_name
    if stage.exists():
        raise RuntimeError("Prior public stage must remain unchanged")
    frontend_report = helpers.checked_file({"source": args.frontend_stage + "/prepare-report.json", "sha256": args.expected_frontend_report_sha256})
    front = json.loads(frontend_report.read_text("utf-8"))
    if front.get("credentials_copied") is not False or front.get("user_data_copied") is not False:
        raise RuntimeError("Public frontend stage lacks exclusions")
    if helpers.digest(DESKTOP_REPORT) != DESKTOP_REPORT_SHA or helpers.digest(INSTALLER / "DeepSteamSetup.cs") != INSTALLER_SOURCE_SHA:
        raise RuntimeError("Desktop or installer source freeze changed")
    desktop = json.loads(DESKTOP_REPORT.read_text("utf-8"))
    desktop_root = contained(Path(desktop["runtime"]))
    if helpers.digest(desktop_root / "resources/app.asar") != desktop["app_asar_sha256"]:
        raise RuntimeError("Frozen desktop ASAR differs")
    for item in desktop["source_files"]:
        for source in (ROOT / "desktop" / item["path"], desktop_root / "resources/app" / item["path"]):
            if source.stat().st_size != item["bytes"] or helpers.digest(source) != item["sha256"]:
                raise RuntimeError("Frozen desktop source mirror differs")
    with zipfile.ZipFile(BASELINE) as archive:
        manifest_blob = archive.read(helpers.MANIFEST_NAME)
        if hashlib.sha256(manifest_blob).hexdigest() != BASELINE_MANIFEST_SHA:
            raise RuntimeError("Preserved r4 baseline manifest differs")
        baseline = helpers.rows_by_path(json.loads(manifest_blob))
        baseline_links = json.loads(archive.read("installer/junctions.json"))
        old_frontend = json.loads(archive.read("installer/frontend-payload-manifest.json"))
    stage.mkdir()
    components = list(front["components"])
    rows = dict(baseline)
    files = []
    public_inputs = []
    def add_component(entry, inventory_rows):
        prefix = "runtime/native-frontends/" if entry["name"] == "native" else entry["target"] + "/"
        for old in [name for name in rows if name.startswith(prefix)]:
            del rows[old]
        for item in inventory_rows:
            path = entry["target"] + "/" + item["path"]
            build.safe_name(path)
            row = {**item, "path": path, "source": entry["source"] + "/" + item["path"]}
            files.append(row)
            rows[path] = {key: row[key] for key in ("path", "bytes", "sha256")}
    for entry in front["components"]:
        source = helpers.workspace_path(entry["source"])
        inv = json.loads(helpers.checked_file(entry["inventory"]).read_text("utf-8"))
        actual = helpers.collect_tree(source, entry["target"])
        if inv["files"] != actual:
            raise RuntimeError("Frozen frontend component inventory differs")
        add_component(entry, actual)
    for name, source, target, source_only in (
        ("portal", ROOT / "portal", "portal", False),
        ("scripts", ROOT / "scripts", "scripts", False),
        ("harness", ROOT / "runtime/harness", "runtime/harness", False),
        ("desktop_runtime", desktop_root, "runtime/desktop", False),
        ("desktop_source", ROOT / "desktop", "desktop", True),
        ("harness_bridge", ROOT / "integration/harness", "integration/harness", True),
    ):
        print(json.dumps({"phase": "public-component", "name": name}), flush=True)
        entry, actual = component(stage, name, source, target, source_only=source_only)
        components.append(entry)
        add_component(entry, actual)
    explicit = [item.relative_to(ROOT).as_posix() for item in (ROOT / "integration").iterdir() if item.is_file() and item.suffix == ".py"]
    explicit += ["installer/DeepSteamSetup.cs", "installer/DeepSteam.manifest", "installer/UNINSTALL.md",
                 "installer/Start-DeepSteam.ps1", "installer/Stop-DeepSteam.ps1", "installer/Install-DeepSteam.ps1",
                 "installer/deepsteam-start.html"]
    explicit += [item.relative_to(ROOT).as_posix() for item in (ROOT / "licenses").iterdir() if item.is_file()]
    documentation = "reports/DeepSteam-Models-And-Workspaces.md"
    if (ROOT / documentation).is_file():
        explicit.append(documentation)
    for name in sorted(explicit):
        build.safe_name(name)
        source = ROOT / name
        destination = stage / name
        copy_file(source, destination)
        scan_public_text(destination)
        row = {"path": name, "source": destination.relative_to(ROOT).as_posix(), "bytes": destination.stat().st_size, "sha256": helpers.digest(destination)}
        files.append(row)
        public_inputs.append(row)
        rows[name] = {key: row[key] for key in ("path", "bytes", "sha256")}
    staged_links = json.loads(helpers.checked_file(front["junctions"]).read_text("utf-8"))
    replaced = ("runtime/native-frontends/", "runtime/openmaic-standalone/")
    links = sorted([row for row in baseline_links if not row["path"].startswith(replaced)] +
                   [row for row in staged_links if row["path"].startswith(replaced)], key=lambda row: row["path"])
    helpers.validate_junctions(links, rows)
    native = json.loads((ROOT / args.frontend_stage / "runtime/native-frontend.json").read_text("utf-8"))
    native_prefix = native["root"]
    om = next(item for item in components if item["name"] == "openmaic")
    frontend = {**old_frontend, "version": "2026.10.11-r5-unified-staged", "native_build_id": native["build_id"],
                "openmaic_build_id": om["build_id"], "openmaic_next_build_id": om["next_build_id"],
                "desktop_harness_included": True, "credentials_and_user_data_copied": False,
                "junctions": len(links), "components": [helpers.component_inventory(target, rows) for target in
                (native_prefix, "runtime/openmaic-standalone", "runtime/render-service", "runtime/desktop", "runtime/harness")]}
    generated = {}
    for name, value in (("installer/junctions.json", links), ("runtime/native-frontend.json", native),
                        ("installer/frontend-payload-manifest.json", frontend)):
        descriptor = write_new(stage / name, value)
        generated[name] = descriptor
        files.append({"path": name, **descriptor})
    for row in files:
        # Runtime dependencies are pinned separately; scan executable project text.
        if "node_modules/" not in row["path"] and row["path"].startswith(("portal/", "scripts/", "desktop/", "integration/")):
            scan_public_text(ROOT / row["source"])
    files.sort(key=lambda row: row["path"])
    if len({row["path"] for row in files}) != len(files):
        raise RuntimeError("Repeated public overlay target")
    descriptor = {"kind": "deepsteam-unified-public-program-overlay", "credentials_copied": False,
                  "user_data_copied": False, "private_storage_configuration_changed": False,
                  "preserve_existing_public_files": True, "deletions": [], "files": files, "junctions": links,
                  "components": components, "public_source_files": public_inputs, "generated": generated,
                  "builds": {"native": {"build_id": native["build_id"], "receipt": {"source": "reports/native-ui-runtime-build-20261011-225806.json", "sha256": helpers.digest(ROOT / "reports/native-ui-runtime-build-20261011-225806.json")}},
                             "openmaic": {"build_id": om["build_id"], "next_build_id": om["next_build_id"]}},
                  "baseline": {"source": BASELINE.relative_to(ROOT).as_posix(), "sha256": BASELINE_SHA,
                               "manifest_sha256": BASELINE_MANIFEST_SHA},
                  "baseline_complete_archive_sha_rechecked": False, "source_only_acceptance": True,
                  "models_called": False, "services_started": False, "production_changed": False,
                  "published_to_e": False, "full_installer_built": False}
    overlay = write_new(stage / "public-overlay.json", descriptor)
    runtime_prefixes = ("integration/", "portal/", "scripts/", "desktop/", "runtime/harness/",
                        "runtime/desktop/", "runtime/native-frontends/", "runtime/openmaic-standalone/")
    runtime_exact = {"runtime/native-frontend.json", "installer/junctions.json",
                     "installer/frontend-payload-manifest.json", "installer/UNINSTALL.md"}
    runtime_files = [row for row in files if row["path"].startswith(runtime_prefixes) or row["path"] in runtime_exact]
    runtime_overlay = write_new(stage / "runtime-overlay.json", {
        **descriptor, "kind": "deepsteam-unified-public-runtime-overlay", "files": runtime_files,
        "derivation": {"complete_public_overlay": overlay,
                       "deferred_public_documents": [row["path"] for row in files if row not in runtime_files]}})
    report = {"kind": "deepsteam-unified-public-stage", "overlay": overlay, "runtime_overlay": runtime_overlay, "components": components,
              "junctions": generated["installer/junctions.json"], "overlay_file_count": len(files),
              "overlay_uncompressed_bytes": sum(row["bytes"] for row in files), "junction_count": len(links),
              "desktop_report_sha256": DESKTOP_REPORT_SHA, "installer_source_sha256": INSTALLER_SOURCE_SHA,
              "credentials_copied": False, "user_data_copied": False, "production_changed": False,
              "published_to_e": False, "models_called": False, "services_started": False,
              "full_installer_built": False, "elapsed_seconds": round(time.monotonic() - started, 3)}
    report_descriptor = write_new(stage / "prepare-report.json", report)
    print(json.dumps({"report": report_descriptor, "overlay": overlay, "runtime_overlay": runtime_overlay,
                      "files": len(files), "junctions": len(links), "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
