"""Run the existing public component preparer with Windows long mkdir paths.

No source-helper changes; every stage remains new and independently inventoried.
The long-path prefix affects filesystem mkdir only, never portable inventory names.
"""
from pathlib import Path
import importlib.util
import os

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "installer/prepare_r4_components.py"
specification = importlib.util.spec_from_file_location("unified_frontend_preparer", source)
preparer = importlib.util.module_from_spec(specification)
specification.loader.exec_module(preparer)

original_mkdir = Path.mkdir


def long_mkdir(self, mode=0o777, parents=False, exist_ok=False):
    value = str(self)
    if os.name == "nt" and len(value) >= 240 and self.is_absolute() and not value.startswith("\\\\?\\"):
        return original_mkdir(Path("\\\\?\\" + value), mode=mode, parents=parents, exist_ok=exist_ok)
    return original_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)


if __name__ == "__main__":
    Path.mkdir = long_mkdir
    try:
        preparer.main()
    finally:
        Path.mkdir = original_mkdir
