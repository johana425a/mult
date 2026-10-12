"""Book-owned model references and public provenance, never credentials.

DeepSteam modification: a book is a durable generation task. Its default is
resolved when accepted; later worker requests restore that concrete choice.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from deeptutor.services.model_selection.llm import LLMSelection
from deeptutor.services.model_selection.runtime import (
    reset_llm_selection,
    resolve_model_selection,
)

_BOOK_MODEL: ContextVar[dict[str, Any] | None] = ContextVar("book_model", default=None)


def normalize_book_selection(value: Any) -> dict[str, str] | None:
    selection = LLMSelection.from_payload(value)
    return selection.to_dict() if selection else None


def current_book_model() -> dict[str, Any] | None:
    """Public snapshot of the generation scope, safe for events and storage."""
    value = _BOOK_MODEL.get()
    return dict(value) if value else None


@contextmanager
def book_model_scope(book=None, *, selection: Any = None):
    """Restore a saved task reference without inheriting another request.

    The catalog can rotate credentials. If the model or its execution settings
    change, stop instead of silently changing an accepted task.
    """
    requested = normalize_book_selection(book.llm_selection if book else selection)
    metadata = book.metadata if book else {}
    frozen = metadata.get("generation_model_selection")
    previous = metadata.get("generation_model")
    config, frozen, public = resolve_model_selection(
        normalize_book_selection(frozen) if isinstance(previous, dict) else requested
    )
    if config.reasoning_effort:
        frozen["reasoning_effort"] = config.reasoning_effort
    from deeptutor.services.llm.config import set_scoped_llm_config

    token = set_scoped_llm_config(config)
    try:
        if isinstance(previous, dict) and any(
            key in previous and previous.get(key) != public.get(key)
            for key in ("provider", "model", "reasoning_effort", "configuration_revision")
        ):
            raise ValueError(
                "The saved book model changed. Choose its model again before continuing."
            )
        public["selection_source"] = "override" if requested else "default"
        state = {"selection": frozen, "resolved_model": public}
        scope_token = _BOOK_MODEL.set(public)
        try:
            yield state
        finally:
            _BOOK_MODEL.reset(scope_token)
    finally:
        reset_llm_selection(token)


def apply_book_model_snapshot(book, state: dict[str, Any]) -> None:
    book.metadata = {
        **book.metadata,
        "generation_model_selection": state["selection"],
        "generation_model": state["resolved_model"],
    }
