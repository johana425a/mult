"""Migration for DeepSteam's retired bundled chat model; never seeds a model.

Old identities are retained only to recognize product-owned settings. User
providers, encrypted credentials and model identities in history are preserved.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

LOCAL_BASE_URL = "http://127.0.0.1:3795/v1"
LOCAL_MODEL = "qwen3.5-4b-local"
LOCAL_PROFILE_ID = "deepsteam-local-qwen"
LOCAL_MODEL_ID = "deepsteam-qwen35-4b"
LOCAL_LABEL = "Retired bundled local model"
RETIRED_MODEL_CODE = "bundled_model_removed"
RETIRED_MODEL_MESSAGE = "The bundled local model was removed. Sign in to DeepSeek or choose a configured model. History is retained."


def is_local_provider(config: dict[str, Any]) -> bool:
    """Match the former product endpoint/model, not a generic Qwen provider."""
    if config.get("model") != LOCAL_MODEL:
        return False
    try:
        url = urlsplit(str(config.get("base_url", "")))
        return (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}
                and url.port == 3795 and url.path.rstrip("/") == "/v1"
                and not (url.username or url.password or url.query or url.fragment))
    except ValueError:
        return False


def execution_provider(settings: dict[str, Any]) -> dict[str, Any]:
    """Resolve an explicit API, with no implicit local or cloud fallback."""
    if settings.get("model_mode") == "local" or is_local_provider(settings):
        raise ValueError(RETIRED_MODEL_MESSAGE)
    base_url, model = str(settings.get("base_url", "")).strip(), str(settings.get("model", "")).strip()
    if settings.get("connection_mode") == "unconfigured" or not base_url or not model:
        raise ValueError("Connect or choose a model first.")
    return {"base_url": base_url, "model": model,
            "api_key": settings.get("api_key", ""), "provider_type": "openai"}


def local_profile() -> dict[str, Any]:
    """Stale callers must not recreate the retired profile."""
    raise ValueError(RETIRED_MODEL_MESSAGE)


def retire_bundled_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """Retire only the exact owned model; keep added models in its profile."""
    result = deepcopy(catalog)
    service = result.get("services", {}).get("llm", {})
    profiles = service.get("profiles", [])
    for profile in list(profiles):
        if profile.get("id") != LOCAL_PROFILE_ID:
            continue
        owned = [model for model in profile.get("models", [])
                 if model.get("id") == LOCAL_MODEL_ID and is_local_provider({
                     "base_url": profile.get("base_url"), "model": model.get("model")})]
        if not owned:
            continue
        if (service.get("active_profile_id") == LOCAL_PROFILE_ID
                and service.get("active_model_id") in (None, "", LOCAL_MODEL_ID)):
            service.update(active_profile_id=None, active_model_id=None,
                           selection_required=RETIRED_MODEL_CODE)
        profile["models"] = [model for model in profile.get("models", []) if model not in owned]
        if not profile["models"]:
            profiles.remove(profile)
    return result


def retire_native_local_model() -> dict[str, Any]:
    from deeptutor.services.config import get_model_catalog_service
    service = get_model_catalog_service()
    current = service.load()
    proposed = retire_bundled_catalog(current)
    if proposed != current:
        service.apply(proposed)
    return {"retired": True, "changed": proposed != current,
            "selection_required": proposed.get("services", {}).get("llm", {}).get("selection_required")}
