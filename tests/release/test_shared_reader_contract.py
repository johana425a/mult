"""Include the complete reader contract suite in the candidate release gate."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1]/'test_workspace_document_reader.py'),run_name='__main__')
