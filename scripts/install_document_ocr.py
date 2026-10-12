"""Stage pinned official OCR wheels for the portable Python; no live install.

Only creates D-drive developer staging/download/report files. Existing runtime
dependencies are never overwritten. The root deployer consumes the exact
source/target/SHA manifest after offline synthetic acceptance succeeds.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import importlib.metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "runtime/document-ocr-r6.2/site-packages"
DOWNLOADS = ROOT / "downloads/document-ocr-r6.2"
REPORT = ROOT / "reports/workspace-document-ocr-dependencies.json"
PINNED = [
    ("rapidocr", "3.10.0", "rapidocr-3.10.0-py3-none-any.whl"),
    ("onnxruntime", "1.31.0", "onnxruntime-1.31.0-cp313-cp313-win_amd64.whl"),
    ("opencv-python-headless", "5.0.0.93", "opencv_python_headless-5.0.0.93-cp37-abi3-win_amd64.whl"),
    ("pyclipper", "1.4.0", "pyclipper-1.4.0-cp313-cp313-win_amd64.whl"),
    ("Shapely", "2.2.0", "shapely-2.2.0-cp313-cp313-win_amd64.whl"),
    ("omegaconf", "2.4.0", "omegaconf-2.4.0-py3-none-any.whl"),
    ("colorlog", "6.12.0", "colorlog-6.12.0-py3-none-any.whl"),
    ("flatbuffers", "25.12.19", "flatbuffers-25.12.19-py2.py3-none-any.whl"),
    ("protobuf", "7.36.2", "protobuf-7.36.2-cp310-abi3-win_amd64.whl"),
]
MAX_DOWNLOAD = 120 * 1024 * 1024
MAX_EXPANDED = 500 * 1024 * 1024


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    part = PurePosixPath(relative)
    if part.is_absolute() or ".." in part.parts or "\\" in relative or ":" in relative:
        raise ValueError("Unsafe archive path")
    path = root.joinpath(*part.parts)
    path.resolve().relative_to(root.resolve())
    for item in [path, *path.parents]:
        if item.exists() and (item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("Reparse point refused")
    return path


def read_official(url: str, maximum: int) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"pypi.org", "files.pythonhosted.org"}:
        raise ValueError("Only official PyPI files accepted")
    with urllib.request.urlopen(url, timeout=60) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in {"pypi.org", "files.pythonhosted.org"}:
            raise ValueError("Unexpected download redirect")
        content = response.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("Download exceeds declared budget")
    return content


def prepare() -> dict:
    if ROOT.drive.lower() != "d:":
        raise ValueError("This local staging operation requires the D-drive project")
    downloads = []
    for name, version, filename in PINNED:
        metadata_url = f"https://pypi.org/pypi/{name}/{version}/json"
        meta = json.loads(read_official(metadata_url, 2 * 1024 * 1024))
        entry = next(row for row in meta["urls"] if row["filename"] == filename)
        if entry.get("yanked"):
            raise ValueError("Refusing yanked wheel")
        downloads.append({"name": name, "version": version, "filename": filename, "url": entry["url"], "bytes": entry["size"], "sha256": entry["digests"]["sha256"], "requires_python": meta["info"]["requires_python"], "requires_dist": meta["info"]["requires_dist"], "metadata_url": metadata_url})
    download_bytes = sum(item["bytes"] for item in downloads)
    if download_bytes > MAX_DOWNLOAD:
        raise ValueError("OCR download plan is larger than the approved small package budget")
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    STAGE.mkdir(parents=True, exist_ok=True)
    files = {}
    expanded = 0
    for item in downloads:
        wheel = safe_path(DOWNLOADS, item["filename"])
        if wheel.exists():
            data = wheel.read_bytes()
        else:
            data = read_official(item["url"], item["bytes"])
            if len(data) != item["bytes"] or sha(data) != item["sha256"]:
                raise ValueError("Official wheel integrity check failed")
            wheel.write_bytes(data)
        if len(data) != item["bytes"] or sha(data) != item["sha256"]:
            raise ValueError("Existing wheel integrity check failed")
        with zipfile.ZipFile(wheel) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if ".data/" in info.filename:
                    # These pinned wheels currently contain direct packages,
                    # not relocatable installation-scheme files.
                    raise ValueError("Wheel install scheme requires review")
                destination = safe_path(STAGE, info.filename)
                expanded += info.file_size
                if expanded > MAX_EXPANDED:
                    raise ValueError("OCR expanded package budget exceeded")
                content = archive.read(info)
                digest = sha(content)
                if destination.exists():
                    if sha(destination.read_bytes()) != digest:
                        raise ValueError("Staged file differs; refusing to overwrite")
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                target = "runtime/python/Lib/site-packages/" + info.filename
                files[target] = {"source": str(destination), "target": target, "bytes": len(content), "sha256": digest}
        print(f"verified {item['name']}=={item['version']}", flush=True)
    # All copied metadata and bundled licenses are retained with their wheels.
    report = {"schema": "deepsteam-document-ocr-dependencies-v1", "status": "staged-not-deployed", "python": "CPython 3.13 win_amd64", "stage": str(STAGE), "download_bytes": download_bytes, "expanded_bytes": sum(item["bytes"] for item in files.values()), "wheels": downloads, "files": sorted(files.values(), key=lambda x: x["target"]), "preserves_existing_dependencies": ["numpy", "six", "PyYAML", "Pillow", "tqdm", "requests", "packaging", "colorama"], "offline_acceptance": "pending"}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report": str(REPORT), "manifest_sha256": sha(REPORT.read_bytes()), "download_bytes": download_bytes, "expanded_bytes": report["expanded_bytes"], "files": len(files)}


def verify() -> dict:
    if sys.version_info[:2] != (3, 13) or not sys.flags.isolated:
        raise ValueError("Verify with the portable CPython 3.13 in isolated mode")
    manifest = json.loads(REPORT.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        source = Path(item["source"])
        source.resolve().relative_to(STAGE.resolve())
        if source.stat().st_size != item["bytes"] or sha(source.read_bytes()) != item["sha256"]:
            raise ValueError("Staged OCR dependency changed")
    sys.path.insert(0, str(STAGE))
    from packaging.requirements import Requirement
    from packaging.version import Version
    dependency_checks = []
    for package in manifest["wheels"]:
        for raw in package.get("requires_dist") or []:
            requirement = Requirement(raw)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            actual = importlib.metadata.version(requirement.name)
            if Version(actual) not in requirement.specifier:
                raise ValueError(f"Unsatisfied dependency {requirement.name}")
            dependency_checks.append({"name": requirement.name, "version": actual})
    spec = importlib.util.spec_from_file_location("workspace_document_reader", ROOT / "scripts/workspace_document_reader.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from PIL import Image, ImageDraw, ImageFont
    import pymupdf
    from rapidocr.utils.download_file import DownloadFile
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
    if not font_path.is_file():
        raise ValueError("Synthetic scan acceptance requires the system UI font")
    font = ImageFont.truetype(str(font_path), 46)
    results = []
    network_calls = []

    def no_network(*args, **kwargs):
        network_calls.append(True)
        raise RuntimeError("Synthetic OCR acceptance blocks network")

    with tempfile.TemporaryDirectory(prefix="ocr-offline-fixture-", dir=STAGE.parent) as temp:
        folder = Path(temp)
        samples = [("science", "Cell biology mitochondria provide energy", ["Cell biology", "mitochondria"]), ("general", "Local document reading works", ["Local", "reading"]), ("blank", "", [])]
        for label, sample, terms in samples:
            image = Image.new("RGB", (1200, 400), "white")
            ImageDraw.Draw(image).text((60, 100), sample, font=font, fill="black")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            pdf = pymupdf.open()
            page = pdf.new_page(width=1200, height=400)
            page.insert_image(page.rect, stream=buffer.getvalue())
            filename = label + ".pdf"
            pdf.save(folder / filename)
            pdf.close()
            start = time.perf_counter()
            with mock.patch("socket.socket.connect", side_effect=no_network), mock.patch("socket.socket.connect_ex", side_effect=no_network), mock.patch("socket.getaddrinfo", side_effect=no_network), mock.patch("urllib.request.urlopen", side_effect=no_network), mock.patch.object(DownloadFile, "run", side_effect=no_network):
                response = module.handle_request({"root": temp, "path": filename, "ocr": "auto", "max_units": 1})
            elapsed = time.perf_counter() - start
            if not response.get("ok"):
                raise AssertionError(f"{label}: reader failed: {response}")
            if sample:
                passed = response["units"][0]["extraction"] == "ocr" and all(term in response["text"] for term in terms)
            else:
                passed = not response["text"].strip() and response["status"] in {"needs_ocr", "empty"}
            if not passed:
                raise AssertionError(f"{label}: synthetic OCR acceptance failed: {response}")
            results.append({"sample": label, "passed": passed, "status": response["status"], "extraction": response["units"][0]["extraction"], "elapsed_seconds": round(elapsed, 3), "recognized_characters": len(response["text"]), "expected_terms_found": terms if sample else []})
    if network_calls:
        raise AssertionError("OCR attempted network access")
    dependency_plan_hash = sha(json.dumps({"wheels": manifest["wheels"], "files": manifest["files"]}, sort_keys=True, separators=(",", ":")).encode())
    acceptance = {"kind": "deepsteam-document-ocr-offline-acceptance", "passed": True, "fixtures_only": True, "python_isolated": True, "python_version": sys.version.split()[0], "dependency_plan_sha256": dependency_plan_hash, "reader_sha256": sha((ROOT / "scripts/workspace_document_reader.py").read_bytes()), "network_attempts": 0, "results": results, "requirements_satisfied": dependency_checks, "deployed": False}
    path = ROOT / "reports/workspace-document-ocr-acceptance.json"
    path.write_text(json.dumps(acceptance, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["offline_acceptance"] = {"passed": True, "report": str(path), "sha256": sha(path.read_bytes()), "dependency_plan_sha256": dependency_plan_hash}
    REPORT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    source = ROOT / "scripts/workspace_document_reader.py"
    source_receipt = {"schema": "deepsteam-workspace-document-reader-files-v1", "source_files": [{"source": str(source), "target": "scripts/workspace_document_reader.py", "bytes": source.stat().st_size, "sha256": sha(source.read_bytes())}], "dependency_manifest": str(REPORT), "dependency_manifest_sha256": sha(REPORT.read_bytes()), "offline_acceptance": manifest["offline_acceptance"]}
    source_receipt_path = ROOT / "reports/workspace-documents-reader-files.json"
    source_receipt_path.write_text(json.dumps(source_receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report": str(path), "sha256": sha(path.read_bytes()), "dependency_manifest_sha256": sha(REPORT.read_bytes()), "source_receipt": str(source_receipt_path), "results": results, "network_attempts": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "verify"])
    arguments = parser.parse_args()
    print(json.dumps(prepare() if arguments.command == "prepare" else verify(), ensure_ascii=False))
