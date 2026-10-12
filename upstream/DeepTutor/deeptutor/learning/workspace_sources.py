"""DeepSteam bounded document grounding within the trusted content workspace.

Source metadata identifies a document; it never authorizes a root or switches
the active workspace. Text and provenance come only from the document reader.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any

from deeptutor.learning.models import TopicSource
from deeptutor.services.workspace.context import current_workspace_id

MAX_DOCUMENT_CHARS = 24_000
MAX_DOCUMENT_UNITS = 8
_LOCATOR_KEYS = {
    "page",
    "page_kind",
    "slide",
    "paragraph",
    "table",
    "line_start",
    "line_end",
    "unit",
    "sheet",
    "row",
    "image",
    "part",
    "section",
}


def _trusted_workspace_id() -> str:
    current = current_workspace_id()
    if current:
        return current
    from deeptutor.services.workspace import get_content_workspace_service

    return get_content_workspace_service().general_binding().workspace_id


def _locator(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - _LOCATOR_KEYS:
        raise ValueError("workspace_document_locator_invalid")
    result = {}
    for key, item in value.items():
        if key == "page_kind":
            if item != "pdf_physical":
                raise ValueError("workspace_document_locator_invalid")
        elif key in {"sheet", "part", "section"}:
            if not isinstance(item, str) or not item or len(item) > 200:
                raise ValueError("workspace_document_locator_invalid")
        elif type(item) is not int or item < 1:
            raise ValueError("workspace_document_locator_invalid")
        result[key] = item
    return result


def validate_workspace_source(source: TopicSource) -> dict[str, Any]:
    """Resolve identity from the active trusted context, never source origins."""
    metadata = source.metadata or {}
    trusted = _trusted_workspace_id()
    if metadata.get("workspace_id") != trusted:
        raise ValueError("workspace_document_scope_mismatch")
    if metadata.get("content_workspace_id", trusted) not in {trusted, current_workspace_id()}:
        raise ValueError("workspace_document_scope_mismatch")
    if any(key in metadata for key in ("root", "workspace_root", "absolute_path")):
        raise ValueError("workspace_document_root_not_allowed")
    path = metadata.get("path")
    if not isinstance(path, str) or not path or len(path) > 2048 or "\x00" in path:
        raise ValueError("workspace_document_path_invalid")
    windows = PureWindowsPath(path)
    if windows.drive or windows.root or ".." in windows.parts or ":" in path:
        raise ValueError("workspace_document_path_invalid")
    path = PurePosixPath(path.replace("\\", "/")).as_posix()
    if path == ".":
        raise ValueError("workspace_document_path_invalid")
    digest = metadata.get("document_sha256")
    if digest is not None and (
        not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)
    ):
        raise ValueError("workspace_document_hash_invalid")
    return {
        "workspace_id": trusted,
        "content_workspace_id": current_workspace_id(),
        "path": path,
        **({"document_sha256": digest.lower()} if digest else {}),
        **({"locator": _locator(metadata["locator"])} if metadata.get("locator") else {}),
    }


async def _read_document(workspace_id: str, **request) -> dict[str, Any]:
    from integration.workspace_documents import document_request

    return await document_request(workspace_id, "read", **request)


async def _list_documents(workspace_id: str) -> dict[str, Any]:
    from integration.workspace_documents import document_request

    return await document_request(workspace_id, "list", path=".", depth=2, limit=24)


async def workspace_inventory() -> dict[str, Any]:
    """Name a small custom-workspace inventory without claiming bodies were read."""
    workspace_id = current_workspace_id()
    if not workspace_id:
        return {}
    inventory: dict[str, Any] = {
        "kind": "workspace_inventory",
        "workspace_id": workspace_id,
        "documents": [],
        "document_bodies_read": False,
        "partial": True,
        "note": "No workspace documents were selected or read. File names alone are not evidence. Ask the learner to select files before teaching from their local documents; do not describe or quote unread contents.",
    }
    try:
        result = await _list_documents(workspace_id)
        if not result.get("ok"):
            return inventory
        entries = result.get("entries") or []
        names = []
        for entry in entries[:24]:
            path = entry.get("path")
            if entry.get("is_dir") or not isinstance(path, str):
                continue
            windows = PureWindowsPath(path)
            if (
                windows.drive
                or windows.root
                or ".." in windows.parts
                or ":" in path
                or "\x00" in path
            ):
                continue
            names.append(path[:2048])
        inventory["documents"] = names
        inventory["inventory_truncated"] = bool(result.get("truncated") or len(entries) > 24)
    except Exception:
        # A missing local reader is explicit, never permission to invent text.
        inventory["inventory_unavailable"] = True
    return inventory


async def ground_workspace_source(source: TopicSource, *, max_chars: int = 4_000) -> TopicSource:
    """Read one bounded slice; never trust supplied excerpts or prior read flags."""
    grounded = source.model_copy(deep=True)
    grounded.excerpt = ""
    grounded.available = False
    metadata: dict[str, Any] = {}
    try:
        metadata = validate_workspace_source(source)
        grounded.source_id = metadata["path"]
        limit = max(0, min(int(max_chars), MAX_DOCUMENT_CHARS))
        if limit < 512:
            raise ValueError("workspace_document_budget_exhausted")
        requested_locator = metadata.get("locator", {})
        start = next(
            (
                requested_locator[key]
                for key in ("unit", "page", "slide", "line_start")
                if key in requested_locator
            ),
            None,
        )
        # DOCX paragraphs and tables have separate counters, not page numbers.
        if requested_locator and start is None:
            raise ValueError("workspace_document_locator_requires_unit")
        request = {"path": metadata["path"], "max_chars": limit, "max_units": MAX_DOCUMENT_UNITS}
        if start is not None:
            request["start_unit"] = start
        if metadata.get("document_sha256"):
            request["document_sha256"] = metadata["document_sha256"]
        result = await _read_document(metadata["workspace_id"], **request)
        if not result.get("ok"):
            raise ValueError("workspace_document_unavailable")
        if (
            result.get("workspace_id", metadata["workspace_id"]) != metadata["workspace_id"]
            or result.get("path") != metadata["path"]
        ):
            raise ValueError("workspace_document_identity_mismatch")
        document = result.get("document") or {}
        digest = document.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            raise ValueError("workspace_document_hash_unavailable")
        if metadata.get("document_sha256", digest.lower()) != digest.lower():
            raise ValueError("workspace_document_changed_reselect_source")
        remaining = limit
        units = []
        omitted = False
        raw_units = result.get("units") or []
        for row in raw_units[:MAX_DOCUMENT_UNITS]:
            locator = _locator(row.get("locator"))
            raw_text = str(row.get("text") or "")
            text = raw_text[:remaining]
            remaining -= len(text)
            omitted = omitted or len(text) != len(raw_text)
            raw_assets = row.get("assets") or []
            if len(raw_assets) > 64:
                raise ValueError("workspace_document_visual_limit_select_smaller_range")
            assets = [
                {key: item[key] for key in ("id", "mime_type", "locator") if key in item}
                for item in raw_assets
                if isinstance(item, dict)
            ]
            units.append(
                {
                    "kind": str(row.get("kind") or "text"),
                    "text": text,
                    "locator": locator,
                    "assets": assets,
                    **{
                        key: row[key]
                        for key in (
                            "extraction",
                            "status",
                            "char_start",
                            "char_end",
                            "total_chars",
                            "truncated_unit",
                            "coverage",
                            "equations",
                            "table",
                        )
                        if key in row
                    },
                }
            )
        omitted = (
            omitted
            or len(raw_units) > len(units)
            or (type(document.get("unit_count")) is int and document["unit_count"] > len(units))
        )
        partial = bool(
            result.get("truncated")
            or result.get("next_cursor")
            or result.get("status") == "partial"
            or omitted
            or start
            and start > 1
        )
        body = "\n\n".join(
            f"[locator={json.dumps(row['locator'], ensure_ascii=False)}; extraction={row.get('extraction', 'text')}]\n{row['text']}"
            for row in units
        )
        header = f"[Workspace document: {metadata['path']}; sha256={digest.lower()}; {'partial excerpt; not the entire document' if partial else 'read excerpt'}]"
        excerpt = f"{header}\n{body}"
        if len(excerpt) > limit:
            partial = True
            header = f"[Workspace document: {metadata['path']}; sha256={digest.lower()}; partial excerpt; not the entire document]"
            excerpt = (header + "\n" + body)[:limit]
        # Scanned pages/figures remain usable evidence even when OCR has no
        # reliable text. The generation entrypoints must transmit these assets
        # to a vision model, not mistake this locator header for their content.
        has_visuals = any(row["assets"] for row in units)
        grounded.excerpt = excerpt if has_visuals or any(row["text"].strip() for row in units) else ""
        grounded.available = bool(grounded.excerpt)
        grounded.metadata = {
            **metadata,
            "document_sha256": digest.lower(),
            "document": {
                key: document[key] for key in ("sha256", "bytes", "unit_count") if key in document
            },
            "format": result.get("format"),
            "units": units,
            "partial": partial,
            "truncated": partial,
            "next_cursor": result.get("next_cursor"),
            "warnings": result.get("warnings") or [],
            "coverage": result.get("coverage") or {},
            "requires_visual_input": has_visuals,
            "grounded_for_route": grounded.available,
            "documents": [metadata["path"]],
        }
        if not grounded.available:
            grounded.metadata["read_error"] = "workspace_document_no_readable_text"
    except Exception as error:
        code = str(error)
        if not code.startswith("workspace_document_") or len(code) > 100:
            code = "workspace_document_unavailable"
        grounded.metadata = {
            **metadata,
            "partial": True,
            "unavailable_during_generation": True,
            "read_error": code,
        }
    return grounded
