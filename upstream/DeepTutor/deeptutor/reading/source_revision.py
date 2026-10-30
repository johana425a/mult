"""Bind a video question before execution without changing an executing task.

DeepSteam modification: the reader can retain its initial placeholder revision
after captions finish importing. New unselected questions follow the current
media; replays and selected quotations retain their original source contract.
"""
from __future__ import annotations

from fastapi import HTTPException


class ReadingRevisionConflict(HTTPException):
    error_code = "execution_source_context_changed"
    retryable = False
    phase = "source_binding"

    def __init__(self, language="en", *, during_execution=False):
        if str(language).lower().startswith("zh"):
            message = ("本次回答期间资料已更新。请重新打开当前视频或文档，再发送问题。"
                       if during_execution else
                       "当前引用的字幕或资料已更新。请重新打开当前视频或文档，再发送问题；原有聊天和笔记仍然保留。")
        else:
            message = ("The source changed during this answer. Reopen the current video or document and send your question again."
                       if during_execution else
                       "The referenced transcript or material has changed. Reopen the current video or document and send your question again. Your conversation and notes are preserved.")
        super().__init__(409, {"code": self.error_code, "message": message,
                              "phase": self.phase, "retryable": False})

    def __str__(self):
        return self.detail["message"]


_PLACEHOLDER_EXTRACTORS = {
    "bilibili-no-subtitles", "bilibili-chapters-only", "youtube-no-captions",
    "youtube-no-subtitles", "media-pending-transcript", "media-pending",
}


def resolve_media_revision(store, material_id, requested, viewport, *, replay=False, language="en"):
    """Return the admitted revision, viewport and an auditable refresh record.

    Call only after material authorization, before persisting a request or
    building prompts. An admitted Harness task continues to enforce its frozen
    snapshot on every tool call; this function is never called by that guard.
    """
    viewport = dict(viewport or {})
    current = store.manifest(material_id)
    if current.render_mode not in {"video", "audio"}:
        return requested, viewport, None
    if requested is None or requested == current.revision:
        return current.revision, viewport, None
    if not isinstance(requested, int) or not 1 <= requested < current.revision:
        raise ReadingRevisionConflict(language)
    old = next((row for row in store.revisions(material_id) if row.revision == requested), None)
    if (old is None or old.material_id != current.source_hash
            or old.source_hash != current.source_hash or old.render_mode != current.render_mode
            or old.unit != current.unit):
        raise ReadingRevisionConflict(language)
    equivalent = store.revision_content_matches(material_id, requested)
    selection = str(viewport.get("selection") or "").strip()
    placeholder = old.extractor in _PLACEHOLDER_EXTRACTORS and not selection
    if not equivalent and (selection or (replay and not placeholder)):
        raise ReadingRevisionConflict(language)
    if not equivalent:
        # Segment numbers can shift when captions arrive. Preserve video time,
        # then resolve its new segment; never reuse an old arbitrary locator.
        seconds = viewport.get("time_seconds")
        locator = 0
        if isinstance(seconds, (int, float)) and seconds >= 0:
            for ref in store.unit_references(material_id):
                try:
                    start = float(ref.source_href.removeprefix("#t="))
                except (ValueError, AttributeError):
                    continue
                if start <= seconds:
                    locator = ref.locator
        viewport.pop("locator", None)
        if locator:
            viewport["locator"] = locator
    return current.revision, viewport, {
        "material_id": material_id, "requested_revision": requested,
        "resolved_revision": current.revision,
        "reason": "identical_content" if equivalent else "captions_became_available" if placeholder else "current_media_for_new_question",
    }
