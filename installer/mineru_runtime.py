"""Build the isolated, relocatable MinerU 4.0.12 offline document-tool runtime.

DeepSteam integration, 2026-10-12. Does not modify the shared Python or providers.
Network is used only by explicit build commands; the production worker is offline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime/mineru"
MODELS = ROOT / "models/mineru"
DOWNLOADS = ROOT / "downloads/mineru-build"
REPORTS = ROOT / "reports"
VERSION = "4.0.12"
COMMIT = "b7f3dd0c5f6e6d66a298239ffd02b328b873918e"
PYTHON_URL = "https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip"
PYTHON_SHA = "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"
ONNX_REPO = "opendatalab/MinerU-4_models_onnx"
ONNX_REVISION = "358310b4f64b95f9fefc372ad899356e4111f376"
GGUF_REPO = "jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF"
GGUF_REVISION = "9185688a0495e1577d521a757c7c0b62dd38ca48"
LLAMA_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b11541/llama-b11541-bin-win-cpu-x64.zip"
LLAMA_SHA = "cdc0535d11038bb337dfba3c15682050eaa9c07aedd0f915b4c09e8a8e8c0a5c"
GGUF_FILES = {
    "MinerU2.5-Pro-2605-1.2B-Q8_0.gguf": (531066496, "3f3523429c880d675c0330cb3de78240452bc40a961d037e24f91ab8488f03e7"),
    "mmproj-MinerU2.5-Pro-2605-1.2B-Q8_0.gguf": (709409600, "b6c08ab50352677f7396af45ee60682f353f55488e26911d8154bfc37514d3f8"),
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def confined(base: Path, relative: str) -> Path:
    p = PurePosixPath(relative)
    if p.is_absolute() or ".." in p.parts or "\\" in relative or ":" in relative:
        raise ValueError("Unsafe relative path")
    target = base.joinpath(*p.parts)
    target.resolve().relative_to(base.resolve())
    for ancestor in (target, *target.parents):
        if ancestor.exists() and (ancestor.is_symlink() or getattr(ancestor.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("Reparse points are not allowed in the runtime")
        if ancestor == base:
            break
    return target


def download(url: str, target: Path, expected: str, maximum: int = 40_000_000) -> None:
    if target.exists():
        if digest(target) != expected:
            raise ValueError("Existing download does not match: " + target.name)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    count = 0
    hasher = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=90) as response, temporary.open("wb") as stream:
        started = time.monotonic()
        reported = 0
        reader = getattr(response, "read1", response.read)
        while chunk := reader(1024 * 1024):
            count += len(chunk)
            if count > maximum:
                raise ValueError("Download exceeds manifest size")
            hasher.update(chunk)
            stream.write(chunk)
            if count - reported >= 64 * 1024 * 1024:
                print(json.dumps({"event": "download", "file": target.name, "bytes": count}), flush=True)
                reported = count
            if time.monotonic() - started > 180 and count < 1024 * 1024:
                raise TimeoutError("Model download is not making progress")
    if hasher.hexdigest() != expected:
        raise ValueError("Download checksum mismatch")
    temporary.replace(target)


def bootstrap() -> dict:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    archive = DOWNLOADS / "python-3.13.15-embed-amd64.zip"
    download(PYTHON_URL, archive, PYTHON_SHA)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            target = confined(RUNTIME, item.filename)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(item))
    # No external site-packages, user site, project directory or credential paths.
    (RUNTIME / "python313._pth").write_text("python313.zip\n.\nLib/site-packages\nimport site\n", encoding="utf-8")
    (RUNTIME / "Lib/site-packages").mkdir(parents=True, exist_ok=True)
    # Existing explicitly redistributed Microsoft runtime file, not an app profile.
    msvc = ROOT / "installer/runtime-python/msvcp140.dll"
    if msvc.is_file():
        shutil.copy2(msvc, RUNTIME / msvc.name)
    return {"python": "3.13.15", "source": PYTHON_URL, "sha256": PYTHON_SHA}


def pip_command(*args: str) -> None:
    # Build tooling is outside the product; only its target is copied to the release.
    builder = Path(os.environ.get("DEEPSTEAM_BUILD_PYTHON", sys.executable))
    if not builder.exists():
        builder = Path(sys.executable)
    environment = os.environ.copy()
    environment.update({"PIP_CACHE_DIR": str(DOWNLOADS / "pip-cache"), "TEMP": str(DOWNLOADS / "temp"),
                        "TMP": str(DOWNLOADS / "temp"), "PYTHONNOUSERSITE": "1"})
    (DOWNLOADS / "temp").mkdir(parents=True, exist_ok=True)
    subprocess.run([str(builder), "-m", "pip", *args], check=True, env=environment)


def resolve() -> None:
    REPORTS.mkdir(exist_ok=True)
    pip_command("install", "--dry-run", "--ignore-installed", "--only-binary=:all:", "--no-binary=jieba",
                "--report", str(REPORTS / "mineru-resolution.json"), "mineru==" + VERSION)


def write_lock() -> Path:
    resolution = json.loads((REPORTS / "mineru-resolution.json").read_text("utf-8"))
    # Upstream's optional native wrapper has no verified redistribution license.
    # Use the licensed official standalone llama.cpp server through the SDK's
    # documented HTTP client instead. Retain this explicit exception in the lock.
    rows = [row for row in resolution["install"] if row["metadata"]["name"].lower().replace("_", "-") != "mineru-llama-cpp"]
    denied = {"torch", "torchvision", "vllm", "lmdeploy", "tensorflow", "triton"}
    if any(row["metadata"]["name"].lower() in denied for row in rows):
        raise ValueError("Accelerator stacks are not part of this portable base")
    pins = []
    for row in rows:
        entry = row["download_info"]
        url = entry["url"]
        if not url.startswith("https://files.pythonhosted.org/"):
            raise ValueError("Runtime dependency is not an official PyPI wheel")
        sha = entry["archive_info"]["hashes"]["sha256"]
        pins.append(url + " --hash=sha256:" + sha)
    lock = ROOT / "installer/mineru-runtime-lock.txt"
    lock.write_text("# Generated from official PyPI metadata. MinerU " + VERSION + " Windows CPython 3.13.\n" + "\n".join(pins) + "\n", encoding="utf-8")
    metadata = RUNTIME / "runtime.json"
    if metadata.exists():
        record = json.loads(metadata.read_text("utf-8"))
        record.update({"vlm_engine": "official-local-llama-server", "excluded_dependency": "mineru-llama-cpp",
                       "device": "cpu", "tool_only": True, "provider": False})
        metadata.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return lock


def install_resolved() -> None:
    lock = write_lock()
    pip_command("install", "--no-deps", "--require-hashes", "--no-compile", "--no-build-isolation",
                "--target", str(RUNTIME / "Lib/site-packages"), "-r", str(lock))
    (RUNTIME / "runtime.json").write_text(json.dumps({"schema_version": 1, "engine": "mineru", "version": VERSION,
        "commit": COMMIT, "python_version": "3.13.15", "tool_only": True, "provider": False,
        "small_backend": "onnx", "vlm_engine": "official-local-llama-server", "model_root": "../../models/mineru",
        "dependency_resolution_sha256": digest(REPORTS / "mineru-resolution.json")}, indent=2), encoding="utf-8")


def llama_server() -> dict:
    archive = DOWNLOADS / "llama-b11541-bin-win-cpu-x64.zip"
    download(LLAMA_URL, archive, LLAMA_SHA, 19518702)
    destination = RUNTIME / "llama-server"
    rows = []
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            name = PurePosixPath(entry.filename).name
            if entry.is_dir() or not (name.endswith(".dll") or name == "llama-server.exe" or name.startswith("LICENSE")):
                continue
            if len(PurePosixPath(entry.filename).parts) != 1:
                raise ValueError("Unexpected release layout")
            target = confined(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(entry))
            rows.append({"file": name, "bytes": target.stat().st_size, "sha256": digest(target)})
    result = {"release": "b11541", "commit": "f2918cabbffe8abf8e2a90c1c089085fa116c2cf", "source": LLAMA_URL,
              "archive_sha256": LLAMA_SHA, "license": "MIT plus bundled dependency notices", "files": rows,
              "tool_only": True, "provider": False, "device": "cpu"}
    (destination / "runtime-manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    notice_directory = ROOT / "licenses/mineru/llama-server-dependencies"
    # These checked-in notices already record fixed official source URLs/hashes.
    for source in (ROOT / "licenses/llama.cpp-dependencies").rglob("*"):
        if source.is_file():
            target = confined(notice_directory, source.relative_to(ROOT / "licenses/llama.cpp-dependencies").as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return {"files": len(rows), "bytes": sum(row["bytes"] for row in rows)}


def onnx_models() -> dict:
    """Use pinned, hash-checked assets directly; no global HF cache or duplicate blobs."""
    url = f"https://huggingface.co/api/models/{ONNX_REPO}/revision/{ONNX_REVISION}?blobs=true"
    with urllib.request.urlopen(url, timeout=60) as response:
        metadata = json.load(response)
    if metadata["sha"] != ONNX_REVISION:
        raise ValueError("Unexpected ONNX model revision")
    rows = [row for row in metadata["siblings"] if row["rfilename"] != ".gitattributes"]

    def transfer(row: dict) -> dict:
        relative = row["rfilename"]
        target = confined(MODELS / "MinerU-4_models_onnx", relative)
        source = f"https://huggingface.co/{ONNX_REPO}/resolve/{ONNX_REVISION}/{relative}"
        sha = row.get("lfs", {}).get("sha256")
        if sha:
            download(source, target, sha, row["size"])
        else:
            with urllib.request.urlopen(source, timeout=90) as response:
                data = response.read(row["size"] + 1)
            if len(data) != row["size"] or hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != row["blobId"]:
                raise ValueError("Git blob verification failed: " + relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            sha = hashlib.sha256(data).hexdigest()
        print(json.dumps({"event": "model_file_ready", "path": relative, "bytes": row["size"]}), flush=True)
        return {"path": target.relative_to(ROOT).as_posix(), "bytes": row["size"], "sha256": sha,
                "source_url": source, "revision": ONNX_REVISION, "repository": ONNX_REPO}

    with ThreadPoolExecutor(max_workers=3) as pool:
        assets = list(pool.map(transfer, rows))
    result = {"schema": "deepsteam-mineru-model-provenance-v1", "repository": ONNX_REPO,
              "revision": ONNX_REVISION, "files": assets, "bytes": sum(row["bytes"] for row in assets)}
    (REPORTS / "mineru-onnx-models.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {"files": len(assets), "bytes": result["bytes"]}


def gguf_models() -> dict:
    assets = []
    for name, (size, sha) in GGUF_FILES.items():
        target = confined(MODELS / "MinerU2.5-Pro-2605-1.2B-GGUF", name)
        url = f"https://huggingface.co/{GGUF_REPO}/resolve/{GGUF_REVISION}/{name}"
        download(url, target, sha, size)
        assets.append({"path": target.relative_to(ROOT).as_posix(), "bytes": size, "sha256": sha,
                       "source_url": url, "revision": GGUF_REVISION, "repository": GGUF_REPO})
        print(json.dumps({"event": "model_file_ready", "path": name, "bytes": size}), flush=True)
    result = {"schema": "deepsteam-mineru-model-provenance-v1", "repository": GGUF_REPO,
              "revision": GGUF_REVISION, "files": assets, "bytes": sum(row["bytes"] for row in assets),
              "license": "Apache-2.0 embedded in both GGUF files", "conversion_revision": None,
              "base_weight_revision": None, "source_status": "Pinned artifact selected by official MinerU registry; not a locally reproduced conversion"}
    (REPORTS / "mineru-gguf-models.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {"files": len(assets), "bytes": result["bytes"]}


def finalize_models() -> dict:
    """Let the upstream download finalizer verify our pinned local mirror.

    This replaces only the transport with verified, already downloaded bytes;
    completion markers are generated by upstream after its readiness checks.
    """
    os.environ.update({"MINERU_HOME": str(ROOT / "runtime/mineru-build-home"),
                       "MINERU_MODEL_BASE_DIR": str(MODELS), "MINERU_MODEL_SOURCE": "local",
                       "MINERU_MODEL_SMALL_BACKEND": "onnx", "MINERU_MODEL_VLM_ENGINE": "llama-cpp"})
    from mineru.model import download as model_download
    from mineru.model.registry import MINERU_2_5_PRO_2605_1_2B_GGUF, MINERU_4_MODELS_ONNX
    from unittest.mock import patch
    all_files = []
    for name in ("onnx", "gguf"):
        data = json.loads((REPORTS / f"mineru-{name}-models.json").read_text("utf-8"))
        for entry in data["files"]:
            source = confined(ROOT, entry["path"])
            if source.stat().st_size != entry["bytes"] or digest(source) != entry["sha256"]:
                raise ValueError("Pinned model checksum mismatch")
            all_files.append({**entry, "path": source.relative_to(MODELS).as_posix()})

    def checked_local_transport(source: str, repo: object, patterns: object) -> str:
        expected = [item for item in all_files if item["path"].startswith(repo.local_name + "/")]
        if not expected:
            raise ValueError("No pinned local mirror for requested model")
        for item in expected:
            if not (MODELS / item["path"]).is_file():
                raise ValueError("Pinned local mirror incomplete")
        return str(repo.local_dir())

    with patch.object(model_download, "_snapshot_download", checked_local_transport):
        for repo in (MINERU_4_MODELS_ONNX, MINERU_2_5_PRO_2605_1_2B_GGUF):
            model_download.download_model_repo(repo, source="huggingface")
            if not model_download.verify_model_repo(repo).ready:
                raise ValueError("Upstream readiness check failed")
    output = {"schema": "deepsteam-mineru-offline-models-v1", "engine_version": VERSION,
              "tiers": ["flash", "basic", "standard", "advanced"], "files": all_files,
              "conversion_reproduced": False, "source": "Pinned official-registry artifacts with embedded Apache-2.0 model license"}
    (MODELS / "runtime-models.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return {"files": len(all_files), "ready": True}


def licenses() -> dict:
    sources = {
        "MinerU-LICENSE.md": f"https://raw.githubusercontent.com/opendatalab/MinerU/{COMMIT}/LICENSE.md",
        "Apache-2.0.txt": "https://www.apache.org/licenses/LICENSE-2.0.txt",
        "original-vlm-model-card.md": "https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B/raw/08aaea840498d49ce16247b6263196cf02814885/README.md",
        "onnx-model-card.md": f"https://huggingface.co/{ONNX_REPO}/raw/{ONNX_REVISION}/README.md",
        "onnx-upstream-manifest.json": f"https://huggingface.co/{ONNX_REPO}/raw/{ONNX_REVISION}/manifest.json",
        "torch-source-model-card.md": "https://huggingface.co/opendatalab/MinerU-4_models_torch/raw/2b3afb86f4d23fa623f6b2f4b2279ed4ef93a89d/README.md",
        "model-registry.py.txt": f"https://raw.githubusercontent.com/opendatalab/MinerU/{COMMIT}/mineru/model/registry.py",
        "official-llama-server-MIT.txt": "https://raw.githubusercontent.com/ggml-org/llama.cpp/f2918cabbffe8abf8e2a90c1c089085fa116c2cf/LICENSE",
    }
    directory = ROOT / "licenses/mineru"
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, url in sources.items():
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("Unexpected license document size")
        target = confined(directory, name)
        target.write_bytes(data)
        rows.append({"file": name, "source": url, "bytes": len(data), "sha256": digest(target)})
    for name in ("onnx", "gguf"):
        report = REPORTS / f"mineru-{name}-models.json"
        if report.is_file():
            shutil.copy2(report, directory / report.name)
    (directory / "license-sources.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return {"files": len(rows)}


def license_evidence() -> dict:
    """Verify the embedded declaration in the actual full-hash-checked GGUF files."""
    evidence = []
    for name, (size, sha) in GGUF_FILES.items():
        path = MODELS / "MinerU2.5-Pro-2605-1.2B-GGUF" / name
        if path.stat().st_size != size or digest(path) != sha:
            raise ValueError("Model license evidence must refer to checked production bytes")
        with path.open("rb") as stream:
            header = stream.read(65536)
        offset = 0

        def take(fmt):
            nonlocal offset
            result = struct.unpack_from("<" + fmt, header, offset)[0]
            offset += struct.calcsize("<" + fmt)
            return result

        def string():
            nonlocal offset
            length = take("Q")
            if length > len(header) - offset:
                raise ValueError("License is not present in bounded header")
            text = header[offset:offset + length].decode("utf-8")
            offset += length
            return text

        def value(kind):
            formats = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
            if kind == 8:
                return string()
            if kind == 9:
                element, count = take("I"), take("Q")
                if count > 10000:
                    raise ValueError("License not found before large metadata array")
                return [value(element) for _ in range(count)]
            return take(formats[kind])

        if header[:4] != b"GGUF":
            raise ValueError("Expected GGUF file")
        offset = 4
        version, tensors, fields = take("I"), take("Q"), take("Q")
        metadata = {}
        for _ in range(fields):
            key, kind = string(), take("I")
            item = value(kind)
            if key.startswith("general."):
                metadata[key] = item
            if key == "general.license":
                break
        if metadata.get("general.license") != "apache-2.0":
            raise ValueError("Expected embedded Apache-2.0 declaration")
        evidence.append({"file": name, "bytes": size, "sha256": sha, "full_file_sha256_verified": True,
                         "header_bytes_read": len(header), "header_sha256": hashlib.sha256(header).hexdigest(),
                         "gguf_version": version, "metadata_until_license": metadata,
                         "source_url": f"https://huggingface.co/{GGUF_REPO}/resolve/{GGUF_REVISION}/{name}",
                         "conversion_revision_provided": False, "quantization_reproduced": False})
    directory = ROOT / "licenses/mineru"
    (directory / "gguf-embedded-license-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    shutil.copy2(REPORTS / "mineru-gguf-models.json", directory / "mineru-gguf-models.json")
    return {"files": len(evidence), "verified": True}


def manifest() -> dict:
    acceptance_path = REPORTS / "mineru-licensed-offline-acceptance-20261012.json"
    acceptance = json.loads(acceptance_path.read_text("utf-8"))
    if not acceptance.get("passed") or acceptance.get("worker_sha256") != digest(ROOT / "scripts/mineru_document_worker.py"):
        raise ValueError("Final worker has not passed offline acceptance")
    entries = []
    def owned_files(directory):
        directory.resolve(strict=True).relative_to(ROOT.resolve(strict=True))
        for current, names, files in os.walk(directory, followlinks=False):
            base = Path(current)
            for name in [*names, *files]:
                path = base / name
                if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                    raise ValueError("Runtime reparse point refused")
            names[:] = sorted(name for name in names if name not in {"__pycache__", ".locks"} and not name.startswith("mineru_llama_cpp"))
            yield from (base / name for name in sorted(files))

    for directory in (RUNTIME, MODELS, ROOT / "licenses/mineru"):
        if not directory.exists():
            continue
        for path in owned_files(directory):
            if not path.is_file() or "__pycache__" in path.parts or ".locks" in path.parts or path.suffix == ".pyc":
                continue
            if any(part.startswith("mineru_llama_cpp") for part in path.parts):
                continue
            if path.name in {"llama-cpp-engine-source.cpp.txt", "llama-cpp-GCC-COPYING.RUNTIME.txt", "llama-cpp-GCC-COPYING3.txt", "llama.cpp-MIT-LICENSE.txt"}:
                continue
            relative = path.relative_to(ROOT).as_posix()
            if any(part in {".env", "auth.json", "token.json", "logs", "cache", "profile"} for part in path.parts):
                raise ValueError("Private or mutable file is not a runtime asset")
            entries.append({"source": str(path), "target": relative, "bytes": path.stat().st_size, "sha256": digest(path)})
    for relative in ("scripts/mineru_document_worker.py", "installer/mineru-runtime-lock.txt"):
        path = ROOT / relative
        if path.exists():
            entries.append({"source": str(path), "target": relative, "bytes": path.stat().st_size, "sha256": digest(path)})
    result = {"schema": "deepsteam-mineru-runtime-v1", "engine_version": VERSION, "commit": COMMIT,
              "tool_only": True, "redistribution_status": "verified", "files": entries, "bytes": sum(row["bytes"] for row in entries),
              "excluded_components": [{"name": "mineru-llama-cpp", "reason": "No separately verified wrapper license; replaced with official MIT llama.cpp local server."}],
              "acceptance": {"source": str(acceptance_path), "bytes": acceptance_path.stat().st_size,
                             "sha256": digest(acceptance_path)},
              "model_manifest_sha256": digest(MODELS / "runtime-models.json")}
    (REPORTS / "mineru-licensed-runtime-files-20261012.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"files": len(entries), "bytes": result["bytes"]}


def accept() -> dict:
    worker_sha = digest(ROOT / "scripts/mineru_document_worker.py")
    reports = []
    for name in ("licensed-basic-final", "licensed-standard-final"):
        path = REPORTS / ("mineru-offline-acceptance-" + name + ".json")
        report = json.loads(path.read_text("utf-8"))
        if report.get("passed") is not True or report.get("worker_sha256") != worker_sha or report.get("worker_unchanged") is not True:
            raise ValueError("Final runtime acceptance is missing or stale")
        reports.append({"source": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "report": report})
    result = {"schema": "deepsteam-mineru-offline-acceptance-v1", "passed": True,
              "worker_sha256": worker_sha, "engine_version": VERSION, "reports": reports,
              "default_tier": "basic", "gpu_required": False, "synthetic_only": True,
              "private_inputs_used": False, "remote_model_calls": 0,
              "scope": "Exact isolated portable Python, CPU-only local parsing, source identity, Chinese text, equation exponent, table values, assets, source-page pixels; not perfect transcription certification.",
              "limitations": ["Standard added absolute-value delimiters to one synthetic equation; its real output is retained in the report. Basic extracted this example correctly.",
                              "Office embedded image pixels are preserved; native Office text extraction does not certify OCR of all text inside those images.",
                              "No physical network adapter was disabled; local-only model paths and Python outbound socket/DNS guards were active, with zero blocked outbound attempts.",
                              "This CPU test ran on the development PC, not a partner's physical computer."]}
    (REPORTS / "mineru-licensed-offline-acceptance-20261012.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"passed": True, "worker_sha256": worker_sha, "cases": sum(len(row["report"]["results"]) for row in reports)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["bootstrap", "resolve", "lock", "install", "llama-server", "onnx-models", "gguf-models", "finalize-models", "licenses", "license-evidence", "accept", "manifest"])
    args = parser.parse_args()
    result = {"bootstrap": bootstrap, "resolve": resolve, "lock": write_lock, "install": install_resolved, "llama-server": llama_server, "onnx-models": onnx_models, "gguf-models": gguf_models, "finalize-models": finalize_models, "licenses": licenses, "license-evidence": license_evidence, "accept": accept, "manifest": manifest}[args.action]()
    print(json.dumps(result or {"ok": True}, default=str))


if __name__ == "__main__":
    main()
