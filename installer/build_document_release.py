"""Freeze and build a new document-capable release from a public baseline.

This is the current parameterized entry point. Changed program files come from
reviewed manifests; unchanged ZIP records are reused without extracting/copying
models. A final packaged Python OCR/Office check is mandatory. Never writes E.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_module("document_release_base", "reports/build_r6_models_release.py")
runtime = load_module("document_release_runtime", "installer/document_runtime.py")
retired = load_module("document_release_retired", "installer/retired_components.py")
original_target = release.program_target
OCR_TARGETS = {entry["target"] for entry in json.loads(runtime.OCR_MANIFEST.read_text("utf8"))["files"]}
COMPONENT_TARGETS = set()


def program_target(name):
    retired.assert_no_retired_components([name])
    release.h.safe_name(name)
    reject_private_component(name)
    try:
        original_target(name)
        return
    except RuntimeError:
        pass
    if name in {"installer/UNINSTALL.md", "runtime/desktop/resources/app.asar"}:
        return
    desktop_names = {"main.cjs", "preload.cjs", "policy.cjs", "transport.cjs", "storage-migration.cjs",
                     "oauth-placeholder.cjs", "starting.html", "package.json"}
    if name in {prefix + part for prefix in ("desktop/", "runtime/desktop/resources/app/") for part in desktop_names}:
        return
    if name in OCR_TARGETS:
        return
    if (name == release.OM + 'lib/server/agent-runtime/import-pptx-worker.mjs'
            or (name.startswith(release.OM + 'skills/') and Path(name).suffix.casefold() in {'.md', '.json', '.yaml', '.yml'})):
        return
    if name in COMPONENT_TARGETS:
        return
    raise RuntimeError("File is outside the program-only document update scope: " + name)


release.program_target = program_target
release.validate_document_rows = retired.assert_no_retired_components


def uninstall_tests_passed(report):
    tests = report.get("tests")
    if isinstance(tests, dict):
        return tests.get("passed") is True
    if isinstance(tests, list) and tests:
        return (all(isinstance(row, dict) and row.get("passed") is True
                    and isinstance(row.get("checks"), int) and row["checks"] > 0 for row in tests)
                and report.get("total_checks") == sum(row["checks"] for row in tests))
    return False


def project_file(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    for ancestor in [path, *path.parents]:
        if ancestor.exists() and (ancestor.is_symlink() or getattr(ancestor.lstat(), "st_file_attributes", 0) & 0x400):
            raise RuntimeError("Release input crosses a reparse point")
    path = path.resolve(strict=True)
    path.relative_to(ROOT.resolve())
    if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        raise RuntimeError("Release input is a reparse point")
    if not path.is_file():
        raise RuntimeError("Release input must be a regular file")
    return path


def configure(args):
    if not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-r[0-9][A-Za-z0-9.-]*", args.version):
        raise RuntimeError("Use an explicit dated release version")
    if not re.fullmatch(r"r[0-9][A-Za-z0-9.-]*", args.artifact):
        raise RuntimeError("Artifact must be a new installer/r* directory name")
    release.VERSION = args.version
    release.ARTIFACT = ROOT / "installer" / args.artifact
    release.SPEC = ROOT / "reports" / (args.artifact + "-spec.json")
    if args.action == "prepare":
        if not args.baseline or not args.baseline_sha256:
            raise RuntimeError("Preparation requires a public baseline and its SHA-256")
        baseline = project_file(args.baseline)
        if release.h.digest(baseline) != args.baseline_sha256:
            raise RuntimeError("Public baseline SHA-256 differs")
        baseline_sha = args.baseline_sha256
        with zipfile.ZipFile(baseline) as archive:
            import hashlib
            manifest_sha = hashlib.sha256(archive.read(release.h.MANIFEST_NAME)).hexdigest()
    else:
        if not release.SPEC.is_file() or release.h.digest(release.SPEC) != args.spec_sha256:
            raise RuntimeError("Pass the exact frozen release specification SHA-256")
        spec = json.loads(release.SPEC.read_text("utf8"))
        baseline = release.h.checked_file(spec["baseline"])
        baseline_sha = spec["baseline"]["sha256"]
        manifest_sha = spec["baseline"]["manifest_sha256"]
        component_rows = {}
        for record in spec.get("component_manifests", []):
            component = load_component_manifest(release.h.checked_file(record))
            for row in component['files']:
                key = row['target'].casefold()
                if key in component_rows:
                    raise RuntimeError('Frozen component targets overlap')
                component_rows[key] = row
        plan_rows = {}
        for row in spec.get('files', []):
            key = row['path'].casefold()
            if key in plan_rows:
                raise RuntimeError('Duplicate frozen program target')
            plan_rows[key] = row
        for target, row in component_rows.items():
            planned = plan_rows.get(target)
            if (not planned or any(planned.get(key) != row[key] for key in ('bytes', 'sha256'))
                    or project_file(planned['source']) != project_file(row['source'])):
                raise RuntimeError('Frozen program plan differs from its licensed runtime component')
    release.BASELINE, release.BASELINE_SHA, release.BASELINE_MANIFEST_SHA = baseline, baseline_sha, manifest_sha


def load_component_manifest(path):
    value = json.loads(Path(path).read_text('utf8'))
    targets = set()
    if value.get('schema') == 'deepsteam-mineru-runtime-v1':
        if value.get('tool_only') is not True or value.get('engine_version') != '4.0.12':
            raise RuntimeError('MinerU must be the fixed document tool runtime')
        if value.get('redistribution_status') != 'verified':
            raise RuntimeError('MinerU runtime requires verified redistribution licenses')
        prefixes = ('runtime/mineru/', 'models/mineru/', 'licenses/mineru/')
        exact = {'scripts/mineru_document_worker.py', 'installer/mineru-runtime-lock.txt'}
    elif value.get('schema') == 'deepsteam-harness-runtime-v1':
        prefixes = ('runtime/harness/node_modules/',)
        exact = {'runtime/harness/package.json', 'runtime/harness/package-lock.json'}
    else:
        raise RuntimeError('Unknown independently verified runtime component')
    for row in value.get('files', []):
        target = row['target']
        release.h.safe_name(target)
        reject_private_component(target)
        if target.casefold() in targets:
            raise RuntimeError('Duplicate runtime component target: ' + target)
        targets.add(target.casefold())
        if target not in exact and not target.startswith(prefixes):
            raise RuntimeError('Unexpected runtime component target: ' + target)
        source = project_file(row['source'])
        desc = release.descriptor(source)
        if any(desc[key] != row[key] for key in ('bytes', 'sha256')):
            raise RuntimeError('Runtime component changed: ' + target)
        if target == 'runtime/mineru/runtime.json':
            config = json.loads(source.read_text('utf8'))
            expected = {'schema_version': 1, 'engine': 'mineru', 'version': '4.0.12',
                        'commit': 'b7f3dd0c5f6e6d66a298239ffd02b328b873918e',
                        'python_version': '3.13.15', 'tool_only': True, 'provider': False,
                        'small_backend': 'onnx', 'vlm_engine': 'official-local-llama-server',
                        'model_root': '../../models/mineru', 'excluded_dependency': 'mineru-llama-cpp',
                        'device': 'cpu'}
            if (set(config) != set(expected) | {'dependency_resolution_sha256'}
                    or any(config[key] != value for key, value in expected.items())
                    or not re.fullmatch(r'[0-9a-f]{64}', str(config['dependency_resolution_sha256']))):
                raise RuntimeError('MinerU runtime configuration must contain fixed public metadata only')
    if not value.get('files'):
        raise RuntimeError('Empty runtime component manifest')
    if value.get('schema') == 'deepsteam-mineru-runtime-v1':
        acceptance = value.get('acceptance')
        if not isinstance(acceptance, dict):
            raise RuntimeError('MinerU requires its verified offline acceptance descriptor')
        report_path = project_file(acceptance['source'])
        actual = release.descriptor(report_path)
        if any(actual[field] != acceptance[field] for field in ('bytes', 'sha256')):
            raise RuntimeError('MinerU offline acceptance changed')
        report = json.loads(report_path.read_text('utf8'))
        worker = next((row for row in value['files'] if row['target'] == 'scripts/mineru_document_worker.py'), None)
        if report.get('passed') is not True or not worker or report.get('worker_sha256') != worker['sha256']:
            raise RuntimeError('MinerU offline acceptance does not cover the packaged worker')
    COMPONENT_TARGETS.update(row['target'] for row in value['files'])
    return value


def reject_private_component(name):
    parts = {part.casefold() for part in Path(name).parts}
    leaf = Path(name).name.casefold()
    fixed_tool_config = name == 'runtime/mineru/runtime.json'
    dependency_code = name.startswith('runtime/harness/node_modules/')
    compiled_code = (re.fullmatch(r'runtime/native-frontends/[0-9]{8}-[0-9]{6}/\.next-contest-native/(?:server|static)/.+', name)
                     or re.fullmatch(r'runtime/openmaic-standalone/\.next/(?:server|static)/.+', name))
    forbidden = {'.dsh', '.deepseek', 'browser-profile', 'userdata', 'harness-state', '.cache', '__pycache__'}
    if not dependency_code and not compiled_code:
        forbidden.update({'cache', 'logs', 'profile', 'sessions', 'credentials'})
    if (parts.intersection(forbidden)
            or leaf in {'control-token', 'account-state.json', 'credentials.json', 'cookies.json',
                        'auth.json', 'token.json', '.env', '.env.local'}
            or (leaf == 'runtime.json' and not fixed_tool_config)
            or leaf.startswith('.env.')
            or Path(name).suffix.casefold() in {'.sqlite', '.sqlite3', '.db', '.pyc'}):
        raise RuntimeError('Private or mutable runtime state is not distributable: ' + name)


def prepare(args):
    if release.SPEC.exists() or release.ARTIFACT.exists():
        raise RuntimeError("Use a fresh artifact identity; previous packages are preserved")
    if not args.program_manifest or not args.native_receipt or not args.acceptance or not args.uninstaller_report:
        raise RuntimeError("Supply program manifests, final native receipt, software acceptance and uninstaller test report")
    baseline, metadata = release.read_baseline(check_digest=False)
    selected, inputs = {}, []
    component_manifests = []
    component_prefixes = []
    for path in args.component_manifest or []:
        source = project_file(path)
        component = load_component_manifest(source)
        component_manifests.append(release.descriptor(source))
        if component.get('schema') == 'deepsteam-mineru-runtime-v1':
            component_prefixes.extend(('runtime/mineru/', 'models/mineru/', 'licenses/mineru/'))
        elif component.get('schema') == 'deepsteam-harness-runtime-v1':
            component_prefixes.append('runtime/harness/node_modules/')
    for path in [*args.program_manifest, *(args.component_manifest or [])]:
        source = project_file(path)
        inputs.append(release.descriptor(source))
        content = json.loads(source.read_text("utf8"))
        if content.get("user_data_copied") or content.get("credentials_copied") or content.get("data_copied"):
            raise RuntimeError("Release manifests must contain program files only")
        entries = content.get("files", content.get("source_files"))
        if not isinstance(entries, list):
            raise RuntimeError("Expected a program file manifest")
        for entry in entries:
            target = entry.get("target", entry.get("path"))
            program_target(target)
            file = project_file(entry["source"])
            desc = release.descriptor(file)
            if any(desc[key] != entry[key] for key in ("bytes", "sha256")):
                raise RuntimeError("Program file changed after review: " + target)
            # Later manifests intentionally replace earlier reviewed program deltas.
            selected[target] = {"path": target, **desc}
    for name, file in runtime.diagnostic_files().items():
        selected[name] = {"path": name, **release.descriptor(file)}
    # Explicitly consume the accepted OCR component even for a pre-OCR baseline.
    ocr = json.loads(runtime.OCR_MANIFEST.read_text("utf8"))
    inputs.append(release.descriptor(runtime.OCR_MANIFEST))
    for entry in ocr["files"]:
        file = project_file(entry["source"])
        desc = release.descriptor(file)
        if any(desc[key] != entry[key] for key in ("bytes", "sha256")):
            raise RuntimeError("Staged OCR dependency changed")
        selected[entry["target"]] = {"path": entry["target"], **desc}
    native_path = project_file(args.native_receipt)
    native = json.loads(native_path.read_text("utf8"))
    build_id = native.get("build_id", "")
    if not re.fullmatch(r"\d{8}-\d{6}", build_id):
        raise RuntimeError("Native build receipt lacks its immutable identity")
    new_prefix = release.NATIVE + build_id + "/"
    selected = {key: val for key, val in selected.items() if not key.startswith(release.NATIVE) or key.startswith(new_prefix)}
    selected.pop("runtime/native-frontend.json", None)
    if new_prefix + "server.js" not in selected or release.OM + ".next/BUILD_ID" not in selected:
        raise RuntimeError("Supply complete final native and OpenMAIC program inventories")
    om_id = release.h.checked_file(selected[release.OM + ".next/BUILD_ID"]).read_text("utf8").strip()
    old_prefix = release.NATIVE + metadata["runtime/native-frontend.json"]["build_id"] + "/"
    links = [{key: val.replace(old_prefix, new_prefix) if key in {"path", "target"} else val
              for key, val in item.items()} for item in metadata["installer/junctions.json"]]
    if args.junctions:
        junction_path = project_file(args.junctions)
        links = json.loads(junction_path.read_text("utf8"))
        inputs.append(release.descriptor(junction_path))
    prefixes = [release.NATIVE, release.OM + ".next/", release.OM + "public/",
                *retired.RETIRED_PREFIXES, *component_prefixes]
    removed_files = sorted(retired.RETIRED_FILES)
    rows = {key: val for key, val in baseline.items()
            if not any(key.startswith(prefix) for prefix in prefixes) and key not in removed_files}
    rows.update({key: {field: val[field] for field in ("path", "bytes", "sha256")} for key, val in selected.items()})
    retired.assert_no_retired_components(rows)
    release.h.validate_junctions(links, rows)
    runtime.check_rows(rows)
    acceptance = project_file(args.acceptance)
    if json.loads(acceptance.read_text("utf8")).get("passed") is not True:
        raise RuntimeError("Current software acceptance has not passed")
    uninstall_report = project_file(args.uninstaller_report)
    uninstall = json.loads(uninstall_report.read_text("utf8"))
    csharp = ROOT / "installer/DeepSteamSetup.cs"
    if uninstall.get("source_sha256") != release.h.digest(csharp) or not uninstall_tests_passed(uninstall):
        raise RuntimeError("Current uninstaller source is not covered by the passing test report")
    inputs.append(release.descriptor(uninstall_report))
    extra_share_files = []
    for path in args.extra_share_file or []:
        extra = project_file(path)
        if extra.suffix.lower() != ".zip" or not extra.name.startswith("DeepSteam-"):
            raise RuntimeError("Additional reviewed share artifacts must be named DeepSteam-*.zip")
        with zipfile.ZipFile(extra) as archive:
            if archive.testzip() is not None or not archive.namelist():
                raise RuntimeError("Additional reviewed ZIP failed integrity checks")
        if any(Path(record["source"]).name == extra.name for record in extra_share_files):
            raise RuntimeError("Duplicate additional share artifact name")
        extra_share_files.append(release.descriptor(extra))
    # Retain explicit unchanged required model/Host source mirrors for base validation.
    for prefix, relative in [(release.PYTHON, "deeptutor/services/config/provider_runtime.py"),
                             (release.OVERLAY, "deeptutor/services/config/provider_runtime.py"),
                             (release.PYTHON, "deeptutor/services/model_selection/llm.py"),
                             (release.OVERLAY, "deeptutor/services/model_selection/llm.py")]:
        name = prefix + relative
        if name not in selected:
            source = ROOT / "upstream/DeepTutor" / relative
            desc = release.descriptor(source)
            if desc["sha256"] != rows.get(name, {}).get("sha256"):
                raise RuntimeError("Missing reviewed model dependency update: " + name)
            selected[name] = {"path": name, **desc}
    for part in ("sidecar.mjs", "workspaces.mjs", "workspace_http.mjs"):
        for prefix in ("runtime/harness/", "integration/harness/"):
            name = prefix + part
            if name not in selected:
                source = ROOT / "integration/harness" / part
                desc = release.descriptor(source)
                if desc["sha256"] != rows.get(name, {}).get("sha256"):
                    raise RuntimeError("Missing reviewed Host dependency update: " + name)
                selected[name] = {"path": name, **desc}
    plan = {"kind": "deepsteam-document-delivery-frozen-package-v1", "version": release.VERSION,
            "artifact": release.ARTIFACT.relative_to(ROOT).as_posix(),
            "baseline": {**release.descriptor(release.BASELINE), "manifest_sha256": release.BASELINE_MANIFEST_SHA},
            "inputs": inputs, "native_receipt": release.descriptor(native_path), "native": native,
            "component_manifests": component_manifests,
            "openmaic_next_build_id": om_id, "tzdata_wheel": release.descriptor(release.WHEEL),
            "files": sorted(selected.values(), key=lambda val: val["path"]), "replace_prefixes": prefixes,
            "remove_files": removed_files, "builtin_chat_model": False,
            "junctions": links, "installer_source": release.descriptor(csharp),
            "windows_manifest": release.descriptor(ROOT / "installer/DeepSteam.manifest"),
            "feature_acceptance": release.descriptor(acceptance),
            "extra_share_files": extra_share_files,
            "document_runtime": {key: release.descriptor(ROOT / path) for key, path in {
                "dependency_manifest": "reports/workspace-document-ocr-dependencies.json",
                "requirements": "installer/document-runtime-requirements.txt", "probe": "scripts/check_document_runtime.py",
                "packaging_helper": "installer/document_runtime.py", "scan_fixture": "installer/document-fixtures/scanned-en.png"}.items()},
            "deferred_validation": ["second_physical_computer", "fresh_cloud_inference", "production_uninstall"],
            "user_data_copied": False, "credentials_copied": False,
            "document_tool_models_included": any(record for record in component_manifests
                if 'mineru' in Path(record['source']).name.casefold()), "builtin_chat_model_included": False,
            "old_complete_dependencies_reused": True}
    release.write_new(release.SPEC, plan)
    print(json.dumps({"spec": release.descriptor(release.SPEC), "files": len(selected),
                      "full_build_performed": False}, ensure_ascii=False), flush=True)


def share(args):
    """Create reviewed source/license companions after final runtime verification."""
    plan, _, _, _, _ = release.load_plan(args.spec_sha256)
    build_path = release.ARTIFACT / "build-report.json"
    build = json.loads(build_path.read_text("utf8"))
    if build.get("version") != release.VERSION or build.get("spec", {}).get("sha256") != args.spec_sha256:
        raise RuntimeError("Built release identity differs from its frozen specification")
    if not all(build.get(key) is True for key in ("all_file_sha_passed", "crc_passed", "actual_exe_self_test_passed")):
        raise RuntimeError("Final Windows package gates have not passed")
    document_acceptance = build.get("packaged_document_runtime_acceptance")
    if not document_acceptance or not json.loads(release.h.checked_file(document_acceptance).read_text("utf8")).get("passed"):
        raise RuntimeError("Final package has not passed its isolated document runtime check")
    for row in build["distribution_files"]:
        release.h.checked_file(row)
    public = load_module("document_public_sources", "reports/prepare_r6_models_share.py")
    public.release = release
    selected, upstream = public.source_files()
    destination = release.ARTIFACT / "release"
    notes = f"""# DeepSteam {release.VERSION}

