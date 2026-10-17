"""Formula evidence shared by personalized learning and classroom generation.

Original DeepSteam integration. A frozen task model reads original pixels;
unresolved math remains source-only. No imports trigger inference or settings edits.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import asyncio
import hashlib
import json
import time

from integration.formula_review import TOTAL_SECONDS, review_snapshot, teaching_notes
from integration import formula_review as formula_core


def _page_cache_path(image, manifest, model):
    """Reuse verified pixels across planning batches and later single reads."""
    identity = {'schema': 1, 'review_version': formula_core.VERSION,
        'worker': hashlib.sha256((formula_core.ROOT / 'scripts/formula_ocr_worker.py').read_bytes()).hexdigest(),
        'image': hashlib.sha256(image.encode()).hexdigest(),
        'source': {key: manifest.get(key) for key in
                   ('workspace_id', 'path', 'document_sha256', 'asset_id', 'locator')},
        'model': {key: model.get(key) for key in ('provider', 'model', 'configuration_revision', 'reasoning_effort')}}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    storage = formula_core.select_storage(formula_core.ROOT)
    directory = formula_core.assert_plain_path(storage.cache / 'native-formula-pages')
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (key + '.json')


def _cached_page(image, manifest, model):
    started = time.monotonic()
    try:
        value = json.loads(_page_cache_path(image, manifest, model).read_text('utf-8'))
        if value.get('complete') is True and value.get('version') == formula_core.VERSION:
            value.update(cache_hit=True, cache_scope='original_page',
                         elapsed_seconds=round(time.monotonic() - started, 3), calls=[])
            return value
    except (OSError, ValueError, TypeError):
        pass
    return None


def _cache_pages(images, manifest, model, report):
    # A timeout/error must never become a permanent negative cache. Inputs are
    # re-read and version-checked by the caller, never taken from client metadata.
    if report.get('complete') is not True or report.get('version') != formula_core.VERSION:
        return
    for index, (image, entry) in enumerate(zip(images, manifest, strict=True), 1):
        page = deepcopy(report)
        page['candidates'] = [row for row in page.get('candidates', []) if row['image_index'] == index]
        for row in page['candidates']:
            row['image_index'] = row['original_image_index'] = 1
        page['pages'] = [row for row in page.get('pages', []) if row.get('image_index') == index]
        for row in page['pages']:
            row['image_index'] = 1
        page['unscanned_images'] = []
        page['counts'] = {status: sum(row['status'] == status for row in page['candidates'])
                          for status in ('cross_checked', 'visual_consistent', 'source_only')}
        try:
            formula_core._write(_page_cache_path(image, entry, model), page)
        except (OSError, ValueError):
            # Caching is optional; losing it cannot lose the original evidence.
            pass


@dataclass
class _Budget:
    started: float | None = None

    def remaining(self):
        if self.started is None:
            self.started = time.monotonic()
        return max(0, TOTAL_SECONDS - (time.monotonic() - self.started))


_budget = ContextVar('deepsteam_formula_turn_budget', default=None)


@contextmanager
def formula_review_scope():
    """One lazy 115-second allowance across all reads in a native turn."""
    if _budget.get() is not None:
        yield
        return
    token = _budget.set(_Budget())
    try:
        yield
    finally:
        _budget.reset(token)


async def review_native_visuals(content, manifest, *, source_text=''):
    """Keep original pages and reviewed math without multiplying tool images."""
    from deeptutor.services.llm.config import get_scoped_llm_config
    from deeptutor.services.llm.provider_factory import get_runtime_provider
    from deeptutor.services.model_selection.runtime import resolved_model_snapshot

    images = [part['image_url']['url'] for part in content if part.get('type') == 'image_url']
    if not images:
        return list(content), {'status': 'not_applicable', 'elapsed_seconds': 0}
    config = get_scoped_llm_config()
    if config is None:
        # Never resolve a different/global provider for a secondary operation.
        note = 'Formula verification was unavailable without a frozen selected model. Original images are retained; do not infer unclear expressions or grade answers from them.'
        return [*content, {'type': 'text', 'text': note}], {
            'status': 'partial_source_preserved', 'reason': 'no_frozen_model',
            'all_original_images_retained': True, 'elapsed_seconds': 0}
    if len(manifest) != len(images):
        raise ValueError('Formula image evidence and source manifest do not match')
    snapshot = {'text': source_text, 'images': images,
                'document': {'sha256': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()},
                'image_sources': [{**item, 'image_index': i + 1} for i, item in enumerate(manifest)]}
    model = resolved_model_snapshot(config)
    cached = _cached_page(images[0], manifest[0], model) if len(images) == 1 else None
    if cached is not None:
        return [*content, {'type': 'text', 'text': teaching_notes({'formula_review': cached})}], cached
    native = get_runtime_provider(config)

    async def invoke(messages, seconds):
        response = await native.chat_stream_with_retry(
            messages=messages, model=config.model, max_tokens=3500, temperature=0,
            reasoning_effort=config.reasoning_effort, allow_image_fallback=False, retry_delays=())
        if response.finish_reason in {'length', 'error', 'content_filter'}:
            raise ValueError('Incomplete formula visual response')
        return response.content

    budget = _budget.get() or _Budget()
    remaining = budget.remaining()
    started = time.monotonic()
    try:
        reviewed = await review_snapshot(snapshot, {}, model_snapshot={'resolved_model': model},
                                         call_model=invoke, budget_seconds=remaining)
    except Exception as error:
        # A parser/cache failure must not discard the original evidence. Task
        # cancellation remains a BaseException and propagates normally.
        return [*content, {'type': 'text', 'text':
            'Formula verification could not finish. Keep these original source images visible, '
            'mark unclear formulas unverified, and do not guess or base a quiz answer on them.'}], {
            'status': 'partial_source_preserved', 'reason': type(error).__name__,
            'all_original_images_retained': True,
            'elapsed_seconds': round(time.monotonic() - started, 3)}
    report = reviewed['formula_review']
    # The native tool dispatcher has a per-batch image budget. Appending every
    # detected crop made it reject the whole message, including the source page.
    # The unchanged parent pixels already contain each crop. Point annotations
    # back to that parent and keep the bounding box for focused inspection.
    for candidate in report.get('candidates', []):
        candidate['original_image_index'] = candidate['image_index']
    report['image_delivery'] = 'original_pages_with_formula_locations'
    _cache_pages(images, manifest, model, report)
    parts = list(content)
    parts.append({'type': 'text', 'text': teaching_notes(reviewed)})
    return parts, report


async def present_mastery_source(grounded):
    """Reuse a private, immutable preview of the verified original source.

    A model-facing image is not automatically a user-facing attachment. Publish
    through the existing workspace presentation service so links open the
    viewer and survive refresh, without exposing a filesystem path as a route.
    """
    from deeptutor.learning.workspace_sources import validate_workspace_source
    from deeptutor.services.workspace import get_content_workspace_service, WorkspaceError
    from deeptutor.services.workspace.service import _workspace_item_id

    identity = validate_workspace_source(grounded)
    digest = identity.get('document_sha256')
    if not digest or not grounded.available:
        raise ValueError('The source version has not been verified')
    service = get_content_workspace_service()
    binding = service.binding_by_id(identity['workspace_id'])
    item_id = _workspace_item_id(binding.workspace_id, identity['path'], digest)

    def snapshot():
        try:
            _path, item = service.resolve_published_item(binding.workspace_id, item_id)
        except (OSError, ValueError, WorkspaceError):
            items = service.publish(binding, [{'path': identity['path'],
                'caption': 'Original source evidence; not generated content.'}])
            if len(items) != 1:
                raise ValueError('The source preview could not be prepared')
            item = items[0]
        row = item.to_dict()
        if (row.get('sha256') != digest or row.get('relative_path') != identity['path']
                or row.get('workspace_id') != identity['workspace_id']):
            raise ValueError('The source changed while its preview was prepared')
        return [{**row, 'generated': False}]

    return await asyncio.to_thread(snapshot)


async def resolve_mastery_source_id(path_id, source_id, source_index):
    """Resolve a persisted topic row only to a verified source in this turn.

    The mastery status includes topic source row ids while Attached Sources uses
    content-versioned wf ids. Both may be visible to the tutor. Do not resolve
    arbitrary paths or a row from another topic, nor accept a changed file that
    no longer matches the current turn's manifest.
    """
    from deeptutor.learning.storage import LearningStore
    from deeptutor.learning.workspace_sources import ground_workspace_source, validate_workspace_source

    if not source_id.startswith('source_') or not source_index:
        return None
    topic = LearningStore().get_topic(path_id)
    if topic is None:
        return None
    matches = [source for source in topic.sources
               if source.kind.value == 'workspace_file' and source.id == source_id]
    if len(matches) != 1:
        return None
    source = matches[0]
    validate_workspace_source(source)
    grounded = await ground_workspace_source(source, max_chars=24000)
    if not grounded.available:
        return None
    identity = validate_workspace_source(grounded)
    key = f"{identity.get('workspace_id')}:{identity.get('path')}:{identity.get('document_sha256')}"
    expected = 'wf-' + hashlib.sha256(key.encode()).hexdigest()[:24]
    return expected if source_index.get(expected) else None


async def mastery_source_evidence(path_id, source_id):
    """Resolve a source id from this topic; callers cannot supply paths/bytes."""
    from deeptutor.learning.storage import LearningStore
    from deeptutor.learning.workspace_sources import ground_workspace_source, validate_workspace_source
    from deeptutor.learning.workspace_visuals import collect_workspace_visuals

    topic = LearningStore().get_topic(path_id)
    if topic is None:
        raise ValueError('The selected learning topic is no longer available')
    for source in topic.sources:
        if source.kind.value != 'workspace_file':
            continue
        # The picker stores a workspace path before it has read the document.
        # The manifest derives its wf-id from the grounded file hash, so use
        # that same validated snapshot here rather than hashing a missing hash.
        validate_workspace_source(source)
        grounded = await ground_workspace_source(source, max_chars=24000)
        if not grounded.available:
            continue
        identity = validate_workspace_source(grounded)
        key = f"{identity.get('workspace_id')}:{identity.get('path')}:{identity.get('document_sha256')}"
        expected = 'wf-' + hashlib.sha256(key.encode()).hexdigest()[:24]
        if expected != source_id:
            continue
        return grounded, await collect_workspace_visuals([grounded])
    raise ValueError('This source is not attached to the active learning topic')
