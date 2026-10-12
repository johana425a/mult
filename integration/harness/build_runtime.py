"""Stage public code and locked dependencies only; never stage private Host state."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent
DESTINATION = ROOT / "runtime" / "harness"
DESTINATION.mkdir(parents=True, exist_ok=True)
for path in DESTINATION.rglob("*"):
    if "node_modules" not in path.relative_to(DESTINATION).parts and path.name in {"profile", "control-token", "runtime.json", "credentials.dpapi", ".credentials.yaml", "sessions"}:
        raise RuntimeError("Private state found in public Harness runtime")
for name in ("package.json", "package-lock.json", "sidecar.mjs", "host.mjs", "workspaces.mjs", "workspace_http.mjs", "workspace_management.mjs", "execution_tasks.mjs", "capabilities.mjs", "task_ledger.mjs", "documents.mjs", "credentials.mjs", "protocol.mjs", "credential_store.py", "README.md", "pinned-source-build.json"):
    shutil.copy2(SOURCE / name, DESTINATION / name)
shutil.copytree(SOURCE / "node_modules", DESTINATION / "node_modules", dirs_exist_ok=True)
# These assets are required for real Windows managed-process and filesystem
# search execution. Refuse an incomplete public build rather than degrade at a
# teammate's first terminal call. The runner is rebuilt from pinned src/bin.ts.
native_assets = (
    "node_modules/@deepseek-ai/dsh-subprocess-local/lib/runner.js",
    "node_modules/@koromix/koffi-win32-x64/win32_x64/koffi.node",
    "node_modules/@vscode/ripgrep-win32-x64/bin/rg.exe",
    "node_modules/node-pty/prebuilds/win32-x64/conpty.node",
    "node_modules/node-pty/prebuilds/win32-x64/conpty_console_list.node",
    "node_modules/node-pty/prebuilds/win32-x64/conpty/conpty.dll",
    "node_modules/node-pty/prebuilds/win32-x64/conpty/OpenConsole.exe",
)
asset_receipts = []
for relative_path in native_assets:
    path = DESTINATION / relative_path
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Required Windows Harness runtime asset missing: {relative_path}")
    asset_receipts.append({"path": relative_path, "bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
license_source = ROOT / "upstream" / "DeepSeekHarness" / "LICENSE"
for output in (SOURCE / "DEEPSEEK-HARNESS-LICENSE.txt", DESTINATION / "DEEPSEEK-HARNESS-LICENSE.txt", ROOT / "licenses" / "harness-MIT.txt"):
    shutil.copy2(license_source, output)
lock = json.loads((SOURCE / "package-lock.json").read_text(encoding="utf-8"))
manifest = {
    "source_repository": "https://github.com/deepseek-ai/deepseek-harness",
    "source_commit": "d743267388641bc76f17c45ce8b4c231aed1d32c",
    "official_package_version": "0.2.1-alpha.2",
    "artifact_origin": "Official npm dependencies locked; installed official package main and available runtime leaf exports rebuilt from the pinned source with esbuild 0.28.2, including subprocess runner from src/bin.ts. Generated unused Remote/Typert metadata remains official npm, listed explicitly in pinned-source-build.json.",
    "entry": "runtime/harness/sidecar.mjs",
    "package_lock_sha256": hashlib.sha256((SOURCE / "package-lock.json").read_bytes()).hexdigest(),
    "windows_runtime_assets": asset_receipts,
    "packages": {name: {"version": value.get("version"), "integrity": value.get("integrity"), "resolved": value.get("resolved")} for name, value in lock["packages"].items() if name},
}
(DESTINATION / "dependency-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps({"ok": True, "destination": str(DESTINATION), "packages": len(manifest["packages"])}))
