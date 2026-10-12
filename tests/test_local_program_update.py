from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "reports/apply_local_model_management_update.py"
spec = spec_from_file_location("local_program_update", SOURCE)
update = module_from_spec(spec)
spec.loader.exec_module(update)


@pytest.mark.parametrize("name", ["../outside.py", "E:/share/new.py", "D:/data/db.sqlite3", "a/../../b", "a\\b"])
def test_program_paths_reject_escape(tmp_path, name):
    with pytest.raises(ValueError):
        update.path_under(tmp_path, name)


@pytest.mark.parametrize("target", ["data/deeptutor/records.sqlite3", "runtime/harness/profile/account.json",
                                   "runtime/native-frontends/v1/sessions/private.json"])
def test_manifest_never_accepts_private_state(tmp_path, monkeypatch, target):
    monkeypatch.setattr(update, "PROJECT", tmp_path / "source")
    monkeypatch.setattr(update, "INSTALL", tmp_path / "install")
    with pytest.raises(ValueError):
        update.validate({"user_data_copied": False, "credentials_copied": False,
                         "files": [{"source": "scripts/helper.py", "target": target}]})


def test_validated_file_is_frozen_before_copy(tmp_path, monkeypatch):
    root = tmp_path / "source"
    source = root / "scripts/helper.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('program only')", encoding="utf-8")
    monkeypatch.setattr(update, "PROJECT", root)
    monkeypatch.setattr(update, "INSTALL", tmp_path / "install")
    row = {"source": "scripts/helper.py", "target": "scripts/helper.py",
           "bytes": source.stat().st_size, "sha256": update.sha(source)}
    manifest = {"user_data_copied": False, "credentials_copied": False, "files": [row]}
    assert len(update.validate(manifest)) == 1
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after"):
        update.validate(manifest)


def test_compiled_profile_route_is_program_code(tmp_path, monkeypatch):
    root = tmp_path / "source"
    name = "runtime/native-frontends/v1/.next-contest-native/server/app/profile/page.js"
    source = root / name
    source.parent.mkdir(parents=True)
    source.write_text("compiled frontend", encoding="utf-8")
    monkeypatch.setattr(update, "PROJECT", root)
    monkeypatch.setattr(update, "INSTALL", tmp_path / "install")
    row = {"source": name, "target": name, "bytes": source.stat().st_size,
           "sha256": update.sha(source)}
    assert len(update.validate({"user_data_copied": False, "credentials_copied": False,
                                "files": [row]})) == 1


@pytest.mark.parametrize("name", ["sidecar.mjs", "workspaces.mjs", "workspace_http.mjs"])
def test_only_reviewed_harness_entrypoints_can_be_updated(tmp_path, monkeypatch, name):
    root = tmp_path / "source"
    source = root / "integration/harness" / name
    source.parent.mkdir(parents=True)
    source.write_text("export const revision = 'verified';", encoding="utf-8")
    monkeypatch.setattr(update, "PROJECT", root)
    monkeypatch.setattr(update, "INSTALL", tmp_path / "install")
    row = {"source": "integration/harness/" + name, "target": "runtime/harness/" + name,
           "bytes": source.stat().st_size, "sha256": update.sha(source)}
    manifest = {"user_data_copied": False, "credentials_copied": False, "files": [row]}
    assert len(update.validate(manifest)) == 1
    row["target"] = "runtime/harness/credentials.mjs"
    with pytest.raises(ValueError, match="unsupported"):
        update.validate(manifest)
