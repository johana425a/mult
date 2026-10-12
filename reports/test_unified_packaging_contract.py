"""Deterministic packaging-scope guards; no build, model, network or services."""
from pathlib import Path
import importlib.util
import unittest

specification = importlib.util.spec_from_file_location("unified_packaging_contract", Path(__file__).with_name("build_unified_r5_candidate.py"))
wrapper = importlib.util.module_from_spec(specification)
specification.loader.exec_module(wrapper)


def receipt():
    return {"kind": "deepsteam-unified-runtime-acceptance", "credentials_included": False,
            "user_data_included": False, "deferred_validation": list(wrapper.DEFERRED_VALIDATION),
            "distribution_ready": True, **{name: True for name in wrapper.REQUIRED_GATES}}


class CurrentPackagingContract(unittest.TestCase):
    def test_all_current_gates_pass_but_deferred_proof_stays_deferred(self):
        result = wrapper.receipt_status(receipt())
        self.assertEqual(result, {"missing_gates": [], "distribution_ready": True})
        self.assertEqual(wrapper.builder.LIVE_GATES, ())
        self.assertNotIn("qwen_guidance_real_model_passed", wrapper.REQUIRED_GATES)

    def test_each_current_gate_is_required(self):
        for name in wrapper.REQUIRED_GATES:
            with self.subTest(gate=name):
                value = receipt()
                value[name] = False
                result = wrapper.receipt_status(value)
                self.assertFalse(result["distribution_ready"])
                self.assertEqual(result["missing_gates"], [name])

    def test_old_live_receipt_cannot_authorize_this_package(self):
        value = receipt()
        value["kind"] = "deepsteam-desktop-harness-acceptance"
        with self.assertRaises(RuntimeError):
            wrapper.receipt_status(value)

    def test_private_state_or_hidden_deferred_checks_block(self):
        for field in ("credentials_included", "user_data_included"):
            value = receipt()
            value[field] = True
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                wrapper.receipt_status(value)
        for name in wrapper.DEFERRED_VALIDATION:
            value = receipt()
            value["deferred_validation"].remove(name)
            with self.subTest(deferred=name), self.assertRaises(RuntimeError):
                wrapper.receipt_status(value)

    def test_root_distribution_permission_is_still_required(self):
        value = receipt()
        value["distribution_ready"] = False
        self.assertFalse(wrapper.receipt_status(value)["distribution_ready"])


if __name__ == "__main__":
    unittest.main()
