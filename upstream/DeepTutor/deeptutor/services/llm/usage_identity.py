"""Small public identifier contract for usage records; no transport secrets."""
from __future__ import annotations

import re
from typing import Any


def safe_usage_identifier(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if (value.lower().startswith(("dsroute_", "dsexec_", "sk-", "bearer", "http:", "https:"))
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,191}", value)):
        return ""
    return value


def dispatch_usage_identity(model: str, provider: str) -> dict[str, str]:
    """Resolve only this exact dispatch; unrelated task-model overrides stay separate."""
    public_model, public_provider = model, provider
    try:
        from .config import get_llm_config
        from deeptutor.services.model_selection.runtime import resolved_model_snapshot

        config = get_llm_config()
        if model == config.model:
            snapshot = resolved_model_snapshot(config)
            public_model = snapshot.get("model", "")
            public_provider = snapshot.get("provider", "")
    except Exception:
        # Accounting cannot break a successful provider call. The sanitizer still
        # strips a private route if its public configuration is unavailable.
        pass
    resolved_model = safe_usage_identifier(public_model)
    return {
        "requested_model_id": safe_usage_identifier(model) or resolved_model,
        "resolved_model_id": resolved_model,
        "resolved_provider_id": safe_usage_identifier(public_provider),
        "model_identity_source": "dispatch" if resolved_model else "unknown",
    }
