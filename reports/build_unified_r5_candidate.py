"""Build r5-unified only after the root's current software acceptance receipt.

The original startup-fix packager is preserved. Current validation scope does
not invent fresh Qwen/API-key/classroom/second-computer evidence. Calling this
helper without --validate-only performs the full EXE/payload build; the root
must authorize that step separately after its runtime checks.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location("unified_r5_candidate_builder", ROOT / "installer/build_r5_candidate.py")
builder = importlib.util.module_from_spec(specification)
specification.loader.exec_module(builder)
VERSION = "2026.10.11-r5-unified"
REQUIRED_GATES = (
    "current_launch_page_loaded", "all7_owned_loopback_services",
    "exact_managed_global_model_sync", "task_inherit_no_pinned_refs",
    "verified_vision_inherit", "learning_records_preserved",
    "desktop_close_reopen_ownership", "program_manifest_complete_SHA",
    "credentials_user_state_excluded", "core_Harness_real_OS_fixture_tests",
    "one_click_uninstall_fixture_preservation",
)
DEFERRED_VALIDATION = ("new_cloud_inference", "real_api_key", "classroom_generation", "second_pc")


def receipt_status(receipt):
    if receipt.get("kind") != "deepsteam-unified-runtime-acceptance":
        raise RuntimeError("A current root unified-runtime acceptance receipt is required")
    if receipt.get("credentials_included") is not False or receipt.get("user_data_included") is not False:
        raise RuntimeError("Receipt must explicitly exclude credentials and user state")
    deferred = receipt.get("deferred_validation")
    if not isinstance(deferred, list) or not set(DEFERRED_VALIDATION).issubset(deferred):
        raise RuntimeError("Deferred cloud/API-key/classroom/second-PC validation must remain explicit")
    missing = [name for name in REQUIRED_GATES if receipt.get(name) is not True]
    return {"missing_gates": missing,
            "distribution_ready": not missing and receipt.get("distribution_ready") is True}


builder.VERSION = VERSION
builder.REQUIRED_GATES = REQUIRED_GATES
builder.LIVE_GATES = ()
builder.receipt_status = receipt_status


def main():
    if "--allow-pending-live" in sys.argv:
        raise RuntimeError("The unified release cannot bypass an incomplete current software gate")
    builder.main()
    if "--validate-only" in sys.argv:
        return
    # These external distribution reports are not payload inputs. Retain the
    # generic builder's actual hash/CRC/self-test results but label their scope.
    arguments = sys.argv[1:]
    spec_path = ROOT / arguments[arguments.index("--spec") + 1]
    plan = json.loads(spec_path.read_text("utf-8"))
    artifact = ROOT / "installer" / plan["artifact_name"]
    for path in (artifact / "build-report.json", artifact / "release/DeepSteam-Package-Manifest.json"):
        report = json.loads(path.read_text("utf-8"))
        report.update(release_kind="software-validated-release", validation_scope="current runtime/configuration and isolated fixtures",
                      deferred_validation=list(DEFERRED_VALIDATION), fresh_cloud_inference_performed=False,
                      fresh_classroom_generation_performed=False, second_computer_validated=False)
        path.write_bytes(builder.helpers.json_bytes(report))
    print(json.dumps({"version": VERSION, "validation_scope": "software-validated-release",
                      "deferred_validation": list(DEFERRED_VALIDATION),
                      "build_report_sha256": hashlib.sha256((artifact / "build-report.json").read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
