"""DeepSteam's offline MinerU document tool, not a language-model provider.

One JSON request on stdin, one JSON result on stdout; diagnostics use stderr.
Owns only the supplied task output directory. Never edits the source document.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import importlib
import ipaddress
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import socket
import secrets
import subprocess
import sys
import time
import urllib.request
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENGINE_VERSION = "4.0.12"
MODEL_ROOT = ROOT / "models/mineru"
# The only VLM this worker runs: the open-source MinerU2.5-Pro model as GGUF,
# served by the official llama.cpp server on this computer (loopback only).
VLM_MODEL_NAME = "MinerU2.5-Pro-2605-1.2B"
VLM_MODEL_DIR = MODEL_ROOT / "MinerU2.5-Pro-2605-1.2B-GGUF"
VLM_WEIGHTS = VLM_MODEL_DIR / "MinerU2.5-Pro-2605-1.2B-Q8_0.gguf"
VLM_PROJECTOR = VLM_MODEL_DIR / "mmproj-MinerU2.5-Pro-2605-1.2B-Q8_0.gguf"
LLAMA_SERVER = ROOT / "runtime/mineru/llama-server/llama-server.exe"
LLAMA_RELEASE = "b11541"
VLM_ALIAS = "mineru-document-tool"
SMALL_MODEL_DIR = MODEL_ROOT / "MinerU-4_models_onnx"
# MinerU 4.0.12 tier -> analysis effort (parser/tier.py). Only standard/high and
# advanced/xhigh run the VLM; advanced also enables VLM image analysis.
TIER_EFFORT = {"flash": "flash", "basic": "medium", "standard": "high", "advanced": "xhigh"}
VLM_TIERS = {"standard", "advanced"}
DEFAULT_TIER = "advanced"
NATIVE_SUFFIXES = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".rtf", ".odt", ".ods", ".odp", ".epub", ".ofd", ".html", ".htm", ".mhtml", ".mht", ".csv", ".tsv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
NETWORK_ATTEMPTS: list[str] = []


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_asset(root: Path, relative: str) -> Path:
    part = PurePosixPath(relative)
    if not relative or part.is_absolute() or ".." in part.parts or "\\" in relative or ":" in relative:
        raise ValueError("Unsafe artifact path")
    path = root.joinpath(*part.parts)
    path.resolve().relative_to(root.resolve())
    for candidate in (path, *path.parents):
        if candidate.exists() and (candidate.is_symlink() or getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("Reparse artifact path refused")
        if candidate == root:
            break
    return path


def progress(stage: str, **fields: Any) -> None:
    print(json.dumps({"event": "progress", "stage": stage, **fields}, ensure_ascii=False), file=sys.stderr, flush=True)


def disable_network() -> None:
    """Block outbound Python sockets; permit socketpair loopback for asyncio only.

    No HTTP endpoints are configured and the native engine receives local files.
    This guard is not a general-purpose OS sandbox for arbitrary native code.
    """
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_lookup = socket.getaddrinfo

    def local(host: Any) -> bool:
        try:
            return ipaddress.ip_address(str(host)).is_loopback
        except ValueError:
            return host in {"localhost", None}

    def checked(address: Any) -> None:
        if isinstance(address, tuple) and not local(address[0]):
            NETWORK_ATTEMPTS.append("blocked_outbound_connection")
            raise OSError("Offline document parsing does not allow network access")

    def connect(sock: socket.socket, address: Any) -> Any:
        checked(address)
        return original_connect(sock, address)

    def connect_ex(sock: socket.socket, address: Any) -> Any:
        checked(address)
        return original_connect_ex(sock, address)

    def lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not local(host):
            NETWORK_ATTEMPTS.append("blocked_outbound_dns")
            raise OSError("Offline document parsing does not allow DNS access")
        return original_lookup(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = lookup


def configure(output: Path) -> None:
    # Do not inherit API keys, remote MinerU settings or another app's HF profile.
    for key in list(os.environ):
        if key.startswith(("MINERU_", "HF_", "HUGGINGFACE_")) or key in {"OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY"}:
            os.environ.pop(key, None)
    home = output / ".worker"
    home.mkdir(parents=True, exist_ok=True)
    values = {
        "MINERU_HOME": str(home), "MINERU_MODEL_BASE_DIR": str(MODEL_ROOT),
        "MINERU_MODEL_SOURCE": "local", "MINERU_MODEL_SMALL_BACKEND": "onnx",
        "MINERU_MODEL_VLM_ENGINE": "llama-cpp", "MINERU_MODEL_VLM_SERVER_URL": "",
        "MINERU_MODEL_VLM_MAX_CONCURRENCY": "1", "MINERU_LOG_LEVEL": "warning",
        "MINERU_LLM_AIDED_FEATURES_TITLE_LEVELING": "false",
        "MINERU_LLM_AIDED_FEATURES_CROSS_PAGE_TABLE_CELL_MERGE": "false",
        "MINERU_TABLE_DEVICE": "cpu", "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HOME": str(home / "hf"), "TRANSFORMERS_OFFLINE": "1", "DO_NOT_TRACK": "1",
        "GRADIO_ANALYTICS_ENABLED": "false", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "TEMP": str(home), "TMP": str(home), "OMP_NUM_THREADS": str(max(1, min(8, os.cpu_count() or 1))),
        # The dispatcher passes a minimal environment. Libraries that expand
        # "~" get this task's private folder, never the user's real profile.
        "HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "appdata"),
        "LOCALAPPDATA": str(home / "localappdata"), "XDG_CACHE_HOME": str(home / "cache"),
        "MODELSCOPE_CACHE": str(home / "modelscope"), "TORCH_HOME": str(home / "torch"),
        "MPLCONFIGDIR": str(home / "matplotlib"), "NUMBA_CACHE_DIR": str(home / "numba"),
    }
    for key in ("appdata", "localappdata", "cache"):
        (home / key).mkdir(exist_ok=True)
    os.environ.update(values)
    class ExcludedWrapper:
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "mineru_llama_cpp" or fullname.startswith("mineru_llama_cpp."):
                raise ModuleNotFoundError("Excluded native wrapper; use the official local document server")
            return None
    sys.meta_path.insert(0, ExcludedWrapper())
    disable_network()


def windows_child_job(process):
    """Closing the owning worker kills its private native process tree too."""
    import ctypes
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
    class Limits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    limits = Limits()
    limits.BasicLimitInformation.LimitFlags = 0x2000
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
        error = ctypes.get_last_error()
        kernel.CloseHandle(job)
        raise ctypes.WinError(error)
    return lambda: kernel.CloseHandle(job)


@contextlib.contextmanager
def portable_vlm_engine(tier: str, output: Path):
    """Official MIT llama.cpp is a private document subprocess, never a provider."""
    policy = {"device": "cpu", "n_gpu_layers": 0, "n_parallel": 1,
              "n_threads": max(1, min(8, os.cpu_count() or 1)), "context": "model_training_default",
              "engine": "official-llama.cpp-b11541", "transport": "private_loopback_http"}
    if tier not in VLM_TIERS:
        yield {**policy, "vlm": False}
        return
    require_vlm_assets()
    exe = LLAMA_SERVER
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    key = secrets.token_urlsafe(32)
    endpoint = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith("LLAMA_") or name.lower().endswith("_proxy"):
            environment.pop(name, None)
    environment["LLAMA_API_KEY"] = key
    args = [str(exe), "--model", str(VLM_WEIGHTS),
            "--mmproj", str(VLM_PROJECTOR),
            "--host", "127.0.0.1", "--port", str(port), "--alias", VLM_ALIAS,
            "--n-gpu-layers", "0", "--no-mmproj-offload", "--parallel", "1", "--ctx-size", "0",
            "--threads", str(policy["n_threads"]), "--no-webui", "--no-warmup", "--jinja",
            "--special", "--skip-chat-parsing"]
    process = None
    close_job = None
    try:
        with (output / ".worker/native-engine.log").open("wb") as log:
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
            close_job = windows_child_job(process)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Local document engine stopped during startup")
                try:
                    request = urllib.request.Request(endpoint + "/v1/models", headers={"Authorization": "Bearer " + key})
                    with opener.open(request, timeout=1) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(.2)
            else:
                raise TimeoutError("Local document engine startup timed out")
            os.environ.update({"MINERU_MODEL_VLM_SERVER_URL": endpoint,
                               "MINERU_MODEL_VLM_API_KEY": key, "MINERU_MODEL_VLM_MODEL": VLM_ALIAS})
            progress("local_engine", device="cpu", engine=policy["engine"], process_id=process.pid)
            yield {**policy, "vlm": True, "endpoint": endpoint, "api_key": key, "alias": VLM_ALIAS}
    finally:
        os.environ.pop("MINERU_MODEL_VLM_API_KEY", None)
        os.environ.pop("MINERU_MODEL_VLM_SERVER_URL", None)
        if close_job:
            close_job()
        if process and process.poll() is None:
            process.kill()
        if process:
            process.wait(timeout=10)


class VlmUnavailable(RuntimeError):
    """The requested local VLM tier cannot run. Never downgrade silently."""


def installation_relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def missing_vlm_assets() -> list[str]:
    return [installation_relative(path) for path in (LLAMA_SERVER, VLM_WEIGHTS, VLM_PROJECTOR) if not path.is_file()]


def require_vlm_assets() -> None:
    missing = missing_vlm_assets()
    if missing:
        raise VlmUnavailable("The local MinerU VLM is not installed; missing " + ", ".join(missing)
                             + ". Repair the DeepSteam document runtime. No remote parsing service is used.")


def loopback_host(host: Any) -> bool:
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False  # Host names are refused; the worker always uses 127.0.0.1.


def loopback_vlm_config(policy: dict):
    """Validated MinerU VlmConfig that can only address this computer's server."""
    from urllib.parse import urlsplit
    from mineru.config import VlmConfig
    endpoint = policy.get("endpoint", "")
    host = urlsplit(endpoint).hostname
    if not endpoint or not loopback_host(host):
        raise VlmUnavailable("Refusing a non-loopback VLM endpoint; MinerU inference must stay on this computer.")
    return VlmConfig(engine="llama-cpp", server_url=endpoint, api_key=policy["api_key"], model=policy["alias"],
                     max_concurrency=1, http_timeout=1800)


