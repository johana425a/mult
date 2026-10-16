"""Start services for a desktop session and stop only that session's new PIDs.

Opening the desktop beside an already-running browser session must not acquire
ownership of those services. Journals contain process identities, never model
credentials or chat data. Service-specific launchers still own their state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import python_executable
from storage_paths import select_storage
from installation_identity import command_in_install

ROOT = Path(__file__).resolve().parents[1]
STORAGE = select_storage(ROOT)
PYTHON = python_executable("portal")
PORTS = {3791, 3792, 3793, 3794, 3795, 3796, 8011}


def identity(process):
    """Require our install path in its command; PID and creation time survive reuse."""
    import psutil
    try:
        command = process.cmdline()
        if not command_in_install(command, ROOT):
            return None
        return {"pid": process.pid, "created": process.create_time(),
                "executable": str(Path(process.exe()).resolve()),
                "command_hash": hashlib.sha256(json.dumps(command).encode()).hexdigest()}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def snapshot():
    import psutil
    result = {}
    for connection in psutil.net_connections(kind="inet"):
        if connection.status != "LISTEN" or connection.laddr.port not in PORTS or connection.pid is None:
            continue
        if connection.laddr.ip not in {"127.0.0.1", "::1"}:
            raise RuntimeError("A DeepSteam port is exposed outside loopback")
        try:
            item = identity(psutil.Process(connection.pid))
            if item:
                result[item["pid"]] = item
        except psutil.NoSuchProcess:
            pass
    # A failed start may not have reached LISTEN. Capture its recorded service
    # process too, so closing a failed desktop doesn't leak that process.
    files = [STORAGE.process_root / name for name in
             ("portal-process.json", "deeptutor-processes.json", "openmaic-process.json")]
    files += [STORAGE.qwen_state / "process.json", STORAGE.state_root / "runtime" / "render-service" / ".local" / "process.json",
              ROOT / "runtime" / "render-service" / ".local" / "process.json",
              ROOT / "upstream" / "OpenMAIC" / "render-service" / ".local" / "process.json",
              STORAGE.process_root / "harness-state" / "runtime.json"]
    for filename in files:
        try:
            value = json.loads(filename.read_text("utf-8"))
            entries = value.get("processes", [value])
            for entry in entries:
                process = psutil.Process(entry["pid"])
                if abs(process.create_time() - entry["created"]) < 1:
                    item = identity(process)
                    if item:
                        result[item["pid"]] = item
        except (OSError, ValueError, KeyError, psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def claim_file(claim):
    if not re.fullmatch(r"[0-9]+-[0-9]+", claim):
        raise ValueError("Invalid desktop session identity")
    folder = STORAGE.process_root / "desktop-claims"
    STORAGE.prepare(folder)
    return folder / (claim + ".json")


def start_owned(claim):
    journal = claim_file(claim)
    if journal.exists():
        raise RuntimeError("This desktop session has already started")
    before = snapshot()
    journal.write_text(json.dumps({"claim": claim, "processes": []}), "utf-8")
    env = os.environ.copy()
    for key in list(env):
        if key.endswith("_API_KEY") or key in {"OPENAI_BASE_URL", "ANTHROPIC_AUTH_TOKEN"}:
            env.pop(key, None)
    env.update(STORAGE.child_environment())
    try:
        result = subprocess.run([str(PYTHON), "-I", "-B", str(ROOT / "scripts" / "portal_runtime.py"), "start"],
                                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
        return result.returncode
    finally:
        after = snapshot()
        owned = [item for pid, item in after.items() if pid not in before or item["created"] != before[pid]["created"]]
        journal.write_text(json.dumps({"claim": claim, "processes": owned}, indent=2), "utf-8")


def stop_owned(claim):
    import psutil
    journal = claim_file(claim)
    if not journal.exists():
        return 0
    value = json.loads(journal.read_text("utf-8"))
    owned = {item["pid"]: item for item in value.get("processes", [])}
    # The Harness host drains sessions and credential jobs on /shutdown. Only
    # call its launcher when that exact host belongs to this desktop session.
    harness_state = STORAGE.process_root / "harness-state" / "runtime.json"
    try:
        harness = json.loads(harness_state.read_text("utf-8"))
        expected = owned.get(harness["pid"])
        if expected and abs(expected["created"] - harness["created"]) < 1 and identity(psutil.Process(harness["pid"])) == expected:
            subprocess.run([str(PYTHON), "-I", "-B", str(ROOT / "scripts" / "harness_runtime.py"), "stop"],
                           cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=40, check=False)
    except (OSError, ValueError, KeyError, psutil.NoSuchProcess, psutil.AccessDenied, subprocess.TimeoutExpired):
        pass
    targets = {}
    for item in reversed(value.get("processes", [])):
        try:
            process = psutil.Process(item["pid"])
            if identity(process) != item:
                continue
            for child in process.children(recursive=True):
                targets[child.pid] = child
            targets[process.pid] = process
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    for process in targets.values():
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(list(targets.values()), timeout=10)
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    _, remaining = psutil.wait_procs(alive, timeout=3)
    if remaining:
        return 1
    journal.unlink()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start-owned", "stop-owned"))
    parser.add_argument("--claim", required=True)
    args = parser.parse_args()
    sys.exit(start_owned(args.claim) if args.action == "start-owned" else stop_owned(args.claim))
