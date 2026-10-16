"""Verify the official Electron archive and stage DeepSteam's desktop runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "desktop"
VERSION = json.loads((SOURCE / "package.json").read_text("utf-8"))["devDependencies"]["electron"]
ARCHIVE_NAME = f"electron-v{VERSION}-win32-x64.zip"
ARCHIVE = ROOT / "downloads" / ARCHIVE_NAME
DESTINATION = ROOT / "runtime" / "desktop"
checksums = json.loads((SOURCE / "node_modules" / "electron" / "checksums.json").read_text("utf-8"))
digest = hashlib.file_digest(ARCHIVE.open("rb"), "sha256").hexdigest()
if digest != checksums[ARCHIVE_NAME]:
    raise RuntimeError("Electron archive checksum does not match the official npm package")
if DESTINATION.exists():
    raise RuntimeError("Desktop runtime already exists; stage into a fresh version directory before replacing it")
DESTINATION.mkdir(parents=True)
with zipfile.ZipFile(ARCHIVE) as archive:
    for item in archive.infolist():
        target = (DESTINATION / item.filename).resolve()
        if not target.is_relative_to(DESTINATION.resolve()):
            raise RuntimeError("Archive contains a path outside the desktop runtime")
    archive.extractall(DESTINATION)
(DESTINATION / "electron.exe").rename(DESTINATION / "DeepSteam Desktop.exe")
application = DESTINATION / "resources" / "app"
application.mkdir()
for name in ("package.json", "main.cjs", "preload.cjs", "oauth-placeholder.cjs", "policy.cjs", "transport.cjs", "storage-migration.cjs", "starting.html"):
    shutil.copy2(SOURCE / name, application / name)
report = {"electron_version": VERSION, "archive": ARCHIVE_NAME, "sha256": digest,
          "source": "https://github.com/electron/electron/releases/download/v" + VERSION + "/" + ARCHIVE_NAME,
          "executable": "runtime/desktop/DeepSteam Desktop.exe",
          "app": "runtime/desktop/resources/app", "license_retained": (DESTINATION / "LICENSE").is_file(),
          "third_party_notices_retained": (DESTINATION / "LICENSES.chromium.html").is_file()}
(ROOT / "reports" / "desktop-runtime-stage.json").write_text(json.dumps(report, indent=2), "utf-8")
print(json.dumps(report, indent=2))
