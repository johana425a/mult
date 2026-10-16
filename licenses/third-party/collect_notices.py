"""Collect notices from matching installed dependency packages, without user data."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import urllib.request

DEST = Path(__file__).resolve().parent
PAYLOAD = DEST.parent.parent
PROJECT = PAYLOAD.parent.parent
MAPPINGS = [
    ("deeptutor-web", PAYLOAD / "runtime/native-frontends/20261010-193459/node_modules", PROJECT / "upstream/DeepTutor/web/node_modules"),
    ("openmaic", PAYLOAD / "runtime/openmaic-standalone/node_modules", PROJECT / "upstream/OpenMAIC/node_modules"),
    ("render-service", PAYLOAD / "runtime/render-service/node_modules", PROJECT / "upstream/OpenMAIC/render-service/node_modules"),
]
NOTICE = re.compile(r"^(license|licence|notice|copying|copyright|third.party.notices?)([._-].*)?$", re.I)

def long(path):
    return "\\\\?\\" + str(path.absolute()) if os.name == "nt" else str(path)

def load(path):
    with open(long(path), "r", encoding="utf-8-sig") as stream:
        return json.load(stream)

records = []
missing = []
for component, installed, source_root in MAPPINGS:
    for directory, dirs, files in os.walk(installed):
        if "package.json" not in files:
            continue
        package_dir = Path(directory)
        relative = package_dir.relative_to(installed)
        metadata = load(package_dir / "package.json")
        source_dir = source_root / relative
        source_meta = source_dir / "package.json"
        if not source_meta.is_file():
            continue
        original = load(source_meta)
        if (metadata.get("name"), metadata.get("version")) != (original.get("name"), original.get("version")):
            raise RuntimeError(f"Dependency version mismatch: {component}/{relative}")
        name, version = metadata.get("name", relative.as_posix()), metadata.get("version", "bundled")
        found = []
        for entry in os.scandir(long(source_dir)):
            if NOTICE.match(entry.name):
                if entry.is_file():
                    found.append(source_dir / entry.name)
                elif entry.is_dir() and entry.name.lower() in {"licenses", "licences"}:
                    for root, subdirs, subfiles in os.walk(source_dir / entry.name):
                        found.extend(Path(root) / item for item in subfiles)
        if not found:
            if name and version and metadata.get("license"):
                missing.append({"component": component, "name": name, "version": version, "license": metadata.get("license"), "package_path": relative.as_posix()})
            continue
        short = re.sub(r"[^A-Za-z0-9._-]", "_", f"{name}-{version}")[:100]
        identity = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:8]
        target = DEST / component / f"{short}-{identity}"
        target.mkdir(parents=True, exist_ok=True)
        copied = []
        for notice in found:
            notice_relative = notice.relative_to(source_dir)
            destination = target / notice_relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(long(notice), long(destination))
            copied.append({"file": destination.relative_to(DEST).as_posix(), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
        records.append({"component": component, "name": name, "version": version, "license": metadata.get("license"), "package_path": relative.as_posix(), "notices": copied})

chromium_url = "https://chromium.googlesource.com/chromium/src/+/refs/tags/155.0.8059.39/LICENSE?format=TEXT"
chromium_path = DEST / "chromium" / "LICENSE"
chromium_path.parent.mkdir(parents=True, exist_ok=True)
chromium_path.write_bytes(base64.b64decode(urllib.request.urlopen(chromium_url, timeout=30).read()))
provenance = {"url": chromium_url, "sha256": hashlib.sha256(chromium_path.read_bytes()).hexdigest(), "note": "Official Chromium root license at the bundled Chrome for Testing version. Additional notices and browser terms remain available at chrome://credits and chrome://terms; original browser ABOUT retained."}
(DEST / "chromium" / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
manifest = {"notice_package_count": len(records), "notice_file_count": sum(len(item["notices"]) for item in records), "records": records, "packages_without_separate_root_notice": missing, "chromium": provenance}
(DEST / "NOTICE-INVENTORY.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"notice_package_count": len(records), "notice_file_count": manifest["notice_file_count"], "packages_without_separate_root_notice": len(missing)}, indent=2))