This release includes the Windows application and pinned local document tools,
without a bundled chat model. Isolated offline payload checks cover PDF text,
scanned-page OCR, Word text/tables/images, PPTX, XLSX formula strings, Markdown,
and original PDF page images. Scan quality, complex formulas, and diagram meaning
still require comparison with source pages. Partial or review states are not
complete recognition.

Application version: {release.VERSION}
Learning interface build: {plan['native']['build_id']}
Classroom interface build: {plan['openmaic_next_build_id']}
Accounts, credentials, learning databases, and private documents are excluded.
Users authorize their own model accounts or configure their own APIs. Final
container SHA, CRC, and Windows installer checks must pass before distribution.
Physical second-computer, fresh cloud-generation, and production-uninstall
results are reported separately rather than inferred from isolated checks.

This product integrates HKUDS/DeepTutor, THU-MAIC/OpenMAIC, DeepSeek Harness,
OpenDataLab/MinerU, and official llama.cpp document-tool runtime components.
Their licenses and attribution are preserved. MinerU is a document tool, not
a chat model. Test fixture paths are not user API or installation settings.
"""
    identity = {"version": release.VERSION, "native_build_id": plan["native"]["build_id"],
                "openmaic_next_build_id": plan["openmaic_next_build_id"], "upstream": upstream,
                "deferred_validation": build["deferred_validation"], "user_data_copied": False,
                "credentials_copied": False}
    generated = {"RELEASE.md": notes.encode("utf8"), "RELEASE-IDENTITY.json": release.h.json_bytes(identity)}
    source = public.build_zip(destination / f"DeepSteam-{release.VERSION}-source.zip", selected, generated)
    licenses = {name: file for name, file in selected.items() if name.startswith("licenses/")}
    license_generated = dict(generated)
    with zipfile.ZipFile(destination / f"DeepSteam-Setup-{release.VERSION}-x64.payload.dat") as archive:
        for name in archive.namelist():
            if name.startswith("licenses/") and name not in licenses:
                release.h.safe_name(name)
                license_generated[name] = archive.read(name)
    licenses["installer/UNINSTALL.md"] = ROOT / "installer/UNINSTALL.md"
    docs = public.build_zip(destination / f"DeepSteam-{release.VERSION}-licenses-and-guide.zip", licenses, license_generated)
    for project in upstream:
        if not any(name.startswith("upstream/" + project + "/LICENSE") for name in selected):
            raise RuntimeError("Missing upstream license: " + project)
    readme = f"""DeepSteam {release.VERSION}

