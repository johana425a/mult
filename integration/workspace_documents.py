"""Trusted, loopback-only adapter for the shared Harness document reader.

HTTP callers supply workspace identities and relative paths, never process
commands or roots. ``read_managed_document`` is for server-owned upload roots.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path, PureWindowsPath
import re

import httpx

from integration.harness_bridge import HarnessError, HarnessTransport

_ROOT = Path(__file__).resolve().parents[1]
_ACTIONS = {'list', 'search', 'inventory', 'coverage', 'read', 'asset', 'status', 'cancel', 'prepare', 'queue'}
_READ_FIELDS = {'path', 'cursor', 'start_unit', 'ocr', 'max_chars', 'max_units', 'asset_id', 'document_sha256', 'max_dimension', 'engine', 'job_id', 'tier'}
_CATALOG_FIELDS = {'path', 'depth', 'limit', 'query'}
_INVENTORY_FIELDS = {'path', 'cursor', 'limit', 'refresh'}
_COVERAGE_FIELDS = {'path', 'coverage_cursor', 'limit', 'document_sha256'}
_BATCH_FIELDS = {'paths', 'engine', 'tier', 'cancel'}


def _failure(code, message, *, retryable=False, stage=None):
    return {'ok': False, 'status': 'error', 'error': {'code': code, 'message': message,
            'retryable': retryable, 'stage': stage}}


def _payload(action, payload):
    if action in {'list', 'search', 'inventory'} and payload.get('path') == '':
        payload = {**payload, 'path': '.'}
    allowed = (_CATALOG_FIELDS if action in {'list', 'search'} else _INVENTORY_FIELDS if action == 'inventory'
               else _COVERAGE_FIELDS if action == 'coverage' else _BATCH_FIELDS if action in {'prepare', 'queue'}
               else _READ_FIELDS)
    if action not in _ACTIONS or set(payload) - allowed:
        raise ValueError('document_request_invalid')
    if action in {'prepare', 'queue'}:
        paths = payload.get('paths', [])
        if not isinstance(paths, list) or len(paths) > 50 or (action == 'prepare' and not paths):
            raise ValueError('document_path_invalid')
        for path in paths:
            _relative_path(path)
        return dict(payload)
    _relative_path(payload.get('path', '.'))
    return dict(payload)


def _relative_path(path):
    if not isinstance(path, str) or not path or len(path) > 2048 or '\x00' in path:
        raise ValueError('document_path_invalid')
    windows = PureWindowsPath(path)
    if windows.drive or windows.root or '..' in windows.parts:
        raise ValueError('document_path_invalid')


async def document_request(workspace_id: str, action: str, *, wait_seconds: float | None = None, **payload) -> dict:
    """Resolve a native workspace id through its existing authenticated binding.

    A read waits until its job finishes unless ``wait_seconds`` is given; then
    a job still running after that budget is returned as pending (with its
    progress) so a model can continue other work and read again later.
    """
    try:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', workspace_id or ''):
            raise ValueError('workspace_identity_invalid')
        request = _payload(action, payload)
        loop = asyncio.get_running_loop()
        deadline = None if wait_seconds is None else loop.time() + max(0.0, min(300.0, float(wait_seconds)))
        transport = HarnessTransport(_ROOT)
        binding_params = {}
        try:
            from deeptutor.multi_user.context import get_current_user_or_none
            current = get_current_user_or_none()
            if current is not None:
                binding_params['owner'] = current.id
        except ImportError:
            pass  # Standalone Portal has no native request context.
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                    response = await client.get(
                        f'http://127.0.0.1:3791/api/harness/internal/workspaces/{workspace_id}',
                        headers={'Authorization': 'Bearer ' + transport.token()},
                        **({'params': binding_params} if binding_params else {}),
                    )
                response.raise_for_status()
                break
            except (httpx.TransportError, HarnessError):
                if attempt == 2:
                    raise
                await asyncio.sleep(.5 * (attempt + 1))
        binding = response.json()
        harness_id = binding.get('harness_workspace_id')
        if binding.get('workspace_id') != workspace_id or not isinstance(harness_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', harness_id):
            raise ValueError('workspace_binding_invalid')
        connection_failures = 0
        while True:
            if deadline is not None and action == 'read':
                # Each call waits inside the dispatcher for at most the time left.
                request['wait_seconds'] = int(max(0, min(20, deadline - loop.time())))
            try:
                result = await transport.host('POST', f'/workspaces/{harness_id}/documents/{action}', request, timeout=65)
                connection_failures = 0
            except HarnessError as exc:
                if exc.code not in {'host_unavailable', 'host_closing'} or connection_failures >= 3:
                    raise
                connection_failures += 1
                await asyncio.sleep(min(2, .5 * connection_failures))
                continue  # The same request/job id deduplicates after reconnect.
            if action != 'read' or result.get('status') not in {'queued', 'running'}:
                return {**result, 'workspace_id': workspace_id}
            if deadline is not None and loop.time() >= deadline:
                return {**result, 'workspace_id': workspace_id}
            request['job_id'] = result['job_id']
            await asyncio.sleep(min(2, max(.1, result.get('retry_after_ms', 500) / 1000)))
    except asyncio.CancelledError:
        raise  # Detach this waiter; the persisted job remains resumable.
    except ValueError:
        return _failure('document_request_invalid', 'Document not read: the workspace or relative path is invalid.')
    except HarnessError as exc:
        messages = {'workspace_archived': 'Restore the workspace before continuing to read.',
                    'workspace_unknown': 'Select the source workspace again.',
                    'workspace_missing': 'Select the source workspace again.',
                    'workspace_directory_unavailable': 'The source folder moved or is inaccessible. Select it again.',
                    'workspace_recovery_required': 'Workspace recovery is in progress. Continue shortly.'}
        return _failure(exc.code, messages.get(exc.code, 'The document connection was interrupted. The task is retained; continue shortly.'),
                        retryable=exc.status >= 500, stage='workspace_host')
    except httpx.HTTPStatusError as exc:
        code = 'workspace_binding_failed'
        try:
            data = exc.response.json()
            candidate = data.get('code') or data.get('error', {}).get('code')
            if isinstance(candidate, str) and re.fullmatch(r'[A-Za-z0-9_]{1,80}', candidate):
                code = candidate.lower()
        except (ValueError, AttributeError):
            pass
        return _failure(code, 'The source workspace is unavailable. Select it again to continue.',
                        retryable=exc.response.status_code >= 500, stage='workspace_binding')
    except httpx.HTTPError:
        return _failure('workspace_connection_interrupted', 'The document connection was interrupted. The task is retained; continue shortly.',
                        retryable=True, stage='workspace_binding')


def model_view(result: dict) -> dict:
    """Model-facing read result: no duplicated text, navigation at both ends.

    Tool-output trimming keeps a head and a tail of long results, so the next
    position must be present at both ends. The full result stays in metadata.
    """
    if isinstance(result, dict) and result.get('ok') and result.get('status') in {'queued', 'running'} and result.get('job_id') \
            and not isinstance(result.get('units'), list):
        # Not an error: local work continues while the model does other work.
        body = {key: value for key, value in result.items() if key not in {'status', 'retry_after_ms'}}
        return {'status': 'pending', **body, 'how_to_continue': (
            f"{result.get('message') or 'The document is still being read on this computer.'} To continue, call "
            f"workspace_document_read again with the same arguments (it resumes job {result['job_id']}); "
            'workspace_document_prepare with operation=status shows progress.')}
    if not isinstance(result, dict) or not isinstance(result.get('units'), list):
        return result
    navigation = result.get('navigation') or {'next_cursor': result.get('next_cursor'),
                                              'next_start_unit': result.get('next_start_unit'),
                                              'done': not result.get('truncated')}
    complete_hint = ('Text-layer extraction is complete, but visual content remains unread. '
        'Call workspace_document_image for each vision_pending asset using the selected, '
        'image-verified model; do not mark the document fully read.'
        if result.get('visual_pending') or result.get('vision_pending') else
        'Requested document data has been delivered. Delivery is not proof of semantic comprehension.')
    hint = (complete_hint if navigation.get('done') else
            f'Continue with cursor="{navigation.get("next_cursor")}" or, equivalently, start_unit={navigation.get("next_start_unit")}.')
    navigation = {**navigation, 'how_to_continue': hint}
    body = {key: value for key, value in result.items() if key not in {'text', 'navigation', 'units'}}
    units = [{key: value for key, value in unit.items() if key != 'unit_text_sha256'} for unit in result['units'] if isinstance(unit, dict)]
    return {'navigation': navigation, **body, 'units': units, 'navigation_end': navigation}


async def load_workspace_dependencies() -> dict:
    try:
        return await HarnessTransport(_ROOT).host('GET', '/workspace-dependencies', timeout=20)
    except HarnessError:
        return _failure('document_runtime_unavailable', 'Local runtime information is unavailable. No software was installed or downloaded.')


def _runtime_paths():
    # Installation-owned runtime, independent of ambient PATH and user site.
    portable = _ROOT / 'runtime' / 'python' / 'python.exe'
    development = _ROOT / 'runtime' / 'deeptutor-venv' / 'Scripts' / 'python.exe'
    return (portable if portable.is_file() else development), _ROOT / 'scripts' / 'workspace_document_reader.py'


async def read_managed_document(root: Path, path: str, action='read', **payload) -> dict:
    """Read only a root chosen by a trusted server (e.g. its uploads directory).

