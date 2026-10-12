"""Create a source/demo handoff without machine state or credentials."""
from __future__ import annotations

import hashlib
import argparse
import json
import re
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(r"E:\DeepSteam-Share")
PREFIX = "DeepSteam"
SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".next", ".next-contest-native", ".pytest_cache", ".mypy_cache", ".venv", "downloads", ".dsh", ".deepseek", "browser-profile", "userData"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".sqlite", ".sqlite3", ".db", ".pem", ".pfx", ".p12", ".tsbuildinfo"}
ROOT_FILES = ["README.md", "AGENTS.md", ".gitignore", "requirements-demo.txt", "GUIDE.md",
              "Start-DeepSteam.cmd", "Stop-DeepSteam.cmd", "Check-DeepSteam.cmd"]
REPORTS = ["native-ui-preservation.md", "native-ui-browser-acceptance.md", "native-ui-runtime-notes.md",
           "deepsteam-branding-20261010.md", "deepsteam-claude-palette-20261010.md",
           "portal-audit-final.md", "openmaic-runtime-contract.md", "render-implementation.md",
           "render-demo-lesson.md", "deeptutor-runtime-notes.md", "browser-acceptance.md",
           "deepsteam-claude-palette-20261010.png", "native-ui-classroom-20261010.png",
           "classroom-ui-20261010.png", "classroom-quiz-20261010.png", "demo-lesson-video.mp4",
           "openmaic-runtime-figure-fixture.pdf"]
REPORTS += ["ui-license-cleanup-20261010.md", "contest-requirements-20261010.md"]
REPORTS += ["deeptutor-modification-notice-audit-20261010.json",
            "openmaic-ui-build-20261010-213933.json", "openmaic-ui-probe-20261010-213933.json",
            "local-qwen-acceptance.json", "local-qwen-acceptance-first-native-failure.json",
            "run_qwen_acceptance.py"]
INSTALLER_SOURCES = ["DeepSteamSetup.cs", "DeepSteam.manifest", "build_installer.py",
                     "prepare_install.py", "repair_install_paths.py", "stage_frontend_payload.py",
                     "Install-DeepSteam.ps1", "Start-DeepSteam.ps1", "Stop-DeepSteam.ps1", "USER-GUIDE.txt",
                     "cache_model_payload.py", "build_container_iofix.py", "publish_container_iofix.py",
                     "install_verified_release.py", "resume_verified_release.py",
                     "test_overlay_installer.py", "test_model_cache.py", "test_resume_install.py",
                     "test_relocation_paths.py"]
