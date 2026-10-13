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
LLAMA_SERVER = ROOT / "runtime/mineru/llama-server" / ("llama-server.exe" if os.name == "nt" else "llama-server")
LLAMA_RELEASE = "b11541"
VLM_ALIAS = "mineru-document-tool"
SMALL_MODEL_DIR = MODEL_ROOT / "MinerU-4_models_onnx"
# MinerU 4.0.12 tier -> analysis effort (parser/tier.py). Only standard/high and
# advanced/xhigh run the VLM; advanced also enables VLM image analysis.
TIER_EFFORT = {"flash": "flash", "basic": "medium", "standard": "high", "advanced": "xhigh"}
VLM_TIERS = {"standard", "advanced"}
# Default: basic first (small local ONNX models, no VLM); only pages whose basic
# layout shows tables or display formulas are parsed again with the standard
# local VLM tier. Figures are flagged for an explicit advanced read.
ADAPTIVE = "adaptive"
DEFAULT_TIER = ADAPTIVE
COMPLEX_LAYOUT = {"table", "equation", "interline_equation"}
FIGURE_BLOCKS = {"image", "chart", "figure"}
NATIVE_SUFFIXES = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".rtf", ".odt", ".ods", ".odp", ".epub", ".ofd", ".html", ".htm", ".mhtml", ".mht", ".csv", ".tsv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
NETWORK_ATTEMPTS: list[str] = []
# Set once per process by configure_home(); a --serve process configures its
# private home a single time and then parses many documents.
CONFIGURED_HOME: Path | None = None
CURRENT_REQUEST = ""
# Decoding slots requested by the dispatcher (--vlm-parallel); None = default.
VLM_PARALLEL: int | None = None


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
    event = {"event": "progress", "stage": stage, **fields}
    if CURRENT_REQUEST:
        event["request_id"] = CURRENT_REQUEST
    print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)


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
    configure_home(output / ".worker")


def configure_home(home: Path) -> None:
    """Private, offline environment for this process (applied once)."""
    global CONFIGURED_HOME
    if CONFIGURED_HOME is not None:
        return
    # Do not inherit API keys, remote MinerU settings or another app's HF profile.
    for key in list(os.environ):
        if key.startswith(("MINERU_", "HF_", "HUGGINGFACE_")) or key in {"OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY"}:
            os.environ.pop(key, None)
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
    CONFIGURED_HOME = home


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


def vlm_parallel() -> int:
    """Decoding slots for the private VLM server.

    llama.cpp batches the token generation of concurrent requests, which on a
    CPU (bound by memory bandwidth) yields more pages per minute than serving
    MinerU's requests one by one. Machines with fewer cores keep one slot; a
    local benchmark can record a different value for this computer.
    """
    configured = VLM_PARALLEL if VLM_PARALLEL is not None else (2 if (os.cpu_count() or 1) >= 8 else 1)
    return max(1, min(4, int(configured)))


def set_vlm_parallel(value: Any) -> None:
    global VLM_PARALLEL
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
        raise ValueError("vlm_parallel must be an integer from 1 to 4")
    VLM_PARALLEL = value


def server_args(port: int, slots: int, threads: int) -> list[str]:
    args = [str(LLAMA_SERVER), "--model", str(VLM_WEIGHTS),
            "--mmproj", str(VLM_PROJECTOR),
            "--host", "127.0.0.1", "--port", str(port), "--alias", VLM_ALIAS,
            "--n-gpu-layers", "0", "--no-mmproj-offload", "--parallel", str(slots), "--ctx-size", "0",
            "--threads", str(threads), "--no-webui", "--no-warmup", "--jinja",
            "--special", "--skip-chat-parsing", "--metrics"]
    if slots > 1:
        # One KV buffer shared by all slots, so batching never shrinks the
        # context available to a single page request.
        args.append("--kv-unified")
    return args


class EngineStartupFailed(RuntimeError):
    """llama-server exited before it was ready."""


