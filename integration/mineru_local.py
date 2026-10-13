"""DeepSteam's single local MinerU entry for callers outside the document queue.

Runs the installation's own MinerU worker (MinerU 4.0.12 library, MinerU2.5 VLM
weights on disk, official llama.cpp server on loopback). There is no hosted API
path, no API key and no model download here. If the local runtime cannot run
the requested tier, the caller receives an explicit error; nothing downgrades
to another tier or to a remote service.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
from typing import Any, Callable

from integration import document_jobs as jobs

DEFAULT_TIER = jobs.DEFAULT_MINERU_TIER
TIERS = jobs.MINERU_TIERS


class LocalMinerUError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def installed() -> bool:
    python, helper = jobs.mineru_runtime()
    return python.is_file() and helper.is_file()


def status(*, verify: bool = False) -> dict[str, Any]:
    return jobs.engine_status(verify=verify)


def parse_to_directory(source: Path | str, output: Path | str, *, tier: str = DEFAULT_TIER,
                       on_output: Callable[[str], None] | None = None, timeout: int | None = None) -> dict[str, Any]:
    """Parse one local file into a fresh owned directory; return the result."""
    if tier not in TIERS:
        raise LocalMinerUError('tier_invalid', 'Use the advanced, standard or basic local MinerU tier.')
    python, helper = jobs.mineru_runtime()
    if not python.is_file() or not helper.is_file():
        raise LocalMinerUError('document_engine_unavailable',
                               'The local MinerU runtime is not installed in this DeepSteam folder. '
                               'Repair the document runtime; no remote parsing service is used.')
    source = Path(source).resolve(strict=True)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    request = {'schema_version': 1, 'action': 'parse', 'source_path': str(source), 'output_dir': str(output.resolve()),
               'source_sha256': digest, 'engine_options': {'tier': tier}, 'request_id': uuid.uuid4().hex}
    if on_output:
        on_output(f'Parsing locally with MinerU ({tier} tier)...')
    try:
        completed = subprocess.run([str(python), '-I', '-B', str(helper)], input=json.dumps(request).encode('utf-8'),
                                   capture_output=True, env=jobs.child_environment(),
                                   timeout=timeout or jobs.MINERU_TIMEOUT_SECONDS[tier],
                                   **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
    except subprocess.TimeoutExpired:
        raise LocalMinerUError('document_timeout', 'Local MinerU parsing timed out. Split the document or use the standard tier.') from None
    try:
        value = json.loads(completed.stdout.decode('utf-8') or '{}')
    except ValueError:
        value = {}
    if value.get('ok') and value.get('result_path') == 'result.json':
        value = json.loads((output / 'result.json').read_text('utf-8'))
    if not value.get('ok'):
        error = value.get('error') or {}
        raise LocalMinerUError(str(error.get('code') or 'parse_failed'),
                               'Local MinerU parsing failed: ' + str(error.get('message') or 'no result') + ' No remote service was used.')
    if value.get('source_sha256') != digest:
        raise LocalMinerUError('source_changed', 'The source changed during local parsing. Parse it again.')
    return value


def content_list(result: dict[str, Any]) -> list[dict[str, Any]]:
    """MinerU 2.x-style flat ``content_list`` blocks from a MinerU 4 result."""
    blocks: list[dict[str, Any]] = []
    for unit in result.get('units', []):
        page_idx = unit.get('locator', {}).get('page_idx', 0)
        for block in unit.get('blocks', []):
            kind = str(block.get('type', 'text'))
            content = block.get('content')
            text = content if isinstance(content, str) else ''
            captions = [item['content'] for item in block.get('captions', []) if isinstance(item, dict) and isinstance(item.get('content'), str)]
            image = next(_asset_refs(block), None)
            if 'table' in kind:
                body = next((block[key] for key in ('html', 'table_body', 'body', 'content') if isinstance(block.get(key), str)), '')
                blocks.append({'type': 'table', 'table_body': body, 'table_caption': captions, 'img_path': image, 'page_idx': page_idx})
            elif 'equation' in kind or 'formula' in kind:
                blocks.append({'type': 'equation', 'text': text, 'text_format': 'latex', 'img_path': image, 'page_idx': page_idx})
            elif image and any(word in kind for word in ('image', 'figure', 'chart')):
                # Advanced-tier VLM image analysis arrives as block text.
                blocks.append({'type': 'image', 'img_path': image, 'image_caption': captions + ([text] if text else []), 'page_idx': page_idx})
            elif text:
                item = {'type': 'text', 'text': text, 'page_idx': page_idx}
                if 'title' in kind:
                    item['text_level'] = 1
                blocks.append(item)
    return blocks


def _asset_refs(block: dict[str, Any]):
    for key in ('image_path', 'img_path'):
        if isinstance(block.get(key), str) and block[key].startswith('images/'):
            yield block[key]


def parse_to_workdir(source: Path | str, output_base: Path | str, *, tier: str = DEFAULT_TIER,
                     on_output: Callable[[str], None] | None = None) -> Path:
    """DeepTutor layout: ``<base>/<stem>/<stem>.md``, ``<stem>_content_list.json``, ``images/``."""
    source = Path(source)
    stem = source.stem or 'document'
    directory = Path(output_base) / stem
    if directory.exists() and any(directory.iterdir()):
        # Never delete or overwrite an existing folder; use a fresh sibling.
        directory = Path(output_base) / f'{stem}-{uuid.uuid4().hex[:8]}'
    result = parse_to_directory(source, directory, tier=tier, on_output=on_output)
    markdown = directory / 'markdown.md'
    if markdown.is_file():
        os.replace(markdown, directory / f'{stem}.md')
    (directory / f'{stem}_content_list.json').write_text(json.dumps(content_list(result), ensure_ascii=False), encoding='utf-8')
    # The worker's private home (caches, engine log) is not a parse artifact
    # and must not be picked up as content by "*.md" discovery.
    private = directory / '.worker'
    if private.is_dir() and not private.is_symlink() and private.parent == directory:
        shutil.rmtree(private, ignore_errors=True)
    if on_output:
        inference = result.get('inference', {})
        model = inference.get('vlm', {}).get('model') if inference.get('vlm_used') else 'small local models'
        on_output(f'Parsed locally with MinerU {result.get("engine_version")} ({inference.get("actual_tier", tier)} tier, {model}).')
    return directory


__all__ = ['DEFAULT_TIER', 'LocalMinerUError', 'content_list', 'installed', 'parse_to_directory', 'parse_to_workdir', 'status']
