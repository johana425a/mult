"""Boundary tests for the offline tool protocol (no inference downloads)."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

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

    def test_vlm_tier_without_local_model_fails_explicitly_instead_of_downgrading(self):
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(worker, "LLAMA_SERVER", Path(tmp) / "absent.exe"):
            base = Path(tmp)
            source = base / "scan.pdf"
            source.write_bytes(b"%PDF-1.7 synthetic")
            digest = worker.digest(source)
            for tier in ("advanced", "standard"):
                with self.subTest(tier=tier), self.assertRaises(worker.VlmUnavailable):
                    options = {} if tier is None else {"tier": tier}
                    worker.run({"schema_version": 1, "action": "parse", "source_path": str(source),
                                "output_dir": str(base / f"out-{tier}"), "source_sha256": digest,
                                "request_id": "job", "engine_options": options})

    def test_result_identity_names_local_model_backend_and_tier(self):
        identity = worker.inference_identity("advanced", "advanced", ".pdf")
        self.assertEqual(worker.DEFAULT_TIER, "adaptive")
        self.assertEqual(identity["mode"], "local")
        self.assertFalse(identity["remote_api"])
        self.assertTrue(identity["vlm_used"])
        self.assertTrue(identity["image_analysis"])
        self.assertEqual(identity["effort"], "xhigh")
        self.assertEqual(identity["vlm"]["model"], "MinerU2.5-Pro-2605-1.2B")
        self.assertTrue(identity["vlm"]["weights"].startswith("models/mineru/"))
        self.assertIn("llama.cpp", identity["vlm"]["backend"])
        basic = worker.inference_identity("basic", "basic", ".pdf")
        self.assertFalse(basic["vlm_used"])
        office = worker.inference_identity("flash", "advanced", ".docx")
        self.assertFalse(office["vlm_used"])
        self.assertIn("natively", office["vlm_not_applicable"])

    @unittest.skipUnless(importlib.util.find_spec("mineru") is not None, "MinerU library not installed")
    def test_vlm_config_only_addresses_loopback(self):
        config = worker.loopback_vlm_config({"endpoint": "http://127.0.0.1:41234", "api_key": "k", "alias": worker.VLM_ALIAS})
        self.assertEqual(config.engine, "llama-cpp")
        self.assertEqual(config.model, worker.VLM_ALIAS)
        for endpoint in ("https://mineru.net", "http://10.0.0.5:8000", "http://localhost.example:1", ""):
            with self.subTest(endpoint=endpoint), self.assertRaises(worker.VlmUnavailable):
                worker.loopback_vlm_config({"endpoint": endpoint, "api_key": "k", "alias": "x"})


    def test_serve_loop_answers_each_request_on_its_own_line(self):
        lines = [json.dumps({"request_id": "a"}) + "\n", "\n", "not json\n", json.dumps(["list"]) + "\n",
                 json.dumps({"request_id": "b"}) + "\n"]
        protocol = io.StringIO()
        worker.serve_loop(lines, protocol, lambda request: {"ok": True, "request_id": request["request_id"]})
        replies = [json.loads(line) for line in protocol.getvalue().splitlines()]
        self.assertEqual([reply.get("request_id") for reply in replies], ["a", "", "", "b"])
        self.assertEqual([reply["ok"] for reply in replies], [True, False, False, True])

    def test_serving_process_keeps_running_between_requests(self):
        # Real --serve process; requests are invalid on purpose, so no model runs.
        with tempfile.TemporaryDirectory() as tmp:
            process = subprocess.Popen([sys.executable, "-I", "-B", str(ROOT / "scripts/mineru_document_worker.py"),
                                        "--serve", "--home", str(Path(tmp) / "home")],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                replies = []
                for request_id in ("first", "second"):
                    process.stdin.write((json.dumps({"schema_version": 1, "action": "parse", "source_path": "relative.pdf",
                                                     "output_dir": "relative", "request_id": request_id}) + "\n").encode())
                    process.stdin.flush()
                    replies.append(json.loads(process.stdout.readline()))
                process.stdin.close()
                self.assertEqual(process.wait(timeout=30), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.stdout.close()
        self.assertEqual([reply["request_id"] for reply in replies], ["first", "second"])
        self.assertTrue(all(reply["ok"] is False and reply["error"]["code"] == "parse_failed" for reply in replies))

    def test_shared_engine_starts_the_vlm_server_once_and_restarts_after_exit(self):
        started = []

        class Process:
            code = None

            def poll(self):
                return self.code

        @contextlib.contextmanager
        def engine(tier, home):
            if tier not in worker.VLM_TIERS:
                yield {"vlm": False}
                return
            process = Process()
            started.append(process)
            yield {"vlm": True, "n_parallel": 2, "_process": process}

        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(worker, "portable_vlm_engine", engine):
            shared = worker.SharedVlmEngine(Path(tmp))
            for tier in ("advanced", "advanced", "standard"):
                with shared.lease(tier) as policy:
                    self.assertTrue(policy["vlm"])
            self.assertEqual(len(started), 1)  # one server for many batches and both VLM tiers
            started[0].code = 1
            with shared.lease("advanced"):
                pass
            self.assertEqual(len(started), 2)  # an exited server is replaced
            with shared.lease("basic") as policy:
                self.assertFalse(policy["vlm"])
            shared.close()
        self.assertEqual(len(started), 2)

    def test_parallel_slots_share_one_kv_buffer_and_fall_back_to_one_slot(self):
        args = worker.server_args(1234, 2, 4)
        self.assertEqual(args[args.index("--parallel") + 1], "2")
        self.assertIn("--kv-unified", args)
        self.assertNotIn("--kv-unified", worker.server_args(1234, 1, 4))
        launched = []

        class Process:
            pid = 4242

            def __init__(self, args, **kwargs):
                launched.append(args)
                self.code = None

            def poll(self):
                return self.code

            def kill(self):
                self.code = -9

            def wait(self, timeout=None):
                return self.code

        def ready(process, endpoint, key):
            slots = launched[-1][launched[-1].index("--parallel") + 1]
            if slots != "1":
                raise worker.EngineStartupFailed("synthetic: this build refuses parallel slots")

        with tempfile.TemporaryDirectory() as tmp, \
                unittest.mock.patch.object(worker, "require_vlm_assets"), \
                unittest.mock.patch.object(worker, "choose_device", return_value={"kind": "cpu", "reason": "synthetic"}), \
                unittest.mock.patch.object(worker.subprocess, "Popen", Process), \
                unittest.mock.patch.object(worker, "wait_until_ready", ready), \
                unittest.mock.patch.object(worker, "VLM_PARALLEL", 2):
            with worker.portable_vlm_engine("advanced", Path(tmp)) as policy:
                self.assertEqual(policy["n_parallel"], 1)
                self.assertIn("parallel_fallback", policy)
                self.assertEqual(policy["engine"], "official-llama.cpp-b11541")
        self.assertEqual([args[args.index("--parallel") + 1] for args in launched], ["2", "1"])

    def test_decoding_slots_are_bounded(self):
        for value in (0, 5, True, "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                worker.set_vlm_parallel(value)
        with unittest.mock.patch.object(worker, "VLM_PARALLEL", 3):
            self.assertEqual(worker.vlm_parallel(), 3)

    @unittest.skipUnless(importlib.util.find_spec("mineru") is not None, "MinerU library not installed")
    def test_client_concurrency_matches_server_slots(self):
        policy = {"endpoint": "http://127.0.0.1:41234", "api_key": "k", "alias": worker.VLM_ALIAS}
        self.assertEqual(worker.loopback_vlm_config({**policy, "n_parallel": 2}).max_concurrency, 2)
        self.assertEqual(worker.loopback_vlm_config(policy).max_concurrency, 1)

    def test_measured_vlm_use_distinguishes_tier_from_actual_inference(self):
        idle = {"prompt_tokens": 0, "generated_tokens": 0, "prompt_seconds": 0.0, "generation_seconds": 0.0}
        identity = worker.inference_identity("standard", "standard", ".pdf", {"device": "cpu"}, idle)
        self.assertTrue(identity["vlm_tier"])
        self.assertFalse(identity["vlm_used"])  # text layer: the hybrid tier needed no VLM call
        self.assertTrue(identity["vlm_use_measured"])
        used = worker.inference_identity("standard", "standard", ".pdf", {}, {**idle, "prompt_tokens": 831, "generated_tokens": 738})
        self.assertTrue(used["vlm_used"])
        self.assertEqual(used["vlm_usage"]["generated_tokens"], 738)
        self.assertEqual(worker.vlm_usage({"prompt_tokens_total": 10.0, "tokens_predicted_total": 5.0},
                                          {"prompt_tokens_total": 40.0, "tokens_predicted_total": 25.0})["generated_tokens"], 20)
        self.assertIsNone(worker.vlm_usage(None, {}))

    def test_adaptive_escalates_only_tables_and_display_formulas(self):
        structured = {"pages": [
            {"page_idx": 0, "blocks": [{"type": "text"}, {"type": "header"}]},
            {"page_idx": 1, "blocks": [{"type": "text"}, {"type": "equation"}]},
            {"page_idx": 2, "blocks": [{"type": "table"}, {"type": "chart"}]},
            {"page_idx": 3, "blocks": [{"type": "image"}, {"type": "text"}]}]}
        pages, figures = worker.complex_layout_pages(structured)
        self.assertEqual(pages, {1: ["equation"], 2: ["table"]})
        self.assertEqual(figures, [2, 3])

    def test_escalated_pages_replace_basic_units_with_original_locators(self):
        def unit(page_idx, text, asset=None):
            locator = {"kind": "pdf_page", "page": page_idx + 1, "page_idx": page_idx}
            assets = [{"id": "x", "relative_path": asset, "locator": locator}] if asset else []
            return {"index": page_idx, "locator": locator, "text": text, "assets": assets, "equations": [], "tables": [],
                    "coverage": {"status": "processed"}}
        normalized = {"units": [unit(0, "basic 1"), unit(1, "basic 2"), unit(2, "basic 3")], "assets": [], "warnings": [],
                      "coverage": {"processed_units": 3}}
        escalated = {"units": [unit(0, "vlm 2", "images/t.png"), unit(1, "vlm 3")],
                     "warnings": [{"code": "recognized_region_without_text", "locator": {"page": 2, "page_idx": 1}}]}
        replaced = worker.merge_escalated(normalized, escalated, [1, 2], {1: ["equation"], 2: ["table"]}, "vlm/")
        self.assertEqual(replaced, [1, 2])
        self.assertEqual([u["text"] for u in normalized["units"]], ["basic 1", "vlm 2", "vlm 3"])
        self.assertEqual([u["coverage"]["parsed_with"] for u in normalized["units"]], ["basic", "standard", "standard"])
        self.assertEqual(normalized["units"][1]["locator"], {"kind": "pdf_page", "page": 2, "page_idx": 1})
        self.assertEqual(normalized["units"][1]["assets"][0]["relative_path"], "vlm/images/t.png")
        self.assertEqual(normalized["units"][1]["assets"][0]["locator"]["page"], 2)
        self.assertEqual(normalized["warnings"][0]["locator"], {"page": 3, "page_idx": 2})
        self.assertEqual(normalized["units"][2]["coverage"]["escalation_reasons"], ["table"])

    def test_complex_pages_without_local_vlm_stay_basic_with_a_visible_warning(self):
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(worker, "LLAMA_SERVER", Path(tmp) / "absent.exe"):
            normalized = {"units": [{"index": 0, "locator": {"page": 1, "page_idx": 0}, "text": "t", "coverage": {}}],
                          "warnings": [], "assets": [], "coverage": {}}
            record = worker.escalate_complex_pages(Path(tmp) / "x.pdf", Path(tmp), ".pdf",
                                                   {"pages": [{"page_idx": 0, "blocks": [{"type": "table"}]}]}, normalized, None, None)
        self.assertEqual(record["vlm_pages"], [])
        self.assertEqual(normalized["warnings"][0]["code"], "vlm_escalation_unavailable")
        self.assertEqual(normalized["warnings"][0]["pages"], [1])
        self.assertTrue(normalized["units"][0]["coverage"]["requires_vlm_review"])

    def test_vulkan_device_list_is_parsed_from_llama_server(self):
        output = (b"Available devices:\n  Vulkan0: NVIDIA GeForce RTX 3060 (12288 MiB, 11010 MiB free)\n"
                  b"  Vulkan1: Intel(R) UHD Graphics 770 (8045 MiB, 7900 MiB free)\n")
        completed = subprocess.CompletedProcess([], 0, stdout=output, stderr=b"")
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "llama-server"
            exe.write_bytes(b"")
            with unittest.mock.patch.object(worker, "LLAMA_SERVER_VULKAN", exe), \
                    unittest.mock.patch.object(worker.subprocess, "run", return_value=completed):
                devices = worker.vulkan_devices()
        self.assertEqual([device["id"] for device in devices], ["Vulkan0", "Vulkan1"])
        self.assertEqual(devices[0], {"id": "Vulkan0", "name": "NVIDIA GeForce RTX 3060", "memory_mib": 12288, "free_mib": 11010})

    def test_gpu_is_chosen_only_when_real_and_large_enough(self):
        rtx = {"id": "Vulkan0", "name": "NVIDIA GeForce RTX 3060", "memory_mib": 12288, "free_mib": 11010}
        igpu = {"id": "Vulkan1", "name": "Intel(R) UHD Graphics 770", "memory_mib": 8045, "free_mib": 7900}
        soft = {"id": "Vulkan0", "name": "llvmpipe (LLVM 20.1.2, 256 bits)", "memory_mib": 15000, "free_mib": 15000}
        small = {"id": "Vulkan0", "name": "Old GPU", "memory_mib": 1024, "free_mib": 900}
        with tempfile.TemporaryDirectory() as tmp:
            home, exe = Path(tmp), Path(tmp) / "llama-server"
            with unittest.mock.patch.object(worker, "LLAMA_SERVER_VULKAN", exe):
                self.assertEqual(worker.choose_device(home)["reason"], "Vulkan build not installed")
                exe.write_bytes(b"")
                cases = [([rtx, igpu], "Vulkan0"), ([igpu], "Vulkan1"), ([soft], None), ([small], None), ([], None)]
                for devices, expected in cases:
                    with self.subTest(devices=[d["name"] for d in devices]), \
                            unittest.mock.patch.object(worker, "vulkan_devices", return_value=devices):
                        choice = worker.choose_device(home)
                        self.assertEqual(choice.get("id"), expected)
                        self.assertEqual(choice["kind"], "vulkan" if expected else "cpu")
                with unittest.mock.patch.object(worker, "vulkan_devices", return_value=[soft]), \
                        unittest.mock.patch.object(worker, "VLM_DEVICE", "vulkan"):
                    self.assertEqual(worker.choose_device(home)["kind"], "vulkan")  # diagnostics only
                with unittest.mock.patch.object(worker, "vulkan_devices", return_value=[rtx]):
                    with unittest.mock.patch.object(worker, "VLM_DEVICE", "cpu"):
                        self.assertEqual(worker.choose_device(home)["kind"], "cpu")
                    worker.mark_gpu_failed(home, "synthetic crash")
                    self.assertIn("GPU failed recently", worker.choose_device(home)["reason"])

    def test_gpu_server_offloads_everything_and_cpu_server_offloads_nothing(self):
        device = {"kind": "vulkan", "id": "Vulkan1", "name": "GPU", "memory_mib": 8000, "free_mib": 7000}
        gpu = worker.server_args(1234, 1, 4, device)
        self.assertEqual(gpu[0], str(worker.LLAMA_SERVER_VULKAN))
        self.assertEqual(gpu[gpu.index("--device") + 1], "Vulkan1")
        self.assertEqual(gpu[gpu.index("--n-gpu-layers") + 1], "99")
        self.assertNotIn("--no-mmproj-offload", gpu)
        cpu = worker.server_args(1234, 1, 4, {"kind": "cpu"})
        self.assertEqual(cpu[0], str(worker.LLAMA_SERVER))
        self.assertNotIn("--device", cpu)
        self.assertIn("--no-mmproj-offload", cpu)
        self.assertEqual(cpu, worker.server_args(1234, 1, 4))

    def test_gpu_that_fails_to_start_falls_back_to_the_cpu_build(self):
        launched = []

        class Process:
            pid = 7

            def __init__(self, args, **kwargs):
                launched.append(args)
                self.code = None

            def poll(self):
                return self.code

            def kill(self):
                self.code = -9

            def wait(self, timeout=None):
                return self.code

        def ready(process, endpoint, key):
            if launched[-1][0] == str(worker.LLAMA_SERVER_VULKAN):
                raise worker.EngineStartupFailed("synthetic: driver refused")

        device = {"kind": "vulkan", "id": "Vulkan0", "name": "Synthetic GPU", "memory_mib": 8000, "free_mib": 7000}
        with tempfile.TemporaryDirectory() as tmp, \
                unittest.mock.patch.object(worker, "require_vlm_assets"), \
                unittest.mock.patch.object(worker, "choose_device", return_value=device), \
                unittest.mock.patch.object(worker.subprocess, "Popen", Process), \
                unittest.mock.patch.object(worker, "wait_until_ready", ready), \
                unittest.mock.patch.object(worker, "VLM_PARALLEL", 1):
            with worker.portable_vlm_engine("standard", Path(tmp)) as policy:
                self.assertEqual(policy["device"], "cpu")
                self.assertIn("Synthetic GPU did not start", policy["gpu_status"])
            self.assertTrue((Path(tmp) / "gpu-unavailable.json").is_file())
        self.assertEqual([args[0] for args in launched], [str(worker.LLAMA_SERVER_VULKAN), str(worker.LLAMA_SERVER)])
        identity = worker.inference_identity("standard", "standard", ".pdf", {"device": "vulkan", "gpu": "Synthetic GPU"})
        self.assertIn("(Vulkan)", identity["vlm"]["backend"])
        self.assertEqual(identity["vlm"]["gpu"], "Synthetic GPU")

if __name__ == "__main__":
    unittest.main()