@contextlib.contextmanager
def portable_vlm_engine(tier: str, home: Path):
    """Official MIT llama.cpp is a private document subprocess, never a provider."""
    slots = vlm_parallel()
    policy = {"device": "cpu", "n_gpu_layers": 0, "n_parallel": slots,
              "n_threads": max(1, min(8, os.cpu_count() or 1)), "context": "model_training_default",
              "engine": "official-llama.cpp-b11541", "transport": "private_loopback_http"}
    if tier not in VLM_TIERS:
        yield {**policy, "vlm": False, "n_parallel": 0}
        return
    require_vlm_assets()
    key = secrets.token_urlsafe(32)
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith("LLAMA_") or name.lower().endswith("_proxy"):
            environment.pop(name, None)
    environment["LLAMA_API_KEY"] = key
    process = None
    close_job = None
    try:
        with (home / "native-engine.log").open("wb") as log:
            # Parallel decoding slots are a scheduling choice, not a quality
            # tier: if this llama-server build refuses them, one slot runs the
            # same model and tier.
            for attempt in ([slots, 1] if slots > 1 else [1]):
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", 0))
                    port = probe.getsockname()[1]
                endpoint = f"http://127.0.0.1:{port}"
                process = subprocess.Popen(server_args(port, attempt, policy["n_threads"]), stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=log, env=environment,
                                           **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
                close_job = windows_child_job(process) if os.name == "nt" else None
                try:
                    wait_until_ready(process, endpoint, key)
                    break
                except EngineStartupFailed:
                    if close_job:
                        close_job()
                        close_job = None
                    process.wait(timeout=10)
                    process = None
                    if attempt == 1:
                        raise
                    policy["parallel_fallback"] = f"llama-server did not start with {attempt} slots; using 1"
            policy["n_parallel"] = attempt
            os.environ.update({"MINERU_MODEL_VLM_SERVER_URL": endpoint,
                               "MINERU_MODEL_VLM_API_KEY": key, "MINERU_MODEL_VLM_MODEL": VLM_ALIAS})
            progress("local_engine", device="cpu", engine=policy["engine"], process_id=process.pid, n_parallel=attempt)
            yield {**policy, "vlm": True, "endpoint": endpoint, "api_key": key, "alias": VLM_ALIAS, "_process": process}
    finally:
        os.environ.pop("MINERU_MODEL_VLM_API_KEY", None)
        os.environ.pop("MINERU_MODEL_VLM_SERVER_URL", None)
        if close_job:
            close_job()
        if process and process.poll() is None:
            process.kill()
        if process:
            process.wait(timeout=10)


def wait_until_ready(process: subprocess.Popen, endpoint: str, key: str) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise EngineStartupFailed("Local document engine stopped during startup")
        try:
            request = urllib.request.Request(endpoint + "/v1/models", headers={"Authorization": "Bearer " + key})
            with opener.open(request, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(.2)
    raise TimeoutError("Local document engine startup timed out")


class VlmUnavailable(RuntimeError):
    """The requested local VLM tier cannot run. Never downgrade silently."""


class SharedVlmEngine:
    """One private llama.cpp server kept loaded across parses (--serve mode).

    Loading the 1.2B model takes far longer than a single page batch, so a
    serving worker starts it once and reuses it. It is restarted if it exits.
    """

    def __init__(self, home: Path):
        self.home = home
        self.stack: contextlib.ExitStack | None = None
        self.policy: dict | None = None

    @contextlib.contextmanager
    def lease(self, tier: str):
        if tier not in VLM_TIERS:
            with portable_vlm_engine(tier, self.home) as policy:
                yield policy
            return
        process = (self.policy or {}).get("_process")
        if process is not None and process.poll() is not None:
            self.close()
        if self.policy is None:
            stack = contextlib.ExitStack()
            try:
                self.policy = stack.enter_context(portable_vlm_engine(tier, self.home))
            except BaseException:
                stack.close()
                raise
            self.stack = stack
        yield self.policy

    def close(self) -> None:
        stack, self.stack, self.policy = self.stack, None, None
        if stack is not None:
            stack.close()


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
    # MinerU sends as many concurrent requests as the server has slots.
    return VlmConfig(engine="llama-cpp", server_url=endpoint, api_key=policy["api_key"], model=policy["alias"],
                     max_concurrency=max(1, int(policy.get("n_parallel") or 1)), http_timeout=1800)


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


def vlm_counters(policy: dict) -> dict | None:
    """Token counters of the private VLM server (its loopback /metrics)."""
    if not policy.get("vlm"):
        return None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(policy["endpoint"] + "/metrics", headers={"Authorization": "Bearer " + policy["api_key"]})
        with opener.open(request, timeout=5) as response:
            text = response.read(1024 * 1024).decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    values = {}
    for line in text.splitlines():
        name, _, number = line.partition(" ")
        if name.startswith("llamacpp:"):
            try:
                values[name.split(":", 1)[1]] = float(number)
            except ValueError:
                pass
    return values


def vlm_usage(before: dict | None, after: dict | None) -> dict | None:
    """Work the local VLM actually did for one document (None if unknown)."""
    if before is None or after is None:
        return None
    delta = {key: max(0.0, after.get(key, 0.0) - before.get(key, 0.0)) for key in after}
    return {"prompt_tokens": int(delta.get("prompt_tokens_total", 0)),
            "generated_tokens": int(delta.get("tokens_predicted_total", 0)),
            "prompt_seconds": round(delta.get("prompt_seconds_total", 0.0), 1),
            "generation_seconds": round(delta.get("tokens_predicted_seconds_total", 0.0), 1)}


def inference_identity(tier: str, requested_tier: str, suffix: str, runtime_policy: dict | None = None,
                       usage: dict | None = None) -> dict:
    """What actually ran, recorded in every result for verification.

    ``vlm_tier`` says the tier engages the local VLM; ``vlm_used`` is measured
    from the VLM server's token counters when they are available: the hybrid
    standard tier calls the VLM only for regions that need it, so a page with
    a clean text layer may not need it at all.
    """
    vlm = tier in VLM_TIERS
    measured = usage is not None and vlm
    identity = {
        "mode": "local", "remote_api": False, "api_key_required": False,
        "engine": f"MinerU {ENGINE_VERSION} (local Python library)",
        "requested_tier": requested_tier, "actual_tier": tier, "effort": TIER_EFFORT.get(tier),
        "vlm_tier": vlm, "vlm_used": bool(usage["prompt_tokens"] or usage["generated_tokens"]) if measured else vlm,
        "vlm_use_measured": measured, "image_analysis": tier == "advanced",
        "small_models": {"backend": "onnxruntime (CPU)", "path": installation_relative(SMALL_MODEL_DIR)},
    }
    if vlm:
        identity["vlm"] = {"model": VLM_MODEL_NAME, "format": "GGUF Q8_0",
                           "weights": installation_relative(VLM_WEIGHTS),
                           "projector": installation_relative(VLM_PROJECTOR),
                           "backend": f"official llama.cpp llama-server {LLAMA_RELEASE}",
                           "transport": "loopback HTTP (127.0.0.1) with a one-time key",
                           "device": (runtime_policy or {}).get("device", "cpu"),
                           "decoding_slots": (runtime_policy or {}).get("n_parallel", vlm_parallel())}
        if measured:
            identity["vlm_usage"] = usage
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
            "inference": inference_identity("standard", DEFAULT_TIER, ".pdf"),
            "default_tier_policy": "basic first; pages with tables or display formulas use the standard local VLM",
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
    with portable_vlm_engine("standard", CONFIGURED_HOME) as policy:
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
            "inference": inference_identity("standard", "standard", ".pdf", policy),
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


def run(request: dict, shared: SharedVlmEngine | None = None) -> dict:
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
    if shared is None and options.get("vlm_parallel") is not None:
        set_vlm_parallel(options["vlm_parallel"])
    if requested_tier not in TIER_EFFORT and requested_tier != ADAPTIVE:
        raise ValueError("Unknown parsing tier")
    suffix = source.suffix.lower()
    # Office/HTML/EPUB/CSV take MinerU's native path for every tier (the VLM is
    # not applicable there); this is recorded in the result, not hidden.
    tier = "flash" if suffix in NATIVE_SUFFIXES else "basic" if requested_tier == ADAPTIVE else requested_tier
    if suffix not in NATIVE_SUFFIXES | IMAGE_SUFFIXES | {".pdf"}:
        raise ValueError("Unsupported document format")
    if tier in VLM_TIERS:
        require_vlm_assets()
    configure(output)
    started = time.monotonic()
    progress("loading", tier=tier)
    from mineru.parser.writer import DataWriter

    def writer(root: Path):
        class ConfinedWriter(DataWriter):
            def write(self, path: str, data: bytes) -> None:
                target = safe_asset(root, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        return ConfinedWriter()

    assert_offline_configuration()
    progress("parsing", tier=tier, effort=TIER_EFFORT[tier], vlm=tier in VLM_TIERS)
    lease = shared.lease(tier) if shared is not None else portable_vlm_engine(tier, CONFIGURED_HOME)
    with lease as runtime_policy:
        from mineru.parser import parse
        vlm_config = loopback_vlm_config(runtime_policy) if runtime_policy.get("vlm") else None
        # Only the local library entry point is used; MinerU's hosted-API
        # client (MinerUApiParser) is never constructed here.
        counters = vlm_counters(runtime_policy)
        result = parse(source, tier=tier, ocr_mode="auto", image_analysis=tier == "advanced", vlm_config=vlm_config)
        usage = vlm_usage(counters, vlm_counters(runtime_policy))
        runtime_policy = {key: value for key, value in runtime_policy.items()
                          if key not in {"api_key", "endpoint"} and not key.startswith("_")}
    progress("saving")
    result.save(writer(output))
    structured = json.loads((output / "structured_content.json").read_text("utf-8"))
    normalized = normalize(structured, output, suffix, tier)
    escalation = None
    inference = inference_identity(tier, requested_tier, suffix, runtime_policy, usage)
    if requested_tier == ADAPTIVE and suffix not in NATIVE_SUFFIXES:
        escalation = escalate_complex_pages(source, output, suffix, structured, normalized, shared, writer)
        if escalation["vlm_pages"]:
            runtime_policy = escalation.pop("runtime_policy")
            inference = inference_identity("standard", requested_tier, suffix, runtime_policy, escalation["vlm_usage"])
            tier = "basic+standard"
            inference.update(actual_tier=tier, effort="medium+high")
        escalation.pop("runtime_policy", None)
        inference["adaptive"] = escalation
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
                       "inference": inference,
                       "elapsed_seconds": round(time.monotonic() - started, 3)})
    (output / "result.json").write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    progress("completed", status=normalized["status"], units=len(normalized["units"]))
    return normalized


def complex_layout_pages(structured: dict) -> tuple[dict[int, list[str]], list[int]]:
    """Pages whose basic layout shows tables or display formulas (with the
    block types found), and pages that contain figures."""
    complex_pages, figures = {}, []
    for ordinal, page in enumerate(structured.get("pages", [])):
        index = page.get("page_idx", ordinal)
        kinds = {str(block.get("type", "")) for block in page.get("blocks", []) if isinstance(block, dict)}
        if kinds & COMPLEX_LAYOUT:
            complex_pages[index] = sorted(kinds & COMPLEX_LAYOUT)
        if kinds & FIGURE_BLOCKS:
            figures.append(index)
    return complex_pages, figures


def merge_escalated(normalized: dict, escalated: dict, page_map: list[int], reasons: dict[int, list[str]], prefix: str) -> list[int]:
    """Replace the basic units of escalated pages with their standard-tier
    units; returns the original page indices that were replaced."""
    def remap(value: Any) -> Any:
        if isinstance(value, list):
            return [remap(item) for item in value]
        if not isinstance(value, dict):
            return value
        output = {key: remap(item) for key, item in value.items()}
        locator = value.get("locator")
        if isinstance(locator, dict) and isinstance(locator.get("page_idx"), int) and 0 <= locator["page_idx"] < len(page_map):
            original = page_map[locator["page_idx"]]
            output["locator"] = {**locator, "page": original + 1, "page_idx": original}
        if isinstance(value.get("relative_path"), str):
            output["relative_path"] = prefix + value["relative_path"]
            output["id"] = hashlib.sha256(output["relative_path"].encode()).hexdigest()[:20]
        return output

    replacements = {}
    for unit in escalated.get("units", []):
        mapped = remap(unit)
        index = mapped["locator"]["page_idx"]
        mapped["coverage"] = {**mapped.get("coverage", {}), "parsed_with": "standard", "escalation_reasons": reasons.get(index, [])}
        replacements[index] = mapped
    units, replaced = [], []
    for unit in normalized["units"]:
        index = unit["locator"]["page_idx"]
        if index in replacements:
            mapped = replacements.pop(index)
            mapped["index"] = unit["index"]
            units.append(mapped)
            replaced.append(index)
        else:
            unit["coverage"] = {**unit.get("coverage", {}), "parsed_with": "basic"}
            units.append(unit)
    normalized["units"] = units
    normalized["warnings"].extend(remap(item) for item in escalated.get("warnings", [])
                                  if not (isinstance(item, dict) and item.get("code") == "partial_document"))
    normalized["assets"] = list({asset["relative_path"]: asset for unit in units for asset in unit.get("assets", [])}.values())
    normalized["coverage"].update(text_units=sum(bool(unit["text"]) for unit in units), asset_count=len(normalized["assets"]),
                                  formula_count=sum(len(unit.get("equations", [])) for unit in units),
                                  table_count=sum(len(unit.get("tables", [])) for unit in units))
    return replaced


def keep_basic(normalized: dict, pages: list[int], code: str, message: str) -> None:
    """Complex pages that could not get the VLM pass stay basic, visibly."""
    normalized["warnings"].append({"code": code, "pages": [page + 1 for page in pages], "message": message})
    for unit in normalized["units"]:
        if unit["locator"]["page_idx"] in pages:
            unit["coverage"] = {**unit.get("coverage", {}), "parsed_with": "basic", "requires_vlm_review": True}


def escalate_complex_pages(source: Path, output: Path, suffix: str, structured: dict, normalized: dict,
                           shared: "SharedVlmEngine | None", writer: Any) -> dict:
    """Adaptive tier: parse only the complex pages again with the standard VLM."""
    reasons, figures = complex_layout_pages(structured)
    pages = sorted(reasons)
    record = {"policy": "basic first; pages with tables or display formulas use the standard local VLM",
              "vlm_pages": [], "basic_pages": sorted(unit["locator"]["page"] for unit in normalized["units"]),
              "reasons": {str(page + 1): kinds for page, kinds in sorted(reasons.items())},
              "figure_pages": [page + 1 for page in figures], "vlm_usage": None, "runtime_policy": None}
    if figures:
        record["figure_hint"] = "Figures are kept as images; read these pages with tier=advanced for local VLM image analysis."
    if not pages:
        return record
    try:
        require_vlm_assets()
    except VlmUnavailable as exc:
        keep_basic(normalized, pages, "vlm_escalation_unavailable",
                   "These pages contain tables or display formulas, but the local VLM is not installed; they keep the basic result. " + str(exc)[:300])
        return record
    folder = output / "vlm"
    folder.mkdir(exist_ok=True)
    escalated_source = source
    if suffix == ".pdf":
        import pypdfium2
        escalated_source = safe_asset(output, "vlm/complex-pages.pdf")
        with pypdfium2.PdfDocument(source) as original:
            subset = pypdfium2.PdfDocument.new()
            try:
                subset.import_pages(original, pages)
                subset.save(escalated_source)
            finally:
                subset.close()
    progress("escalating", pages=len(pages), tier="standard")
    try:
        lease = shared.lease("standard") if shared is not None else portable_vlm_engine("standard", CONFIGURED_HOME)
        with lease as policy:
            from mineru.parser import parse
            counters = vlm_counters(policy)
            result = parse(escalated_source, tier="standard", ocr_mode="auto", image_analysis=False, vlm_config=loopback_vlm_config(policy))
            usage = vlm_usage(counters, vlm_counters(policy))
            policy = {key: value for key, value in policy.items() if key not in {"api_key", "endpoint"} and not key.startswith("_")}
        result.save(writer(folder))
        escalated = normalize(json.loads((folder / "structured_content.json").read_text("utf-8")), folder, suffix, "standard")
    except Exception as exc:
        keep_basic(normalized, pages, "vlm_escalation_failed",
                   "The standard local VLM pass for these complex pages failed; they keep the basic result. " + str(exc)[:300])
        return record
    replaced = merge_escalated(normalized, escalated, pages if suffix == ".pdf" else [0], reasons, "vlm/")
    missing = [page for page in pages if page not in replaced]
    if missing:
        keep_basic(normalized, missing, "vlm_escalation_incomplete", "The standard local VLM pass returned no result for these pages; they keep the basic result.")
    record.update(vlm_pages=[page + 1 for page in replaced], vlm_usage=usage, runtime_policy=policy,
                  basic_pages=sorted(unit["locator"]["page"] for unit in normalized["units"] if unit["coverage"].get("parsed_with") == "basic"))
    return record


def error_result(exc: BaseException) -> dict:
    # Source content and keys are never copied into error messages by this wrapper.
    message = str(exc)
    code = "source_changed" if message.startswith("source_changed") else "parse_failed"
    if isinstance(exc, VlmUnavailable):
        code = "vlm_unavailable"
    elif isinstance(exc, (ModuleNotFoundError, importlib.metadata.PackageNotFoundError)):
        code = "parser_not_configured"
    elif isinstance(exc, FileNotFoundError):
        code = "parser_asset_missing"
    return {"schema_version": 1, "ok": False, "status": "error", "engine": "mineru",
            "engine_version": ENGINE_VERSION, "error": {"code": code, "message": message[:1200]},
            "offline": True, "blocked_network_attempts": len(NETWORK_ATTEMPTS)}


SUMMARY_KEYS = ("schema_version", "ok", "status", "engine", "engine_version", "source_sha256", "coverage",
                "offline", "blocked_network_attempts", "inference")


def serve_request(request: dict, shared: SharedVlmEngine) -> dict:
    """Parse one request inside a serving worker; the full result stays in result.json."""
    global CURRENT_REQUEST
    CURRENT_REQUEST = str(request.get("request_id", ""))
    try:
        result = run(request, shared)
        summary = {key: result[key] for key in SUMMARY_KEYS if key in result}
        summary.update({"result_path": "result.json", "units_inline": False, "warnings": result.get("warnings", [])[:100]})
    except Exception as exc:
        summary = error_result(exc)
    finally:
        CURRENT_REQUEST = ""
    summary["request_id"] = str(request.get("request_id", ""))
    return summary


def serve_loop(lines: Any, protocol: Any, handle: Any) -> None:
    """One JSON request per input line, one JSON response per output line."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("A parse request must be a JSON object")
        except ValueError as exc:
            response = {**error_result(exc), "request_id": ""}
        else:
            response = handle(request)
        protocol.write(json.dumps(response, ensure_ascii=False) + "\n")
        protocol.flush()


def serve(home: Path) -> int:
    """Long-lived worker: MinerU models and the local VLM server load once."""
    if not home.is_absolute():
        raise ValueError("Absolute worker home required")
    # Responses use a private copy of stdout; anything a native library prints
    # to file descriptor 1 is redirected to stderr so it cannot corrupt them.
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    home.mkdir(parents=True, exist_ok=True)
    configure_home(home)
    shared = SharedVlmEngine(home)
    try:
        serve_loop(sys.stdin, protocol, lambda request: serve_request(request, shared))
    finally:
        shared.close()
        protocol.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--verify-vlm", action="store_true", help="load the local VLM in llama-server and report it; no document inference")
    parser.add_argument("--serve", action="store_true", help="parse many requests in one process (models load once)")
    parser.add_argument("--home", help="private worker home for --serve")
    parser.add_argument("--vlm-parallel", type=int, help="decoding slots for the private VLM server (1-4)")
    args = parser.parse_args()
    if args.vlm_parallel is not None:
        set_vlm_parallel(args.vlm_parallel)
    if args.serve:
        return serve(Path(args.home or ""))
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    output_stream = sys.stdout
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = health() if args.health else verify_vlm() if args.verify_vlm else run(json.load(sys.stdin))
    except Exception as exc:
        result = error_result(exc)
    encoded = json.dumps(result, ensure_ascii=False)
    if not args.health and result.get("ok") and len(encoded.encode("utf-8")) > 4 * 1024 * 1024:
        summary = {key: result[key] for key in SUMMARY_KEYS if key in result}
        summary.update({"result_path": "result.json", "warnings": result.get("warnings", [])[:100], "units_inline": False})
        encoded = json.dumps(summary, ensure_ascii=False)
    print(encoded, file=output_stream, flush=True)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
