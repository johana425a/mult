"""Start/stop only this workspace's OpenMAIC process on loopback port 3793."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import node_executable
from storage_paths import select_storage

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "upstream" / "OpenMAIC"
STORAGE = select_storage(ROOT)
STATE = STORAGE.process_root / "openmaic-process.json"
NODE = node_executable()
STANDALONE = ROOT / "runtime" / "openmaic-standalone"
NEXT = SOURCE / "node_modules" / "next" / "dist" / "bin" / "next"
PNPM_CLI = NODE.parent.parent / "node_modules" / "pnpm" / "bin" / "pnpm.mjs"
URL = "http://127.0.0.1:3793"


def environment() -> dict[str, str]:
    # Build an allowlist rather than carrying another application's API keys.
    names = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "PROCESSOR_ARCHITECTURE",
             "NUMBER_OF_PROCESSORS", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
             "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
    env = {key: value for key, value in os.environ.items() if key.upper() in names}
    cache = STORAGE.cache
    temporary = STORAGE.cache / "openmaic-temp"
    STORAGE.prepare(temporary, STORAGE.openmaic_data, STORAGE.openmaic_classrooms)
    env.update(STORAGE.child_environment())
    env.update({
        "TEMP": str(temporary), "TMP": str(temporary),
        "NEXT_TELEMETRY_DISABLED": "1", "npm_package_version": "1.1.2",
        "npm_config_cache": str(cache / "npm"), "PNPM_HOME": str(cache / "pnpm"),
        "COREPACK_HOME": str(cache / "corepack"),
        "OPENMAIC_DATA_DIR": str(STORAGE.openmaic_data),
        # Prompt templates travel with the package; resolve them from this
        # installation so the folder can live at any path.
        "OPENMAIC_PROMPTS_DIR": str(STANDALONE / "packages" / "@openmaic" / "generation"),
        "DEEPSTEAM_APP_ROOT": str(ROOT),
        "DEEPSTEAM_HARNESS_CORE": "1",
        "OPENMAIC_AGENT_RUNTIME_ENABLED": "true",
        # This service is bound to loopback HTTP. Secure cookies would not be
        # sent back by some clients, losing the owner between POST and SSE.
        "COOKIE_SECURE": "0",
        "DATABASE_URL": "pglite:" + str(STORAGE.openmaic_data / 'embedded-postgres'),
        "OPENMAIC_CLASSROOMS_DIR": str(STORAGE.openmaic_classrooms),
        "ALLOWED_FRAME_ANCESTORS": "deepsteam://portal deepsteam://app http://127.0.0.1:3791 http://127.0.0.1:3792",
        "RENDER_SERVICE_URL": "http://127.0.0.1:3794",
        # The bundled local renderer supports the upstream video workflow.
        # This flag is compiled into the browser app as well as set at launch.
        "NEXT_PUBLIC_ENABLE_VIDEO_EXPORT": "true",
        "NODE_OPTIONS": "--max-old-space-size=8192",
        "LOG_LEVEL": "warn",
        # This desktop application intentionally calls its own loopback model.
        # The HTTP service remains bound to 127.0.0.1; cloud metadata endpoints
        # still remain denied by OpenMAIC's upstream outbound validation.
        "ALLOW_LOCAL_NETWORKS": "true",
        # Native classroom/player requests use this same default, not only
        # the portal's request-scoped generation provider. The placeholder is
        # public and contains no user credential; existing browser API choices
        # remain independent and keep their credentials.
        "DEFAULT_MODEL": "custom-deepsteam-shared:current",
        "DEEPSTEAM_HARNESS_TOKEN_FILE": str(STORAGE.process_root / "harness-state" / "control-token"),
        "HOSTNAME": "127.0.0.1", "PORT": "3793",
    })
    return env


def owned_process() -> psutil.Process | None:
    try:
        saved = json.loads(STATE.read_text(encoding="utf-8"))
        process = psutil.Process(saved["pid"])
        if abs(process.create_time() - saved["created"]) > 0.1:
            return None
        command = " ".join(process.cmdline()).lower()
        source_command = str(NEXT).lower() in command and "3793" in command
        standalone_command = str(STANDALONE / "server.js").lower() in command
        if not (source_command or standalone_command):
            return None
        if Path(process.exe()).resolve() != NODE.resolve():
            return None
        return process
    except (OSError, ValueError, KeyError, psutil.Error):
        return None


def status() -> dict:
    process = owned_process()
    result = {"service": "OpenMAIC", "url": URL, "running": process is not None,
              "pid": process.pid if process else None, "healthy": False}
    try:
        with build_opener(ProxyHandler({})).open(URL + "/api/health", timeout=3) as response:
            payload = json.load(response)
        result["healthy"] = payload.get("status") == "ok"
        result["version"] = payload.get("version")
    except Exception:
        pass
    listeners = []
    for connection in psutil.net_connections(kind="tcp"):
        if connection.status == psutil.CONN_LISTEN and connection.laddr.port == 3793:
            listeners.append({"address": connection.laddr.ip, "port": 3793, "pid": connection.pid})
    result["listeners"] = listeners
    result["loopback_only"] = all(item["address"] in {"127.0.0.1", "::1"} for item in listeners)
    return result


def start(dev: bool = False) -> dict:
    current = status()
    if current["running"]:
        return current
    with socket.socket() as check:
        try:
            check.bind(("127.0.0.1", 3793))
        except OSError:
            raise RuntimeError("Port 3793 is already occupied by another process") from None
    if not NODE.exists():
        raise RuntimeError("OpenMAIC dependencies are not installed")
    if not dev and (STANDALONE / "server.js").is_file():
        mode, cwd = "standalone", STANDALONE
        args = [str(NODE), str(STANDALONE / "server.js")]
    else:
        if not NEXT.exists():
            raise RuntimeError("OpenMAIC dependencies are not installed")
        mode = "dev" if dev or not (SOURCE / ".next" / "BUILD_ID").exists() else "start"
        cwd = SOURCE
        args = [str(NODE), str(NEXT), mode, "--hostname", "127.0.0.1", "--port", "3793"]
    STORAGE.prepare(STORAGE.logs, STATE.parent)
    with (STORAGE.logs / "openmaic.stdout.log").open("ab") as stdout, \
         (STORAGE.logs / "openmaic.stderr.log").open("ab") as stderr:
        process = subprocess.Popen(args, cwd=cwd, env=environment(), stdout=stdout, stderr=stderr,
                                   stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    created = psutil.Process(process.pid).create_time()
    STATE.write_text(json.dumps({"pid": process.pid, "created": created, "mode": mode}, indent=2), encoding="utf-8")
    for _ in range(15):
        time.sleep(1)
        current = status()
        if current["healthy"] or not current["running"]:
            break
    current["mode"] = mode
    return current


def stop() -> dict:
    process = owned_process()
    if process:
        children = process.children(recursive=True)
        for item in children + [process]:
            try:
                item.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(children + [process], timeout=5)
        for item in alive:
            try:
                item.kill()
            except psutil.NoSuchProcess:
                pass
        STATE.unlink(missing_ok=True)
    return status()


def build() -> dict:
    """Reproducible Windows build without requiring a globally installed npm."""
    if owned_process():
        raise RuntimeError("Stop this OpenMAIC service before rebuilding")
    env = environment()
    packages = ['mathml2omml', 'pptxgenjs', '@openmaic/dsl', '@openmaic/generation',
                '@openmaic/storage', '@openmaic/importer', '@openmaic/renderer', '@openmaic/editor']
    for name in packages:
        package = (SOURCE / 'packages' / name).resolve()
        package.relative_to((SOURCE / 'packages').resolve())
        subprocess.run([str(NODE), str(PNPM_CLI), '--config.verifyDepsBeforeRun=false',
                        '--dir', str(package), 'run', 'build'], cwd=SOURCE, env=env, check=True)
    subprocess.run([str(NODE), str(SOURCE / 'scripts' / 'sync-maic-importer.mjs')], cwd=SOURCE, env=env, check=True)
    subprocess.run([str(NODE), str(NEXT), 'build'], cwd=SOURCE, env=env, check=True)
    return {'built': True, 'version': '1.1.2', 'source': str(SOURCE)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop", "status", "build"])
    parser.add_argument("--dev", action="store_true")
    options = parser.parse_args()
    try:
        output = (start(options.dev) if options.command == "start" else stop() if options.command == "stop"
                  else build() if options.command == "build" else status())
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(1)
