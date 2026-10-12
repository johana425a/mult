"""Selected document windows, shared local extraction, and classroom snapshots."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SUPPORTED_SUFFIXES = {'.pdf', '.docx', '.pptx', '.md', '.txt', '.xlsx'}
try:
    MAX_DOCUMENT_BYTES = min(512 * 1024 * 1024, max(1024 * 1024, int(os.environ.get('EDUAGENT_DOCUMENT_MAX_BYTES', 200 * 1024 * 1024))))
except ValueError:
    MAX_DOCUMENT_BYTES = 200 * 1024 * 1024
READ_OPTIONS = {'max_chars': 24000, 'max_units': 10}


def decode(value, default=None):
    return json.loads(value) if isinstance(value, str) and value else (value or default)


def same_window(saved, current):
    """Reference identity includes derived text and separately versioned images."""
    previous = decode(saved, {})
    def identity(value):
        return {'text': value.get('text'), 'next_cursor': value.get('next_cursor'),
                'units': [{'text': unit.get('text'), 'locator': unit.get('locator'),
                           'assets': [{'id': asset.get('id'), 'locator': asset.get('locator')}
                                      for asset in unit.get('assets') or []]}
                          for unit in value.get('units') or []]}
    return identity(previous) == identity(current)


def check_result(result):
    if not isinstance(result, dict) or not result.get('ok') or result.get('status') == 'error':
        error = result.get('error') if isinstance(result, dict) else None
        message = error.get('message') if isinstance(error, dict) else error
        raise ValueError(message or 'Material reading failed. Check the format and workspace access.')
    return result


async def workspace_request(workspace_id, action, **payload):
    from integration.workspace_documents import document_request
    return check_result(await document_request(workspace_id, action, **payload))


async def managed_request(root, path, action='read', **payload):
    from integration.workspace_documents import read_managed_document
    return check_result(await read_managed_document(Path(root), path, action=action, **payload))


async def read_source(source, uploads, *, cursor=None, verify=True):
    kwargs = {**READ_OPTIONS, 'cursor': cursor, 'max_units': int(source.get('source_max_units') or READ_OPTIONS['max_units'])}
    if verify and source.get('document_sha256'):
        kwargs['document_sha256'] = source['document_sha256']
    if source.get('source_kind') == 'workspace':
        return await workspace_request(source['workspace_id'], 'read', path=source['relative_path'], **kwargs)
    path = Path(source['path'])
    root = Path(uploads).resolve()
    owned = path.name == source['id'] + path.suffix.lower()
    ranged = source.get('source_kind') == 'upload_range' and re.fullmatch(r'material_[a-f0-9]{32}', path.stem)
    if path.is_symlink() or path.resolve().parent != root or not (owned or ranged):
        raise ValueError('This material is not an application-managed imported copy.')
    return await managed_request(root, path.name, **kwargs)


def window_fields(result, cursor=None):
    document = result.get('document') or {}
    if not document.get('sha256'):
        raise ValueError('The reader did not return a material version. Try again.')
    return {'text': result.get('text') or '', 'char_count': len(result.get('text') or ''),
            'page_count': document.get('unit_count'), 'preview_truncated': int(bool(result.get('truncated'))),
            'document_sha256': document['sha256'], 'source_cursor': cursor,
            'source_snapshot': json.dumps(result, ensure_ascii=False)}


async def classroom_snapshot(source, uploads):
    """Verify the selected version and freeze bounded text plus rendered pictures."""
    verified = await read_source(source, uploads, cursor=source.get('source_cursor'))
    result = decode(source.get('source_snapshot')) or verified
    if result.get('document', {}).get('sha256') != verified.get('document', {}).get('sha256'):
        raise ValueError('The material version changed. Select the reading scope again.')
    if not (result.get('text') or '').strip():
        raise ValueError('The selected scope has no usable text. OCR did not produce usable scan text. Choose a readable scope or complete OCR first.')
    images, image_sources, warnings, locators = [], [], list(result.get('warnings') or []), []
    image_bytes = 0
    assets = []
    for unit in result.get('units') or []:
        locators.append(unit.get('locator') or {})
        assets.extend({**asset, 'locator': asset.get('locator') or unit.get('locator') or {}}
                      for asset in unit.get('assets') or [])
    unique = list({asset['id']: asset for asset in assets if asset.get('id')}.values())
    for asset in unique[:10]:
        payload = {'path': source.get('relative_path') or Path(source['path']).name,
                   'asset_id': asset['id'], 'document_sha256': result['document']['sha256']}
        if source.get('source_kind') == 'workspace':
            picture = await workspace_request(source['workspace_id'], 'asset', **payload)
        else:
            picture = await managed_request(uploads, payload.pop('path'), action='asset', **payload)
        data = (picture.get('asset') or {}).get('base64')
        if not isinstance(data, str) or not data:
            raise ValueError('Material images could not be read. The classroom was not submitted.')
        image_bytes += len(data)
        if image_bytes > 12 * 1024 * 1024:
            raise ValueError('Images in this scope are large. Reduce the reading scope before generating the classroom.')
        images.append('data:image/png;base64,' + data)
        image_sources.append({'image_index': len(images), 'asset_id': asset['id'],
                              'locator': asset['locator'], 'document_sha256': result['document']['sha256'],
                              'source_document_name': str(source.get('filename') or '')[:160]})
    if len(unique) > 10:
        raise ValueError('This scope contains more than 10 images. Reduce the reading scope before generating the classroom.')
    return {'text': result['text'], 'images': images, 'image_sources': image_sources, 'locators': locators,
            'document': result['document'], 'source_kind': source.get('source_kind') or 'upload',
            'workspace_id': source.get('workspace_id'), 'relative_path': source.get('relative_path'),
            'cursor': source.get('source_cursor'), 'partial': bool(result.get('truncated')),
            'warning': '; '.join(str(item) for item in warnings), 'status': result.get('status')}
