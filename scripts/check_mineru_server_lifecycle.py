"""Actual private-server auth/bind/cleanup check; no model inference request."""
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "scripts/mineru_document_worker.py"
spec = importlib.util.spec_from_file_location("worker", path)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
output = ROOT / "runtime/mineru-acceptance/official-server-lifecycle"
output.mkdir(parents=True, exist_ok=True)
worker.configure(output)
events = []
worker.progress = lambda stage, **fields: events.append({"stage": stage, **fields})
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
handle = None
checks = {}
try:
    with worker.portable_vlm_engine("standard", output):
        pid = next(event["process_id"] for event in events if event["stage"] == "local_engine")
        handle = kernel.OpenProcess(0x00100000, False, pid)
        checks["private_owned_process"] = bool(handle)
        command = ("$rows = @(Get-NetTCPConnection -State Listen -OwningProcess " + str(pid)
                   + " -ErrorAction Stop | Select-Object -ExpandProperty LocalAddress); ConvertTo-Json -InputObject $rows -Compress")
        addresses = json.loads(subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", command],
                               creationflags=subprocess.CREATE_NO_WINDOW, text=True))
        checks["loopback_only"] = bool(addresses) and set(addresses) == {"127.0.0.1"}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        endpoint = os.environ["MINERU_MODEL_VLM_SERVER_URL"]
        request = urllib.request.Request(endpoint + "/v1/chat/completions", data=b"{}",
                                         headers={"Content-Type": "application/json"})
        try:
            with opener.open(request, timeout=5):
                checks["unauthenticated_rejected"] = False
        except urllib.error.HTTPError as error:
            checks["unauthenticated_rejected"] = error.code == 401
        request = urllib.request.Request(endpoint + "/v1/models",
                     headers={"Authorization": "Bearer " + os.environ["MINERU_MODEL_VLM_API_KEY"]})
        with opener.open(request, timeout=5) as response:
            checks["authenticated_catalog"] = response.status == 200
    checks["process_stopped_on_context_exit"] = kernel.WaitForSingleObject(handle, 5000) == 0
    checks["ephemeral_key_removed"] = "MINERU_MODEL_VLM_API_KEY" not in os.environ
    checks["no_outbound_attempts"] = len(worker.NETWORK_ATTEMPTS) == 0
finally:
    if handle:
        kernel.CloseHandle(handle)
report = {"passed": all(checks.values()), "checks": checks, "model_inference_requests": 0,
          "private_inputs_used": False, "worker_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
(ROOT / "reports/mineru-official-server-lifecycle.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
raise SystemExit(0 if report["passed"] else 1)
