"""Competition-only launcher. Original integration code, 2026-10-10.

Uses official DeepTutor 1.6.14 and this project's independent Python venv.
Writable state follows the explicit local storage config when selected.
Default auth is native disabled mode: loopback only.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import node_executable
from offline_tokenizer import configure_tokenizer_cache
from storage_paths import select_storage

ROOT = Path(__file__).resolve().parents[1]
STORAGE = select_storage(ROOT)
HOME = STORAGE.deeptutor_home
CONTENT = STORAGE.deeptutor_content
PACKAGES = ROOT / "runtime" / "deeptutor-packages"
LOGS = STORAGE.logs
STATE = STORAGE.process_root / "deeptutor-processes.json"
NATIVE_FRONTEND_MANIFEST = ROOT / "runtime" / "native-frontend.json"
NODE = node_executable().parent
API = "http://127.0.0.1:8011"
WEB = "http://127.0.0.1:3792"


def configure_environment():
    configure_tokenizer_cache(ROOT)
    # Never inherit keys or runtime roots from the personal installation.
    for name in list(os.environ):
        if name.startswith(("DEEPTUTOR_", "AUTH_", "CORS_", "POCKETBASE_", "LLM_", "EMBEDDING_")) or name.endswith("_API_KEY") or name in {"OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "BACKEND_PORT", "FRONTEND_PORT", "NEXT_PUBLIC_API_BASE", "NEXT_PUBLIC_API_BASE_EXTERNAL", "NEXT_PUBLIC_AUTH_ENABLED", "PUBLIC_API_BASE", "DISABLE_SSL_VERIFY"}:
            os.environ.pop(name, None)
    os.environ.update(STORAGE.child_environment())
    os.environ.update({
        "DEEPTUTOR_HOME": str(HOME), "DEEPTUTOR_WORKSPACE_ROOT": str(CONTENT),
        "DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS": str(CONTENT),
        "BACKEND_PORT": "8011", "FRONTEND_PORT": "3792",
        "DEEPTUTOR_VERSION_CHECK_ENABLED": "false",
        "DEEPTUTOR_API_BASE_URL": API, "NEXT_PUBLIC_API_BASE": API,
        "NEXT_TELEMETRY_DISABLED": "1", "HOSTNAME": "127.0.0.1", "PORT": "3792",
        "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TEMP": str(STORAGE.deeptutor_temporary), "TMP": str(STORAGE.deeptutor_temporary),
    })
    os.environ["PATH"] = str(NODE) + os.pathsep + os.environ.get("PATH", "")
    os.environ["PYTHONPATH"] = os.pathsep.join((str(PACKAGES), str(ROOT)))
    for path in (str(PACKAGES), str(ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)
    STORAGE.prepare(HOME, CONTENT, LOGS, STORAGE.deeptutor_temporary, STORAGE.cache)


def initialize():
    configure_environment()
    from deeptutor.services.setup import init_user_directories
    from deeptutor.services.config import get_runtime_settings_service
    init_user_directories()
    settings = get_runtime_settings_service()
    marker = HOME / ".contest-initialized"
    system = settings.load_system(include_process_overrides=False)
    system.update(backend_port=8011, frontend_port=3792, version_check_enabled=False,
                  cors_origins=[WEB, "http://127.0.0.1:3791"])
    if not marker.exists():
        system["sandbox_allow_subprocess"] = False
    settings.save_system(system)
    if not marker.exists():
        auth = settings.load_auth(include_process_overrides=False)
        auth.update(enabled=False, cookie_secure=False)
        settings.save_auth(auth)
        # Preserve native settings UI, but importing documents must not silently
        # invoke a remote captioning model before a user configures a provider.
        parsing = settings.load_document_parsing(include_process_overrides=False)
        parsing.update(image_caption=False, engine="text_only")
        settings.save_document_parsing(parsing)
        marker.write_text("Isolated competition installation; native auth disabled on loopback.\n", encoding="utf-8")
    enabled = bool(settings.load_auth(include_process_overrides=False).get("enabled"))
    os.environ["DEEPTUTOR_AUTH_ENABLED"] = str(enabled).lower()
    os.environ["AUTH_ENABLED"] = str(enabled).lower()
    os.environ["NEXT_PUBLIC_AUTH_ENABLED"] = str(enabled).lower()
    return enabled


def probe(url):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=3) as response:
            return response.status
    except Exception:
        return None


def bootstrap_dependencies():
    """Install official pinned packages into an independent venv.

    Kept for source users. The installer provisions clean runtime packages;
    normal start never downloads or copies another application's dependencies.
    """
    import venv
    target = ROOT / "runtime" / "deeptutor-venv"
    venv.EnvBuilder(with_pip=True).create(target)
    subprocess.run([str(target / "Scripts" / "python.exe"), "-I", "-B", "-m", "pip", "--isolated", "install",
                    "--index-url", "https://pypi.org/simple", "deeptutor==1.6.14",
                    "-r", str(ROOT / "requirements-demo.txt")], check=True)
    report = {"source": "https://pypi.org/simple", "package": "deeptutor==1.6.14",
              "destination": str(target), "personal_home_content_or_credentials_copied": False}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "deeptutor-runtime-bootstrap.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def owned_process(item):
    import psutil
    try:
        process = psutil.Process(item["pid"])
        if abs(process.create_time() - item["created"]) > 0.5:
            return None
        command = " ".join(process.cmdline()).lower()
        if str(ROOT).lower() not in command:
            return None
        return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def status():
    configure_environment()
    import psutil
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"processes": []}
    listeners = [{"address": c.laddr.ip, "port": c.laddr.port, "pid": c.pid}
                 for c in psutil.net_connections(kind="inet")
                 if c.status == "LISTEN" and c.laddr.port in (8011, 3792)]
    result = {"frontend_http": probe(WEB), "backend_http": probe(API + "/api/auth/status"),
              "listeners": listeners, "managed": [{**p, "owned_alive": owned_process(p) is not None} for p in state["processes"]],
              "home": str(HOME), "content": str(CONTENT), "version": "1.6.14"}
    if NATIVE_FRONTEND_MANIFEST.exists():
        manifest, _ = read_native_frontend(NATIVE_FRONTEND_MANIFEST)
        result.update(frontend_mode="native-source", native_build_id=manifest["build_id"])
    else:
        result["frontend_mode"] = "official-wheel"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if any(c["address"] != "127.0.0.1" for c in listeners):
        raise SystemExit("Unexpected non-loopback listener. Stop the competition services.")
    return result


def start():
    enabled = initialize()
    if STATE.exists():
        old = json.loads(STATE.read_text(encoding="utf-8"))
        if any(owned_process(p) for p in old.get("processes", [])):
            return status()
    for port in (8011, 3792):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} belongs to another process; not replacing it.")
    frontend = resolve_frontend(enabled)
    backend_code = ('import sys,runpy; sys.path.insert(0, ' + repr(str(ROOT / "scripts")) + '); '
                    'runpy.run_path(' + repr(str(ROOT / "scripts" / "deeptutor_backend.py")) + ', run_name="__main__")')
    commands = [("backend", [sys.executable, "-I", "-B", "-c", backend_code], HOME),
                ("frontend", frontend.command, frontend.cwd)]
    import psutil
    processes = []
    try:
        for name, command, cwd in commands:
            with (LOGS / ("deeptutor-" + name + ".log")).open("ab") as output:
                child = subprocess.Popen(command, cwd=cwd, env=os.environ.copy(), stdin=subprocess.DEVNULL,
                                         stdout=output, stderr=subprocess.STDOUT,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            processes.append({"name": name, "pid": child.pid, "created": psutil.Process(child.pid).create_time()})
            STATE.write_text(json.dumps({"processes": processes}, indent=2), encoding="utf-8")
        for _ in range(50):
            if probe(API + "/api/auth/status") == 200 and probe(WEB) == 200:
                return status()
            if any(owned_process(p) is None for p in processes):
                raise RuntimeError("A service exited. Inspect logs/deeptutor-*.log.")
            time.sleep(1)
        raise RuntimeError("Startup is not healthy yet; inspect logs and status before restarting.")
    except Exception:
        raise


def read_native_frontend(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    root = Path(manifest["root"])
    if not root.is_absolute():
        root = ROOT / root
    root = root.resolve()
    permitted = (ROOT / "runtime" / "native-frontends").resolve()
    if not root.is_relative_to(permitted) or not (root / "server.js").is_file():
        raise ValueError("Native frontend must be a complete staged build inside this project.")
    if manifest.get("api_base") != API:
        raise ValueError("Native frontend build targets a different backend.")
    return manifest, root


def resolve_frontend(enabled):
    from deeptutor.runtime.launcher import FrontendRuntime, _resolve_frontend
    if NATIVE_FRONTEND_MANIFEST.exists():
        _, root = read_native_frontend(NATIVE_FRONTEND_MANIFEST)
        # Native auth status is fetched by the browser at runtime; the Next
        # proxy prefers DEEPTUTOR_AUTH_ENABLED exported by initialize().
        return FrontendRuntime("native-source", [str(NODE / "node.exe"), str(root / "server.js")], root)
    return _resolve_frontend(HOME, 3792, api_base=API, auth_enabled=enabled, dev=False)


def activate_native_frontend(manifest_path):
    """Switch only the owned frontend; leave backend process/data untouched."""
    initialize()
    manifest, new_root = read_native_frontend(manifest_path)
    if not STATE.exists():
        raise RuntimeError("Start the existing instance before activating a staged frontend.")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    backend_before = [dict(p) for p in state["processes"] if p["name"] == "backend"]
    frontend = next((p for p in state["processes"] if p["name"] == "frontend"), None)
    process = owned_process(frontend) if frontend else None
    if process is None:
        raise RuntimeError("Existing frontend ownership cannot be verified; no process was stopped.")
    import psutil
    old_command = process.cmdline()
    old_cwd = process.cwd()
    children = process.children(recursive=True)
    for member in children + [process]:
        try:
            member.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(children + [process], timeout=8)
    if alive:
        raise RuntimeError("Previous owned frontend has not stopped; refusing a replacement.")

    def launch(command, cwd):
        with (LOGS / "deeptutor-frontend.log").open("ab") as output:
            child = subprocess.Popen(command, cwd=cwd, env=os.environ.copy(), stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        entry = {"name": "frontend", "pid": child.pid, "created": psutil.Process(child.pid).create_time()}
        state["processes"] = [p for p in state["processes"] if p["name"] != "frontend"] + [entry]
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return child

    child = launch([str(NODE / "node.exe"), str(new_root / "server.js")], new_root)
    ready = False
    for _ in range(30):
        if child.poll() is not None:
            break
        if probe(WEB + "/chat") == 200 and probe(WEB + "/education") == 200:
            ready = True
            break
        time.sleep(1)
    if not ready:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=8)
        launch(old_command, old_cwd)
        raise RuntimeError("New native frontend failed health checks; original frontend was relaunched.")
    if NATIVE_FRONTEND_MANIFEST.exists():
        prior = NATIVE_FRONTEND_MANIFEST.with_name("native-frontend-before-" + str(time.time_ns()) + ".json")
        shutil.copy2(NATIVE_FRONTEND_MANIFEST, prior)
    NATIVE_FRONTEND_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"build_id": manifest["build_id"], "previous_frontend_command": old_command,
              "new_frontend_command": [str(NODE / "node.exe"), str(new_root / "server.js")],
              "backend_before": backend_before,
              "backend_after": [p for p in state["processes"] if p["name"] == "backend"],
              "backend_process_preserved": all(owned_process(p) is not None for p in backend_before),
              "original_wheel_frontend_retained": True}
    (ROOT / "reports" / "native-ui-runtime-activation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return status()


def stop():
    if not STATE.exists():
        return
    import psutil
    state = json.loads(STATE.read_text(encoding="utf-8"))
    for item in state.get("processes", []):
        process = owned_process(item)
        if process is None:
            continue
        descendants = process.children(recursive=True)
        for member in descendants + [process]:
            try:
                member.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(descendants + [process], timeout=8)
        for member in alive:
            member.kill()
        _, alive = psutil.wait_procs(alive, timeout=3)
        if alive:
            raise RuntimeError("Managed processes are still stopping; state retained.")
    STATE.unlink()
    print("Competition DeepTutor stopped; saved learning data preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "start", "stop", "status", "bootstrap-dependencies", "activate-native"])
    parser.add_argument("manifest", nargs="?")
    args = parser.parse_args()
    if args.action == "activate-native":
        if not args.manifest:
            parser.error("activate-native requires a staged build manifest")
        activate_native_frontend(args.manifest)
    else:
        {"init": initialize, "start": start, "stop": stop, "status": status,
         "bootstrap-dependencies": bootstrap_dependencies}[args.action]()
