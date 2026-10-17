"""Retain a whole PDF; resolve selected pages through the shared reader.

Indexing does not claim the textbook has been semantically read. Original
bytes and native bookmarks are retained, without an import page-count cap.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import uuid

EXTRACTOR = 'pdf-on-demand'
INDEX_NAME = 'pdf-index.json'


_locks = {}
_locks_guard = threading.Lock()


def _content_lock(directory: str):
    # ReadingStore instances are request-local. Serialize shared media/index
    # writes for the same retained PDF across those instances.
    with _locks_guard:
        return _locks.setdefault(directory, threading.RLock())


def search_text_rows(store, material_id: str):
    """Search the existing PDF text layer, without rendering/OCR of every page.

    This is a locator search index only. It does not mark images, scanned
    pages or formulas as read; read_page still performs selected-page evidence.
    """
    import pymupdf
    directory = store._dir(material_id)
    with pymupdf.open(store.raw_path(material_id)) as document:
        for index in range(document.page_count):
            locator = index + 1
            cached = store._unit_file(directory, locator)
            # Already extracted scans may contribute their verified text too.
            text = cached.read_text('utf-8') if cached.is_file() else document[index].get_text('text')
            yield locator, text


def browser_pdf(store, material_id: str) -> Path:
    """Build a structurally normalized view without changing original bytes.

    Some large PDFs force PDF.js into its whole-file recovery scanner, whose
    string allocation fails past V8's limit. Rewriting only the PDF container
    gives that viewer a valid cross-reference table and preserves page streams.
    """
    import pymupdf
    from .models import ReadingError
    from .store import RENDER_DIR, _atomic_write
    directory = store._dir(material_id)
    with _content_lock(str(directory)):
        output = directory / RENDER_DIR / 'browser.pdf'
        receipt = directory / 'pdf-browser-view.json'
        if output.is_file() and receipt.is_file():
            try:
                if json.loads(receipt.read_text('utf-8')).get('version') == 2:
                    return output
            except (ValueError, OSError):
                pass
        original = store.raw_path(material_id)
        output.parent.mkdir(parents=True, exist_ok=True)
        pending = output.with_name(uuid.uuid4().hex + '.pdf')
        try:
            with pymupdf.open(original) as source:
                repaired = source.is_repaired
                # Copy pages into a clean container: a plain save preserves an
                # invalid object-zero xref found in some otherwise readable PDFs.
                # Retain links, annotations, widgets, metadata and native outline.
                # No downsampling, OCR, cropping, content rewrite or page cap.
                with pymupdf.open() as clean:
                    clean.insert_pdf(source, links=True, annots=True, widgets=True)
                    clean.set_metadata(source.metadata)
                    clean.set_toc(source.get_toc())
                    clean.set_page_labels(source.get_page_labels())
                    clean.save(pending, garbage=0, deflate=False)
                with pymupdf.open(pending) as view:
                    if source.page_count != view.page_count or source.get_toc() != view.get_toc():
                        raise ReadingError('PDF browser view did not preserve its pages or outline.')
                    for index in range(source.page_count):
                        a, b = source[index], view[index]
                        if a.rect != b.rect or a.rotation != b.rotation or a.read_contents() != b.read_contents():
                            raise ReadingError('PDF browser view did not preserve the original page content.')
                    count = source.page_count
            os.replace(pending, output)
            _atomic_write(receipt, json.dumps({'version':2,'page_count':count,
                'original_preserved':True,'original_needed_repair':repaired,
                'all_page_content_streams_equal':True,'native_outline_equal':True}))
        finally:
            pending.unlink(missing_ok=True)
        return output


def ingest_pdf(store, source: Path, filename: str | None = None):
    import pymupdf
    from .extract import _pdf_outline
    from .models import MaterialManifest, ReadingError
    from .store import MANIFEST_NAME, OUTLINE_NAME, RAW_DIR, _ID_LENGTH, _atomic_write, _safe_filename

    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    material_id = digest[:_ID_LENGTH]
    display_name = (filename or source.name).strip() or source.name
    with _content_lock(str(store._dir(material_id))), store._locked(material_id):
        existing = store._load_manifest(material_id)
        if existing and store._is_complete(material_id, existing):
            return existing
        destination = store._dir(material_id)
        if destination.exists():
            raise ReadingError('An incomplete existing import was retained. Restore or repair it before reimporting.')
        try:
            with pymupdf.open(source) as document:
                if document.is_encrypted and not document.authenticate(''):
                    raise ReadingError('This PDF is encrypted and cannot be opened.')
                count = document.page_count
                if not count:
                    raise ReadingError('The PDF has no pages.')
                outline = _pdf_outline(document, page_count=count)
                title = str((document.metadata or {}).get('title') or '').strip()
        except ReadingError:
            raise
        except Exception as exc:
            raise ReadingError('The PDF could not be indexed; the original has been retained.') from exc
        stage = store.root / f'.{material_id}.{uuid.uuid4().hex}.staging'
        raw = stage / RAW_DIR / _safe_filename(display_name, fallback=source.name)
        raw.parent.mkdir(parents=True)
        try:
            shutil.copyfile(source, raw)
            with raw.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                    raise ReadingError('The retained PDF failed its integrity check.')
            manifest = MaterialManifest(material_id=material_id, filename=display_name,
                unit='page', unit_count=count, mime='application/pdf', title=title or Path(display_name).stem,
                source_hash=material_id, extractor=EXTRACTOR, byte_size=raw.stat().st_size,
                has_raw_view=True, render_mode='pdf')
            _atomic_write(stage / OUTLINE_NAME, json.dumps([row.to_dict() for row in outline], ensure_ascii=False))
            _atomic_write(stage / INDEX_NAME, json.dumps({'version':1, 'sha256':digest,
                'page_count':count, 'text_extraction':'on_demand', 'semantic_completeness':'not_guaranteed'}))
            _atomic_write(stage / MANIFEST_NAME, json.dumps(manifest.to_dict(), ensure_ascii=False))
            os.replace(stage, destination)
        except BaseException:
            # A failed stage is retained as recovery evidence, not called ready.
            raise
        return manifest


def read_page(store, material_id: str, locator: int) -> str:
    import pymupdf
    from integration.shared_document_extraction import extract_document
    from .models import ReadingError
    from .store import MEDIA_DIR, MEDIA_INDEX_NAME, _atomic_write

    manifest = store.manifest(material_id)
    if not 1 <= locator <= manifest.unit_count:
        raise ReadingError('Page is outside the original PDF.')
    with _content_lock(str(store._dir(material_id))), store._locked(material_id):
        directory = store._dir(material_id)
        text_path = store._unit_file(directory, locator)
        evidence_path = directory / 'page-evidence' / f'{locator}.json'
        if evidence_path.is_file() and text_path.is_file():
            return text_path.read_text('utf-8')
        original = store.raw_path(material_id)
        selected = directory / 'page-sources' / f'page-{locator}.pdf'
        selected.parent.mkdir(parents=True, exist_ok=True)
        picture_name = f'original-page-{locator}.png'
        media_dir = directory / MEDIA_DIR
        media_dir.mkdir(parents=True, exist_ok=True)
        with pymupdf.open(original) as document:
            page = document[locator - 1]
            scale = min(2, 2000 / max(page.rect.width, page.rect.height))
            # This full page remains available even when extracted formulas
            # are uncertain. It is evidence, never inferred replacement text.
            page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(media_dir / picture_name)
            if not selected.is_file():
                with pymupdf.open() as part:
                    part.insert_pdf(document, from_page=locator - 1, to_page=locator - 1)
                    part.save(selected, garbage=3, deflate=True)
        result = extract_document(selected, include_assets=True)
        if len(result['units']) != 1:
            raise ReadingError('Selected-page parsing returned an inconsistent page count.')
        row = result['units'][0]
        text = '' if row.get('text_is_placeholder') else row['text']
        # Prefix per-page media names so distinct pages never overwrite them.
        media = [r for r in store.media_items(material_id) if r.get('locator') != locator]
        for index, image in enumerate(result['images'], 1):
            name = f'page-{locator}-' + Path(image['name']).name
            (media_dir / name).write_bytes(image['data'])
            text += f'\n[Image {index}: {name}]'
            media.append({'name':name,'locator':locator,'mime':image['mime_type'],'bytes':len(image['data'])})
        text += f'\n[Image {len(result["images"])+1}: {picture_name}]'
        media.append({'name':picture_name,'locator':locator,'mime':'image/png',
            'bytes':(media_dir / picture_name).stat().st_size})
        _atomic_write(directory / MEDIA_INDEX_NAME, json.dumps(media, ensure_ascii=False))
        _atomic_write(text_path, text)
        _atomic_write(evidence_path, json.dumps({'original_page':locator,'selected_document_page':1,
            'coverage':result.get('coverage'), 'warnings':result.get('warnings'),
            'original_image':picture_name, 'visual_status':'pending'},ensure_ascii=False))
        return text