Never pass an HTTP/model-supplied root to this function. The same standalone
parser enforces canonical/reparse boundaries and budgets in both entrypoints.
"""
    try:
        if action not in {'read', 'asset', 'status', 'cancel', 'inventory', 'coverage'}:
            raise ValueError('document_action_invalid')
        request = _payload(action, {'path': path, **payload})
        trusted_root = Path(root)
        if not trusted_root.is_absolute():
            raise ValueError('document_root_invalid')
        python, _ = _runtime_paths()
        helper = _ROOT / 'scripts/document_job_worker.py'
        if not python.is_file() or not helper.is_file():
            return _failure('document_runtime_unavailable', 'Document not read: the installed reader is incomplete.')
        allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'TEMP', 'TMP'}
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        environment.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
        try:
            max_bytes = min(512 * 1024 * 1024, max(1024 * 1024, int(os.environ.get('EDUAGENT_DOCUMENT_MAX_BYTES', str(200 * 1024 * 1024)))))
        except ValueError:
            max_bytes = 200 * 1024 * 1024
        environment['EDUAGENT_DOCUMENT_MAX_BYTES'] = str(max_bytes)
        arguments = [str(python), '-I', '-B', str(helper)]
        if os.environ.get('DEEPSTEAM_HARNESS_TEST_ROOT'):
            arguments += ['--test-root', os.environ['DEEPSTEAM_HARNESS_TEST_ROOT']]
        while True:
            process = await asyncio.create_subprocess_exec(
                *arguments, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                env=environment, **({'creationflags': 0x08000000} if os.name == 'nt' else {}),
            )
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(json.dumps(
                    {**request, 'action': action, 'root': str(trusted_root)}, ensure_ascii=False,
                ).encode('utf-8')), timeout=35)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                if process.returncode is None:
                    process.kill()  # Only the short waiter, not its detached queue.
                await process.wait()
                raise
            if len(stdout) > 24 * 1024 * 1024:
                return _failure('document_result_limit', 'The document result exceeds the reading limit. Reduce the page range.')
            result = json.loads(stdout)
            if not isinstance(result, dict):
                raise ValueError('document_result_invalid')
            if action != 'read' or result.get('status') not in {'queued', 'running'}:
                return result
            request['job_id'] = result['job_id']
            await asyncio.sleep(.25)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        return _failure('document_connection_interrupted', 'The document connection was interrupted. The task is retained; continue shortly.', retryable=True)
    except (OSError, ValueError):
        return _failure('document_reader_failed', 'Document not read: the file path, format, or reader is unavailable.')
