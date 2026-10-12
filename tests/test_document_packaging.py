"""Failure-oriented packaging guards; all inputs are synthetic except one read-only inventory."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("document_packaging", ROOT / "installer/document_runtime.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DocumentPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="document-package-unit-", dir=ROOT / "runtime")
        self.addCleanup(self.temp.cleanup)
        self.manifest = Path(self.temp.name) / "ocr.json"
        names = [module.SITE + "rapidocr/config.yaml", *[module.SITE + f"rapidocr/models/{x}.onnx" for x in ("det", "rec", "cls")]]
        self.ocr = {"schema": "deepsteam-document-ocr-dependencies-v1", "offline_acceptance": {"passed": True},
                    "files": [{"target": name, "bytes": 1, "sha256": "a" * 64} for name in names]}
        self.manifest.write_text(json.dumps(self.ocr), "utf8")
        self.rows = {row["target"]: {"path": row["target"], "bytes": 1, "sha256": "a" * 64} for row in self.ocr["files"]}
        for name in (module.READER, "runtime/python/python.exe", "runtime/python/python313._pth",
                     "runtime/harness/documents.mjs", "integration/harness/documents.mjs",
                     module.SITE + "rapidocr-3.10.0.dist-info/METADATA"):
            self.rows[name] = {"path": name, "bytes": 1, "sha256": "b" * 64}
        self.pin_patch = mock.patch.object(module, "pins", return_value={"rapidocr": "3.10.0"})
        self.pin_patch.start()
        self.addCleanup(self.pin_patch.stop)

    def test_complete_contract(self):
        result = module.check_rows(self.rows, self.manifest)
        self.assertEqual(result["ocr_files"], 4)
        self.assertFalse(result["model_download_on_first_use_required"])

    def test_missing_ocr_model_fails_even_when_metadata_exists(self):
        del self.rows[module.SITE + "rapidocr/models/det.onnx"]
        with self.assertRaisesRegex(RuntimeError, "Incomplete or changed"):
            module.check_rows(self.rows, self.manifest)

    def test_changed_ocr_config_fails(self):
        self.rows[module.SITE + "rapidocr/config.yaml"]["sha256"] = "c" * 64
        with self.assertRaisesRegex(RuntimeError, "Incomplete or changed"):
            module.check_rows(self.rows, self.manifest)

    def test_different_versions_fail(self):
        del self.rows[module.SITE + "rapidocr-3.10.0.dist-info/METADATA"]
        self.rows[module.SITE + "rapidocr-1.0.0.dist-info/METADATA"] = {"sha256": "a" * 64, "bytes": 1}
        with self.assertRaisesRegex(RuntimeError, "versions are missing"):
            module.check_rows(self.rows, self.manifest)

    def test_ambiguous_versions_fail(self):
        self.rows[module.SITE + "rapidocr-1.0.0.dist-info/METADATA"] = {"sha256": "a" * 64, "bytes": 1}
        with self.assertRaisesRegex(RuntimeError, "Conflicting"):
            module.check_rows(self.rows, self.manifest)

    def test_divergent_host_mirrors_fail(self):
        self.rows["runtime/harness/documents.mjs"]["sha256"] = "c" * 64
        with self.assertRaisesRegex(RuntimeError, "mirrors differ"):
            module.check_rows(self.rows, self.manifest)

    def test_missing_actual_python_fails(self):
        del self.rows["runtime/python/python.exe"]
        with self.assertRaisesRegex(RuntimeError, "entry missing"):
            module.check_rows(self.rows, self.manifest)

    def test_unaccepted_dependency_plan_fails(self):
        self.ocr["offline_acceptance"]["passed"] = False
        self.manifest.write_text(json.dumps(self.ocr), "utf8")
        with self.assertRaisesRegex(RuntimeError, "not passed"):
            module.check_rows(self.rows, self.manifest)

    def test_runtime_only_extraction_excludes_state_and_language_model(self):
        for name in ("runtime/harness-state/profile/attachments/user.pdf", "models/local-qwen/model.gguf",
                     "data/records.db", "runtime/python/Lib/site-packages/deeptutor/agent.py"):
            self.assertFalse(module.selected_for_probe(name))
        for name in ("runtime/python/python313.dll", module.SITE + "rapidocr/models/det.onnx",
                     module.SITE + "numpy.libs/math.dll", module.SITE + "rapidocr-3.10.0.dist-info/licenses/LICENSE"):
            self.assertTrue(module.selected_for_probe(name))

    def test_zip_path_escapes_fail(self):
        for name in ("../secret", "/absolute", "C:/secret", "a\\b", "a//b"):
            with self.assertRaises(RuntimeError):
                module.selected_for_probe(name)

    def test_legacy_entry_fails_before_io(self):
        spec = importlib.util.spec_from_file_location("legacy_builder", ROOT / "installer/build_installer.py")
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        with mock.patch.object(old, "copy_tree", side_effect=AssertionError("must not copy old payload")):
            with self.assertRaisesRegex(RuntimeError, "historical r3 entry"):
                old.main()

    def test_uninstaller_test_report_requires_all_success_and_real_checks(self):
        spec = importlib.util.spec_from_file_location("new_document_builder", ROOT / "installer/build_document_release.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        self.assertTrue(builder.uninstall_tests_passed({"tests": {"passed": True}}))
        self.assertTrue(builder.uninstall_tests_passed({"tests": [{"passed": True, "checks": 31}], "total_checks": 31}))
        for report in ({"tests": []}, {"tests": [{"passed": True, "checks": 0}], "total_checks": 0},
                       {"tests": [{"passed": False, "checks": 31}], "total_checks": 31},
                       {"tests": [{"passed": True, "checks": 31}], "total_checks": 32}):
            self.assertFalse(builder.uninstall_tests_passed(report))


if __name__ == "__main__":
    unittest.main()
