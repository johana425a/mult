"""Release gates for the portable document reader and its offline OCR closure.

The package, never a user's installed environment, is the source of verification.
The temporary extraction is limited to document libraries, not the full app,
models, account state, or learning data. No network access or downloads.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SITE = "runtime/python/Lib/site-packages/"
MANIFEST = "installer/payload-manifest.json"
OCR_MANIFEST = ROOT / "reports/workspace-document-ocr-dependencies.json"
REQUIREMENTS = ROOT / "installer/document-runtime-requirements.txt"
PROBE = ROOT / "scripts/check_document_runtime.py"
READER = "scripts/workspace_document_reader.py"
MAX_EXTRACTED_BYTES = 550 * 1024 * 1024
PACKAGE_ROOTS = {
    "pymupdf", "fitz", "docx", "pptx", "openpyxl", "PIL", "lxml", "defusedxml",
    "rapidocr", "onnxruntime", "cv2", "pyclipper", "shapely", "shapely.libs",
    "omegaconf", "colorlog", "flatbuffers", "google", "numpy", "numpy.libs",
    "yaml", "_yaml", "tqdm", "requests", "packaging", "colorama", "six.py",
    "certifi", "urllib3", "idna", "charset_normalizer", "et_xmlfile", "xlsxwriter",
    "typing_extensions.py", "antlr4",
}
DIST_NAMES = {
    "pymupdf", "python_docx", "python_pptx", "openpyxl", "pillow", "lxml", "defusedxml",
    "rapidocr", "onnxruntime", "opencv_python_headless", "pyclipper", "shapely",
    "omegaconf", "colorlog", "flatbuffers", "protobuf", "numpy", "pyyaml", "tqdm",
    "requests", "packaging", "colorama", "six", "certifi", "urllib3", "idna",
    "charset_normalizer", "et_xmlfile", "xlsxwriter", "typing_extensions", "antlr4_python3_runtime",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or path.as_posix() != name:
        raise RuntimeError("Unsafe package path")
    return name


def pins(path: Path = REQUIREMENTS) -> dict[str, str]:
    result = {}
    for line in path.read_text("utf8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, version = line.strip().split("==")
            result[name.lower().replace("-", "_")] = version
    return result


def check_rows(rows: dict, ocr_manifest: Path = OCR_MANIFEST) -> dict:
    """Fail closed before writing a release when the parser closure is incomplete."""
    manifest = json.loads(ocr_manifest.read_text("utf8"))
    if manifest.get("schema") != "deepsteam-document-ocr-dependencies-v1" or not manifest.get("offline_acceptance", {}).get("passed"):
        raise RuntimeError("Pinned OCR wheels have not passed offline acceptance")
    checked = []
    for row in manifest["files"]:
        name = safe_name(row["target"])
        if not name.startswith(SITE):
            raise RuntimeError("OCR runtime file is outside portable site-packages")
        actual = rows.get(name)
        if not actual or any(actual.get(key) != row[key] for key in ("bytes", "sha256")):
            raise RuntimeError("Incomplete or changed packaged OCR file: " + name)
        checked.append(name)
    required_pins = pins()
    metadata = {}
    for name in rows:
        if name.startswith(SITE) and name.endswith(".dist-info/METADATA") and name[len(SITE):].count("/") == 1:
            folder = name[len(SITE):].split("/", 1)[0]
            distribution, version = folder.removesuffix(".dist-info").rsplit("-", 1)
            canonical = distribution.lower().replace("-", "_")
            if canonical in required_pins:
                if canonical in metadata:
                    raise RuntimeError("Conflicting document dependency versions: " + canonical)
                metadata[canonical] = version
    if metadata != required_pins:
        raise RuntimeError("Document dependency versions are missing or different: " + ", ".join(k for k in required_pins if metadata.get(k) != required_pins[k]))
    for name in (READER, "runtime/python/python.exe", "runtime/python/python313._pth",
                 "runtime/harness/documents.mjs", "integration/harness/documents.mjs"):
        if name not in rows:
            raise RuntimeError("Shared reader entry missing: " + name)
    if rows["runtime/harness/documents.mjs"]["sha256"] != rows["integration/harness/documents.mjs"]["sha256"]:
        raise RuntimeError("Shared reader Host/source mirrors differ")
    model_files = [name for name in checked if name.startswith(SITE + "rapidocr/models/") and name.endswith(".onnx")]
    if len(model_files) < 3 or SITE + "rapidocr/config.yaml" not in checked:
        raise RuntimeError("Offline OCR weights/config missing")
    return {"schema": "deepsteam-document-runtime-lock-v1", "python": "CPython 3.13 win_amd64",
            "versions": required_pins, "ocr_files": len(checked),
            "ocr_manifest_sha256": digest(ocr_manifest), "offline_model_files": model_files,
            "reader_sha256": rows[READER]["sha256"],
            "ocr_files_sha256": hashlib.sha256(json.dumps(sorted((name, rows[name]["sha256"]) for name in checked), separators=(",", ":")).encode()).hexdigest(),
            "model_download_on_first_use_required": False}


def diagnostic_files() -> dict[str, Path]:
    return {"scripts/check_document_runtime.py": PROBE,
            "installer/document-runtime-requirements.txt": REQUIREMENTS,
            "installer/document-fixtures/scanned-en.png": ROOT / "installer/document-fixtures/scanned-en.png"}


def selected_for_probe(name: str) -> bool:
    safe_name(name)
    if name in {READER, *diagnostic_files(), "installer/document-runtime-lock.json"}:
        return True
    if not name.startswith("runtime/python/"):
        return False
    if not name.startswith(SITE):
        return len(PurePosixPath(name).parts) == 3
    top = name[len(SITE):].split("/", 1)[0]
    if top in PACKAGE_ROOTS:
        return True
    if top.lower().endswith(".dist-info"):
        distribution = top.removesuffix(".dist-info").rsplit("-", 1)[0].lower().replace("-", "_")
        return distribution in DIST_NAMES
    return False


def verify_archive_runtime(payload: Path, work_parent: Path, report: Path,
                           *, allow_legacy_probe: bool = False) -> dict:
    """Run packaged Python against packaged libraries, in a fresh scoped directory.

    Legacy diagnostics can supply only this self-check and its requirement pins;
    reader/libraries always come from the archive. New releases must contain both.
    """
    work_parent = work_parent.resolve(strict=True)
    if work_parent.drive.upper() != "D:" or not work_parent.is_relative_to(ROOT.resolve()):
        raise RuntimeError("Package runtime test must stay inside the D project")
    if report.exists():
        raise RuntimeError("Preserve prior package runtime acceptance report")
    with zipfile.ZipFile(payload) as archive:
        manifest = json.loads(archive.read(MANIFEST))
        rows = {row["path"]: row for row in manifest["files"]}
        if len(rows) != len(manifest["files"]) or len(set(archive.namelist())) != len(archive.infolist()):
            raise RuntimeError("Duplicate package entry")
        lock = check_rows(rows)
        selected = {name: row for name, row in rows.items() if selected_for_probe(name)}
        required = set(diagnostic_files())
        missing = required - set(selected)
        if missing and not allow_legacy_probe:
            raise RuntimeError("Package is missing the document self-check: " + ", ".join(sorted(missing)))
        expanded = sum(row["bytes"] for row in selected.values())
        if expanded > MAX_EXTRACTED_BYTES:
            raise RuntimeError("Document runtime check exceeds extraction budget")
        with tempfile.TemporaryDirectory(prefix="packaged-document-check-", dir=work_parent) as temp:
            root = Path(temp).resolve()
            root.relative_to(work_parent)
            for name, row in selected.items():
                safe_name(name)
                info = archive.getinfo(name)
                if info.file_size != row["bytes"] or info.file_size > MAX_EXTRACTED_BYTES:
                    raise RuntimeError("Package member length differs: " + name)
                target = root / name
                target.resolve().relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(info)
                if hashlib.sha256(data).hexdigest() != row["sha256"]:
                    raise RuntimeError("Packaged document dependency hash differs: " + name)
                target.write_bytes(data)
            for name in missing:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(diagnostic_files()[name].read_bytes())
            clean_env = {key: value for key, value in os.environ.items()
                         if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"}}
            clean_env["PATH"] = str(root / "runtime/python") + os.pathsep + str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32")
            process = subprocess.run([str(root / "runtime/python/python.exe"), "-I", "-B",
                                      str(root / "scripts/check_document_runtime.py"), "--root", str(root)],
                                     cwd=root, env=clean_env, capture_output=True, text=True, encoding="utf8", timeout=150,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                outcome = json.loads(process.stdout)
            except json.JSONDecodeError:
                raise RuntimeError("Packaged document diagnostic did not return JSON: " + process.stderr[-1000:]) from None
            if process.returncode or not outcome.get("passed"):
                raise RuntimeError("Packaged document runtime failed: " + str(outcome.get("error", process.stderr[-1000:])))
    result = {"schema": "deepsteam-packaged-document-acceptance-v1", "passed": True,
              "payload": str(payload), "payload_sha256": digest(payload),
              "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
              "document_lock": lock, "isolated_extracted_files": len(selected), "temporary_bytes": expanded,
              "temporary_runtime_removed": not root.exists(), "legacy_diagnostic_supplied": bool(missing),
              "diagnostic_source_sha256": digest(PROBE), "actual_runtime": outcome,
              "user_data_read": False, "model_requests": 0, "written_to_e": False}
    with report.open("x", encoding="utf8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    return result