HARNESS_INSTALLER_SOURCES = ["build_r4_candidate.py", "prepare_r4_components.py", "build_r5_candidate.py",
                             "deploy_harness_overlay.py", "prepare_harness_delivery.py",
                             "stage_harness_sources.py", "assemble_r5_spec.py", "test_harness_delivery.py",
                             "build_desktop_runtime.py", "pack_desktop_asar.mjs", "inspect_superseded_packages.py",
                             "desktop-build-tools/package.json", "desktop-build-tools/package-lock.json",
                             "desktop-build-tools/.npmrc", "desktop-build-tools/.npmrc-global",
                             "test_default_install_root.cs"]
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".cs", ".json", ".md", ".toml", ".yaml", ".yml", ".txt", ".html", ".css", ".cmd", ".ps1"}
SECRET_PATTERNS = {
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "openai_key": rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b",
    "github_token": rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
    "aws_access_key": rb"\bAKIA[0-9A-Z]{16}\b",
}


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def allowed(path: Path) -> bool:
    skipped = {part.casefold() for part in SKIP_DIRS}
    if any(p.casefold() in skipped or p.casefold().startswith(".next-") for p in path.parts):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    name = path.name.lower()
    if name.startswith(".env") and name not in {".env.example", ".env.sample", ".env.template"}:
        return False
    return name not in {"auth.json", "credentials.json", "cookies.json", "id_rsa", "id_ed25519", "control-token", "account-state.json"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--release", choices=["r3", "r4", "r5"], default="r3")
    parser.add_argument("--openmaic-source-baseline", type=Path,
                        help="Verified prior source ZIP; use its approved OpenMAIC source rather than unshipped edits")
    parser.add_argument("--expected-openmaic-source-baseline-sha256")
    options = parser.parse_args()
    if bool(options.openmaic_source_baseline) != bool(options.expected_openmaic_source_baseline_sha256):
        raise RuntimeError("A frozen OpenMAIC source ZIP and its SHA must be supplied together")
    output = options.output.resolve()
    selected: dict[str, Path | bytes] = {}
    frozen_openmaic = None
    frozen_versions = None
    if options.openmaic_source_baseline:
        baseline = options.openmaic_source_baseline.resolve()
        if (not baseline.is_relative_to(ROOT.resolve()) or not baseline.is_file() or baseline.is_symlink()
                or not re.fullmatch(r"[0-9a-f]{64}", options.expected_openmaic_source_baseline_sha256)):
            raise RuntimeError("Frozen public OpenMAIC source ZIP identity differs")
        with baseline.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != options.expected_openmaic_source_baseline_sha256:
                raise RuntimeError("Frozen public OpenMAIC source ZIP identity differs")
        with zipfile.ZipFile(baseline) as prior:
            original = json.loads(prior.read(f"{PREFIX}/PACKAGE-MANIFEST.json"))
            frozen_versions = original["upstream"]["OpenMAIC"]
            names = set()
            for row in original["files"]:
                name = row["path"]
                if not name.startswith("upstream/OpenMAIC/"):
                    continue
                relative = Path(name)
                if name in names or relative.is_absolute() or ".." in relative.parts or not allowed(relative):
                    raise RuntimeError("Unsafe or repeated frozen OpenMAIC source path")
                names.add(name)
                blob = prior.read(f"{PREFIX}/{name}")
                if len(blob) != row["bytes"] or hashlib.sha256(blob).hexdigest() != row["sha256"]:
                    raise RuntimeError("Frozen OpenMAIC source entry SHA differs: " + name)
                selected[name] = blob
            if not names or not any(name.startswith("upstream/OpenMAIC/LICENSE") for name in names):
                raise RuntimeError("Frozen OpenMAIC source is empty or lacks its license")
        frozen_openmaic = {"source_zip": str(baseline),
                           "source_zip_sha256": options.expected_openmaic_source_baseline_sha256,
                           "files": len(names),
                           "current_unshipped_working_tree_edits_included": False}
    for name in ROOT_FILES:
        file = ROOT / name
        if not file.is_file():
            raise RuntimeError(f"Required handoff file missing: {name}")
        selected[name] = file
    for directory in ["portal", "integration", "scripts", "tests", "demo", "licenses", "desktop"]:
        for file in (ROOT / directory).rglob("*"):
            rel = file.relative_to(ROOT)
            if file.is_file() and allowed(rel):
                selected[rel.as_posix()] = file
    installer_sources = INSTALLER_SOURCES + (HARNESS_INSTALLER_SOURCES if options.release == "r5" else [])
    for name in installer_sources:
        file = ROOT / "installer" / name
        if not file.is_file():
            raise RuntimeError("Missing installer source: " + name)
        selected["installer/" + name] = file
    reports = REPORTS + (["r5-packaging-hooks.md"] if options.release == "r5" else [])
    for name in reports:
        file = ROOT / "reports" / name
        if not file.is_file():
            raise RuntimeError(f"Required report missing: {name}")
        selected[f"reports/{name}"] = file

    versions = {}
    projects = ["DeepTutor", "OpenMAIC"]
    if options.release == "r5":
        projects.append("DeepSeekHarness")
    for project in projects:
        if project == "OpenMAIC" and frozen_versions:
            versions[project] = {**frozen_versions, "source_snapshot": frozen_openmaic,
                                 "working_tree_changes_included": True,
                                 "working_tree_note": "Approved changes from the pinned prior public source snapshot only"}
            continue
        repo = ROOT / "upstream" / project
        names = git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")
        for raw in names:
            if not raw:
                continue
            rel = Path(raw.decode("utf-8"))
            file = repo / rel
            if file.is_file() and allowed(rel):
                selected[f"upstream/{project}/{rel.as_posix()}"] = file
        versions[project] = {
            "commit": git(repo, "rev-parse", "HEAD").decode().strip(),
            "version": git(repo, "describe", "--tags", "--always", "HEAD").decode().strip(),
            "working_tree_changes_included": True,
        }

    manifest = []
    findings = []
    total = 0
    for name, file in sorted(selected.items()):
        if isinstance(file, Path) and (file.is_symlink() or not file.resolve().is_relative_to(ROOT.resolve())):
            raise RuntimeError(f"Unexpected symlink or external path: {name}")
        blob = file.read_bytes() if isinstance(file, Path) else file
        total += len(blob)
        manifest.append({"path": name, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()})
        entry_path = Path(name)
        if entry_path.suffix.lower() in TEXT_SUFFIXES or entry_path.name.startswith(".env"):
            for kind, pattern in SECRET_PATTERNS.items():
                if re.search(pattern, blob):
                    findings.append({"path": name, "pattern": kind})
    if findings:
        # Report paths/categories only, never potential credential values.
        print(json.dumps({"blocked_for_review": findings}, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    created = datetime.now(timezone(timedelta(hours=9)))
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"DeepSteam-{options.release}-Source-And-Demo-{created:%Y%m%d-%H%M%S}.zip"
    summary = {
        "created_at": created.isoformat(), "purpose": "Teammate source and demonstration handoff; not a portable installer",
        "upstream": versions, "file_count": len(manifest), "source_bytes": total,
        "frozen_openmaic_source": frozen_openmaic,
        "excluded": ["runtime", "data", "logs", "cache", "downloads", ".git", "node_modules", "build outputs",
                     "actual .env/auth/credential files", "local model/provider settings", "browser state",
                     "Harness .dsh/account state and desktop user profile"],
        "notes": ["Working-tree edits and new nonignored files are included, except any explicitly pinned prior OpenMAIC source snapshot.",
                  "Source scan found no matches for the listed high-confidence credential patterns; this is not a proof against all secret formats.",
                  f"Source bundle excludes runtime binaries and model weights. Use the {options.release} installer for the bundled local model and ready-to-run environment.",
                  "Read GUIDE.md before running the machine-specific launch scripts."],
        "files": manifest,
    }
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for name, file in sorted(selected.items()):
            if isinstance(file, Path):
                package.write(file, f"{PREFIX}/{name}")
            else:
                package.writestr(f"{PREFIX}/{name}", file)
        package.writestr(f"{PREFIX}/PACKAGE-MANIFEST.json", json.dumps(summary, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(archive) as package:
        corrupt = package.testzip()
        if corrupt:
            raise RuntimeError(f"ZIP CRC check failed: {corrupt}")
        for row in manifest:
            if hashlib.sha256(package.read(f"{PREFIX}/{row['path']}")).hexdigest() != row["sha256"]:
                raise RuntimeError(f"ZIP contents differ from source: {row['path']}")
        names = package.namelist()
        for project in versions:
            if not any(n.startswith(f"{PREFIX}/upstream/{project}/LICENSE") for n in names):
                raise RuntimeError(f"Missing upstream license: {project}")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    result = {"zip": str(archive), "bytes": archive.stat().st_size, "file_count": len(manifest) + 1,
              "source_bytes": total, "sha256": digest, "crc_passed": True, "all_file_hashes_passed": True,
              "secret_pattern_findings": 0, "upstream_licenses_present": True,
              "frozen_openmaic_source": frozen_openmaic}
    archive.with_suffix(".zip.report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