Installation: keep DeepSteam-Setup-{release.VERSION}-x64.exe and its matching
.payload.dat in one folder, then open the EXE. Both files are required. Launch
from the installed DeepSteam entry; internal service addresses need no setup.
The package includes runtimes, document parsers, and OCR tools, without a chat
model. Users log in or configure their own APIs. Embedding and speech capabilities
retain distinct settings. Uninstall through Windows Installed apps or the app's
Settings; personal data and workspaces are preserved by default.
Accounts, learning databases, and private materials are excluded. See the source
and license companion ZIPs. checksums.json lists distribution SHA-256 values.
"""
    if plan.get("extra_share_files"):
        readme += "\nIf a legacy uninstall entry fails, read the included legacy-entry repair ZIP guide. The patch does not automatically uninstall the application.\n"
    release.write_new(destination / "README.txt", readme.encode("utf8"))
    for record in plan.get("extra_share_files", []):
        source_file = release.h.checked_file(record)
        release.write_new(destination / source_file.name, source_file.read_bytes())
    files = [{"name": path.name, "bytes": path.stat().st_size, "sha256": release.h.digest(path)}
             for path in sorted(destination.iterdir())]
    if len(files) != 5 + len(plan.get("extra_share_files", [])):
        raise RuntimeError("Unexpected file present in the fresh release directory")
    release.write_new(destination / "checksums.json", {"version": release.VERSION, "algorithm": "SHA-256", "files": files})
    release.write_new(release.ARTIFACT / "public-share-report.json", {
        "version": release.VERSION, "source_zip": source, "licenses_zip": docs, "distribution_file_count": len(files) + 1,
        "user_data_copied": False, "credentials_copied": False, "written_to_e": False,
        "files": [release.descriptor(path) for path in sorted(destination.iterdir())]})
    print(json.dumps({"share_report": release.descriptor(release.ARTIFACT / "public-share-report.json")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "validate", "build", "share"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--baseline-sha256")
    parser.add_argument("--program-manifest", action="append")
    parser.add_argument("--component-manifest", action="append", help="Verified parser or Harness dependency closure")
    parser.add_argument("--native-receipt")
    parser.add_argument("--acceptance")
    parser.add_argument("--uninstaller-report")
    parser.add_argument("--junctions")
    parser.add_argument("--extra-share-file", action="append", help="Reviewed DeepSteam ZIP to freeze and include beside the installer")
    parser.add_argument("--spec-sha256")
    args = parser.parse_args()
    configure(args)
    if args.action == "prepare":
        prepare(args)
    elif args.action == "share":
        share(args)
    else:
        release.build(argparse.Namespace(expected_spec_sha256=args.spec_sha256, validate_only=args.action == "validate"))


if __name__ == "__main__":
    main()
