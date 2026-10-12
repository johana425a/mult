"""Boundary tests for the offline tool protocol (no inference downloads)."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mineru_worker", ROOT / "scripts/mineru_document_worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class MinerUWorkerContract(unittest.TestCase):
    def test_traversal_and_absolute_artifacts_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for path in ("../source.pdf", "D:/source.pdf", "/source.pdf", "images\\escape.png"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    worker.safe_asset(base, path)

    def test_page_identity_formula_and_asset_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "images").mkdir()
            (base / "images/equation.png").write_bytes(b"synthetic image")
            source = {"is_full_document": True, "pages": [{"page_idx": 7, "blocks": [
                {"type": "text", "content": "Known text"},
                {"type": "interline_equation", "content": "E=mc^2", "image_path": "images/equation.png"},
                {"type": "table", "html": "<table><tr><td>12</td></tr></table>"}]}]}
            result = worker.normalize(source, base, ".pdf", "standard")
            unit = result["units"][0]
            self.assertEqual(unit["locator"]["page"], 8)
            self.assertEqual(unit["locator"]["page_idx"], 7)
            self.assertIn("E=mc^2", unit["text"])
            self.assertIn("12", unit["text"])
            self.assertEqual(result["coverage"]["formula_count"], 1)
            self.assertEqual(result["coverage"]["table_count"], 1)
            self.assertEqual(result["coverage"]["asset_count"], 1)
            self.assertFalse(result["coverage"]["accuracy_verified"])

    def test_missing_asset_and_partial_pages_are_not_successfully_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = worker.normalize({"is_full_document": False, "pages": [{"page_idx": 0,
                "blocks": [{"type": "image", "image_path": "images/missing.png"}]}]}, Path(tmp), ".pdf", "basic")
            self.assertEqual({x["code"] for x in result["warnings"]}, {"missing_asset", "partial_document"})
            self.assertFalse(result["coverage"]["full_document"])
            self.assertEqual(result["units"][0]["coverage"]["status"], "empty_or_unrecognized")

    def test_word_sections_are_not_printed_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = worker.normalize({"is_full_document": True, "pages": [{"page_idx": 0, "blocks": []}]}, Path(tmp), ".docx", "flash")
            self.assertEqual(result["units"][0]["locator"]["page_number_semantics"], "logical_section_not_printed_page")

    def test_empty_table_is_partial_even_when_page_count_is_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = worker.normalize({"is_full_document": True, "pages": [{"page_idx": 0,
                "blocks": [{"type": "table", "content": "", "bbox": [0, 0, 1, 1]}]}]}, Path(tmp), ".pdf", "standard")
            self.assertEqual(result["warnings"][0]["code"], "recognized_region_without_text")
            self.assertTrue(result["coverage"]["full_document"])
            self.assertFalse(result["coverage"]["accuracy_verified"])

    @unittest.skipUnless(os.name == "nt", "Windows process ownership")
    def test_abrupt_worker_exit_terminates_only_its_child_job(self):
        import ctypes
        from ctypes import wintypes
        code = ("import importlib.util,subprocess,sys,time; "
                f"s=importlib.util.spec_from_file_location('w',{str(ROOT / 'scripts/mineru_document_worker.py')!r}); "
                "w=importlib.util.module_from_spec(s); s.loader.exec_module(w); "
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
                "close=w.windows_child_job(p); print(p.pid,flush=True); time.sleep(60)")
        parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = None
        try:
            child_pid = int(parent.stdout.readline().strip())
            handle = kernel.OpenProcess(0x00100000, False, child_pid)
            self.assertTrue(handle)
            parent.terminate()
            parent.wait(timeout=5)
            self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
        finally:
            if parent.poll() is None:
                parent.terminate()
                parent.wait(timeout=5)
            if handle:
                kernel.CloseHandle(handle)
            parent.stdout.close()
            parent.stderr.close()

    def test_other_task_cannot_overwrite_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source.pdf"
            source.write_bytes(b"PDF fixture")
            output = base / "output"
            output.mkdir()
            (output / ".worker-owner.json").write_text(json.dumps({"request_id": "other", "source_sha256": "0" * 64}))
            with self.assertRaisesRegex(ValueError, "another task"):
                worker.run({"schema_version": 1, "action": "parse", "source_path": str(source), "output_dir": str(output), "source_sha256": "0" * 64, "request_id": "current"})


if __name__ == "__main__":
    unittest.main()