def assert_offline_configuration() -> None:
    """Fail closed if any configuration could route parsing to a remote service."""
    from mineru.config import config
    from urllib.parse import urlsplit
    url = config.model.vlm.server_url
    if url and not loopback_host(urlsplit(url).hostname):
        raise VlmUnavailable("A remote MinerU VLM endpoint is configured; refusing to send documents off this computer.")
    features = config.llm_aided.features
    if features.title_leveling or features.cross_page_table_cell_merge:
        raise VlmUnavailable("Remote LLM-aided post-processing is enabled; it is not allowed for local parsing.")
    if str(config.model.source).lower() != "local":
        raise VlmUnavailable("MinerU model downloads are not allowed; local model files are required.")


def inference_identity(tier: str, requested_tier: str, suffix: str, runtime_policy: dict | None = None) -> dict:
    """What actually ran, recorded in every result for verification."""
    vlm = tier in VLM_TIERS
    identity = {
        "mode": "local", "remote_api": False, "api_key_required": False,
        "engine": f"MinerU {ENGINE_VERSION} (local Python library)",
        "requested_tier": requested_tier, "actual_tier": tier, "effort": TIER_EFFORT.get(tier),
        "vlm_used": vlm, "image_analysis": tier == "advanced",
        "small_models": {"backend": "onnxruntime (CPU)", "path": installation_relative(SMALL_MODEL_DIR)},
    }
    if vlm:
        identity["vlm"] = {"model": VLM_MODEL_NAME, "format": "GGUF Q8_0",
                           "weights": installation_relative(VLM_WEIGHTS),
                           "projector": installation_relative(VLM_PROJECTOR),
                           "backend": f"official llama.cpp llama-server {LLAMA_RELEASE}",
                           "transport": "loopback HTTP (127.0.0.1) with a one-time key",
                           "device": (runtime_policy or {}).get("device", "cpu")}
    elif suffix in NATIVE_SUFFIXES:
        identity["vlm_not_applicable"] = ("MinerU 4.0.12 parses Office, HTML, EPUB and table files natively for every tier; "
                                          "its VLM only analyses PDF pages and images.")
    return identity


