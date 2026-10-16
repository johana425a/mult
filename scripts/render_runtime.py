"""Local Windows OpenMAIC renderer lifecycle; no model or paid API calls.

Original EduAgent integration. Upstream render-service keeps its public API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import browser_executable, node_executable
from storage_paths import select_storage

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "runtime" / "render-service"
if not (SERVICE / "src" / "main.ts").is_file():
    SERVICE = ROOT / "upstream" / "OpenMAIC" / "render-service"
STORAGE = select_storage(ROOT)
LOCAL = STORAGE.render_local(SERVICE)
STATE = LOCAL / "process.json"
REPORTS = ROOT / "reports"
NODE = node_executable()
BASE = "http://127.0.0.1:3794"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def prepare():
    STORAGE.prepare(LOCAL, LOCAL / "cache", LOCAL / "temp", LOCAL / "jobs")
    REPORTS.mkdir(parents=True, exist_ok=True)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch(url, timeout=15):
    # Explicit loopback requests must never travel through inherited proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if url.startswith(BASE) else urllib.request.build_opener()
    return opener.open(url, timeout=timeout)


def bootstrap():
    prepare()
    archive = LOCAL / "ffmpeg-release-essentials.zip"
    manifest = REPORTS / "render-dependencies.json"
    # Once installed, retain the exact verified release; bootstrap is not an
    # implicit update command and must not silently follow a newer download.
    if manifest.exists() and archive.exists():
        existing = json.loads(manifest.read_text(encoding="utf-8"))
        with archive.open('rb') as stream:
            pinned_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        if pinned_hash == existing.get('sha256') and Path(existing.get('path', '')).is_file():
            print(json.dumps({**existing, 'reused_pinned_release': True}, ensure_ascii=False))
            return
    expected = fetch(FFMPEG_URL + ".sha256", 60).read().decode().split()[0].lower()
    if not archive.exists() or hashlib.file_digest(archive.open("rb"), "sha256").hexdigest() != expected:
        with fetch(FFMPEG_URL, 120) as source, archive.open("wb") as output:
            shutil.copyfileobj(source, output)
    actual = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
    if actual != expected:
        raise RuntimeError("FFmpeg archive checksum mismatch")
    dest = LOCAL / "ffmpeg"
    dest.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as zipf:
        for info in zipf.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise RuntimeError("Unsafe path in FFmpeg archive")
        zipf.extractall(dest)
    exe = ffmpeg()
    version = subprocess.check_output([str(exe), "-version"], text=True, encoding="utf-8").splitlines()[0]
    report = {"source": FFMPEG_URL, "source_discovery": "https://ffmpeg.org/download.html", "sha256": actual, "verified_publisher_sha256": True, "version": version, "path": str(exe), "license": "Gyan essentials GPLv3; retained LICENSE and README in extracted directory"}
    dump(REPORTS / "render-dependencies.json", report)
    print(json.dumps(report, ensure_ascii=False))


def ffmpeg():
    bundled = ROOT / "runtime" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if bundled.is_file():
        return bundled
    found = list((LOCAL / "ffmpeg").glob("*/bin/ffmpeg.exe"))
    if len(found) != 1:
        raise RuntimeError("Run render_runtime.py bootstrap to provision verified FFmpeg")
    return found[0]


def owned():
    if not STATE.exists():
        return None
    state = json.loads(STATE.read_text(encoding="utf-8"))
    try:
        process = psutil.Process(state["pid"])
        if abs(process.create_time() - state["created"]) > .05:
            return None
        if Path(process.exe()).resolve() != NODE.resolve():
            return None
        if str(SERVICE / "src" / "main.ts").lower() not in " ".join(process.cmdline()).lower():
            return None
        return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def health():
    try:
        with fetch(BASE + "/health", 3) as response:
            return json.load(response)
    except Exception:
        return None


def status():
    process = owned()
    return {"owned_pid": process.pid if process else None, "url": BASE, "health": health()}


def environment(executable: Path, chrome: Path, browser_version: str):
    env = os.environ.copy()
    # Renderer has no provider role; do not inherit model credentials.
    for key in list(env):
        if key.upper().endswith("_API_KEY") or key.upper().startswith(("OPENAI_", "ANTHROPIC_", "DEEPSEEK_")):
            env.pop(key, None)
    env.update(STORAGE.child_environment())
    # Keep Windows USERPROFILE intact: changing it makes Chrome reject even an
    # explicit temporary --user-data-dir as a default profile. Pin caches by
    # their documented dedicated knobs instead; no existing browser data opens.
    env.update({"PORT": "3794", "RENDER_RESOURCE_PROFILE": "low-memory", "RENDER_EGRESS_LOCKDOWN": "false", "RENDER_HOME": str(LOCAL), "XDG_CACHE_HOME": str(LOCAL / "cache"), "HYPERFRAMES_FONT_CACHE_DIR": str(LOCAL / "cache" / "fonts"), "HYPERFRAMES_EXTRACT_CACHE_DIR": str(LOCAL / "cache" / "extract"), "TEMP": str(LOCAL / "temp"), "TMP": str(LOCAL / "temp"), "PRODUCER_TMP_PROJECT_DIR": str(LOCAL / "jobs"), "PRODUCER_HEADLESS_SHELL_PATH": str(chrome), "PUPPETEER_EXECUTABLE_PATH": str(chrome), "HYPERFRAMES_FFMPEG_PATH": str(executable), "FFMPEG_PATH": str(executable), "HF_STATIC_DEDUP": "false", "RENDER_JOB_TTL_MS": "86400000", "PRODUCER_PUPPETEER_PROTOCOL_TIMEOUT_MS": "120000"})
    env["PATH"] = str(executable.parent) + os.pathsep + str(NODE.parent) + os.pathsep + env.get("PATH", "")
    env["RENDER_WINDOWS_CHROMIUM_MAJOR"] = browser_version.split('.')[0]
    return env


def start():
    prepare()
    process = owned()
    if process:
        print(json.dumps(status(), ensure_ascii=False))
        return
    if health():
        raise RuntimeError("Port 3794 responds but ownership is unverified; will not replace it")
    executable = ffmpeg()
    chrome = browser_executable()
    browser_version = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', "(Get-Item -LiteralPath '" + str(chrome).replace("'", "''") + "').VersionInfo.FileVersion"], text=True, creationflags=subprocess.CREATE_NO_WINDOW).strip()
    env = environment(executable, chrome, browser_version)
    log = (LOCAL / "service.log").open("ab", buffering=0)
    command = [str(NODE), str(SERVICE / "node_modules" / "tsx" / "dist" / "cli.mjs"), str(SERVICE / "src" / "main.ts")]
    child = subprocess.Popen(command, cwd=SERVICE, env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    tracked = psutil.Process(child.pid)
    dump(STATE, {"pid": child.pid, "created": tracked.create_time(), "command": command})
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError("Renderer exited; inspect render-service/.local/service.log")
        if health():
            print(json.dumps(status(), ensure_ascii=False))
            return
        time.sleep(1)
    raise RuntimeError("Renderer is still starting; inspect status and service.log before retrying")


def stop():
    process = owned()
    if process:
        children = process.children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        process.terminate()
        psutil.wait_procs(children + [process], timeout=10)
    print(json.dumps(status(), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["bootstrap", "start", "stop", "status"])
    args = parser.parse_args()
    if args.action == "status":
        print(json.dumps(status(), ensure_ascii=False))
    else:
        globals()[args.action]()
