"""Server-only reuse of this installation's active DeepTutor model selection.

The native resolver owns credential resolution. No catalog or credential file
is exported to the frontend, persisted elsewhere or copied from another app.
"""
from __future__ import annotations

import asyncio
import hmac
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def native_selection():
    from deeptutor.services.config import get_model_catalog_service
    from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
    from deeptutor.services.keypool import primary_api_key
    service = get_model_catalog_service()
    catalog = service.load()
    bucket = catalog.get('services', {}).get('llm', {})
    if not bucket.get('active_profile_id') or not bucket.get('active_model_id'):
        raise HTTPException(409, {'code': 'native_provider_missing', 'message': 'Choose a model in learning settings first.'})
    resolved = resolve_llm_runtime_config(catalog=catalog, service=service)
    profile = next((item for item in bucket.get('profiles', []) if item.get('id') == bucket['active_profile_id']), {})
    return resolved, primary_api_key(resolved.api_key), profile.get('name') or resolved.provider_name


def provider_payload(resolved, key, label):
    model = str(getattr(resolved, 'model', '') or '')
    display_model = str(getattr(resolved, 'display_model', '') or model)
    budget = {}
    for field in ('context_window', 'max_output_tokens'):
        value = getattr(resolved, field, None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            budget[field] = value
    source = getattr(resolved, 'context_window_source', None)
    if source:
        budget['context_window_source'] = str(source)[:100]
    base_url = str(getattr(resolved, 'base_url', '') or '')
    binding = str(getattr(resolved, 'binding', '') or '')
    api_format = str(getattr(resolved, 'api_format', '') or '')
    mode = str(getattr(resolved, 'provider_mode', '') or '')
    metadata = {'selection': 'native', 'managed': False,
        'provider': str(getattr(resolved, 'provider_name', '') or 'native'),
        'provider_label': str(label or 'Current learning model')[:200], 'model': display_model[:200], 'route': 'native',
        'text': {'verified': False}, 'vision': {'verified': False,
            'configured': bool((getattr(resolved, 'capabilities', {}) or {}).get('vision'))},
        'targets': {'learning': 'selected', 'classroom': 'selected'}, 'available': True, **budget}
    provider_type = ('anthropic' if api_format in ('anthropic', 'anthropic_messages')
                     else 'google' if binding in ('gemini', 'google', 'google_genai')
                     else 'openai' if api_format in ('openai_chat', 'auto', '') else None)
    parsed = urlsplit(base_url)
    unsupported = (not provider_type or 'codex' in binding or 'oauth' in mode or 'azure' in binding
                   or bool(getattr(resolved, 'extra_headers', {}))
                   or not model or parsed.scheme not in ('http', 'https') or not parsed.hostname
                   or parsed.username or parsed.password or parsed.query or parsed.fragment)
    if unsupported:
        metadata.update(available=False, error_code='native_provider_unsupported',
            message='This learning connection cannot be reused for classrooms. Choose a DeepSeek connection or a separate classroom API.')
        metadata['targets']['classroom'] = 'blocked'
        return {'connection': metadata, 'provider': None}
    return {'connection': metadata, 'provider': {'model': model, 'display_model': display_model,
            'base_url': base_url, 'api_key': key or '', 'provider_type': provider_type,
            'binding': binding, **budget}}


def install_routes(app, root=None, token_loader=None, resolver=None,
                   workspace_service_factory=None, workspace_activity_factory=None,
                   workspace_recovery_guard=None):
    if getattr(app.state, '_deepsteam_shared_provider', False):
        return
    app.state._deepsteam_shared_provider = True
    if token_loader is None:
        from integration.harness_bridge import HarnessTransport
        transport = HarnessTransport(root or Path(__file__).resolve().parents[1])
        token_loader = transport.token
    resolve = resolver or native_selection

    def workspace_service():
        if workspace_service_factory is not None:
            return workspace_service_factory()
        from deeptutor.services.workspace import get_content_workspace_service
        return get_content_workspace_service()

    def workspace_activity():
        if workspace_activity_factory is not None:
            return workspace_activity_factory(exclusive=True)
        from deeptutor.services.workspace.activity import data_activity
        return data_activity(exclusive=True)

    def check_workspace_recovery():
        if workspace_recovery_guard is not None:
            workspace_recovery_guard()
            return
        from deeptutor.services.workspace.data_migration import assert_no_pending_recovery
        assert_no_pending_recovery(reject_unreadable=True)

    def authenticate(request):
        if request.headers.get('origin'):
            raise HTTPException(403, 'Service-only model connection')
        try:
            expected = 'Bearer ' + token_loader()
        except Exception:
            raise HTTPException(503, 'Internal model service unavailable') from None
        if not hmac.compare_digest(request.headers.get('authorization', ''), expected):
            raise HTTPException(401, 'Internal authentication required')

    from integration.unified_model_runtime import install_unified_model_routes
    install_unified_model_routes(app, authenticate)
    from integration.bilibili_bridge import install_bilibili_routes
    install_bilibili_routes(app, authenticate)
    from integration.domestic_bridge import install_domestic_routes
    install_domestic_routes(app, authenticate)
    from integration.execution_workspace_binding import install_execution_workspace_binding
    install_execution_workspace_binding(app, authenticate, service_factory=workspace_service)
    from integration.harness_turn import install_routes as install_surface_routes
    install_surface_routes(app, authenticate)

    @app.get('/api/contest/internal/provider')
    async def shared_provider(request: Request):
        authenticate(request)
        try:
            return provider_payload(*resolve())
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(409, {'code': 'native_provider_unavailable', 'message': 'The learning model configuration could not be loaded. Check model settings.'}) from None

    @app.get('/api/contest/internal/workspaces')
    async def shared_workspace_catalog(request: Request):
        authenticate(request)
        try:
            return {'workspaces': await asyncio.to_thread(lambda: workspace_service().list_workspaces())}
        except Exception:
            raise HTTPException(409, {'code': 'workspace_catalog_unavailable',
                'message': 'The workspace directory is temporarily unavailable. Retry shortly.'}) from None

    @app.patch('/api/contest/internal/workspaces/{workspace_id}')
    async def manage_shared_workspace(workspace_id: str, request: Request):
        authenticate(request)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', workspace_id):
            raise HTTPException(422, 'Invalid workspace identity')
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(422, 'Invalid workspace update') from None
        if (not isinstance(body, dict) or set(body) - {'name', 'archived', 'expected'}
                or not {'name', 'archived'}.intersection(body)):
            raise HTTPException(422, 'Invalid workspace update')
        if 'name' in body and (not isinstance(body['name'], str)
                or not 1 <= len(body['name'].strip()) <= 100):
            raise HTTPException(422, 'Invalid workspace name')
        if 'archived' in body and not isinstance(body['archived'], bool):
            raise HTTPException(422, 'Invalid workspace archive state')
        expected = body.get('expected')
        if expected is not None and (not isinstance(expected, dict)
                or not {'name', 'archived'}.issubset(expected)
                or set(expected) - {'name', 'archived', 'path', 'kind'}
                or not isinstance(expected['name'], str)
                or not isinstance(expected['archived'], bool)
                or ('path' in expected and (not isinstance(expected['path'], str)
                    or not expected['path'] or len(expected['path']) > 4000 or '\0' in expected['path']))
                or ('kind' in expected and (not isinstance(expected['kind'], str) or not expected['kind']))):
            raise HTTPException(422, 'Invalid workspace revision')
        patch = {key: body[key] for key in ('name', 'archived') if key in body}

        def apply_change():
            # DeepSteam 2026-10-16 workspaces: renaming, removing and restoring only edit
            # this registry row; folders, chats and answers in progress are
            # left alone. The account-wide exclusive data lock taken here before
            # failed whenever any chat (in any workspace) was still finishing or
            # a background import was running, so a workspace could not be
            # removed after chatting. A pending data-migration recovery still
            # blocks changes, and the registry update is itself transactional.
            check_workspace_recovery()
            service = workspace_service()
            row = next((item for item in service.list_workspaces()
                        if item.get('workspace_id') == workspace_id), None)
            if row is None:
                raise HTTPException(404, {'code': 'workspace_missing', 'message': 'Workspace not found.'})
            if row.get('kind') != 'workspace':
                raise HTTPException(403, {'code': 'workspace_protected',
                    'message': 'System and general workspaces cannot be renamed or removed.'})
            if expected is not None and (row.get('display_name') != expected['name']
                    or bool(row.get('archived')) != expected['archived']
                    or ('kind' in expected and row.get('kind') != expected['kind'])
                    or ('path' in expected and os.path.normcase(os.path.normpath(row.get('path', '')))
                        != os.path.normcase(os.path.normpath(expected['path'])))):
                raise HTTPException(409, {'code': 'workspace_revision_changed',
                    'message': 'The workspace state changed. Refresh and retry.'})
            return {'workspace': service.update_workspace(workspace_id, **patch)}

        try:
            return await asyncio.to_thread(apply_change)
        except HTTPException:
            raise
        except Exception as exc:
            from deeptutor.services.workspace.models import WorkspaceError
            message = str(exc).strip() if isinstance(exc, WorkspaceError) else ''
            raise HTTPException(409, {'code': 'workspace_update_failed',
                'message': message or 'The workspace could not be updated. Retry shortly; files and chats are unchanged.'}) from None

    @app.get('/api/contest/internal/workspaces/{workspace_id}')
    async def shared_workspace(workspace_id: str, request: Request):
        authenticate(request)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', workspace_id):
            raise HTTPException(422, 'Invalid workspace identity')
        rows = await asyncio.to_thread(lambda: workspace_service().list_workspaces())
        row = next((item for item in rows
                    if item.get('workspace_id') == workspace_id and not item.get('archived')), None)
        if not row or row.get('status') != 'ready':
            raise HTTPException(404, 'Registered workspace unavailable')
        return {'workspace_id': workspace_id, 'path': row['path']}

    def default_services():
        from deeptutor.services.config import get_model_catalog_service, get_runtime_settings_service
        return get_model_catalog_service(), get_runtime_settings_service()

    @app.get('/api/contest/internal/learning-defaults')
    async def learning_defaults(request: Request):
        authenticate(request)
        from integration.learning_defaults import snapshot_defaults
        catalog_service, settings = default_services()
        return snapshot_defaults(catalog_service.load(), settings.load_document_parsing(include_process_overrides=False))

    @app.get('/api/contest/internal/embedding-status')
    async def current_embedding_status(request: Request):
        authenticate(request)
        from integration.embedding_route_guard import embedding_status
        from deeptutor.services.config.provider_links import resolve_profile_provider
        catalog_service, _ = default_services()
        return embedding_status(catalog_service.load(), resolve_profile_provider)

    @app.post('/api/contest/internal/learning-context-metadata')
    async def update_context_metadata(request: Request):
        authenticate(request)
        from integration.context_metadata import patch_context_metadata
        from deeptutor.services.config import get_model_catalog_service
        from deeptutor.api.routers.settings import _runtime_catalog_write
        try:
            body = await request.json()
            with _runtime_catalog_write():
                return patch_context_metadata(get_model_catalog_service(), body)
        except ValueError:
            raise HTTPException(422, 'Invalid managed model metadata update') from None

    @app.post('/api/contest/internal/learning-defaults')
    async def apply_learning_defaults(request: Request):
        authenticate(request)
        from integration.learning_defaults import select_defaults
        body = await request.json()
        if not isinstance(body, dict) or set(body) - {'profile_id', 'vision'} or not isinstance(body.get('profile_id'), str):
            raise HTTPException(422, 'Invalid managed model defaults')
        catalog_service, settings = default_services()
        catalog = catalog_service.load()
        parsing = settings.load_document_parsing(include_process_overrides=False)
        try:
            proposed, document = select_defaults(catalog, parsing, body['profile_id'], body.get('vision') is True)
            catalog_service.apply(proposed)
            settings.save_document_parsing(document)
            return {'applied': True, 'task': 'inherit', 'image_reading': 'inherit' if body.get('vision') else 'unchanged'}
        except Exception:
            # The portal has a durable reference-only rollback journal and can
            # restore these changes even after an uncertain HTTP timeout.
            raise HTTPException(409, 'Managed model defaults not applied') from None

    @app.post('/api/contest/internal/learning-defaults/restore')
    async def restore_learning_defaults(request: Request):
        authenticate(request)
        from integration.learning_defaults import restore_defaults
        body = await request.json()
        if not isinstance(body, dict) or set(body) - {'profile_id', 'snapshot'} or not isinstance(body.get('snapshot'), dict):
            raise HTTPException(422, 'Invalid managed model defaults')
        catalog_service, settings = default_services()
        proposed, document, restored = restore_defaults(catalog_service.load(),
            settings.load_document_parsing(include_process_overrides=False), body.get('profile_id'), body['snapshot'])
        if restored:
            catalog_service.apply(proposed)
            settings.save_document_parsing(document)
        return {'restored': restored}