def health() -> dict:
    versions = {}
    missing = []
    for name in ("mineru", "docvortex", "onnxruntime", "pypdfium2"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    model_manifest = MODEL_ROOT / "runtime-models.json"
    model_missing = []
    tiers = []
    if model_manifest.exists():
        data = json.loads(model_manifest.read_text("utf-8"))
        for entry in data.get("files", []):
            target = safe_asset(MODEL_ROOT, entry["path"])
            if not target.is_file() or target.stat().st_size != entry["bytes"]:
                model_missing.append(entry["path"])
        tiers = data.get("tiers", []) if not model_missing else []
    else:
        model_missing.append("runtime-models.json")
    if versions.get("mineru") != ENGINE_VERSION:
        missing.append("mineru_version_mismatch")
    for module in ("docvortex", "onnxruntime", "pypdfium2"):
        try:
            importlib.import_module(module)
        except (ImportError, OSError):
            missing.append(module + "_import_failed")
    native = ROOT / "runtime/mineru/llama-server/runtime-manifest.json"
    if not native.is_file():
        missing.append("official_llama_server")
    else:
        for entry in json.loads(native.read_text("utf-8"))["files"]:
            path = safe_asset(native.parent, entry["file"])
            if not path.is_file() or path.stat().st_size != entry["bytes"]:
                missing.append("official_llama_server_asset")
    vlm_missing = missing_vlm_assets()
    ready = not missing and not model_missing
    return {"ok": ready, "engine": "mineru", "engine_version": ENGINE_VERSION,
            "tool_only": True, "provider": False, "offline": True, "remote_api": False, "versions": versions,
            "missing_dependencies": missing, "missing_models": model_missing,
            "available_tiers": tiers, "default_tier": DEFAULT_TIER,
            "vlm_ready": ready and not vlm_missing, "vlm_missing": vlm_missing,
            "inference": inference_identity(DEFAULT_TIER, DEFAULT_TIER, ".pdf"),
            "python": sys.version.split()[0]}


def verify_vlm() -> dict:
    """Start the private llama.cpp server and read back the model it loaded.

    Proves the local weights load in the local backend; no document inference.
    """
    import shutil
    output = Path(os.environ.get("TEMP") or ROOT / "runtime") / ("mineru-verify-" + secrets.token_hex(6))
    output.mkdir(parents=True, exist_ok=False)
    try:
        return _verify_vlm(output)
    finally:
        shutil.rmtree(output, ignore_errors=True)  # Only this probe's own folder.


def _verify_vlm(output: Path) -> dict:
    configure(output)
    with portable_vlm_engine(DEFAULT_TIER, output) as policy:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        headers = {"Authorization": "Bearer " + policy["api_key"]}
        with opener.open(urllib.request.Request(policy["endpoint"] + "/v1/models", headers=headers), timeout=10) as response:
            models = json.loads(response.read().decode("utf-8"))
        try:
            with opener.open(urllib.request.Request(policy["endpoint"] + "/props", headers=headers), timeout=10) as response:
                props = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError):
            props = {}
        loaded = str(props.get("model_path") or "")
        config = loopback_vlm_config(policy)
    return {"ok": True, "verified": "local_vlm_server_loaded_model", "served_models": [row.get("id") for row in models.get("data", [])],
            "loaded_weights": Path(loaded).name if loaded else None,
            "expected_weights": VLM_WEIGHTS.name, "weights_match": (Path(loaded).name == VLM_WEIGHTS.name) if loaded else None,
            "vlm_config": {"engine": config.engine, "server": "loopback", "model": config.model},
            "inference": inference_identity(DEFAULT_TIER, DEFAULT_TIER, ".pdf", policy),
            "blocked_network_attempts": len(NETWORK_ATTEMPTS), "document_inference_requests": 0}


def strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in {"image_base64", "base64", "id"}:
                yield from strings(item)


def asset_references(value: Any) -> list[str]:
    found = set()
    for text in strings(value):
        found.update(re.findall(r"images/[A-Za-z0-9_./%+-]+", text))
    return sorted(found)


def normalize(structured: dict, output: Path, suffix: str, tier: str) -> dict:
    pages = structured.get("pages", [])
    units = []
    assets = {}
    warnings = []
    for ordinal, page in enumerate(pages):
        page_idx = page.get("page_idx", ordinal)
        if not isinstance(page_idx, int) or page_idx < 0:
            raise ValueError("Invalid source page index")
        kind = "pdf_page" if suffix == ".pdf" else "slide" if suffix in {".ppt", ".pptx", ".odp"} else "image" if suffix in IMAGE_SUFFIXES else "document_section"
        locator = {"kind": kind, "page": page_idx + 1, "page_idx": page_idx}
        if kind == "document_section":
            locator["page_number_semantics"] = "logical_section_not_printed_page"
        visual = []
        for relative in asset_references(page):
            path = safe_asset(output, relative)
            if not path.is_file():
                warnings.append({"code": "missing_asset", "path": relative, "locator": locator})
                continue
            item = {"id": hashlib.sha256(relative.encode()).hexdigest()[:20], "relative_path": relative,
                    "mime_type": mimetypes.guess_type(relative)[0] or "application/octet-stream",
                    "locator": locator, "bytes": path.stat().st_size, "sha256": digest(path)}
            assets[relative] = item
            visual.append(item)
        texts = []
        equations = []
        tables = []
        for block in page.get("blocks", []):
            block_type = block.get("type", "unknown")
            content = block.get("content", "")
            if isinstance(content, str) and content:
                texts.append(content)
            elif isinstance(content, list):
                texts.extend(v for v in strings(content) if not v.startswith(("images/", "data:")))
            # Captions/footnotes are part of the source, not decoration.
            for field in ("captions", "footnotes"):
                for item in block.get(field, []):
                    if isinstance(item, dict) and isinstance(item.get("content"), str):
                        texts.append(item["content"])
            if "equation" in block_type or "formula" in block_type:
                equations.append(block)
            if "table" in block_type:
                tables.append(block)
                for key in ("html", "table_body", "body"):
                    if isinstance(block.get(key), str):
                        texts.append(block[key])
            if ("table" in block_type or "equation" in block_type or "formula" in block_type) and not any(
                isinstance(block.get(key), str) and block[key].strip() for key in ("content", "html", "table_body", "body")
            ):
                warnings.append({"code": "recognized_region_without_text", "type": block_type,
                                 "locator": locator, "bbox": block.get("bbox"),
                                 "message": "Region pixels are preserved but transcription is missing; review the source image."})
        text = "\n\n".join(texts).strip()
        # Empty/visual-only pages remain explicit, never silently omitted.
        units.append({"index": ordinal, "locator": locator, "text": text, "assets": visual,
                      "equations": equations, "tables": tables, "blocks": page.get("blocks", []),
                      "coverage": {"status": "processed" if text or visual else "empty_or_unrecognized",
                                   "text_extracted": bool(text), "assets_retained": len(visual),
                                   "requires_visual_review": tier != "flash" or bool(equations)}})
    full = structured.get("is_full_document") is True
    if not full:
        warnings.append({"code": "partial_document", "message": "Parser did not certify all source pages were processed"})
    return {"units": units, "assets": list(assets.values()), "warnings": warnings,
            "coverage": {"processed_units": len(units), "full_document": full,
                         "text_units": sum(bool(u["text"]) for u in units),
                         "asset_count": len(assets), "formula_count": sum(len(u["equations"]) for u in units),
                         "table_count": sum(len(u["tables"]) for u in units),
                         "accuracy_verified": False, "requires_visual_review": True}}


