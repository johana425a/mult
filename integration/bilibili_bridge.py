"""Desktop-session subtitle ingestion. Authenticated internal calls only."""
from __future__ import annotations
import hashlib
import json
import math
import secrets
import time
from functools import wraps

from fastapi import HTTPException, Request


def install_bilibili_routes(app, authenticate):
    proofs = {}

    def in_content_workspace(function):
        @wraps(function)
        async def run(material_id: str, request: Request):
            authenticate(request)
            from deeptutor.services.workspace.context import workspace_context
            with workspace_context(request.query_params.get("dt_workspace", "")) as scope:
                if scope.archived:
                    raise HTTPException(403, "Restore the workspace before refreshing captions")
                return await function(material_id, request)
        return run

    @app.get("/api/contest/internal/bilibili-source/{material_id}")
    @in_content_workspace
    async def source(material_id: str, request: Request):
        authenticate(request)
        from deeptutor.reading.catalog_store import ReadingCatalogStore
        from deeptutor.reading.catalog_models import SourceKind
        from deeptutor.reading.ingestion import parse_bilibili_url, _load_bilibili_media
        from deeptutor.services.workspace.context import get_workspace_scope
        row = ReadingCatalogStore().get_material(material_id)
        if row is None or row.source_kind is not SourceKind.BILIBILI:
            raise HTTPException(404, "Bilibili material not found")
        parsed = parse_bilibili_url(row.source_url)
        media = await _load_bilibili_media(row.source_url, ("zh", "en"))
        scope = get_workspace_scope()
        for key, value in list(proofs.items()):
            if value["expires"] < time.time():
                proofs.pop(key, None)
        if len(proofs) >= 100:
            proofs.pop(next(iter(proofs)))
        proof = secrets.token_urlsafe(32)
        proofs[proof] = {"material_id": material_id, "workspace": scope.workspace_id if scope else "",
                         "expires": time.time() + 300, "bvid": parsed.bvid, "cid": media.cid,
                         "page": media.page_number, "url": parsed.canonical_url, "title": media.title}
        return {"proof": proof, "bvid": parsed.bvid, "cid": media.cid,
                "source_url": parsed.canonical_url}

    @app.post("/api/contest/internal/bilibili-subtitles/{material_id}")
    @in_content_workspace
    async def subtitles(material_id: str, request: Request):
        authenticate(request)
        from deeptutor.reading import ReadingStore
        from deeptutor.reading.catalog_store import ReadingCatalogStore
        from deeptutor.reading.catalog_models import IngestionStatus
        from deeptutor.reading.ingestion import normalize_transcript_segments, _clock
        from deeptutor.reading.models import OutlineEntry, UnitReference
        from deeptutor.services.workspace.context import get_workspace_scope
        from deeptutor.services.workspace.activity import data_activity
        raw = await request.body()
        if len(raw) > 4 * 1024 * 1024:
            raise HTTPException(413, "Caption request exceeded the limit")
        try:
            body = json.loads(raw)
        except ValueError:
            raise HTTPException(422, "Invalid caption request") from None
        if not isinstance(body, dict) or set(body) - {"proof", "language", "cues"}:
            raise HTTPException(422, "Invalid caption request")
        proof = proofs.pop(str(body.get("proof") or ""), None)
        scope = get_workspace_scope()
        if (proof is None or proof["material_id"] != material_id or proof["expires"] < time.time()
                or proof["workspace"] != (scope.workspace_id if scope else "")):
            raise HTTPException(409, "Caption source verification expired; refresh again")
        cues = body.get("cues")
        if not isinstance(cues, list) or len(cues) > 20_000:
            raise HTTPException(422, "Invalid caption cues")
        total_bytes = 0
        for cue in cues:
            if not isinstance(cue, dict):
                raise HTTPException(422, "Invalid caption cue")
            text = cue.get("content")
            try:
                start, end = float(cue.get("from")), float(cue.get("to"))
            except (TypeError, ValueError):
                raise HTTPException(422, "Invalid caption timestamp") from None
            if not isinstance(text, str) or not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end):
                raise HTTPException(422, "Invalid caption cue")
            total_bytes += len(text.encode("utf-8"))
        if total_bytes > 2 * 1024 * 1024:
            raise HTTPException(413, "Caption text exceeded the limit")
        # Preserve the individual cues and subsecond timing for live captions.
        segments = normalize_transcript_segments(cues)
        if not segments:
            raise HTTPException(422, "Caption response contained no text")
        language = str(body.get("language") or "")[:64]
        evidence = {"bvid": proof["bvid"], "cid": proof["cid"], "page": proof["page"],
                    "language": language, "cues": len(cues), "authenticated_desktop_session": True,
                    "first_cue_seconds": min(row.start_seconds for row in segments),
                    "last_cue_end_seconds": max(row.end_seconds for row in segments),
                    "retained_cues": len(segments),
                    "text_sha256": hashlib.sha256("\n".join(row.text for row in segments).encode()).hexdigest()}
        raw_caption_asset = {"language": language, "cues": [
            {"start": row.start_seconds, "end": row.end_seconds, "text": row.text}
            for row in segments]}
        with data_activity():
            store = ReadingStore()
            store.ingest_units(material_id, filename=f"bilibili-{proof['bvid']}-p{proof['page']}.vtt",
                units=[row.text for row in segments], unit="segment", title=proof["title"],
                mime="text/vtt", extractor="bilibili-subtitles", render_mode="video",
                source_type="bilibili_authenticated_subtitles", source_url=proof["url"],
                assets={"bilibili-source.json": json.dumps(evidence).encode(),
                        "bilibili-cues.json": json.dumps(raw_caption_asset, ensure_ascii=False).encode()},
                outline=[OutlineEntry(locator=i, title=_clock(row.start_seconds)) for i,row in enumerate(segments,1)],
                unit_refs=[UnitReference(locator=i, source_href=f"#t={row.start_seconds:g}", title=_clock(row.start_seconds))
                           for i,row in enumerate(segments,1)])
            ReadingCatalogStore().update_material_status(material_id, IngestionStatus.READY)
        return {"segments": len(segments), "language": language, "status": "ready"}
