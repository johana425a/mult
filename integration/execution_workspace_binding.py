"""Owner-scoped Native workspace admission for installation-authenticated jobs.

The caller is a trusted local service, not a renderer. Its supplied account ID
is resolved against Native identity records before workspace lookup. No missing
or disabled account may inherit the process's default administrator context.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from types import SimpleNamespace

from fastapi import HTTPException, Request


def _error(status, code, message):
    return HTTPException(status, {'code': code, 'message': message})


def native_execution_owner(owner):
    from deeptutor.services.auth import AUTH_ENABLED
    from deeptutor.multi_user.context import user_from_token_payload
    from deeptutor.multi_user.identity import get_user_by_id
    from deeptutor.multi_user.models import LOCAL_ADMIN_ID
    from deeptutor.multi_user.paths import local_admin_user

    # This identity is explicitly returned by Native /api/auth/status only in
    # local auth-disabled mode. It is never a fallback for an arbitrary ID.
    if not AUTH_ENABLED and owner == LOCAL_ADMIN_ID:
        return local_admin_user()
    found = get_user_by_id(owner)
    if not found:
        raise _error(403, 'execution_owner_unavailable', 'The task owner account is unavailable.')
    username, record = found
    if (not isinstance(record, dict) or record.get('disabled')
            or str(record.get('id') or '') != owner):
        raise _error(403, 'execution_owner_unavailable', 'The task owner account is unavailable.')
    # Role comes from the current Native account record, never from the caller.
    user = user_from_token_payload(SimpleNamespace(
        user_id=owner, username=username, role=record.get('role', 'user')))
    if user.id != owner:
        raise _error(403, 'execution_owner_unavailable', 'The task owner account is unavailable.')
    return user


def owner_workspace_binding(owner, workspace_id, *, service_factory=None,
                            owner_resolver=None, context_factory=None):
    if owner_resolver is None:
        owner_resolver = native_execution_owner
    if context_factory is None:
        from deeptutor.multi_user.paths import user_context
        context_factory = user_context
    if service_factory is None:
        from deeptutor.services.workspace import get_content_workspace_service
        service_factory = get_content_workspace_service
    try:
        user = owner_resolver(owner)
        if not user or user.id != owner:
            raise _error(403, 'execution_owner_unavailable', 'The task owner account is unavailable.')
        with context_factory(user):
            service = service_factory()
            row = next((item for item in service.list_workspaces()
                        if item.get('workspace_id') == workspace_id), None)
            if row is None:
                raise _error(404, 'execution_workspace_missing', 'This account has not registered the workspace.')
            if row.get('kind') not in {'workspace', 'general'}:
                raise _error(403, 'execution_workspace_protected', 'Choose a workspace bound to a source folder.')
            if row.get('archived') or row.get('status') != 'ready':
                raise _error(409, 'execution_workspace_unavailable', 'The workspace is archived or its directory is unavailable.')
            binding = service.binding_by_id(workspace_id)
            directory = Path(binding.root).resolve(strict=True)
            # Compare both authoritative resolutions so an inconsistent or
            # concurrently migrated catalog cannot silently select another path.
            registered = Path(row['path']).resolve(strict=True)
            if binding.workspace_id != workspace_id or directory != registered:
                raise _error(409, 'execution_workspace_changed', 'The workspace directory changed. Select it again.')
            service._assert_allowed_root(directory)
            if not directory.is_dir() or not os.access(directory, os.R_OK):
                raise _error(409, 'execution_workspace_unavailable', 'The workspace directory cannot be read.')
            return {'owner': user.id, 'native_workspace_id': binding.workspace_id,
                    'path': str(directory), 'kind': row['kind'], 'archived': False, 'ready': True}
    except HTTPException:
        raise
    except Exception:
        # Do not expose account records, paths or raw backend exceptions.
        raise _error(409, 'execution_workspace_unavailable', 'This account\'s workspace is temporarily unavailable.') from None


def install_execution_workspace_binding(app, authenticate, *, service_factory=None):
    @app.post('/api/contest/internal/workspace-binding')
    async def execution_workspace_binding(request: Request):
        authenticate(request)
        raw = await request.body()
        if len(raw) > 4096:
            raise _error(413, 'execution_binding_invalid', 'The task workspace request is too large.')
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise _error(422, 'execution_binding_invalid', 'The task workspace request is invalid.') from None
        if (not isinstance(body, dict) or set(body) != {'owner', 'native_workspace_id'}
                or any(not isinstance(body[key], str)
                       or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', body[key])
                       for key in ('owner', 'native_workspace_id'))):
            raise _error(422, 'execution_binding_invalid', 'The task account or workspace identifier is invalid.')
        return owner_workspace_binding(body['owner'], body['native_workspace_id'],
                                       service_factory=service_factory)