def add_page_previews(source: Path, output: Path, normalized: dict) -> None:
    """Retain complete source-page pixels even when layout detection misses a figure."""
    if source.suffix.lower() != ".pdf":
        return
    import pypdfium2
    with pypdfium2.PdfDocument(source) as pdf:
        normalized["coverage"]["source_pages"] = len(pdf)
        seen = {unit["locator"]["page_idx"] for unit in normalized["units"]}
        if seen != set(range(len(pdf))):
            normalized["coverage"]["full_document"] = False
            normalized["warnings"].append({"code": "missing_source_pages", "pages": sorted(set(range(len(pdf))) - seen)})
        for unit in normalized["units"]:
            index = unit["locator"]["page_idx"]
            page = pdf[index]
            try:
                # Minimum 150dpi; source remains authoritative for further zoom/crop.
                bitmap = page.render(scale=150 / 72)
                try:
                    image = bitmap.to_pil()
                    relative = f"images/source-page-{index + 1}.png"
                    target = safe_asset(output, relative)
                    target.parent.mkdir(exist_ok=True)
                    image.save(target)
                    dimensions = list(image.size)
                    image.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
            asset = {"id": "source-page-" + str(index + 1), "relative_path": relative,
                     "mime_type": "image/png", "locator": unit["locator"], "role": "source_page_preview",
                     "bytes": target.stat().st_size, "sha256": digest(target), "dimensions": dimensions}
            unit["assets"].append(asset)
            normalized["assets"].append(asset)
        normalized["coverage"]["source_page_previews"] = len(normalized["units"])
        normalized["coverage"]["asset_count"] = len(normalized["assets"])


