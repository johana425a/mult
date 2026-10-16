"""Clean up the exact accidental source-only launch, never installed user data."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
assert str(ROOT).lower() == r"d:\eduagent-contest"
assert not (ROOT / "deepsteam-storage.json").exists()
sys.path.insert(0, str(ROOT / "scripts"))
import desktop_runtime
import psutil

EXPECTED = {30316, 2212, 24420, 10420, 40712, 20280, 12640}
PORTS = {8011, 3796, 3795, 3794, 3793, 3792, 3791}
rows = []
for connection in psutil.net_connections(kind="inet"):
    if connection.status == "LISTEN" and connection.laddr.port in PORTS:
        assert connection.pid in EXPECTED
        assert connection.laddr.ip == "127.0.0.1"
        process = psutil.Process(connection.pid)
        identity = desktop_runtime.identity(process)
        assert identity and 1791765440 <= identity["created"] <= 1791765550
        assert "deepsteam-runcache" not in " ".join(process.cmdline()).lower()
        rows.append({"port": connection.laddr.port, **identity})
assert {row["pid"] for row in rows} == EXPECTED
result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts" / "portal_runtime.py"), "stop"], cwd=ROOT, capture_output=True)
assert result.returncode == 0, "source-owned service cleanup failed"
result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts" / "desktop_runtime.py"), "stop-owned", "--claim", "22828-1791765440637"], cwd=ROOT, capture_output=True)
assert result.returncode == 0, "empty source claim cleanup failed"
remaining = [connection.laddr.port for connection in psutil.net_connections(kind="inet") if connection.status == "LISTEN" and connection.laddr.port in PORTS]
report = {"passed": not remaining, "source_root": str(ROOT), "production_state_routing_present": False, "source_only_identities": rows, "remaining_ports": remaining, "claim_removed": not desktop_runtime.claim_file("22828-1791765440637").exists(), "model_inference_requested": False}
(ROOT / "reports" / "origin-migration-accidental-source-cleanup-20261012.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({"passed": report["passed"], "source_owned_processes": len(rows), "remaining_ports": remaining, "claim_removed": report["claim_removed"]}))
