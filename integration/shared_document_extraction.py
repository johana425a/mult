"""Native DeepTutor adapter to the installation's isolated document reader.

Original DeepSteam integration. No provider, network, shell, or user settings
are involved. Ingest must consume every cursor before calling a source ready.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_FORMATS = frozenset({'.pdf', '.docx', '.pptx', '.xlsx', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff'})
MAX_CHARS = 8_000_000
MAX_UNITS = 10_000
MAX_CALLS = 1500
MAX_SECONDS = 3600
MAX_ASSETS = 120
MAX_ASSET_BYTES = 60 * 1024 * 1024


class SharedDocumentError(RuntimeError):
    """A source cannot be marked fully ingested; its original stays intact."""


def runtime_paths() -> tuple[Path, Path]:
    portable = ROOT / 'runtime/python/python.exe'
    development = ROOT / 'runtime/deeptutor-venv/Scripts/python.exe'
    return (portable if portable.is_file() else development), ROOT / 'scripts/workspace_document_reader.py'


def reader_signature() -> str:
    """Invalidate old plain-text caches and subsequent reader revisions."""
    _, helper = runtime_paths()
    paths = [helper, ROOT / 'integration/document_jobs.py', ROOT / 'integration/document_reading_policy.py', ROOT / 'scripts/mineru_document_worker.py']
    return hashlib.sha256(b''.join(path.read_bytes() for path in paths if path.is_file())).hexdigest() if helper.is_file() else 'missing-reader'


def runtime_ready() -> bool:
    """Cheap installation prerequisite check; no imports, models or network."""
    python, helper = runtime_paths()
    if not python.is_file() or not helper.is_file():
        return False
    runtime = python.parent.parent if python.parent.name.lower() == 'scripts' else python.parent
    packages = runtime / 'Lib/site-packages'
    required = ('pymupdf', 'docx', 'pptx', 'openpyxl', 'PIL')
    return all((packages / name / '__init__.py').is_file() for name in required)


def _request(source: Path, payload: dict[str, Any], timeout: float, *, cancelled=None) -> dict[str, Any]:
    python, helper = runtime_paths()
    if not python.is_file() or not helper.is_file() or not runtime_ready():
        raise SharedDocumentError('The local document reader is incomplete. Repair the installation; no parsing API is required.')
    allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'TEMP', 'TMP'}
    environment = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    environment.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    try:
        deadline = time.monotonic() + timeout
        request = {'root': str(source.parent), 'path': source.name, **payload}
        arguments = [str(python), '-I', '-B', str(ROOT / 'scripts/document_job_worker.py')]
        if os.environ.get('DEEPSTEAM_HARNESS_TEST_ROOT'):
            arguments += ['--test-root', os.environ['DEEPSTEAM_HARNESS_TEST_ROOT']]
        while True:
            if cancelled and cancelled():
                raise SharedDocumentError('Reading stopped. The original file is retained.')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SharedDocumentError('The document is still being prepared. The reading task is retained; read again to resume.')
            result = subprocess.run(
                arguments,
                input=json.dumps({**request, 'wait_seconds': min(20, remaining)}, ensure_ascii=False).encode('utf-8'),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment,
                timeout=min(35, remaining + 5), check=False,
                **({'creationflags': 0x08000000} if os.name == 'nt' else {}),
            )
            if result.returncode or len(result.stdout) > 24 * 1024 * 1024:
                raise SharedDocumentError('Local document reading failed or exceeded its limit. Import is incomplete.')
            value = json.loads(result.stdout)
            if not isinstance(value, dict) or value.get('status') not in {'queued', 'running'}:
                break
            request['job_id'] = value['job_id']
    except subprocess.TimeoutExpired as exc:
        raise SharedDocumentError('The reading connection was interrupted. The task is retained; read again to resume.') from exc
    except (OSError, ValueError) as exc:
        raise SharedDocumentError('The local document reader returned no valid result. Import is incomplete.') from exc
    if not isinstance(value, dict) or value.get('ok') is not True:
        error = value.get('error', {}) if isinstance(value, dict) else {}
        raise SharedDocumentError(str(error.get('message') or 'The document has not been read.'))
    return value


def locator_label(row: dict[str, Any]) -> str:
    locator = row.get('locator') or {}
    if 'page' in locator:
        return f"--- Page {locator['page']} ---"
    if 'slide' in locator:
        return f"--- Slide {locator['slide']} ---"
    return '[Source location: ' + ', '.join(f'{key}={value}' for key, value in locator.items()) + ']'


def warning_note(warnings: list[str]) -> str:
    return '\n\n[Document reading notes]\n' + '\n'.join('- ' + value for value in warnings) if warnings else ''


def extract_document(source: Path | str, *, include_assets: bool = True,
                     on_output: Callable[[str], None] | None = None,
                     cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Return continuously located text and pending original visual assets.

The bridge receives only trusted server-owned source paths. The subprocess
independently verifies canonical paths and reparse points. Assets are bounded
previews; a visible note records previews omitted by the existing media budget.
"""
    source = Path(source).absolute()
    if source.suffix.lower() not in SUPPORTED_FORMATS:
        raise SharedDocumentError('Use the text reader for this format.')
    return _extract(source, include_assets=include_assets, on_output=on_output, cancelled=cancelled)


