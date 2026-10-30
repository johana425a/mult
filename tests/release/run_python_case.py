"""Dependency reuse never replaces the tested checkout's Python implementation."""
import os
from pathlib import Path
import runpy
import sys
root = Path(__file__).resolve().parents[2]
case = Path(sys.argv[1]).resolve(strict=True)
case.relative_to(root / 'tests')
sys.path[:0] = [str(case.parent), str(root), str(root / 'upstream/DeepTutor')]
dependencies = os.environ.get('DEEPSTEAM_PYTHON_DEPENDENCIES')
if dependencies:
    sys.path.append(str(Path(dependencies).resolve(strict=True)))
sys.argv = [str(case)]
runpy.run_path(str(case), run_name='__main__')
