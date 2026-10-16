"""Build the full pinned native frontend and stage an immutable runtime copy.

Original competition integration, 2026-10-10. No upstream route is removed.
The prior wheel frontend and every previous staged native build are retained.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deeptutor_runtime import API, NODE, ROOT, configure_environment

WEB_SOURCE = ROOT / "upstream" / "DeepTutor" / "web"
MANIFEST = ROOT / "runtime" / "native-frontend.json"


def source_fingerprint():
    digest = hashlib.sha256()
    for directory, dirs, files in os.walk(WEB_SOURCE):
        dirs[:] = sorted(d for d in dirs if d != "node_modules" and not d.startswith(".next") and d != ".git")
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix not in {".tsx", ".ts", ".js", ".mjs", ".cjs", ".json", ".css"}:
                continue
            if name.startswith("tsconfig.deeptutor-build-"):
                continue
            digest.update(str(path.relative_to(WEB_SOURCE)).replace("\\", "/").encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auth-enabled', choices=('true', 'false'), default=None,
                        help='Explicit deployment authentication mode for an offline build; omitted probes the live local backend.')
    options = parser.parse_args()
    configure_environment()
    if not (WEB_SOURCE / "node_modules" / "next" / "dist" / "bin" / "next").exists():
        raise SystemExit("Install the official locked frontend dependencies with npm ci first.")
    if options.auth_enabled is not None:
        auth_enabled = options.auth_enabled == 'true'
        auth_source = 'explicit-cli'
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(API + "/api/auth/status", timeout=5) as response:
            auth_enabled = bool(json.load(response)["enabled"])
        auth_source = 'live-local-backend'
    os.environ.update({"NEXT_PUBLIC_API_BASE": API, "NEXT_PUBLIC_AUTH_ENABLED": str(auth_enabled).lower(),
                       "DEEPTUTOR_AUTH_ENABLED": str(auth_enabled).lower(),
                       "DEEPTUTOR_NEXT_DIST_DIR": ".next-contest-native", "NEXT_TELEMETRY_DISABLED": "1",
                       "NODE_OPTIONS": "--max-old-space-size=8192"})
    lock = WEB_SOURCE / "package-lock.json"
    before_lock = hashlib.sha256(lock.read_bytes()).hexdigest()
    before_source = source_fingerprint()
    before_pages = sorted(str(p.relative_to(WEB_SOURCE)).replace("\\", "/") for p in (WEB_SOURCE / "app").rglob("page.tsx"))
    started = time.time()
    log = ROOT / "logs" / "native-ui-build.log"
    with log.open("wb") as output:
        result = subprocess.run([str(NODE / "node.exe"), str(WEB_SOURCE / "scripts" / "build.mjs")],
                                cwd=WEB_SOURCE, env=os.environ.copy(), stdout=output, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise SystemExit(f"Native full frontend build failed ({result.returncode}); inspect {log}")
    if hashlib.sha256(lock.read_bytes()).hexdigest() != before_lock:
        raise SystemExit("The frontend lockfile unexpectedly changed; not activating this build.")
    if source_fingerprint() != before_source:
        raise SystemExit("Frontend source changed during compilation; preserve output and rebuild after source freeze.")
    standalone = WEB_SOURCE / ".next-contest-native" / "standalone"
    if not (standalone / "server.js").exists():
        raise SystemExit("Missing complete native standalone server; no activation performed.")
    build_id = time.strftime("%Y%m%d-%H%M%S")
    staged = ROOT / "runtime" / "native-frontends" / build_id
    if staged.exists():
        raise SystemExit("A staged build with this identifier already exists; preserving it.")
    shutil.copytree(standalone, staged)
    manifest = {"mode": "native-source", "build_id": build_id, "root": str(staged),
                "server": str(staged / "server.js"), "api_base": API,
                "build_auth_enabled": auth_enabled, "build_auth_source": auth_source, "package_lock_sha256": before_lock,
                "source_sha256": before_source,
                "source_page_count": len(before_pages), "source_pages": before_pages,
                "elapsed_seconds": round(time.time() - started, 2), "original_wheel_frontend_retained": True}
    # Stage only. Explicit activation after health checks avoids switching a
    # running user frontend merely because compilation succeeded.
    staged_manifest = ROOT / "reports" / ("native-ui-runtime-build-" + build_id + ".json")
    staged_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"staged_manifest": str(staged_manifest), "server": manifest["server"],
                      "source_page_count": len(before_pages), "elapsed_seconds": manifest["elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
