"""Locate private, installation-relative runtimes without another app's state.

The portable installer provisions runtime/python, runtime/node, and optionally
runtime/chromium. Source checkouts may still use their own venv or PATH tools.
No runtime discovery reads credentials or another application's configuration.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def _first_file(candidates: list[Path]) -> Path | None:
    return next((path.resolve() for path in candidates if path.is_file()), None)


def node_executable() -> Path:
    candidates = [ROOT / "runtime" / "node" / "node.exe",
                  ROOT / "runtime" / "node" / "bin" / "node.exe"]
    if os.environ.get("DEEPSTEAM_NODE"):
        candidates.append(Path(os.environ["DEEPSTEAM_NODE"]))
    on_path = shutil.which("node.exe") or shutil.which("node")
    if on_path:
        candidates.append(Path(on_path))
    return _first_file(candidates) or candidates[0]


def python_executable(service: str = "portal") -> Path:
    candidates = [ROOT / "runtime" / "python" / "python.exe",
                  ROOT / "runtime" / (service + "-venv") / "Scripts" / "python.exe"]
    return _first_file(candidates) or Path(sys.executable).resolve()


def browser_executable() -> Path:
    candidates = [ROOT / "runtime" / "chromium" / "chrome.exe",
                  ROOT / "runtime" / "chromium" / "chrome-win64" / "chrome.exe",
                  ROOT / "runtime" / "chromium" / "chrome-headless-shell.exe",
                  ROOT / "runtime" / "chromium" / "chrome-headless-shell-win64" / "chrome-headless-shell.exe"]
    if os.environ.get("DEEPSTEAM_BROWSER"):
        candidates.append(Path(os.environ["DEEPSTEAM_BROWSER"]))
    # A source installation can use an installed browser binary. Rendering
    # always creates a separate temporary profile, never opens its user data.
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        if os.environ.get(variable):
            base = Path(os.environ[variable])
            candidates.extend((base / "Google" / "Chrome" / "Application" / "chrome.exe",
                               base / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    path = _first_file(candidates)
    if path is None:
        raise RuntimeError("Video rendering needs the bundled Chromium runtime. Repair or reinstall DeepSteam.")
    return path


def add_project_paths() -> None:
    """Embedded Python ignores PYTHONPATH, so add application paths explicitly."""
    for path in (ROOT, ROOT / "scripts", ROOT / "runtime" / "deeptutor-packages"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
