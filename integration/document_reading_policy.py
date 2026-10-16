"""User-owned local parsing policy; model tool arguments cannot grant consent.

The settings file belongs to application state, never to the program or source
tree. Missing, corrupt or older state defaults to the bundled local reading
path: offline scan OCR for image-only pages, plus the selected model for visual
content. Optional local MinerU must be enabled in Settings.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import uuid

from scripts.storage_paths import assert_plain_path

LOCAL_OCR_MODES = ('auto', 'off')
VISION_MODES = ('optional', 'required')


def _local_ocr(value: object) -> str:
    """auto: an image-only page is transcribed by the bundled offline engine."""
    return 'off' if value == 'off' or value is False else 'auto'


def _vision_verification(value: object) -> str:
    """optional: OCR text is the page's text layer, originals stay available.

    required: every page image of a read unit must still be consumed by the
    selected model, which is the older strict contract.
    """
    return 'required' if value == 'required' or value is True else 'optional'


def get_policy(directory: Path) -> dict:
    path = assert_plain_path(Path(directory) / 'document-policy.json')
    try:
        value = json.loads(path.read_text('utf-8')) if path.is_file() else {}
    except (OSError, ValueError, UnicodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    enabled = value.get('local_mineru_enabled') is True
    return {'local_mineru_enabled': enabled,
            'local_ocr': _local_ocr(value.get('local_ocr')),
            'vision_verification': _vision_verification(value.get('vision_verification')),
            'default_engine': 'mineru' if enabled else 'builtin',
            'image_reading': 'selected_model'}


def set_policy(directory: Path, local_mineru_enabled: bool,
               local_ocr: str | None = None, vision_verification: str | None = None) -> dict:
    if type(local_mineru_enabled) is not bool:
        raise ValueError('document_policy_invalid')
    if local_ocr is not None and local_ocr not in LOCAL_OCR_MODES:
        raise ValueError('document_policy_invalid')
    if vision_verification is not None and vision_verification not in VISION_MODES:
        raise ValueError('document_policy_invalid')
    # An older settings file may predate these choices; keep its current values.
    current = get_policy(directory)
    path = assert_plain_path(Path(directory) / 'document-policy.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = assert_plain_path(path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp'))
    try:
        temporary.write_text(json.dumps({'schema_version': 1,
                                        'local_mineru_enabled': local_mineru_enabled,
                                        'local_ocr': local_ocr or current['local_ocr'],
                                        'vision_verification': vision_verification or current['vision_verification']},
                                       sort_keys=True), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return get_policy(directory)
