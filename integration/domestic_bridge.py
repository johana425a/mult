"""Persist observed official browser caption tracks in the matching workspace."""
from __future__ import annotations
import json
import math
from fastapi import HTTPException, Request


def validate_caption_body(body, source):
    from deeptutor.reading.domestic_video import domestic_video_source
    if not isinstance(body, dict) or set(body) - {"source_url", "cues", "language", "title", "duration_seconds"}:
        raise HTTPException(422, "Invalid caption request")
    got = domestic_video_source(str(body.get("source_url") or ""))
    if got is None or (got.platform, got.video_id) != (source.platform, source.video_id):
        raise HTTPException(409, "Caption source changed")
    cues = body.get("cues")
    if not isinstance(cues, list) or not 1 <= len(cues) <= 20000:
        raise HTTPException(422, "Invalid caption track")
    size = 0
    for cue in cues:
        if not isinstance(cue, dict):
            raise HTTPException(422, "Invalid caption cue")
        text, start, end = cue.get("content"), cue.get("from"), cue.get("to")
        if (not isinstance(text, str) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (start, end)) or not 0 <= start <= end <= 604800):
            raise HTTPException(422, "Invalid caption cue")
        size += len(text.encode("utf-8"))
    if size > 2 * 1024 * 1024:
        raise HTTPException(413, "Caption track exceeded the limit")
    return cues


def install_domestic_routes(app, authenticate):
    @app.post("/api/contest/internal/domestic-captions/{material_id}")
    async def subtitles(material_id: str, request: Request):
        authenticate(request)
        from deeptutor.services.workspace.context import workspace_context
        from deeptutor.services.workspace.activity import data_activity
        from deeptutor.reading.catalog_store import ReadingCatalogStore
        from deeptutor.reading.catalog_models import SourceKind, IngestionStatus
        from deeptutor.reading.domestic_video import domestic_video_source
        from deeptutor.reading import ReadingStore
        from deeptutor.reading.ingestion import normalize_transcript_segments, _clock
        from deeptutor.reading.models import OutlineEntry, UnitReference
        with workspace_context(request.query_params.get("dt_workspace", "")) as scope:
            if scope.archived:
                raise HTTPException(403, "Restore this workspace before importing captions")
            catalog = ReadingCatalogStore()
            record = catalog.get_material(material_id)
            source = domestic_video_source(record.source_url) if record else None
            if not record or record.source_kind is not SourceKind.EXTERNAL_VIDEO or source is None:
                raise HTTPException(404, "Domestic video material not found")
            raw = await request.body()
            if len(raw) > 4 * 1024 * 1024:
                raise HTTPException(413, "Caption request exceeded the limit")
            try:
                body = json.loads(raw)
            except ValueError:
                raise HTTPException(422, "Invalid caption request") from None
            cues = validate_caption_body(body, source)
            segments = normalize_transcript_segments(cues)
            if not segments:
                raise HTTPException(422, "Caption track contains no text")
            title = str(body.get("title") or record.title)[:1000]
            evidence = {"platform": source.platform, "video_id": source.video_id,
                        "language": str(body.get("language") or "")[:64],
                        "origin": "official_browser_texttrack", "full_video_coverage_verified": False,
                        "cues": [{"start": r.start_seconds, "end": r.end_seconds, "text": r.text} for r in segments]}
            with data_activity():
                ReadingStore().ingest_units(material_id, filename=record.filename,
                    units=[r.text for r in segments], unit="segment", title=title,
                    mime="text/vtt", extractor="domestic-video-caption-track", render_mode="video",
                    source_type="official_browser_texttrack", source_url=record.source_url,
                    assets={"domestic-cues.json": json.dumps(evidence, ensure_ascii=False).encode()},
                    outline=[OutlineEntry(locator=i, title=_clock(r.start_seconds)) for i,r in enumerate(segments, 1)],
                    unit_refs=[UnitReference(locator=i, source_href=f"#t={r.start_seconds:g}", title=_clock(r.start_seconds)) for i,r in enumerate(segments, 1)])
                catalog.update_material_status(material_id, IngestionStatus.READY)
            return {"status": "ready", "segments": len(segments), "full_video_coverage_verified": False}
