"""Create the current public source ZIP on D, without runtimes or user state.

This wraps the existing independently CRC/SHA-checked source packager. It does
not install, publish, write E, call models, or reinterpret prior live receipts.
"""
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location("unified_clean_source_packager", ROOT / "scripts/package_handoff.py")
packager = importlib.util.module_from_spec(specification)
specification.loader.exec_module(packager)

packager.SKIP_DIRS.update({"data", "logs", "cache", "state", "sessions", "profiles", ".local", "models", "user-data", "harness-state"})
packager.SKIP_SUFFIXES.update({".gguf", ".safetensors", ".bin", ".payload.dat", ".exe", ".dll", ".node", ".asar"})
packager.INSTALLER_SOURCES.append("UNINSTALL.md")
packager.REPORTS += ["DeepSteam-Models-And-Workspaces.md", "prepare_unified_public_stage.py",
                     "prepare_unified_frontend_components.py", "prepare_unified_clean_source.py",
                     "build_unified_r5_candidate.py", "assemble_unified_r5_spec.py",
                     "test_unified_packaging_contract.py",
                     "refresh_unified_native_stage.py",
                     "desktop-workspace-ui-freeze-20261011.md"]

original_allowed = packager.allowed


def allowed(path):
    if path.name.casefold() in {".deepsteam-reviewed-classroom-audit.mjs", "credentials.dpapi", ".credentials.yaml", "runtime.json"}:
        return False
    return original_allowed(path)


packager.allowed = allowed

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Supply one fresh installer/r5-unified-* directory")
    output = ROOT / sys.argv[1]
    output.resolve().relative_to((ROOT / "installer").resolve())
    if not output.name.startswith("r5-unified-") or output.exists():
        raise RuntimeError("A new public source output is required")
    sys.argv = [sys.argv[0], "--release", "r5", "--output", str(output)]
    packager.main()