def _extract(source: Path, *, include_assets: bool, on_output, cancelled=None) -> dict[str, Any]:
    started = time.monotonic()
    calls = 0
    digest = None
    document = None
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    chars = 0
    cursor = None
    seen_cursors: set[str] = set()
    document_unresolved: set[str] = set()
    reading_policy = {'local_mineru_enabled': False, 'default_engine': 'builtin',
                      'image_reading': 'selected_model'}

    def request(payload):
        nonlocal calls, digest, document, reading_policy
        remaining = MAX_SECONDS - (time.monotonic() - started)
        calls += 1
        if calls > MAX_CALLS or remaining <= 0:
            raise SharedDocumentError('Reading reached the local time or pagination limit. Import is incomplete; split the document and retry.')
        if digest:
            payload = {**payload, 'document_sha256': digest}
        if cancelled and cancelled():
            raise SharedDocumentError('Reading stopped. The original file is retained.')
        value = _request(source, payload, remaining, **({'cancelled': cancelled} if cancelled else {}))
        if isinstance(value.get('reading_policy'), dict):
            candidate = value['reading_policy']
            # Keep only harmless Settings references; no resolved transport or
            # credentials ever enter the imported document's metadata.
            reading_policy = {'local_mineru_enabled': candidate.get('local_mineru_enabled') is True,
                              'default_engine': 'mineru' if candidate.get('local_mineru_enabled') is True else 'builtin',
                              'image_reading': 'selected_model'}
        identity = value.get('document') or {}
        if not isinstance(identity.get('unit_count'), int) or not isinstance(identity.get('sha256'), str):
            raise SharedDocumentError('The reading result has no completeness metadata.')
        if digest and (identity.get('sha256') != digest or identity.get('unit_count') != document['unit_count']):
            raise SharedDocumentError('The document changed during reading. Import it again.')
        digest, document = identity['sha256'], identity
        if identity['unit_count'] > MAX_UNITS:
            raise SharedDocumentError('The document has too many units for a complete local import. Split the document.')
        for note in value.get('warnings') or []:
            if isinstance(note, str) and note not in warnings:
                warnings.append(note)
        if payload.get('action') == 'read':
            unit_unresolved = {code for row in value.get('units') or [] for code in (row.get('coverage') or {}).get('unresolved') or []}
            document_unresolved.update(set((value.get('coverage') or {}).get('unresolved') or []) - unit_unresolved)
        return value

    while True:
        value = request({'action': 'read', 'ocr': 'off', 'max_units': 40, 'max_chars': 100000,
                         **({'cursor': cursor} if cursor else {})})
        for fragment in value.get('units') or []:
            if not isinstance(fragment, dict) or not isinstance(fragment.get('text'), str):
                raise SharedDocumentError('The pagination result is invalid. Import is incomplete.')
            start = fragment.get('char_start', 0)
            if start:
                if not rows or rows[-1].get('locator') != fragment.get('locator') or len(rows[-1]['text']) != start:
                    raise SharedDocumentError('Document pagination is discontinuous. Import is incomplete.')
                combined = rows[-1]['text'] + fragment['text']
                rows[-1] = {**fragment, 'text': combined, 'char_start': 0}
            else:
                rows.append(dict(fragment))
            chars += len(fragment['text'])
            if chars > MAX_CHARS or len(rows) > MAX_UNITS:
                raise SharedDocumentError('The document exceeds the local import limit. Split it and retry.')
        if on_output:
            on_output(f"Reading locally: {len(rows)} / {document['unit_count']} source units")
        cursor = value.get('next_cursor')
        if not value.get('truncated'):
            if cursor:
                raise SharedDocumentError('The document pagination state is inconsistent.')
            break
        if not cursor or cursor in seen_cursors:
            raise SharedDocumentError('Document pagination is incomplete. Import it again.')
        seen_cursors.add(cursor)
    if len(rows) != document['unit_count'] or any(row.get('truncated_unit') for row in rows):
        raise SharedDocumentError('Some document content has not been read. Import is incomplete.')

    # Retain every visual location without retrying it through local OCR. The
    # chosen model receives images only when the Agent/user requests image reading.
    for index, row in enumerate(rows):
        if row.get('status') == 'needs_ocr' or not row.get('text', '').strip() and row.get('assets') and row.get('status') != 'empty':
            if not row.get('assets'):
                raise SharedDocumentError(f"{locator_label(row)} contains no recognized text or retained original image.")
            # Keep pixels as pending visual evidence, never recognized prose.
            row.update(status='partial', extraction='visual_only', visual_only=True,
                       visual_pending=True, image_reading='selected_model',
                       text_is_placeholder=True, text='[Source image pending: use read_document_image with the selected model. No image text or meaning has been verified.]')
            prior = row.get('coverage') or {}
            row['coverage'] = {**prior, 'text_method': 'visual_only', 'visual_review_required': True,
                               'visual_status': 'pending',
                               'pending_visual_assets': [asset['id'] for asset in row['assets']],
                               'unresolved': sorted(set(prior.get('unresolved') or []) | {'visual_content_requires_model'})}
        if row.get('status') == 'partial':
            warnings.append(f"{locator_label(row)} contains incomplete extraction. Check the original image at this location.")
    if sum(len(row['text']) for row in rows) > MAX_CHARS:
        raise SharedDocumentError('Recognized content exceeds the local import limit. Split the document and retry.')
    if not any(row['text'].strip() for row in rows):
        raise SharedDocumentError('No readable text was extracted. Import is incomplete; check the source file.')

    images: list[dict[str, Any]] = []
    assets: dict[str, dict[str, Any]] = {}
    image_bytes = 0
    if include_assets or any(row.get('visual_only') for row in rows):
        for index, row in enumerate(rows):
            if not include_assets and not row.get('visual_only'):
                continue
            for metadata in row.get('assets') or []:
                asset_id = metadata.get('id')
                if not isinstance(asset_id, str):
                    continue
                if asset_id not in assets:
                    if len(assets) >= MAX_ASSETS or image_bytes >= MAX_ASSET_BYTES:
                        if row.get('visual_only'):
                            raise SharedDocumentError('Image-only content exceeds the original-image budget. Split the document and retry.')
                        note = 'Image previews reached the local budget. Other images remain in the source file.'
                        if note not in warnings:
                            warnings.append(note)
                        continue
                    value = request({'action': 'asset', 'asset_id': asset_id, 'max_dimension': 1600})
                    asset = value.get('asset') or {}
                    try:
                        data = base64.b64decode(asset.get('base64', ''), validate=True)
                    except (ValueError, TypeError) as exc:
                        raise SharedDocumentError('The returned document image is invalid.') from exc
                    if asset.get('mime_type') != 'image/png' or not data.startswith(b'\x89PNG\r\n\x1a\n'):
                        raise SharedDocumentError('The returned document image format is invalid.')
                    try:
                        from PIL import Image

                        with Image.open(io.BytesIO(data)) as decoded:
                            if decoded.width * decoded.height > 16_000_000:
                                raise ValueError('image too large')
                            decoded.verify()
                    except Exception as exc:
                        raise SharedDocumentError('The original image is corrupt or exceeds the local pixel limit.') from exc
                    if image_bytes + len(data) > MAX_ASSET_BYTES:
                        if row.get('visual_only'):
                            raise SharedDocumentError('Image-only content exceeds the original-image budget. Split the document and retry.')
                        warnings.append('Image previews reached the local byte budget. This image remains in the source file.')
                        continue
                    image_bytes += len(data)
                    assets[asset_id] = {'name': 'source-' + hashlib.sha256(asset_id.encode()).hexdigest()[:16] + '.png',
                                        'mime_type': 'image/png', 'data': data, 'source_asset_id': asset_id}
                images.append({**assets[asset_id], 'unit_index': index, 'locator': row.get('locator') or {}})
    represented = {picture['unit_index'] for picture in images}
    if any(row.get('visual_only') and index not in represented for index, row in enumerate(rows)):
        raise SharedDocumentError('No valid original image was retained for an image-only unit. Import is incomplete.')
    unresolved = document_unresolved | {code for row in rows for code in (row.get('coverage') or {}).get('unresolved') or []}
    if any((row.get('coverage') or {}).get('structured_content') == 'fragmented' for row in rows):
        unresolved.add('structured_content_fragmented')
        warnings.append('Long text units were read continuously. Table and formula metadata are segmented; check the source.')
    pending = [{'unit_index': index + 1, 'locator': row.get('locator') or {},
                'asset_ids': [asset['id'] for asset in row.get('assets') or []],
                'reason': 'visual_content_requires_model'} for index, row in enumerate(rows) if row.get('visual_pending')]
    coverage = {'scope': 'complete_document', 'document_fully_read': not pending,
                'text_layer_complete': True, 'source_units_enumerated': True,
                'text_extraction_complete': not unresolved,
                'visual_status': 'pending' if pending else 'not_requested',
                'visual_fully_read': False if pending else None,
                'semantic_completeness': 'not_guaranteed', 'unresolved': sorted(unresolved),
                'visual_review_required': any((row.get('coverage') or {}).get('visual_review_required') for row in rows)}
    if unresolved:
        warnings.append('Reading status: some structure or image content remains unverified. Check it against the source.')
    return {'document': document, 'units': rows, 'images': images, 'coverage': coverage,
            'reading_policy': reading_policy,
            'visual_pending': bool(pending), 'vision_pending': pending,
            'requires_image_reading': bool(pending), 'image_reading': 'selected_model',
            'next_tool': 'read_document_image' if pending else None,
            'warnings': list(dict.fromkeys(warnings)),
            'status': 'partial' if unresolved or any(r.get('status') == 'partial' for r in rows) else 'ready'}


