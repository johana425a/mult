"""Storage split contracts with disposable fixtures and no running services."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import storage_paths
import deeptutor_runtime
import initialize_deepsteam
import portal_runtime
import openmaic_runtime
import render_runtime


class StorageSplitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="storage-fixture-", dir=ROOT / "reports")
        base = Path(self.temp.name)
        self.program = base / "program"
        self.state = base / "state"
        self.program.mkdir()
        self.storage = storage_paths.StoragePaths(self.program, self.state, True)

    def tearDown(self):
        self.temp.cleanup()

    def configure(self, root):
        (self.program / storage_paths.CONFIG_NAME).write_text(json.dumps({"version": 1, "state_root": str(root)}), encoding="utf-8")

    def test_factory_layout_and_inherited_env_ignored(self):
        with patch.dict(os.environ, {"DEEPSTEAM_STATE_ROOT": str(self.state)}):
            selected = storage_paths.select_storage(self.program)
        self.assertEqual(selected.state_root, self.program)
        self.assertFalse(selected.configured)
        self.assertEqual(selected.child_environment()["DEEPSTEAM_SEPARATE_STORAGE"], "0")
        self.assertEqual(selected.deeptutor_home, self.program / "runtime" / "deeptutor-home")
        self.assertEqual(selected.deeptutor_content, self.program / "data" / "deeptutor")
        self.assertEqual(selected.openmaic_classrooms, self.program / "data" / "openmaic" / "classrooms")
        self.assertEqual(selected.render_local(self.program / "runtime" / "render-service"), self.program / "runtime" / "render-service" / ".local")

    def test_explicit_split_creates_only_selected_state(self):
        self.configure(self.state)
        selected = storage_paths.select_storage(self.program)
        self.assertTrue(selected.configured)
        self.assertEqual(selected.child_environment()["DEEPSTEAM_SEPARATE_STORAGE"], "1")
        self.assertEqual(selected.state_root, self.state)
        selected.prepare(selected.deeptutor_home, selected.data, selected.temporary)
        self.assertTrue(selected.deeptutor_home.is_dir())
        self.assertFalse((self.program / "runtime").exists())
        self.assertEqual(selected.openmaic_classrooms, self.state / "runtime" / "openmaic-standalone" / "data" / "classrooms")
        with self.assertRaisesRegex(ValueError, "leaves"):
            selected.prepare(self.program / "outside")

    def test_invalid_roots_are_rejected_without_creating_folders(self):
        invalid = ["relative-data", str(self.program.parent), str(self.program / "nested"),
                   self.state.anchor, "\\\\server\\share\\data", str(self.state / ".." / "elsewhere")]
        for value in invalid:
            self.configure(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                storage_paths.select_storage(self.program)
        self.assertFalse(self.state.exists())

    def test_unknown_config_fields_and_wrong_version_rejected(self):
        for value in ({"version": True, "state_root": str(self.state)},
                      {"version": 1, "state_root": str(self.state), "api_key": "fixture"}):
            (self.program / storage_paths.CONFIG_NAME).write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "version 1"):
                storage_paths.select_storage(self.program)

    def test_existing_reparse_ancestor_rejected(self):
        actual_lstat = Path.lstat
        class Reparse:
            st_mode = stat.S_IFDIR
            st_file_attributes = storage_paths.REPARSE_POINT
        def fake_lstat(path):
            if path == self.state:
                return Reparse()
            return actual_lstat(path)
        with patch.object(Path, "lstat", fake_lstat), self.assertRaisesRegex(ValueError, "reparse"):
            storage_paths.assert_plain_path(self.state / "child")

    def test_child_writable_paths_and_program_assets_remain_separate(self):
        with patch.object(portal_runtime, "STORAGE", self.storage):
            portal = portal_runtime.environment()
        self.assertEqual(portal["EDUAGENT_DATA"], str(self.state / "data"))
        self.assertEqual(portal["TEMP"], str(self.state / "cache" / "temp"))
        with patch.object(openmaic_runtime, "STORAGE", self.storage):
            maic = openmaic_runtime.environment()
        self.assertEqual(maic["OPENMAIC_DATA_DIR"], str(self.storage.openmaic_data))
        self.assertEqual(maic["OPENMAIC_CLASSROOMS_DIR"], str(self.storage.openmaic_classrooms))
        self.assertEqual(maic["TEMP"], str(self.state / "cache" / "openmaic-temp"))
        self.assertEqual(maic["HOSTNAME"], "127.0.0.1")
        ffmpeg = self.program / "runtime" / "ffmpeg" / "bin" / "ffmpeg.exe"
        chrome = self.program / "runtime" / "chromium" / "chrome.exe"
        local = self.storage.render_local(self.program / "runtime" / "render-service")
        with patch.object(render_runtime, "STORAGE", self.storage), patch.object(render_runtime, "LOCAL", local):
            renderer = render_runtime.environment(ffmpeg, chrome, "130.0")
        self.assertEqual(renderer["RENDER_HOME"], str(local))
        self.assertEqual(renderer["PUPPETEER_EXECUTABLE_PATH"], str(chrome))
        self.assertEqual(renderer["FFMPEG_PATH"], str(ffmpeg))

    def test_dt_does_not_inherit_external_workspace_or_keys(self):
        with patch.object(deeptutor_runtime, "STORAGE", self.storage), \
                patch.object(deeptutor_runtime, "HOME", self.storage.deeptutor_home), \
                patch.object(deeptutor_runtime, "CONTENT", self.storage.deeptutor_content), \
                patch.object(deeptutor_runtime, "LOGS", self.storage.logs), \
                patch.object(deeptutor_runtime, "configure_tokenizer_cache"), \
                patch.dict(os.environ, {"DEEPTUTOR_HOME": "fixture-external", "OPENAI_API_KEY": "fixture-secret"}):
            deeptutor_runtime.configure_environment()
            self.assertEqual(os.environ["DEEPTUTOR_HOME"], str(self.storage.deeptutor_home))
            self.assertEqual(os.environ["DEEPTUTOR_WORKSPACE_ROOT"], str(self.storage.deeptutor_content))
            self.assertEqual(os.environ["TEMP"], str(self.storage.temporary))
            self.assertNotIn("OPENAI_API_KEY", os.environ)

    def test_workspace_rebind_preserves_ids_other_fields_and_unrelated_roots(self):
        dbpath = Path(self.temp.name) / "catalog.sqlite3"
        old = self.program / "data" / "deeptutor"
        new = self.storage.deeptutor_content
        class Catalog:
            @contextmanager
            def _catalog_connection(self):
                db = sqlite3.connect(dbpath)
                try:
                    with db:
                        yield db
                finally:
                    db.close()
        catalog = Catalog()
        fixtures = {
            "owned": {"workspace_id": "owned", "kind": "workspace", "path": str(old), "extension": {"preserve": "yes"}},
            "system-id": {"workspace_id": "system-id", "kind": "system", "path": str(old / "outputs" / "system"), "created_at": "fixture-time"},
            "chat-id": {"workspace_id": "chat-id", "kind": "session", "path": str(old / "outputs" / "sessions" / "chat-id"), "note": str(old)},
            "other": {"workspace_id": "other", "kind": "workspace", "path": str(self.program / "elsewhere"), "api_key_ref": "fixture-ref"},
        }
        with catalog._catalog_connection() as db:
            db.execute("CREATE TABLE workspaces (id TEXT PRIMARY KEY,payload TEXT)")
            db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT)")
            db.executemany("INSERT INTO workspaces VALUES (?,?)", [(key, json.dumps(value)) for key, value in fixtures.items()])
            db.execute("INSERT INTO metadata VALUES ('root',?)", (json.dumps(str(old / "outputs")),))
            db.execute("INSERT INTO metadata VALUES ('history',?)", (json.dumps(str(old)),))
        marker = {"workspace_id": "owned", "workspace_path": str(old), "extension": "keep"}
        with patch.object(initialize_deepsteam.runtime, "CONTENT", new):
            self.assertTrue(initialize_deepsteam.rebind_workspace(catalog, marker))
            self.assertFalse(initialize_deepsteam.rebind_workspace(catalog, marker))
        with catalog._catalog_connection() as db:
            rows = {key: json.loads(value) for key, value in db.execute("SELECT id,payload FROM workspaces")}
            metadata = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM metadata")}
        self.assertEqual(rows["owned"]["path"], str(new))
        self.assertEqual(rows["owned"]["extension"], fixtures["owned"]["extension"])
        self.assertEqual(rows["system-id"]["workspace_id"], "system-id")
        self.assertEqual(rows["chat-id"]["path"], str(new / "outputs" / "sessions" / "chat-id"))
        self.assertEqual(rows["chat-id"]["note"], str(old))
        self.assertEqual(rows["other"], fixtures["other"])
        self.assertEqual(metadata["root"], str(new / "outputs"))
        self.assertEqual(metadata["history"], str(old))
        self.assertEqual(marker["workspace_id"], "owned")
        self.assertEqual(marker["extension"], "keep")

    def test_workspace_rebind_rejects_relative_marker_before_opening_database(self):
        marker = {"workspace_id": "fixture-owned", "workspace_path": "relative/data/deeptutor"}
        with self.assertRaisesRegex(ValueError, "absolute content path"):
            initialize_deepsteam.rebind_workspace(None, marker)
        self.assertEqual(marker["workspace_path"], "relative/data/deeptutor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
