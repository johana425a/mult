"""Trusted native-learning client for the existing DeepSteam Harness Host.

Only source identities and model-selection references cross this boundary.
The host keeps its own durable session; no SDK/CLI or ambient .dsh is used.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
import httpx

from integration.harness_bridge import HarnessError, HarnessTransport

ROOT = Path(__file__).resolve().parents[1]
PORTAL = 'http://127.0.0.1:3791'


def selection_for_config(config=None):
    """Match the frozen current model to an allowed catalog reference, never a key."""
    from deeptutor.services.llm.config import get_llm_config
    from deeptutor.services.model_selection.runtime import resolve_model_selection, resolved_model_snapshot
    from deeptutor.services.config import get_model_catalog_service
    from deeptutor.services.model_selection.llm import list_llm_options
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.model_access import allowed_llm_options

    target = resolved_model_snapshot(config or get_llm_config())
    options = (list_llm_options(get_model_catalog_service().load()) if get_current_user().is_admin else allowed_llm_options())
    for option in options.get('options', []):
        selection = {key: option[key] for key in ('profile_id', 'model_id')}
        if (config or get_llm_config()).reasoning_effort:
            selection['reasoning_effort'] = (config or get_llm_config()).reasoning_effort
        try:
            _, concrete, snapshot = resolve_model_selection(selection)
        except (ValueError, KeyError):
            continue
        if snapshot.get('configuration_revision') == target.get('configuration_revision'):
            return concrete
    raise HarnessError('model_configuration_changed', 'Select the model for this task again to continue.')


class ExecutionClient:
    def __init__(self, transport=None):
        self.transport = transport or HarnessTransport(ROOT)

    async def request(self, method, path, body=None):
        # Every mutation has an idempotency key or an idempotent operation. A
        # reconnect polls the same task instead of starting another execution.
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                    response = await client.request(method, PORTAL + '/api/harness/internal/execution-tasks' + path,
                        headers={'Authorization': 'Bearer ' + self.transport.token()}, json=body)
                if response.status_code not in {502, 503, 504} or attempt == 3:
                    break
            except httpx.TransportError:
                if attempt == 3:
                    raise HarnessError('execution_connection_interrupted', 'Task progress is saved. Continue when the connection is restored.', 503) from None
            await asyncio.sleep(min(2, .25 * 2 ** attempt))
        if response.status_code >= 400:
            raise HarnessError('execution_connection_interrupted', 'The task connection was interrupted. Saved progress can be resumed.', response.status_code)
        return response.json()

    async def execute(self, *, text, workspace_id, source, task_key, llm_selection=None,
                      owner=None, on_event=None, source_references=None, parent_task_id=None, continuation_task_id=None):
        if owner is None:
            from deeptutor.multi_user.context import get_current_user
            owner = get_current_user().id
        payload = {'owner': owner, 'native_workspace_id': workspace_id, 'source': source,
                   'task_key': task_key, 'text': text, 'llm_selection': llm_selection,
                   'source_references': source_references or [], 'parent_task_id': parent_task_id,
                   'continuation_task_id': continuation_task_id}
        accepted = await self.request('POST', '', payload)
        task = accepted['task']; task_id = task['id']; after = -1
        try:
            while True:
                value = await self.request('GET', '/' + task_id + '?' + urlencode({'owner': owner, 'after_seq': after}))
                task = value['task']
                for event in value.get('events', []):
                    if on_event:
                        await on_event(event)
                after = value.get('next_seq', after)
                if task['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
                    return task
                await asyncio.sleep(.25)
        except asyncio.CancelledError:
            await asyncio.shield(self.request('POST', '/' + task_id + '/cancel', {'owner': owner}))
            raise


def stable_task_key(session_id, turn_id, text):
    return hashlib.sha256(json.dumps([session_id, turn_id, text], ensure_ascii=False).encode()).hexdigest()


async def execute_native_task(text, *, workspace_id=None, source='learning', task_key=None,
                              model_config=None, source_references=None, on_event=None, continuation_task_id=None):
    from deeptutor.services.workspace import get_content_workspace_service
    from deeptutor.services.workspace.context import current_workspace_id
    service = get_content_workspace_service()
    current = workspace_id or current_workspace_id()
    binding = service.binding_by_id(current) if current else service.current_binding()
    # Access check remains tied to the authenticated native user.
    service._assert_allowed_root(binding.root)
    return await ExecutionClient().execute(text=text, workspace_id=binding.workspace_id,
        source=source, task_key=task_key or stable_task_key(binding.workspace_id, source, text),
        llm_selection=selection_for_config(model_config), source_references=source_references, on_event=on_event,
        continuation_task_id=continuation_task_id)
