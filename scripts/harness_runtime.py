"""Start and stop only DeepSteam's isolated official Harness sidecar."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib import request
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from storage_paths import select_storage
from runtime_paths import node_executable, python_executable

STORAGE = select_storage(ROOT)
STATE = STORAGE.process_root / "harness-state"
PROFILE = STATE / "profile"
TOKEN = STATE / "control-token"
RECORD = STATE / "runtime.json"
PORT = 3796
BASE = "http://127.0.0.1:3796"

def http(path: str, value=None):
    headers = {}
    if path != "/health":
        headers["Authorization"] = "Bearer " + TOKEN.read_text(encoding="utf-8").strip()
    if value is not None:
        headers["Content-Type"] = "application/json"
    req = request.Request(BASE + path, data=json.dumps(value).encode() if value is not None else None, headers=headers)
    opener = request.build_opener(request.ProxyHandler({}))
    with opener.open(req, timeout=5) as response:
        return json.load(response)

def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # The parent ACL is inherited by token, grant and session files.
        username = subprocess.check_output(["whoami.exe"], text=True).strip()
        result = subprocess.run(["icacls.exe", str(path), "/inheritance:r", "/grant:r", username + ":(OI)(CI)F"], capture_output=True)
        if result.returncode:
            raise RuntimeError("Could not protect Harness storage")
    else:
        path.chmod(0o700)

def status():
    try:
        health = http("/health")
        record = json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}
        return {"running": bool(health.get("healthy")), "port": PORT, "pid": record.get("pid"), "implementation": health.get("implementation"), "version": health.get("version")}
    except Exception:
        return {"running": False, "port": PORT}

def start():
    current = status()
    if current["running"]:
        if not RECORD.exists():
            raise RuntimeError("Harness port belongs to an unregistered host")
        return current
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError("Harness port is occupied")
    STORAGE.prepare(STATE, PROFILE, STORAGE.logs, STORAGE.temporary)
    private_directory(STATE)
    if not TOKEN.exists():
        TOKEN.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    entry = ROOT / "runtime" / "harness" / "sidecar.mjs"
    if not entry.is_file():
        entry = ROOT / "integration" / "harness" / "sidecar.mjs"
    if not (entry.parent / "node_modules").is_dir():
        raise RuntimeError("Harness dependencies are not installed")
    env = dict(os.environ)
    for key in tuple(env):
        if any(fragment in key.upper() for fragment in ("API_KEY", "TOKEN", "PASSWORD", "SECRET")) or key == "DSH_HOME":
            env.pop(key, None)
    env.update(STORAGE.child_environment())
    env.update({"DSH_HOME": str(PROFILE), "DEEPSTEAM_HARNESS_PROFILE": str(PROFILE),
                "DEEPSTEAM_HARNESS_TOKEN_FILE": str(TOKEN), "DEEPSTEAM_HARNESS_PORT": str(PORT),
                "DEEPSTEAM_HARNESS_PYTHON": str(python_executable("deeptutor")),
                "DEEPSTEAM_CHROMIUM": str(ROOT / "runtime/chromium/chrome-win64/chrome.exe"),
                "DEEPSTEAM_PORTAL_ORIGIN": "http://127.0.0.1:3791"})
    node = node_executable()
    if not node.is_file():
        raise RuntimeError("Bundled Node runtime is missing")
    with (STORAGE.logs / "harness.log").open("ab") as log:
        process = subprocess.Popen([str(node), str(entry)], cwd=str(ROOT), env=env, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    RECORD.write_text(json.dumps({"pid": process.pid, "created": psutil.Process(process.pid).create_time(), "entry": str(entry), "executable": str(node), "root": str(ROOT), "started_at": time.time()}, indent=2), encoding="utf-8")
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError("Harness did not initialize; see the protected local log")
        if status()["running"]:
            return status()
        time.sleep(0.5)
    process.terminate()
    process.wait(timeout=10)
    raise RuntimeError("Harness startup timed out")

def stop():
    if not RECORD.exists():
        return {"running": False, "port": PORT}
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    if record.get("root") != str(ROOT):
        raise RuntimeError("Harness process ownership does not match this installation")
    try:
        process = psutil.Process(record["pid"])
        if (abs(process.create_time() - record.get("created", process.create_time())) > .1
                or (record.get("executable") and str(Path(process.exe()).resolve()) != str(Path(record["executable"]).resolve()))
                or record["entry"] not in process.cmdline()):
            raise RuntimeError("Harness process ownership no longer matches")
    except psutil.NoSuchProcess:
        return {"running": False, "port": PORT}
    try:
        http("/shutdown", {})
    except Exception:
        if status()["running"]:
            raise RuntimeError("Could not authenticate Harness shutdown")
    for _ in range(40):
        if not status()["running"]:
            return {"running": False, "port": PORT}
        time.sleep(0.25)
    raise RuntimeError("Harness did not finish shutting down")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "status"))
    args = parser.parse_args()
    try:
        print(json.dumps({"start": start, "stop": stop, "status": status}[args.action](), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        sys.exit(1)

if __name__ == "__main__":
    main()
