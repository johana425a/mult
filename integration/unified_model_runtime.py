"""One catalog resolver and installation-only adapter bridge.

Execution leases hold configuration only in memory. Public snapshots contain no
keys/endpoints, and a lost lease is an explicit error rather than a new default.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
import hmac
import hashlib
import json
import secrets
import time
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


@dataclass
class ExecutionLease:
    config: Any
    selection: dict
    snapshot: dict
    user: Any
    guard: str
    created: float
    surface: str = 'chat'


class UnifiedModelRuntime:
    def __init__(self, *, resolver=None, provider_factory=None, user_loader=None):
        self.resolver = resolver
        self.provider_factory = provider_factory
        self.user_loader = user_loader
        self.leases: dict[str, ExecutionLease] = {}

    def resolve(self, selection=None, surface='chat'):
        from deeptutor.services.model_selection.runtime import resolve_model_selection
        try:
            config, concrete, snapshot = (self.resolver or resolve_model_selection)(selection)
        except PermissionError:
            raise HTTPException(403, {'code': 'model_not_allowed', 'message': 'This model is unavailable to the current account.'}) from None
        except (ValueError, KeyError):
            raise HTTPException(409, {'code': 'model_selection_unavailable', 'message': 'The selected model is unavailable. Check unified model settings.'}) from None
        if surface == 'workspace' and not snapshot.get('capabilities', {}).get('tools'):
            raise HTTPException(409, {'code': 'model_tools_unsupported', 'message': 'This model does not support the tool calls required by the file agent.'})
        return config, concrete, snapshot

    def freeze(self, selection=None, surface='chat', model_snapshot=None):
        from deeptutor.multi_user.context import get_current_user
        if model_snapshot is not None:
            if not isinstance(model_snapshot, dict) or not isinstance(model_snapshot.get('selection'), dict) or not isinstance(model_snapshot.get('resolved_model'), dict):
                raise HTTPException(422, 'Invalid saved model snapshot')
            selection = model_snapshot['selection']
        config, concrete, snapshot = self.resolve(selection, surface)
        if model_snapshot is not None:
            previous = model_snapshot['resolved_model']
            if any(snapshot.get(key) != previous.get(key) for key in ('provider', 'model', 'reasoning_effort', 'configuration_revision')):
                raise HTTPException(409, {'code': 'model_configuration_changed',
                    'message': 'The saved task model configuration changed. Select a model explicitly and restart the task.'})
            snapshot['selection_source'] = previous.get('selection_source', 'override')
        now = time.monotonic()
        self.leases = {key: lease for key, lease in self.leases.items() if now - lease.created < 86400}
        if len(self.leases) >= 1024:
            raise HTTPException(503, {'code': 'model_execution_capacity', 'message': 'Too many model tasks are running. Retry shortly.'})
        key = 'dsexec_' + secrets.token_urlsafe(24)
        self.leases[key] = ExecutionLease(deepcopy(config), deepcopy(concrete), deepcopy(snapshot),
            (self.user_loader or get_current_user)(), secrets.token_urlsafe(32), now, surface)
        return self.execution(key)

    def lease(self, key):
        lease = self.leases.get(key)
        if lease is None or time.monotonic() - lease.created >= 86400:
            raise HTTPException(409, {'code': 'model_execution_expired',
                'message': 'The model task expired. Start again; no other model will be substituted.'})
        return lease

    def execution(self, key):
        lease = self.lease(key)
        value = deepcopy(lease.snapshot)
        return {'execution_id': key, 'selection': dict(lease.selection), 'resolved_model': dict(value),
            'model_snapshot': {'selection': dict(lease.selection), 'resolved_model': dict(value)},
            'provider': {'base_url': 'http://127.0.0.1:8011/api/contest/internal/model/v1',
                'model': key, 'display_model': value['model'], 'api_key': lease.guard,
                'provider_type': 'openai', 'binding': 'openai',
                **{field: value[field] for field in ('context_window', 'max_output_tokens', 'context_window_source') if field in value}},
            'connection': {'selection': 'native', 'managed': False, 'provider': value['provider'],
                'provider_label': value['provider_label'], 'model': value['model'], 'route': 'native',
                'available': True, 'text': {'verified': False},
                'vision': {'verified': False, 'configured': value.get('capabilities', {}).get('vision') is True},
                'targets': {'learning': 'selected', 'classroom': 'selected'},
                'resolved_model': dict(value),
                **{field: value[field] for field in ('context_window', 'max_output_tokens', 'context_window_source') if field in value}}}

    def authorize(self, body, authorization):
        key = body.get('model')
        lease = self.lease(key if isinstance(key, str) else '')
        if not hmac.compare_digest(authorization or '', 'Bearer ' + lease.guard):
            raise HTTPException(401, 'Model execution authentication required')
        messages = body.get('messages')
        if not isinstance(messages, list) or not messages or len(messages) > 10000:
            raise HTTPException(422, 'Invalid model messages')
        if any(not isinstance(item, dict) or item.get('role') not in ('system', 'developer', 'user', 'assistant', 'tool') for item in messages):
            raise HTTPException(422, 'Invalid model message')
        caps = lease.snapshot.get('capabilities', {})
        if body.get('tools') and not caps.get('tools'):
            raise HTTPException(422, {'code': 'model_tools_unsupported'})
        images = any(isinstance(item.get('content'), list) and any(
            isinstance(part, dict) and part.get('type') in ('image_url', 'input_image', 'image')
            for part in item['content']) for item in messages)
        if images and not caps.get('vision'):
            raise HTTPException(422, {'code': 'model_vision_unsupported'})
        response_format = body.get('response_format')
        if response_format is not None and not isinstance(response_format, dict):
            raise HTTPException(422, 'Invalid response format')
        if (response_format or {}).get('type') not in (None, 'text') and not caps.get('json_output'):
            raise HTTPException(422, {'code': 'model_json_unsupported'})
        return lease

    async def invoke(self, lease, body, *, on_content=None, on_reasoning=None):
        from deeptutor.multi_user.context import set_current_user, reset_current_user
        from deeptutor.services.llm.config import set_scoped_llm_config, reset_scoped_llm_config
        from deeptutor.services.llm.provider_factory import get_runtime_provider
        from deeptutor.services.llm.metrics import TurnUsage, current_usage
        config = lease.config
        user_token = set_current_user(lease.user)
        config_token = set_scoped_llm_config(config)
        usage_token = current_usage.set(TurnUsage(source='deepsteam-' + lease.surface))
        try:
            provider = (self.provider_factory or get_runtime_provider)(config)
            maximum = body.get('max_completion_tokens', body.get('max_tokens', 4096))
            if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
                raise HTTPException(422, 'Invalid output token budget')
            cap = getattr(config, 'max_output_tokens', None)
            if cap:
                maximum = min(maximum, cap)
            return await provider.chat_stream_with_retry(
                messages=body['messages'], tools=body.get('tools'), model=config.model,
                max_tokens=maximum, temperature=body.get('temperature', 0.7),
                reasoning_effort=config.reasoning_effort, tool_choice=body.get('tool_choice'),
                on_content_delta=on_content, on_reasoning_delta=on_reasoning,
                allow_image_fallback=False, retry_delays=(),
                **{field: body[field] for field in ('response_format', 'stop', 'parallel_tool_calls') if field in body})
        finally:
            current_usage.reset(usage_token)
            reset_scoped_llm_config(config_token)
            reset_current_user(user_token)

    @staticmethod
    def error(exc):
        from deeptutor.services.llm.provider_core.base import LLMProvider
        status = exc.status_code if isinstance(exc, HTTPException) else LLMProvider._status_code_from_exception(exc)
        status = status or LLMProvider._status_code_from_message(str(exc)) or 502
        return status, {'error': {'code': 'model_execution_failed', 'status': status,
            'message': f'Model request failed (HTTP {status}). Check the selected model connection.'}}

    async def completion(self, body, authorization):
        lease = self.authorize(body, authorization)
        base = {'id': 'chatcmpl-' + secrets.token_hex(12), 'created': int(time.time()),
                'model': lease.snapshot['model'], 'resolved_model': lease.snapshot}
        def tools(response):
            return [call.to_openai_tool_call() for call in response.tool_calls]
        def validate(response):
            if response.finish_reason == 'error':
                raise RuntimeError(response.content or 'Model execution failed')
        if not body.get('stream'):
            try:
                response = await self.invoke(lease, body)
                validate(response)
            except Exception as exc:
                status, failure = self.error(exc)
                return JSONResponse(failure, status_code=status)
            message = {'role': 'assistant', 'content': response.content,
                **({'tool_calls': tools(response)} if response.tool_calls else {}),
                **({'reasoning_content': response.reasoning_content} if response.reasoning_content else {})}
            return JSONResponse({**base, 'object': 'chat.completion', 'choices': [
                {'index': 0, 'message': message, 'finish_reason': response.finish_reason}], 'usage': response.usage})

        async def events():
            queue = asyncio.Queue(maxsize=256)
            async def content(value):
                await queue.put(('delta', {'content': value}))
            async def reasoning(value):
                await queue.put(('delta', {'reasoning_content': value}))
            async def run():
                try:
                    response = await self.invoke(lease, body, on_content=content, on_reasoning=reasoning)
                    validate(response)
                    await queue.put(('done', response))
                except Exception as exc:
                    await queue.put(('error', self.error(exc)[1]))
            task = asyncio.create_task(run())
            def frame(delta, finish=None, usage=None):
                return 'data: ' + json.dumps({**base, 'object': 'chat.completion.chunk',
                    'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}],
                    **({'usage': usage} if usage else {})}, ensure_ascii=False) + '\n\n'
            try:
                yield frame({'role': 'assistant'})
                while True:
                    kind, value = await queue.get()
                    if kind == 'delta':
                        yield frame(value)
                    elif kind == 'error':
                        yield 'data: ' + json.dumps(value, ensure_ascii=False) + '\n\n'
                        break
                    else:
                        if value.tool_calls:
                            yield frame({'tool_calls': [{'index': index, **call} for index, call in enumerate(tools(value))]})
                        yield frame({}, value.finish_reason, value.usage)
                        break
                yield 'data: [DONE]\n\n'
            finally:
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control': 'no-store'})


def install_unified_model_routes(app, authenticate, *, runtime=None):
    from deeptutor.api.routers.auth import require_auth
    runtime = runtime or UnifiedModelRuntime()
    app.state.deepsteam_model_runtime = runtime

    async def body_of(request, allowed):
        raw = await request.body()
        if len(raw) > 25 * 1024 * 1024:
            raise HTTPException(413, 'Model request too large')
        try:
            body = json.loads(raw or '{}')
        except ValueError:
            raise HTTPException(422, 'Invalid model request') from None
        if not isinstance(body, dict) or (allowed is not None and set(body) - set(allowed)):
            raise HTTPException(422, 'Invalid model request fields')
        return body

    @app.post('/api/contest/models/resolve', dependencies=[Depends(require_auth)])
    async def preview(request: Request):
        body = await body_of(request, ('llm_selection', 'surface'))
        _, selection, snapshot = runtime.resolve(body.get('llm_selection'), body.get('surface', 'chat'))
        return {'selection': selection, 'resolved_model': snapshot, 'available': True}

    @app.put('/api/contest/models/default', dependencies=[Depends(require_auth)])
    async def choose_default(request: Request):
        from deeptutor.api.routers.settings import _require_settings_admin
        from deeptutor.services.config import get_model_catalog_service
        from deeptutor.services.llm.config import clear_llm_config_cache
        from deeptutor.services.model_selection import apply_llm_selection_to_catalog
        _require_settings_admin()
        body = await body_of(request, ('llm_selection',))
        if not body.get('llm_selection'):
            raise HTTPException(422, 'Choose a configured model')
        _, selection, _ = runtime.resolve(body['llm_selection'])
        service = get_model_catalog_service()
        def update(catalog):
            selected = apply_llm_selection_to_catalog(catalog, selection)['services']['llm']
            catalog['services']['llm']['active_profile_id'] = selected['active_profile_id']
            catalog['services']['llm']['active_model_id'] = selected['active_model_id']
        service.update(update)
        # Provider pools are keyed by full configuration. Changing the default
        # must not close the client used by an already accepted, pinned task.
        clear_llm_config_cache()
        _, selection, snapshot = runtime.resolve()
        return {'selection': selection, 'resolved_model': snapshot, 'available': True}

    @app.put('/api/contest/models/sessions/{session_id}', dependencies=[Depends(require_auth)])
    async def choose_session(session_id: str, request: Request):
        from deeptutor.services.session import get_session_store
        body = await body_of(request, ('llm_selection',))
        if 'llm_selection' not in body:
            raise HTTPException(422, 'Model selection required')
        _, _, snapshot = runtime.resolve(body['llm_selection'])
        store = get_session_store()
        if not await store.get_session(session_id):
            raise HTTPException(404, 'Session not found')
        await store.update_session_preferences(session_id, {'llm_selection': body['llm_selection']})
        return {'llm_selection': body['llm_selection'], 'resolved_model': snapshot}

    @app.post('/api/contest/internal/model-executions')
    async def freeze(request: Request):
        authenticate(request)
        body = await body_of(request, ('llm_selection', 'surface', 'execution_id', 'model_snapshot', 'legacy_provider'))
        if body.get('execution_id'):
            try:
                return runtime.execution(body['execution_id'])
            except HTTPException:
                if not body.get('model_snapshot'):
                    raise
        selection = body.get('llm_selection')
        if body.get('legacy_provider'):
            selection = materialize_legacy_provider(body['legacy_provider'])
        return runtime.freeze(selection, body.get('surface', 'classroom'), body.get('model_snapshot'))

    @app.post('/api/contest/internal/model-resolution')
    async def internal_preview(request: Request):
        authenticate(request)
        body = await body_of(request, ('llm_selection', 'surface'))
        _, selection, snapshot = runtime.resolve(body.get('llm_selection'), body.get('surface', 'chat'))
        return {'selection': selection, 'resolved_model': snapshot, 'available': True}

    @app.post('/api/contest/internal/model/v1/chat/completions')
    async def complete(request: Request):
        if request.headers.get('origin'):
            raise HTTPException(403, 'Service-only model execution')
        return await runtime.completion(await body_of(request, None), request.headers.get('authorization'))

    return runtime


def materialize_legacy_provider(provider):
    """Move one explicitly saved local classroom override into the same catalog.

    Only installation-authenticated requests reach this migration. No profile is
    activated and no credentials are returned through a browser endpoint.
    """
    from urllib.parse import urlsplit
    from deeptutor.services.config import get_model_catalog_service
    from deeptutor.services.llm.config import clear_llm_config_cache
    if not isinstance(provider, dict):
        raise HTTPException(422, 'Invalid legacy model')
    model, base = str(provider.get('model', '')), str(provider.get('base_url', ''))
    url = urlsplit(base)
    if not model or model.startswith(('dsroute_', 'dsexec_')) or '/api/contest/internal/model/' in base or url.scheme not in ('http', 'https') or not url.hostname:
        raise HTTPException(422, 'Invalid legacy model route')
    identity = hashlib.sha256((base + '\n' + model).encode()).hexdigest()[:20]
    profile_id = 'deepsteam-legacy-classroom-' + identity
    binding = {'openai': 'openai', 'anthropic': 'anthropic', 'google': 'gemini'}.get(provider.get('provider_type', 'openai'))
    if not binding:
        raise HTTPException(409, 'Unsupported saved model protocol')
    def update(catalog):
        profiles = catalog['services']['llm']['profiles']
        migrated = {'id': profile_id, 'name': 'Previous independent classroom configuration', 'binding': binding,
            'base_url': base, 'api_key': provider.get('api_key', ''),
            'api_format': 'anthropic' if binding == 'anthropic' else 'auto',
            'models': [{'id': identity, 'name': model, 'model': model,
                **{key: provider[key] for key in ('context_window', 'max_output_tokens', 'context_window_source') if key in provider}}]}
        for index, item in enumerate(profiles):
            if item.get('id') == profile_id:
                # Keep catalog references stable while honoring edits to the
                # original explicit connection, including credential rotation.
                profiles[index] = migrated
                return
        profiles.append(migrated)
    get_model_catalog_service().update(update)
    clear_llm_config_cache()
    return {'profile_id': profile_id, 'model_id': identity}
