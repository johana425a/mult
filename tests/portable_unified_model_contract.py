"""Run with installed portable Python only: no source import path or model call."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def main():
    configured_install = os.environ.get("DEEPSTEAM_TEST_INSTALL")
    if not configured_install:
        raise SystemExit("Set DEEPSTEAM_TEST_INSTALL to the isolated installation being tested.")
    install = Path(configured_install).resolve(strict=True)
    fixture = Path(tempfile.mkdtemp(prefix="portable-model-contract-"))
    os.environ["DEEPTUTOR_HOME"] = str(fixture)
    os.environ["EDUAGENT_DATA"] = str(fixture / "portal")
    os.chdir(fixture)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from integration.unified_model_runtime import UnifiedModelRuntime, install_unified_model_routes
    import integration.unified_model_runtime as installed_bridge
    from deeptutor.api.routers.auth import require_auth
    from deeptutor.services.config import get_model_catalog_service
    from deeptutor.services.config import provider_runtime
    from deeptutor.services.model_selection import runtime
    from deeptutor.services.model_selection.llm import list_llm_options

    expected_site = (install / "runtime/python/Lib/site-packages").resolve()
    assert Path(runtime.__file__).resolve().is_relative_to(expected_site), runtime.__file__
    assert Path(provider_runtime.__file__).resolve().is_relative_to(expected_site), provider_runtime.__file__
    assert Path(installed_bridge.__file__).resolve().is_relative_to(install), installed_bridge.__file__
    assert sys.version_info[:2] == (3, 13), sys.version

    service = get_model_catalog_service()
    catalog = service.load()
    profiles = []
    for name, binding, model, actual in [
        ("codex", "openai_codex", "fixture-codex-model", "fixture-codex-model"),
        ("harness", "openai", "dsroute_fixture", "deepseek-fixture-model"),
        ("api", "openai", "fixture-api-model", "fixture-api-model"),
    ]:
        profiles.append({"id": name, "name": name, "binding": binding,
            "base_url": "https://fixture.invalid/v1", "api_key": "fixture-private-key" if name != "codex" else "",
            "models": [{"id": name + "-ref", "model": model, "name": actual, "actual_model": actual,
                "context_window": 100000, "max_output_tokens": 5000, "context_window_source": "fixture",
                "capabilities": {"tools": True, "vision": name == "codex", "json_output": name != "codex"}}]})
    catalog["services"]["llm"].update(profiles=profiles, active_profile_id="codex", active_model_id="codex-ref")
    service.save(catalog)

    broker = UnifiedModelRuntime()
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    install_unified_model_routes(app, lambda request: None, runtime=broker)
    client = TestClient(app)
    checks = []
    # Block every outgoing provider transport; test HTTP stays inside ASGI.
    async def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected external transport in portable model fixture")
    with patch("httpx.AsyncClient.send", forbidden):
        for surface in ("chat", "learning", "book", "book-qa", "classroom", "workspace"):
            response = client.post("/api/contest/models/resolve", json={"llm_selection": None, "surface": surface})
            assert response.status_code == 200, (surface, response.status_code, response.text)
            snapshot = response.json()["resolved_model"]
            assert snapshot["model"] == "fixture-codex-model"
            assert snapshot["provider"] == "openai_codex"
            assert snapshot["context_window"] == 100000
            assert snapshot["max_output_tokens"] == 5000
            assert "fixture-private-key" not in response.text and "fixture.invalid" not in response.text
            checks.append(surface + ":200")
        for name, expected in (("harness", "deepseek-fixture-model"), ("api", "fixture-api-model")):
            reference = {"profile_id": name, "model_id": name + "-ref"}
            response = client.post("/api/contest/models/resolve", json={"llm_selection": reference})
            assert response.status_code == 200, response.text
            assert response.json()["resolved_model"]["model"] == expected
            assert "dsroute_" not in json.dumps(response.json()["resolved_model"])
            execution = broker.freeze(reference)
            assert execution["model_snapshot"]["resolved_model"]["model"] == expected
            recovered = broker.freeze(model_snapshot=execution["model_snapshot"])
            assert recovered["resolved_model"]["model"] == expected
            checks.append(name + ":override+freeze+recover")
        options = list_llm_options(service.load())
        route = next(item for item in options["options"] if item["profile_id"] == "harness")
        assert route["actual_model"] == "deepseek-fixture-model"
        response = client.post("/api/contest/models/resolve", json={"llm_selection": {}})
        assert response.status_code == 409
        checks.append("malformed:409")
    print(json.dumps({"python": sys.version.split()[0], "runtime_module": runtime.__file__,
        "provider_runtime_module": provider_runtime.__file__, "bridge_module": installed_bridge.__file__,
        "checks": checks, "model_calls": 0, "fixture_directory": str(fixture)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
