"""Application-owned writable paths, optionally separate from portable binaries.

An absent local ``deepsteam-storage.json`` preserves the self-contained layout.
Only that installation's explicit, non-secret JSON selects another local disk;
environment variables and other applications' settings are never consulted.
This module selects/validates paths and never copies or deletes user data.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from urllib import request as urlrequest

CONFIG_NAME = "deepsteam-storage.json"
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def assert_plain_path(path: Path) -> Path:
    """Reject symlinks/junctions in every existing ancestor before resolving."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("DeepSteam storage paths must be absolute")
    for current in (path, *path.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
            raise ValueError("DeepSteam storage cannot use a symlink or reparse point")
    return path.resolve()


@dataclass(frozen=True)
class StoragePaths:
    program_root: Path
    state_root: Path
    configured: bool = False

    @property
    def data(self) -> Path:
        return self.state_root / "data"

    @property
    def deeptutor_home(self) -> Path:
        return self.state_root / "runtime" / "deeptutor-home"

    @property
    def deeptutor_content(self) -> Path:
        return self.data / "deeptutor"

    @property
    def cache(self) -> Path:
        return self.state_root / "cache"

    @property
    def temporary(self) -> Path:
        return self.cache / "temp"

    @property
    def deeptutor_temporary(self) -> Path:
        return self.temporary if self.configured else self.program_root / "runtime" / "temp"

    @property
    def logs(self) -> Path:
        return self.state_root / "logs"

    @property
    def process_root(self) -> Path:
        return self.state_root / "runtime"

    @property
    def openmaic_data(self) -> Path:
        if self.configured or (self.program_root / "runtime" / "openmaic-standalone" / "server.js").is_file():
            return self.state_root / "runtime" / "openmaic-standalone" / "data"
        return self.program_root / "upstream" / "OpenMAIC" / "data"

    @property
    def openmaic_classrooms(self) -> Path:
        return self.openmaic_data / "classrooms" if self.configured else self.data / "openmaic" / "classrooms"

    @property
    def qwen_state(self) -> Path:
        return self.state_root / "runtime" / "local-qwen"

    def render_local(self, service_root: Path) -> Path:
        return self.state_root / "runtime" / "render-service" / ".local" if self.configured else service_root / ".local"

    def prepare(self, *paths: Path) -> None:
        """Create only validated children of the selected writable root."""
        for path in paths:
            path = assert_plain_path(path)
            if not path.is_relative_to(self.state_root):
                raise ValueError("Writable path leaves the selected DeepSteam storage root")
            path.mkdir(parents=True, exist_ok=True)
            # Recheck after mkdir so no unnoticed pre-existing junction is used.
            assert_plain_path(path)

    def child_environment(self) -> dict[str, str]:
        # Windows httpx/urllib also discover the user's system proxy when no
        # proxy variables are inherited by a desktop/background launch. Our
        # local service-to-service requests must always remain on loopback.
        # Preserve existing bypass entries and all external API proxy choices.
        # A NO_PROXY-only environment prevents Windows urllib from falling
        # back to the registry. Capture effective routing first and carry only
        # otherwise-lost routes into this application's child environment.
        # These transient values are never logged, saved or applied globally.
        effective_proxies = urlrequest.getproxies()
        inherited_proxies = urlrequest.getproxies_environment()
        proxy_routes = {}
        for scheme in ("http", "https", "all"):
            route = effective_proxies.get(scheme)
            if route and scheme not in inherited_proxies:
                proxy_routes[scheme.upper() + "_PROXY"] = route
        bypass_entries = []
        seen = set()
        for raw in (os.environ.get("NO_PROXY", ""), os.environ.get("no_proxy", ""),
                    "127.0.0.1,localhost,::1"):
            for entry in raw.split(","):
                entry = entry.strip()
                if entry and entry.casefold() not in seen:
                    seen.add(entry.casefold())
                    bypass_entries.append(entry)
        bypass = ",".join(bypass_entries)
        return {
            **proxy_routes,
            "NO_PROXY": bypass,
            "no_proxy": bypass,
            "DEEPSTEAM_STATE_ROOT": str(self.state_root),
            "DEEPSTEAM_SEPARATE_STORAGE": "1" if self.configured else "0",
            "XDG_CACHE_HOME": str(self.cache),
            "HF_HOME": str(self.cache / "huggingface"),
            "TORCH_HOME": str(self.cache / "torch"),
            "MPLCONFIGDIR": str(self.cache / "matplotlib"),
            "TEMP": str(self.temporary), "TMP": str(self.temporary),
        }


def select_storage(program_root: Path) -> StoragePaths:
    program_root = assert_plain_path(Path(program_root))
    config = program_root / CONFIG_NAME
    if not config.exists() and not config.is_symlink():
        return StoragePaths(program_root, program_root)
    assert_plain_path(config)
    if not config.is_file() or config.stat().st_size > 8192:
        raise ValueError("DeepSteam storage configuration must be a small regular JSON file")
    value = json.loads(config.read_text(encoding="utf-8-sig"))
    if (not isinstance(value, dict) or set(value) != {"version", "state_root"}
            or type(value.get("version")) is not int or value["version"] != 1
            or not isinstance(value.get("state_root"), str)):
        raise ValueError("DeepSteam storage configuration requires version 1 and state_root")
    raw = value["state_root"]
    if not raw or raw != raw.strip() or "\x00" in raw or raw.startswith(("\\\\", "//")):
        raise ValueError("DeepSteam state_root must name a local absolute folder")
    target = Path(raw)
    if (not target.is_absolute()
            or any(part in {".", ".."} for part in raw.replace("\\", "/").split("/"))
            or any(":" in part or any(char in '<>"|?*' for char in part)
                   or part.endswith((" ", ".")) for part in target.parts[1:])):
        raise ValueError("DeepSteam state_root must name a local absolute folder without traversal")
    target = assert_plain_path(target)
    if target == Path(target.anchor):
        raise ValueError("A drive root cannot be used as a DeepSteam data folder")
    if target == program_root:
        return StoragePaths(program_root, program_root)
    if target.is_relative_to(program_root) or program_root.is_relative_to(target):
        raise ValueError("Separate DeepSteam storage cannot overlap the program directory")
    if target.exists() and not target.is_dir():
        raise ValueError("DeepSteam state_root is not a directory")
    return StoragePaths(program_root, target, True)
