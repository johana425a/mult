"""DeepSteam: lossless whole-PDF storage and bounded classroom planning.

The book has no page-count cap. Each classroom still has a finite, auditable
source budget. PyMuPDF opens a file by path; a 500+ MiB book is never copied into
a Python bytes object. Page images are rendered only for the selected part.
No model call, OCR completion, or teaching coverage is implied by indexing.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import threading
import uuid

import pymupdf

VERSION = 1
MAX_PART_CHARS = 24000
MAX_PART_UNITS = 140
MAX_PART_IMAGES = 20
CLAUSES = re.compile(r'[\s\S]+?(?:[。！？；，,]|[.!?](?=\s|$)|\n[ \t]*\n|$)')
_hash_cache = {}
_hash_lock = threading.Lock()


def source_units(text):
    return sum(bool(m.group().strip()) for m in CLAUSES.finditer(text))


def owned_pdf(source, uploads):
    from scripts.workspace_document_reader import _plain_ancestors
    root = Path(uploads).resolve(strict=True)
    path = Path(source['path'])
    _plain_ancestors(path)
    if (path.suffix.lower() != '.pdf' or path.is_symlink()
            or path.resolve(strict=True).parent != root
            or not re.fullmatch(r'material_[a-f0-9]{32}\.pdf', path.name)):
        raise ValueError('Choose an application-managed PDF copy.')
    return path.resolve(strict=True)


def signature(path):
    stat = path.stat()
    return (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)


def fingerprint(path):
    before = signature(path)
    with _hash_lock:
        digest = _hash_cache.get(before)
    if not digest:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if before != signature(path):
            raise ValueError('The PDF changed while it was being read. Try again.')
        with _hash_lock:
            if len(_hash_cache) > 128:
                _hash_cache.clear()
            _hash_cache[before] = digest
    return digest


def verify(source, uploads):
    path = owned_pdf(source, uploads)
    digest = fingerprint(path)
    if source.get('document_sha256') and source['document_sha256'] != digest:
        raise ValueError('The original PDF changed. Import or select its new version first.')
    return path, digest


def _open(path):
    doc = pymupdf.open(path)
    if not doc.is_pdf or doc.needs_pass:
        doc.close()
        raise ValueError('A readable, unencrypted PDF is required.')
    return doc


def _row(doc, index):
    page = doc[index]
    text = page.get_text()
    locator = {'page': index + 1, 'page_kind': 'pdf_physical'}
    return {'kind': 'page', 'unit_index': index + 1, 'locator': locator,
            'text': text, 'char_start': 0, 'char_end': len(text), 'total_chars': len(text),
            'truncated_unit': False, 'extraction': 'native_pdf_text',
            'status': 'ready' if len(text.strip()) >= 120 else 'needs_visual_reading',
            'assets': [{'id': f'pdf-page:{index + 1}', 'locator': locator}],
            'unit_text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}


def _result(path, digest, count, rows, cursor=None, next_cursor=None):
    text = '\n\n'.join(row['text'] for row in rows)
    return {'schema_version': 1, 'ok': True, 'status': 'ready', 'text': text,
            'document': {'sha256': digest, 'bytes': path.stat().st_size, 'unit_count': count},
            'units': rows, 'cursor': cursor, 'next_cursor': next_cursor,
            'truncated': next_cursor is not None, 'requires_image_reading': bool(rows),
            'long_pdf': VERSION,
            'warnings': ['PDF page numbers are physical file pages. Text extraction is not a verification of formulas or figures; original page images are retained.'],
            'coverage': {'source_pages_retained': count, 'selected_pages': len(rows),
                         'model_visual_review': 'not_started', 'teaching': 'not_started'}}


def read_window(source, uploads, *, cursor=None, max_units=40, max_chars=24000):
    from scripts.workspace_document_reader import cursor_decode, cursor_encode
    path, digest = verify(source, uploads)
    index, offset = cursor_decode(cursor, digest)
    before = signature(path)
    rows = []
    with _open(path) as doc:
        if index >= len(doc):
            raise ValueError('The selected page is beyond the end of this PDF.')
        remaining = max_chars
        while index < len(doc) and len(rows) < max(1, min(40, max_units)) and remaining > 0:
            row = _row(doc, index)
            raw = row['text']
            end = min(len(raw), offset + remaining)
            row.update(text=raw[offset:end], char_start=offset, char_end=end,
                       truncated_unit=end < len(raw))
            rows.append(row)
            remaining -= end - offset + 2
            if end < len(raw):
                offset = end
                break
            index, offset = index + 1, 0
        next_cursor = cursor_encode(digest, index, offset) if index < len(doc) else None
        result = _result(path, digest, len(doc), rows, cursor, next_cursor)
    if before != signature(path):
        raise ValueError('The PDF changed during reading.')
    return result


def build_plan(source, uploads):
    """Index every physical page, then pack whole pages inside each AI budget.

    A page which cannot fit on its own stays in the plan as blocked; nothing
    is dropped or marked ready. Book and chapter totals have no numeric cap.
    """
    path, digest = verify(source, uploads)
    cache_dir = Path(uploads).parent / 'material-plans'
    cache_dir.mkdir(exist_ok=True)
    cache = cache_dir / f'{digest}-v{VERSION}.json'
    if cache.is_file():
        try:
            saved = json.loads(cache.read_text('utf-8'))
            if (saved.get('version') == VERSION and saved.get('document_sha256') == digest
                    and saved.get('file_bytes') == path.stat().st_size and saved.get('parts')
                    and saved.get('retained_pages') == saved.get('page_count')):
                return saved
        except (ValueError, OSError):
            pass  # Rebuild a broken cache from the unchanged source PDF.
    before = signature(path)
    parts, current = [], []
    with _open(path) as doc:
        toc = doc.get_toc()
        boundaries = {}
        for level, title, page in toc:
            if level <= 2 or re.match(r'^Chapter\s+\d+\b', title, re.I):
                boundaries.setdefault(page, title)
        chapter = 'Front matter'

        def flush():
            if not current:
                return
            text = '\n\n'.join(row['text'] for row in current)
            count = source_units(text)
            reason = ('A single PDF page exceeds the classroom text or verification budget. Select a smaller semantic scope before generation.'
                      if len(text) > MAX_PART_CHARS or count > MAX_PART_UNITS else None)
            number = len(parts) + 1
            parts.append({'id': number, 'title': chapter, 'page_start': current[0]['unit_index'],
                          'page_end': current[-1]['unit_index'], 'text_chars': len(text),
                          'source_units': count, 'image_count': len(current),
                          'status': 'blocked' if reason else 'ready_for_generation',
                          'reason': reason, 'text': text, 'units': list(current)})
            current.clear()

        for index in range(len(doc)):
            if index + 1 in boundaries:
                flush()
                chapter = boundaries[index + 1]
            row = _row(doc, index)
            candidate = '\n\n'.join([*(r['text'] for r in current), row['text']])
            if current and (len(current) >= MAX_PART_IMAGES or len(candidate) > MAX_PART_CHARS
                            or source_units(candidate) > MAX_PART_UNITS):
                flush()
            current.append(row)
        flush()
        page_count = len(doc)
        # Contiguity includes covers, blanks, answers, glossary, and index.
        pages = [row['unit_index'] for part in parts for row in part['units']]
        if pages != list(range(1, page_count + 1)):
            raise ValueError('Whole-book page coverage did not verify; no plan was saved.')
        result = {'version': VERSION, 'document_sha256': digest, 'file_bytes': path.stat().st_size,
                  'title': doc.metadata.get('title') or source.get('title'),
                  'page_count': page_count, 'toc': toc, 'part_count': len(parts),
                  'chapter_count': len([t for t in toc if re.match(r'^Chapter\s+\d+\b', t[1], re.I)]),
                  'retained_pages': len(pages), 'coverage_complete': True,
                  'generated_parts': 0, 'teaching_complete': False,
                  'text_chars': sum(len(r['text']) for p in parts for r in p['units']),
                  'low_text_pages': [r['unit_index'] for p in parts for r in p['units'] if len(r['text'].strip()) < 120],
                  'blocked_parts': [p['id'] for p in parts if p['status'] == 'blocked'],
                  'budgets_per_part': {'characters': MAX_PART_CHARS, 'source_units': MAX_PART_UNITS,
                                       'page_images': MAX_PART_IMAGES}, 'parts': parts}
    if before != signature(path):
        raise ValueError('The PDF changed during indexing; no plan was saved.')
    temp = cache.with_name(cache.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        temp.replace(cache)
    finally:
        temp.unlink(missing_ok=True)
    return result


def public_plan(plan):
    return {**{k: v for k, v in plan.items() if k not in {'parts', 'toc'}},
            'parts': [{k: v for k, v in part.items() if k not in {'text', 'units'}} for part in plan['parts']]}


def part_snapshot(source, uploads, part_id):
    path, digest = verify(source, uploads)
    plan = build_plan(source, uploads)
    if not 1 <= part_id <= len(plan['parts']):
        raise ValueError('This textbook part does not exist.')
    part = plan['parts'][part_id - 1]
    if part['status'] == 'blocked':
        raise ValueError(part['reason'])
    result = _result(path, digest, plan['page_count'], deepcopy(part['units']))
    result['prepared_pdf_part'] = {'version': VERSION, 'id': part_id, 'title': part['title'],
                                   'page_start': part['page_start'], 'page_end': part['page_end']}
    result['coverage']['selected_scope_complete'] = True
    return result


def read_asset(source, uploads, asset_id, document_sha256, max_dimension=1600):
    path, digest = verify(source, uploads)
    before = signature(path)
    if digest != document_sha256:
        raise ValueError('The PDF image source version changed.')
    match = re.fullmatch(r'pdf-page:([1-9][0-9]*)', asset_id or '')
    if not match:
        raise ValueError('Invalid PDF page image.')
    number = int(match[1])
    with _open(path) as doc:
        if not 1 <= number <= len(doc):
            raise ValueError('The PDF page image does not exist.')
        page = doc[number - 1]
        scale = min(2.5, max_dimension / max(page.rect.width, page.rect.height))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        data = pix.tobytes('png')
        if before != signature(path):
            raise ValueError('The PDF changed during image rendering.')
        return {'ok': True, 'asset': {'id': asset_id, 'mime_type': 'image/png',
                 'base64': base64.b64encode(data).decode('ascii'), 'width': pix.width,
                 'height': pix.height, 'locator': {'page': number, 'page_kind': 'pdf_physical'}}}
