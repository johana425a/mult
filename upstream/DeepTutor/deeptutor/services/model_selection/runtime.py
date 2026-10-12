"""Runtime helpers for request-scoped model selection."""

from __future__ import annotations

from contextvars import Token
from copy import deepcopy
import hashlib
import json
from typing import Any

from deeptutor.services.config.provider_runtime import ResolvedLLMConfig, resolve_llm_runtime_config
from deeptutor.services.llm import config as llm_config_module
from deeptutor.services.llm.config import LLMConfig


def llm_config_from_resolved(resolved: ResolvedLLMConfig) -> LLMConfig:
    """Convert provider-runtime output into the LLM service config shape."""
    return LLMConfig(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        effective_url=resolved.effective_url,
        binding=resolved.binding,
        provider_name=resolved.provider_name,
        provider_mode=resolved.provider_mode,
        api_version=resolved.api_version,
        extra_headers=resolved.extra_headers,
        wire_api=resolved.wire_api,
        api_format=resolved.api_format,
        reasoning_effort=resolved.reasoning_effort,
        context_window=resolved.context_window,
        display_model=resolved.display_model,
        context_window_source=resolved.context_window_source,
        max_output_tokens=resolved.max_output_tokens,
        capabilities=resolved.capabilities,
    )


def resolve_llm_config_for_selection(selection: Any) -> LLMConfig:
    """Resolve the LLM config for a chat/session selection reference."""
    if selection is None:
        return llm_config_module.get_llm_config()
    return llm_config_from_resolved(resolve_llm_runtime_config(llm_selection=selection))


def activate_llm_selection(selection: Any) -> tuple[LLMConfig, Token[LLMConfig | None]]:
    """Resolve and install a scoped LLM config for the current async context."""
    config = resolve_llm_config_for_selection(selection)
    token = llm_config_module.set_scoped_llm_config(config)
    return config, token


def reset_llm_selection(token: Token[LLMConfig | None] | None) -> None:
    if token is not None:
        llm_config_module.reset_scoped_llm_config(token)


def resolved_model_snapshot(config: LLMConfig, selection: Any = None) -> dict[str, Any]:
    """Public dispatch identity; never includes transport routes or credentials."""
    from deeptutor.services.llm.capabilities import supports_tools, supports_vision, supports_response_format
    from deeptutor.services.provider_registry import find_by_name

    model = str(getattr(config, "display_model", None) or config.model or "")
    provider = str(config.provider_name or config.binding or "")
    if str(config.model).startswith("dsroute_"):
        provider = "deepseek"
        if model.startswith("dsroute_"):
            model = ""
    spec = find_by_name(provider)
    declared = getattr(config, "capabilities", None) or {}
    value = {
        "provider": provider,
        "provider_label": spec.label if spec else provider,
        "model": model,
        "model_name": model,
        "selection_source": "override" if selection else "default",
        "reasoning_effort": config.reasoning_effort,
        "capabilities": {
            "tools": declared.get("tools", supports_tools(config.binding, model)),
            "vision": declared.get("vision", supports_vision(config.binding, model)),
            "json_output": declared.get("json_output", supports_response_format(config.binding, model)),
        },
    }
    for key in ("context_window", "max_output_tokens", "context_window_source"):
        item = getattr(config, key, None)
        if item is not None:
            value[key] = item
    value["configuration_revision"] = hashlib.sha256(json.dumps({
        "model": config.model, "binding": config.binding, "provider": config.provider_name,
        "base_url": config.base_url, "api_format": config.api_format,
        "effective_url": config.effective_url, "api_version": config.api_version,
        "wire_api": config.wire_api, "max_output_tokens": config.max_output_tokens,
        # Authentication may rotate without changing dispatch identity. Routing
        # headers affect the destination/configuration and must invalidate resume.
        "routing_headers": {key: val for key, val in (config.extra_headers or {}).items()
                            if not any(word in key.lower() for word in
                                       ("authorization", "token", "key", "secret", "cookie", "credential", "password", "signature"))},
        "reasoning_effort": config.reasoning_effort, "capabilities": value["capabilities"],
        "context_window": config.context_window,
    }, sort_keys=True).encode()).hexdigest()[:24]
    return value


def resolve_model_selection(selection: Any = None) -> tuple[LLMConfig, dict[str, str], dict[str, Any]]:
    """Validate one catalog reference, resolve defaults now, and freeze the config.

    Consumers keep the concrete reference for recovery and the public snapshot
    for history. The mutable global default is never changed by a task override.
    """
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.model_access import allowed_llm_options, apply_allowed_llm_selection
    from deeptutor.services.config import get_model_catalog_service
    from deeptutor.services.model_selection.llm import LLMSelection, list_llm_options

    if selection is not None and (not isinstance(selection, (dict, LLMSelection))
            or isinstance(selection, dict) and (set(selection) - {"profile_id", "model_id", "reasoning_effort"}
                or any(not isinstance(selection.get(key), str) or not selection[key].strip()
                       for key in ("profile_id", "model_id")))):
        raise ValueError("Invalid model selection reference")
    parsed = LLMSelection.from_payload(selection)
    requested = parsed.to_dict() if parsed else None
    options = (list_llm_options(get_model_catalog_service().load())
               if get_current_user().is_admin else allowed_llm_options())
    concrete = requested or options.get("active")
    if not concrete:
        raise ValueError("Select a default model first.")
    concrete = apply_allowed_llm_selection(concrete)
    config = deepcopy(resolve_llm_config_for_selection(concrete))
    if str(config.model).startswith("dsexec_") or "/api/contest/internal/model/" in str(config.base_url or ""):
        raise ValueError("A model configuration cannot reference a temporary task connection. Select the original model.")
    snapshot = resolved_model_snapshot(config, requested)
    if not snapshot["model"]:
        raise ValueError("The actual model identity is not configured. Reselect the model connection.")
    return config, dict(concrete), snapshot


__all__ = [
    "activate_llm_selection",
    "llm_config_from_resolved",
    "reset_llm_selection",
    "resolve_llm_config_for_selection",
    "resolved_model_snapshot",
    "resolve_model_selection",
]
