"""Installer boundary tests; no network or package mutation."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_document_ocr", ROOT / "scripts/install_document_ocr.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OCRInstallerTests(unittest.TestCase):
    def test_pinned_packages_exclude_existing_shared_dependencies(self):
        names = {row[0].lower() for row in module.PINNED}
        self.assertNotIn("numpy", names)
        self.assertNotIn("pillow", names)
        self.assertNotIn("rapidocr-onnxruntime", names)
        self.assertEqual(len(module.PINNED), len(names))

    def test_stage_paths_cannot_escape(self):
        for path in ["../secret", "/absolute", "C:/outside", "inside\\outside"]:
            with self.assertRaises(ValueError):
                module.safe_path(module.STAGE, path)

    def test_nonofficial_downloads_rejected_without_network(self):
        for url in ["http://pypi.org/file.whl", "https://example.invalid/file.whl", "file:///D:/package.whl"]:
            with self.assertRaises(ValueError):
                module.read_official(url, 100)


if __name__ == "__main__":
    unittest.main()