def write_parser_artifacts(result: dict[str, Any], workdir: Path, stem: str) -> None:
    """Write canonical located markdown plus source images; never edit inputs."""
    workdir.mkdir(parents=True, exist_ok=True)
    blocks = []
    sections = []
    by_unit: dict[int, list[dict[str, Any]]] = {}
    for picture in result['images']:
        by_unit.setdefault(picture['unit_index'], []).append(picture)
        directory = workdir / 'images'
        directory.mkdir(exist_ok=True)
        (directory / picture['name']).write_bytes(picture['data'])
    for index, row in enumerate(result['units']):
        text = locator_label(row) + '\n' + row['text']
        # Only PDFs carry physical page indices. Office blocks/slides/sheets
        # must never become invented paper-page numbers in downstream citation.
        locator = row.get('locator') or {}
        page = {'page_idx': int(locator['page']) - 1} if 'page' in locator else {}
        blocks.append({'type': 'text', 'text': text, **page,
                       'source_locator': row.get('locator'), 'extraction': row.get('extraction'),
                       'coverage': row.get('coverage'), 'equations': row.get('equations'), 'table': row.get('table')})
        for picture in by_unit.get(index, []):
            path = 'images/' + picture['name']
            text += f'\n\n![Source image]({path})'
            blocks.append({'type': 'image', 'img_path': path, 'img_caption': [], 'img_footnote': [],
                           **page, 'source_locator': picture['locator']})
        sections.append(text)
    note = warning_note(result['warnings'])
    (workdir / f'{stem}.md').write_text('\n\n'.join(sections) + note, encoding='utf-8')
    (workdir / f'{stem}_content_list.json').write_text(json.dumps(blocks, ensure_ascii=False), encoding='utf-8')
    (workdir / 'source-extraction.json').write_text(json.dumps({
        'reader': 'shared-workspace-document-reader', 'status': result['status'],
        'document': result['document'], 'warnings': result['warnings'], 'coverage': result.get('coverage'),
    }, ensure_ascii=False), encoding='utf-8')