def run(request: dict) -> dict:
    if request.get("schema_version") != 1 or request.get("action") != "parse":
        raise ValueError("Expected schema_version=1 and action=parse")
    source = Path(request["source_path"])
    output = Path(request["output_dir"])
    if not source.is_absolute() or not output.is_absolute():
        raise ValueError("Absolute source and output paths required")
    source = source.resolve(strict=True)
    if not source.is_file() or output.resolve() in source.parents or source == output.resolve():
        raise ValueError("Output must be a separate job directory")
    output.mkdir(parents=True, exist_ok=True)
    safe_asset(output, ".worker-owner.json")
    owner_path = output / ".worker-owner.json"
    owner = {"request_id": str(request.get("request_id", "")), "source_sha256": str(request.get("source_sha256", ""))}
    if not owner["request_id"] or not re.fullmatch(r"[a-fA-F0-9]{64}", owner["source_sha256"]):
        raise ValueError("A request id and source SHA-256 are required")
    if owner_path.exists():
        if json.loads(owner_path.read_text("utf-8")) != owner:
            raise ValueError("Output directory belongs to another task")
    elif any(output.iterdir()):
        raise ValueError("Output directory must be empty")
    owner_path.write_text(json.dumps(owner), encoding="utf-8")
    actual_hash = digest(source)
    if actual_hash.lower() != owner["source_sha256"].lower():
        raise ValueError("source_changed")
    options = request.get("engine_options") or {}
    requested_tier = options.get("tier", DEFAULT_TIER)
    if requested_tier not in TIER_EFFORT:
        raise ValueError("Unknown parsing tier")
    suffix = source.suffix.lower()
    # Office/HTML/EPUB/CSV take MinerU's native path for every tier (the VLM is
    # not applicable there); this is recorded in the result, not hidden.
    tier = "flash" if suffix in NATIVE_SUFFIXES else requested_tier
    if suffix not in NATIVE_SUFFIXES | IMAGE_SUFFIXES | {".pdf"}:
        raise ValueError("Unsupported document format")
    if tier in VLM_TIERS:
        require_vlm_assets()
    configure(output)
    started = time.monotonic()
    progress("loading", tier=tier)
    from mineru.parser.writer import DataWriter

    class ConfinedWriter(DataWriter):
        def write(self, path: str, data: bytes) -> None:
            target = safe_asset(output, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    assert_offline_configuration()
    progress("parsing", tier=tier, effort=TIER_EFFORT[tier], vlm=tier in VLM_TIERS)
    with portable_vlm_engine(tier, output) as runtime_policy:
        from mineru.parser import parse
        vlm_config = loopback_vlm_config(runtime_policy) if runtime_policy.get("vlm") else None
        # Only the local library entry point is used; MinerU's hosted-API
        # client (MinerUApiParser) is never constructed here.
        result = parse(source, tier=tier, ocr_mode="auto", image_analysis=tier == "advanced", vlm_config=vlm_config)
        runtime_policy = {key: value for key, value in runtime_policy.items() if key not in {"api_key", "endpoint"}}
    progress("saving")
    result.save(ConfinedWriter())
    structured = json.loads((output / "structured_content.json").read_text("utf-8"))
    normalized = normalize(structured, output, suffix, tier)
    add_page_previews(source, output, normalized)
    if digest(source) != actual_hash:
        raise ValueError("source_changed_during_parse")
    normalized.update({"schema_version": 1, "ok": True, "status": "partial" if normalized["warnings"] else "ready",
                       "engine": "mineru", "engine_version": ENGINE_VERSION, "requested_tier": requested_tier,
                       "actual_tier": tier, "source_sha256": actual_hash, "request_id": owner["request_id"],
                       "markdown_path": "markdown.md", "content_list_path": "structured_content.json",
                       "middle_json_path": "middle_json.json", "artifact_dir": str(output), "asset_dir": "images",
                       "offline": True, "blocked_network_attempts": len(NETWORK_ATTEMPTS),
                       "runtime_policy": runtime_policy,
                       "inference": inference_identity(tier, requested_tier, suffix, runtime_policy),
                       "elapsed_seconds": round(time.monotonic() - started, 3)})
    (output / "result.json").write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    progress("completed", status=normalized["status"], units=len(normalized["units"]))
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--verify-vlm", action="store_true", help="load the local VLM in llama-server and report it; no document inference")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    output_stream = sys.stdout
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = health() if args.health else verify_vlm() if args.verify_vlm else run(json.load(sys.stdin))
    except Exception as exc:
        # Source content and keys are never copied into error messages by this wrapper.
        message = str(exc)
        code = "source_changed" if message.startswith("source_changed") else "parse_failed"
        if isinstance(exc, VlmUnavailable):
            code = "vlm_unavailable"
        elif isinstance(exc, (ModuleNotFoundError, importlib.metadata.PackageNotFoundError)):
            code = "parser_not_configured"
        elif isinstance(exc, FileNotFoundError):
            code = "parser_asset_missing"
        result = {"schema_version": 1, "ok": False, "status": "error", "engine": "mineru",
                  "engine_version": ENGINE_VERSION, "error": {"code": code, "message": message[:1200]},
                  "offline": True, "blocked_network_attempts": len(NETWORK_ATTEMPTS)}
    encoded = json.dumps(result, ensure_ascii=False)
    if not args.health and result.get("ok") and len(encoded.encode("utf-8")) > 4 * 1024 * 1024:
        summary = {key: result[key] for key in ("schema_version", "ok", "status", "engine", "engine_version", "source_sha256", "coverage", "offline", "blocked_network_attempts", "inference") if key in result}
        summary.update({"result_path": "result.json", "warnings": result.get("warnings", [])[:100], "units_inline": False})
        encoded = json.dumps(summary, ensure_ascii=False)
    print(encoded, file=output_stream, flush=True)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
