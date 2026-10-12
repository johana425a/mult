"""DeepSteam's restricted Harness onboarding bridge.

The LLM proposes tools; this module owns credential custody, state transitions
and configuration commits. Unit transports are fixtures, never model evidence.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hmac
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

import httpx
from portal.storage import identifier, now
from integration.model_limits import managed_model_limits

GATEWAY = 'http://127.0.0.1:3796'
GUIDE = {
    'provider': 'deepseek', 'label': 'DeepSeek',
    'links': [
        {'label': 'DeepSeek platform', 'url': 'https://platform.deepseek.com/'},
        {'label': 'API key management', 'url': 'https://platform.deepseek.com/api_keys'},
        {'label': 'Official API documentation', 'url': 'https://api-docs.deepseek.com/'},
        {'label': 'Balance and billing', 'url': 'https://platform.deepseek.com/top_up'},
    ],
    'steps': ['Choose Sign in to DeepSeek and complete authorization on the official page.',
              'If you have an API key, use the dedicated secure field. Do not paste it into chat.',
              'Register on the official platform and review current prices and billing requirements. Complete purchases yourself.',
              'After a successful model test, enable learning and classrooms. Speech uses separate settings.'],
    'billing': 'Signing in does not guarantee free calls. DeepSeek determines permissions and quota.',
}


_UNSET_SELECTION = object()


class HarnessError(RuntimeError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def public_operation(op):
    if not op:
        return None
    return {key: deepcopy(op.get(key)) for key in
            ('id', 'revision', 'status', 'mode', 'model', 'credential_set', 'probe',
             'error_code', 'applied_targets', 'created_at', 'updated_at')}


def safe_code(value):
    value = str(value or 'unavailable').lower()
    return value if re.fullmatch(r'[a-z0-9_]{1,60}', value) else 'upstream_error'


class HarnessTransport:
    def __init__(self, root, dt_url='http://127.0.0.1:8011'):
        self.root = Path(root)
        self.dt_url = dt_url.rstrip('/')

    def token(self):
        from scripts.storage_paths import select_storage
        selected = select_storage(self.root)
        state_root = Path(os.environ.get('DEEPSTEAM_STATE_ROOT', str(selected.state_root)))
        path = state_root / 'runtime' / 'harness-state' / 'control-token'
        if not path.is_file():
            raise HarnessError('host_unavailable', 'The desktop model service has not started.', 503)
        token = path.read_text('utf-8').strip()
        if len(token) < 32:
            raise HarnessError('host_unavailable', 'Desktop model service authentication is not ready.', 503)
        return token

    async def host(self, method, path, body=None, timeout=45):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.request(method, GATEWAY + path,
                    headers={'Authorization': 'Bearer ' + self.token()}, json=body)
            if response.status_code >= 400:
                data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                code = safe_code(data.get('code') or (data.get('error') or {}).get('code') or ('unauthorized' if response.status_code == 401 else 'upstream_error'))
                message = {'workspace_busy': 'This workspace has a running task, pending confirmation, or background command. Stop it before managing the workspace.',
                    'workspace_recovery_required': 'Workspace management is incomplete. Refresh and retry. Files and sessions are retained.',
                    'workspace_archived': 'This workspace was removed. Restore it in workspace management first.',
                    'workspace_protected': 'The default workspace cannot be renamed or removed.',
                    'workspace_unknown': 'The workspace is not registered.'}.get(code, 'The model service request failed. Check connection status.')
                raise HarnessError(code, message, response.status_code)
            return response.json()
        except HarnessError:
            raise
        except (httpx.HTTPError, ValueError):
            raise HarnessError('host_unavailable', 'The model service is temporarily unavailable. Previous settings are retained.', 503) from None

    async def native(self, method, path, body=None):
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                response = await client.request(method, self.dt_url + path, json=body)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise HarnessError('learning_settings_unavailable', 'Learning settings were not saved. Check the learning service and sign-in permissions.', 503) from None

    async def native_internal(self):
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                response = await client.get(self.dt_url + '/api/contest/internal/provider',
                    headers={'Authorization': 'Bearer ' + self.token()})
            if response.status_code != 200:
                raise HarnessError('native_provider_unavailable', 'The learning model is temporarily unavailable. Check learning settings.', 409)
            return response.json()
        except HarnessError:
            raise
        except (httpx.HTTPError, ValueError):
            raise HarnessError('native_provider_unavailable', 'The learning model is temporarily unavailable. Check the learning service.', 503) from None

    async def native_service(self, method, path, body=None):
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                response = await client.request(method, self.dt_url + '/api/contest/internal/' + path,
                    headers={'Authorization': 'Bearer ' + self.token()}, json=body)
            if response.status_code != 200:
                data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                detail = data.get('detail', {}) if isinstance(data, dict) else {}
                code = detail.get('code') if isinstance(detail, dict) else None
                messages = {
                    'model_configuration_changed': 'The saved task model configuration changed. Select a model explicitly and restart the task.',
                    'model_execution_expired': 'The model task expired. Start it again.',
                    'model_selection_unavailable': 'The selected model is unavailable. Check unified model settings.',
                    'model_tools_unsupported': 'This model does not support the tool calls required by the file agent.',
                    'model_not_allowed': 'This model is unavailable to the current account.',
                }
                if code in messages:
                    raise HarnessError(code, messages[code], response.status_code)
                raise HarnessError('learning_defaults_unavailable', 'The default model selection did not synchronize. Check the learning service.', response.status_code)
            return response.json()
        except HarnessError:
            raise
        except (httpx.HTTPError, ValueError):
            raise HarnessError('learning_defaults_unavailable', 'The default model selection did not synchronize. Check the learning service.', 503) from None

    async def native_workspace_service(self, method, path='workspaces', body=None):
        if not re.fullmatch(r'workspaces(?:/[A-Za-z0-9_-]{1,100})?', path):
            raise HarnessError('workspace_identity_invalid', 'The workspace identifier is invalid.', 422)
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                response = await client.request(method, self.dt_url + '/api/contest/internal/' + path,
                    headers={'Authorization': 'Bearer ' + self.token()}, json=body)
            if response.status_code != 200:
                data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                detail = data.get('detail')
                code = safe_code(detail.get('code') if isinstance(detail, dict) else 'workspace_unavailable')
                messages = {'workspace_missing': 'The workspace is not registered.',
                    'workspace_protected': 'The default workspace cannot be renamed or removed.',
                    'workspace_revision_changed': 'The workspace state changed. Refresh and retry.',
                    'workspace_busy_or_unavailable': 'The workspace has running or recoverable tasks. Stop them before managing it.',
                    'workspace_catalog_unavailable': 'The workspace directory is temporarily unavailable. Retry shortly.'}
                raise HarnessError(code, messages.get(code, 'The workspace service is temporarily unavailable. Files and sessions are retained.'), response.status_code)
            return response.json()
        except HarnessError:
            raise
        except (httpx.HTTPError, ValueError):
            raise HarnessError('workspace_unavailable', 'The workspace service is temporarily unavailable. Files and sessions are retained.', 503) from None

    async def native_workspace(self, workspace_id):
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                response = await client.get(self.dt_url + '/api/contest/internal/workspaces/' + workspace_id,
                    headers={'Authorization': 'Bearer ' + self.token()})
            if response.status_code != 200:
                raise HarnessError('workspace_missing', 'The workspace is not registered.', 404)
            return response.json()
        except HarnessError:
            raise
        except (httpx.HTTPError, ValueError):
            raise HarnessError('workspace_directory_unavailable', 'The workspace folder is inaccessible.', 503) from None

    async def host_attachment(self, session_id, attachment_id):
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                response = await client.get(GATEWAY + '/sessions/' + session_id + '/attachments/' + attachment_id,
                    headers={'Authorization': 'Bearer ' + self.token()})
            if response.status_code != 200:
                raise HarnessError('attachment_unavailable', 'The image in this session is unavailable.', response.status_code)
            media_type = response.headers.get('content-type', '').split(';', 1)[0]
            if media_type not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif') or len(response.content) > 25 * 1024 * 1024:
                raise HarnessError('attachment_invalid', 'The image format or size is unsupported for preview.', 422)
            return response.content, media_type
        except HarnessError:
            raise
        except httpx.HTTPError:
            raise HarnessError('attachment_unavailable', 'The image is temporarily unavailable. Retry.', 503) from None


class HarnessBridge:
    def __init__(self, store, root=None, transport=None):
        self.store = store
        self.transport = transport or HarnessTransport(root)
        self.commit_lock = asyncio.Lock()

    def _op(self, op_id=None, revision=None):
        op = self.store.harness_state()
        if not op or (op_id and op['id'] != op_id):
            raise HarnessError('operation_missing', 'This connection operation ended. Start again.')
        if revision is not None and op['revision'] != revision:
            raise HarnessError('stale_revision', 'The state changed. Refresh to continue.')
        return op

    def _save(self, op, expected=None):
        op = deepcopy(op)
        op['revision'] += 1
        op['updated_at'] = now()
        if not self.store.save_harness_state(op, expected_revision=expected):
            raise HarnessError('stale_revision', 'The operation was cancelled or its state changed.')
        return op

    def _new(self, mode):
        existing = self.store.harness_state()
        if existing and existing['status'] in ('authorizing', 'probing', 'applying', 'rolling_back'):
            raise HarnessError('operation_busy', 'Settings are being saved or restored. Please wait.')
        op = {'id': identifier('harness'), 'revision': 1, 'status': 'awaiting_credential',
              'mode': mode, 'model': '', 'credential_set': False, 'probe': None,
              'error_code': None, 'applied_targets': [], 'created_at': now(), 'updated_at': now()}
        self.store.save_harness_state(op)
        return op

    def current(self):
        saved = self.store.harness_state('current')
        return ({'model': saved['model'], 'route_id': saved['route_id'], 'targets': saved['targets'],
                 'mode': saved['route'], 'capabilities': self._capabilities(saved),
                 **managed_model_limits(saved['model'], saved['route'])}
                if saved else None)

    def _capabilities(self, current):
        verified = current.get('capabilities')
        if not isinstance(verified, dict):
            # Old installations stored the actual probe in the operation, not
            # the route. Recover only when its identity still matches.
            operation = self.store.harness_state() or {}
            probe = operation.get('probe') or {}
            matches = (operation.get('id') == current.get('operation_id')
                       and operation.get('model') == current.get('model'))
            verified = {'text': True, 'vision': bool(matches and probe.get('ok') and probe.get('vision'))}
        return {'text': bool(verified.get('text')), 'vision': bool(verified.get('vision'))}

    def connection(self, settings=None):
        """Public display metadata; never a gateway URL, key or account grant."""
        settings = settings if settings is not None else self.store.settings()
        current = self.store.harness_state('current')
        route_id = settings.get('harness_route_id')
        if route_id:
            if not current or current.get('route_id') != route_id:
                raise HarnessError('connection_unavailable', 'The model connection changed. Select a verified connection again.', 409)
            caps = self._capabilities(current)
            value = {'selection': 'current', 'managed': True, 'provider': 'deepseek',
                     'provider_label': 'DeepSeek', 'model': current['model'], 'route': current['route'],
                     'text': {'verified': caps['text']}, 'vision': {'verified': caps['vision']},
                     'targets': {'learning': 'not_selected', 'classroom': 'selected'}}
            value.update(managed_model_limits(current['model'], current['route']))
        else:
            from integration.local_qwen_defaults import is_local_provider
            configured = bool(settings.get('base_url') and settings.get('model')) and settings.get('model_mode') != 'local' and not is_local_provider(settings)
            value = {'selection': 'custom' if configured else 'unconfigured', 'managed': False,
                     'provider': 'custom' if configured else '',
                     'provider_label': 'Custom API' if configured else 'Choose a model',
                     'model': str(settings.get('model', ''))[:200] if configured else '',
                     'route': 'custom' if configured else 'unconfigured',
                     'text': {'verified': False}, 'vision': {'verified': False},
                     'targets': {'learning': 'not_selected', 'classroom': 'selected' if configured else 'not_selected'}}
        local_tts = settings.get('tts_mode', 'local') == 'local'
        value['narration'] = {'enabled': bool(settings.get('tts_enabled', True)),
            'mode': 'local' if local_tts else 'api',
            'configured': local_tts or bool(settings.get('tts_base_url') and settings.get('tts_key_set')),
            'provider': 'windows-system-tts' if local_tts else 'openai-tts',
            'model': 'system-speech' if local_tts else settings.get('tts_model') or 'tts-1',
                     'voice': 'auto-en' if local_tts else settings.get('tts_voice') or 'alloy'}
        return value

    def _route(self, route_id):
        current = self.store.harness_state('current')
        while current:
            if current.get('route_id') == route_id:
                return current
            current = current.get('previous')
        return None

    async def _native_execution(self):
        result = await self.transport.native_internal()
        public = result.get('connection') or {}
        provider = result.get('provider')
        if provider and (str(provider.get('base_url', '')).rstrip('/') == GATEWAY + '/v1'
                         or str(provider.get('model', '')).startswith('dsroute_')):
            route = self._route(provider.get('model'))
            if not route or not hmac.compare_digest(provider.get('api_key', ''), route.get('guard', '')):
                raise HarnessError('native_provider_unavailable', 'The selected desktop connection expired. Enable it again.', 409)
            caps = self._capabilities(route)
            public.update(managed=True, provider='deepseek', provider_label='DeepSeek', model=route['model'],
                route=route['route'], text={'verified': caps['text']}, vision={'verified': caps['vision']})
            limits = managed_model_limits(route['model'], route['route'])
            public.update(limits)
            provider.update(limits)
        public['selection'] = 'native'
        # Copy only declared display fields; a native resolver extension cannot
        # accidentally forward private provider values into browser metadata.
        public = {key: deepcopy(public.get(key)) for key in ('selection', 'managed', 'provider', 'provider_label',
            'model', 'route', 'text', 'vision', 'targets', 'available', 'error_code', 'message',
            'context_window', 'max_output_tokens', 'context_window_source') if key in public}
        public['narration'] = self.connection(self.store.settings())['narration']
        return {'provider': provider, 'connection': public}

    async def connection_status(self):
        # The native catalog is the sole application default. Legacy classroom
        # connection fields remain stored but no longer choose a second model.
        settings = self.store.settings()
        if settings.get('connection_mode') in ('custom', 'local'):
            value = self.connection(settings)
            value['selection_source'] = 'override'
            return value
        result = await self.transport.native_service('POST', 'model-resolution', {})
        model = result['resolved_model']
        return {'selection': 'native', 'managed': False, 'provider': model['provider'],
            'provider_label': model['provider_label'], 'model': model['model'], 'route': 'native',
            'available': True, 'resolved_model': model, 'text': {'verified': False},
            'vision': {'verified': False, 'configured': model.get('capabilities', {}).get('vision') is True},
            'targets': {'learning': 'selected', 'classroom': 'selected'},
            'narration': self.connection()['narration'],
            **{field: model[field] for field in ('context_window', 'max_output_tokens', 'context_window_source') if field in model}}

    async def legacy_connection_status(self):
        defaults_error = None
        try:
            await self.reconcile_learning_defaults()
        except HarnessError as exc:
            # Startup may precede the native backend. A later status read can
            # finish the owned-route migration without login or model calls.
            defaults_error = exc.code
        embedding = {'status': 'unavailable', 'configured': False, 'available': False, 'verified': False,
                     'provider': '', 'model': '', 'message': 'The learning service is unavailable; embedding settings could not be read.'}
        native_catalog = None
        try:
            native_catalog = (await self.transport.native('GET', '/api/settings/catalog'))['catalog']
            embedding = await self.transport.native_service('GET', 'embedding-status')
        except (HarnessError, KeyError, TypeError):
            pass
        if self.store.settings().get('connection_mode') == 'native':
            try:
                value = (await self._native_execution())['connection']
                value['embedding'] = embedding
                return value
            except HarnessError as exc:
                return {'selection': 'native', 'managed': False, 'provider': 'native', 'provider_label': 'Current learning model',
                        'model': '', 'route': 'native', 'available': False, 'error_code': exc.code, 'message': exc.message,
                        'text': {'verified': False}, 'vision': {'verified': False},
                        'targets': {'learning': 'unavailable', 'classroom': 'blocked'},
                        'narration': self.connection()['narration'], 'embedding': embedding}
        value = self.connection()
        value['embedding'] = embedding
        value['learning_defaults'] = {'synchronized': bool((self.store.harness_state('current') or {}).get('learning_defaults_revision') == 1),
                                      'error_code': defaults_error}
        current = self.store.harness_state('current')
        try:
            bucket = native_catalog['services']['llm']
            selected = (current and bucket.get('active_profile_id') == current.get('profile_id')
                        and bucket.get('active_model_id') == current.get('route_id'))
            value['targets']['learning'] = 'selected' if selected and value['managed'] else 'not_selected'
        except (HarnessError, KeyError, TypeError):
            value['targets']['learning'] = 'unavailable'
        return value

    async def status(self, refresh_account=False):
        try:
            health, account = await asyncio.gather(self.transport.host('GET', '/health'),
                self.transport.host('GET', '/account/status' + ('?refresh=true' if refresh_account else '')))
            available = health.get('ok', True)
        except HarnessError as exc:
            available, account = False, {'authenticated': False, 'error_code': exc.code}
        # Never expose arbitrary upstream/account credential fields.
        authenticated = account.get('authenticated', account.get('status') == 'credential-stored')
        attempt_id = account.get('attempt_id') or (account.get('attempt') or {}).get('id')
        attempt_phase = (account.get('attempt') or {}).get('phase')
        account = {**account, 'authenticated': authenticated, 'balance_status': account.get('balance_status', 'not_queried'),
                   'login_pending': account.get('login_pending', (account.get('attempt') or {}).get('phase') == 'waiting')}
        account = {key: deepcopy(account.get(key)) for key in
                   ('authenticated', 'balance_status', 'error_code', 'login_pending', 'expires_at')}
        op = self.store.harness_state()
        if op and op['status'] == 'authorizing':
            matching = bool(op.get('auth_attempt_id') and op['auth_attempt_id'] == attempt_id)
            changed = False
            if matching and attempt_phase in ('failed', 'cancelled', 'timed-out', 'expired'):
                op.update(status='failed', credential_set=False,
                          error_code=safe_code(account.get('error_code') or 'authorization_' + attempt_phase.replace('-', '_')))
                changed = True
            elif account.get('authenticated') and (
                    (matching and attempt_phase in ('succeeded', None))
                    or (op.get('auth_attempt_id') and not attempt_id and not account.get('login_pending'))):
                # After a Host restart the official persisted grant survives,
                # but its in-memory attempt does not. It still needs a fresh
                # actual probe and explicit enablement; cancellation never
                # reaches this branch because cancelled operations stay terminal.
                op.update(status='awaiting_model', credential_set=True, error_code=None)
                changed = True
            elif op.get('auth_attempt_id') and not attempt_id and not account.get('authenticated'):
                op.update(status='failed', credential_set=False, error_code='authorization_interrupted')
                changed = True
            try:
                if changed:
                    op = self._save(op, op['revision'])
            except HarnessError:
                op = self.store.harness_state()
        return {'available': bool(available), 'account': account,
                'operation': public_operation(op), 'current': self.current()}

    async def models(self):
        result = await self.transport.host('GET', '/models')
        models = result.get('models', result.get('data', []))
        rows = []
        for model in models if isinstance(models, list) else []:
            if isinstance(model, dict) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,150}', str(model.get('id', ''))):
                rows.append({'id': model['id'], 'label': str(model.get('label', model['id']))[:200],
                             'vision': bool(model.get('vision', False))})
        return {'models': rows, 'source': 'official-harness', 'available': True}

    async def reuse_connection(self, model):
        """Prepare a user-requested model change with this app's saved reference.

        This makes no inference request and never returns the credential. The
        caller must still probe and apply the new operation before selection.
        """
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,150}', model):
            raise HarnessError('model_invalid', 'Choose a valid model.', 422)
        current = self.store.harness_state('current')
        if not current or current.get('route') not in ('account', 'apikey'):
            raise HarnessError('connection_missing', 'Sign in to DeepSeek or connect an API key first.')
        previous = self.store.harness_state() or {}
        same_credential = (previous.get('mode') == current['route']
                           and (current['route'] == 'account'
                                or previous.get('secret_ref') == current.get('secret_ref')))
        if previous.get('status') == 'credential_invalid' and same_credential:
            raise HarnessError('credential_invalid', 'The credential expired. Sign in again or update the key before retrying.')
        if current['route'] == 'account':
            account = await self.transport.host('GET', '/account/status')
            if not account.get('authenticated', account.get('status') == 'credential-stored'):
                raise HarnessError('account_not_authenticated', 'Sign-in expired. Complete official authorization again.')
        elif not current.get('secret_ref') or not self.store.harness_secret(current['secret_ref']):
            raise HarnessError('credential_invalid', 'The saved key is unavailable. Enter it again.')
        op = self._new(current['route'])
        op.update(status='awaiting_model', model=model, credential_set=True,
                  probe=None, error_code=None)
        if current['route'] == 'apikey':
            op['secret_ref'] = current['secret_ref']
        return {'operation': public_operation(self._save(op, op['revision']))}

    async def start(self):
        op = self._new('account')
        op.update(status='authorizing')
        op = self._save(op, op['revision'])
        try:
            result = await self.transport.host('POST', '/account/login/start', {'operation_id': op['id']})
            url = result.get('authorization_url') or (result.get('attempt') or {}).get('authorizeUrl', '')
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or parsed.hostname != 'platform.deepseek.com'
                    or parsed.path != '/dsh/authorize' or parsed.username or parsed.password
                    or parsed.port not in (None, 443) or parsed.fragment):
                raise HarnessError('authorization_url_invalid', 'The official authorization address did not pass validation.', 502)
            op.update(status='authorizing', auth_attempt_id=result.get('attempt_id') or (result.get('attempt') or {}).get('id'))
            op = self._save(op, op['revision'])
            return {'operation': public_operation(op), 'authorization_url': url, 'expires_at': result.get('expires_at')}
        except HarnessError as exc:
            latest = self.store.harness_state()
            if latest and latest['id'] == op['id'] and latest['revision'] == op['revision']:
                op.update(status='failed', error_code=exc.code)
                self._save(op, op['revision'])
            if exc.code == 'stale_revision':
                try:
                    await self.transport.host('POST', '/account/login/cancel', {'operation_id': op['id']})
                except HarnessError:
                    pass
            raise

    def credential(self, api_key, model='', op_id=None, revision=None):
        if not isinstance(api_key, str) or not 8 <= len(api_key.strip()) <= 8000 or any(c in api_key for c in '\r\n\x00'):
            raise HarnessError('credential_invalid', 'Enter a valid DeepSeek API key in the dedicated field.', 422)
        op = self._op(op_id, revision) if op_id else self._new('apikey')
        if op['status'] in ('authorizing', 'probing', 'applying', 'rolling_back', 'applied'):
            raise HarnessError('operation_busy', 'Start a new connection operation.')
        ref = self.store.put_harness_secret(api_key.strip())
        prior_ref = op.get('secret_ref')
        op.update(mode='apikey', secret_ref=ref, credential_set=True, status='awaiting_model',
                  model=model[:150], probe=None, error_code=None)
        try:
            saved = self._save(op, op['revision'])
        except Exception:
            self.store.delete_harness_secret(ref)
            raise
        active = self.store.harness_state('current') or {}
        if prior_ref and prior_ref != active.get('secret_ref'):
            self.store.delete_harness_secret(prior_ref)
        return {'operation': public_operation(saved)}

    async def cancel(self, op_id=None, revision=None):
        op = self._op(op_id, revision)
        if op['status'] in ('applied', 'applying', 'rolling_back'):
            raise HarnessError('already_applied', 'Use restore settings or sign out to change an enabled connection.')
        op.update(status='cancelled', probe=None, error_code=None)
        op = self._save(op, op['revision'])
        if op['mode'] == 'account':
            try:
                await self.transport.host('POST', '/account/login/cancel', {'operation_id': op['id']})
            except HarnessError:
                pass
        active = self.store.harness_state('current') or {}
        if op.get('secret_ref') and op['secret_ref'] != active.get('secret_ref'):
            self.store.delete_harness_secret(op['secret_ref'])
        return {'operation': public_operation(op)}

    async def probe(self, op_id, revision, model):
        op = self._op(op_id, revision)
        if op['status'] not in ('awaiting_model', 'probe_failed') or not op.get('credential_set'):
            raise HarnessError('probe_not_allowed', 'Sign in first or provide an updated valid key.')
        if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,150}', model):
            raise HarnessError('model_invalid', 'Choose a valid model.', 422)
        op.update(status='probing', model=model, probe=None, error_code=None)
        op = self._save(op, op['revision'])
        expected = op['revision']
        payload = {'route': op['mode'], 'model': model}
        if op['mode'] == 'apikey':
            payload['api_key'] = self.store.harness_secret(op['secret_ref'])
        try:
            result = await self.transport.host('POST', '/probe', payload, timeout=90)
            ok = result.get('ok') is True
            code = None if ok else safe_code(result.get('code') or (result.get('error') or {}).get('code'))
            if (result.get('error') or {}).get('status') == 401:
                code = 'unauthorized'
        except HarnessError as exc:
            ok, code, result = False, exc.code, {}
        op.update(status='verified' if ok else ('credential_invalid' if code in ('unauthorized', 'auth_expired', 'invalid_api_key', '401',
                    'account_token_invalid', 'account_sign_in_required', 'missing_credential') else 'probe_failed'),
                  error_code=code, probe={'ok': ok, 'code': code, 'vision': bool(ok and result.get('vision_verified', False))})
        return {'operation': public_operation(self._save(op, expected))}

    async def _register(self, current):
        await self.transport.host('POST', '/routes', {**{key: current.get(key) for key in
            ('route_id', 'route', 'model', 'secret_ref', 'guard')},
            **managed_model_limits(current['model'], current['route'])})

    async def restore_routes(self):
        operation = self.store.harness_state()
        if operation and operation.get('status') in ('applying', 'rolling_back') and operation.get('recovery'):
            # A durable journal exists before the first external write. A crash
            # cannot leave an unverified half-commit silently selected on restart.
            await self.rollback(operation['id'], operation['revision'], True)
        current = self.store.harness_state('current')
        while current:
            await self._register(current)
            current = current.get('previous')
        await self.reconcile_learning_defaults()

    async def reconcile_learning_defaults(self):
        async with self.commit_lock:
            return await self._reconcile_learning_defaults()

    async def _reconcile_learning_defaults(self):
        """Repair owned route metadata and old defaults without inference."""
        current = self.store.harness_state('current')
        if not current or 'learning' not in current.get('targets', []):
            return
        # A revision describes a previous successful write, not the current
        # native catalog. An older editor or restored backup may remove fields.
        catalog = await self._reconcile_context_metadata(current)
        if current.get('learning_defaults_revision') == 1:
            return
        bucket = catalog.get('services', {}).get('llm', {})
        if (bucket.get('active_profile_id') != current.get('profile_id')
                or bucket.get('active_model_id') != current.get('route_id')):
            return  # a later explicit model choice belongs to the user
        snapshot = current.get('native_snapshot')
        if not isinstance(snapshot, dict):
            # Old classroom-only records used None; do not assume every older
            # database has the same snapshot representation.
            snapshot = current['native_snapshot'] = {}
        if 'learning_defaults' not in snapshot:
            snapshot['learning_defaults'] = await self.transport.native_service('GET', 'learning-defaults')
            # Durable rollback references exist before the first defaults write.
            self.store.save_harness_state(current, 'current')
        await self.transport.native_service('POST', 'learning-defaults',
            {'profile_id': current['profile_id'], 'vision': self._capabilities(current)['vision']})
        current['learning_defaults_revision'] = 1
        self.store.save_harness_state(current, 'current')

    async def _reconcile_context_metadata(self, current):
        """Repair owned metadata through a native atomic field-only merge."""
        catalog = (await self.transport.native('GET', '/api/settings/catalog'))['catalog']
        owned = {}
        route = current
        while route:
            if 'learning' in route.get('targets', []):
                owned[route.get('profile_id')] = route
            route = route.get('previous')
        changed, expected, updates = False, {}, []
        for profile in catalog.get('services', {}).get('llm', {}).get('profiles', []):
            route = owned.get(profile.get('id'))
            # Early releases did not write managed_by. Require the persisted
            # route, exact profile/model identities and our gateway instead of
            # treating the editable ownership label as sufficient evidence.
            if (not route or not route.get('route_id')
                    or profile.get('id') != 'deepsteam-harness-' + route['route_id']
                    or str(profile.get('base_url') or '').rstrip('/') != GATEWAY + '/v1'
                    or profile.get('managed_by') not in (None, '', 'deepsteam-harness')):
                continue
            for model in profile.get('models', []):
                if model.get('id') != route.get('route_id') or model.get('model') != route.get('route_id'):
                    continue
                metadata = {'actual_model': route['model'],
                            **managed_model_limits(route['model'], route['route'])}
                updates.append({key: route[key] for key in ('profile_id', 'route_id', 'model', 'route')})
                for key, value in metadata.items():
                    # The public catalog represents context as an editable string.
                    value = str(value) if key == 'context_window' else value
                    if model.get(key) != value:
                        model[key], changed = value, True
                expected[(profile['id'], model['id'])] = {
                    key: model[key] for key in metadata}
        if changed:
            # Never PUT this GET snapshot: the user may have switched models
            # or edited another profile while the request was in flight.
            await self.transport.native_service('POST', 'learning-context-metadata', {'routes': updates})
            # Verify the native serializer and persisted catalog accepted the
            # fields before recording success. Never trust the submitted copy.
            catalog = (await self.transport.native('GET', '/api/settings/catalog'))['catalog']
        persisted = {(profile.get('id'), model.get('id')): model
                     for profile in catalog.get('services', {}).get('llm', {}).get('profiles', [])
                     for model in profile.get('models', [])}
        if expected and not all(
                all(persisted.get(identity, {}).get(key) == value for key, value in metadata.items())
                for identity, metadata in expected.items()):
            if 'context_metadata_revision' in current:
                current.pop('context_metadata_revision')
                self.store.save_harness_state(current, 'current')
            raise HarnessError('context_metadata_not_saved', 'Model context settings were not saved. Refresh connection status and retry.', 503)
        if expected and current.get('context_metadata_revision') != 1:
            current['context_metadata_revision'] = 1
            self.store.save_harness_state(current, 'current')
        return catalog

    async def _native_snapshot(self):
        catalog = (await self.transport.native('GET', '/api/settings/catalog'))['catalog']
        bucket = catalog.get('services', {}).get('llm', {})
        value = {key: bucket.get(key) for key in ('active_profile_id', 'active_model_id')}
        value['learning_defaults'] = await self.transport.native_service('GET', 'learning-defaults')
        return value

    async def _remove_native(self, profile_id, original):
        if original.get('learning_defaults') is not None:
            await self.transport.native_service('POST', 'learning-defaults/restore',
                {'profile_id': profile_id, 'snapshot': original['learning_defaults']})
        result = await self.transport.native('GET', '/api/settings/catalog')
        catalog = result['catalog']
        bucket = catalog.get('services', {}).get('llm', {})
        bucket['profiles'] = [p for p in bucket.get('profiles', []) if p.get('id') != profile_id]
        if bucket.get('active_profile_id') == profile_id:
            for key in ('active_profile_id', 'active_model_id'):
                bucket[key] = original.get(key)
        # Merge into the just-read redacted catalog: upstream restores masked
        # secrets from its live state. Never replay an old whole-catalog snapshot.
        await self.transport.native('PUT', '/api/settings/catalog', {'catalog': catalog})

    async def apply(self, op_id, revision, confirm, targets):
        if confirm is not True or not targets or set(targets) - {'learning', 'classroom'}:
            raise HarnessError('confirmation_required', 'Select and confirm the features to enable.', 422)
        async with self.commit_lock:
            op = self._op(op_id, revision)
            if op['status'] != 'verified' or not (op.get('probe') or {}).get('ok'):
                raise HarnessError('not_verified', 'Only a model with a successful connection test can be enabled.')
            route_id = identifier('dsroute')
            current = {'route_id': route_id, 'route': op['mode'], 'model': op['model'],
                       'secret_ref': op.get('secret_ref'), 'guard': secrets.token_urlsafe(36),
                       'targets': sorted(set(targets)), 'operation_id': op['id'],
                       'profile_id': 'deepsteam-harness-' + route_id,
                       'native_snapshot': None, 'portal_snapshot': self.store.harness_settings_snapshot(),
                       'previous': self.store.harness_state('current'),
                       'capabilities': {'text': True, 'vision': bool(op['probe']['vision'])},
                       **managed_model_limits(op['model'], op['mode'])}
            if 'learning' in targets:
                current['native_snapshot'] = await self._native_snapshot()
            op.update(status='applying', error_code=None, recovery=current)
            op = self._save(op, op['revision'])
            expected = op['revision']
            native_changed, portal_changed = False, False
            try:
                await self._register(current)
                if 'learning' in targets:
                    profile = {'id': current['profile_id'], 'name': 'DeepSeek desktop connection',
                        'managed_by': 'deepsteam-harness', 'read_only': True,
                        'binding': 'openai', 'api_format': 'openai_chat', 'base_url': GATEWAY + '/v1',
                        'api_key': current['guard'], 'models': [{'id': route_id, 'name': op['model'],
                        'managed_by': 'deepsteam-harness', 'read_only': True,
                        'model': route_id, 'actual_model': op['model'],
                        **{key: str(value) if key == 'context_window' else value
                           for key, value in managed_model_limits(op['model'], op['mode']).items()},
                        'capabilities': {'tools': True, 'vision': bool(op['probe']['vision'])}}]}
                    # Mark before call: timeout may happen after upstream commits.
                    native_changed = True
                    await self.transport.native('POST', '/api/settings/apply/provider',
                        {'service': 'llm', 'profile': profile, 'activate': True, 'active_model_id': route_id})
                    await self.transport.native_service('POST', 'learning-defaults',
                        {'profile_id': current['profile_id'], 'vision': bool(op['probe']['vision'])})
                    current['learning_defaults_revision'] = 1
                    current['context_metadata_revision'] = 1
                self._op(op_id, expected)
                if 'classroom' in targets:
                    self.store.apply_harness_settings(route_id, route_id)
                    portal_changed = True
                self._op(op_id, expected)
                self.store.save_harness_state(current, 'current')
                op.update(status='applied', route_id=route_id, applied_targets=current['targets'], recovery=None)
                op = self._save(op, expected)
                return {'operation': public_operation(op), 'current': self.current()}
            except Exception:
                if portal_changed:
                    self.store.restore_harness_settings(route_id, current['portal_snapshot'])
                rollback_ok = True
                if native_changed:
                    try:
                        await self._remove_native(current['profile_id'], current['native_snapshot'])
                    except HarnessError:
                        rollback_ok = False
                try:
                    await self.transport.host('DELETE', '/routes/' + route_id)
                except HarnessError:
                    pass
                latest = self.store.harness_state()
                if latest and latest['id'] == op_id and latest['revision'] == expected:
                    latest.update(status='apply_failed' if rollback_ok else 'rollback_required',
                                  error_code='apply_failed' if rollback_ok else 'rollback_failed',
                                  recovery=current if not rollback_ok else None)
                    self._save(latest, expected)
                raise HarnessError('apply_failed' if rollback_ok else 'rollback_failed',
                    'Configuration failed. Previous settings were restored.' if rollback_ok else 'Configuration failed and learning settings could not be restored. Use restore settings to recover.', 503) from None

    async def rollback(self, op_id=None, revision=None, confirm=False):
        if confirm is not True:
            raise HarnessError('confirmation_required', 'Confirm restoration of the settings changed by this connection.', 422)
        async with self.commit_lock:
            op = self._op(op_id, revision)
            current = op.get('recovery') or self.store.harness_state('current')
            if not current or current.get('operation_id') != op['id']:
                raise HarnessError('nothing_to_rollback', 'There is no connection configuration to restore.')
            op.update(status='rolling_back')
            op = self._save(op, op['revision'])
            try:
                if 'learning' in current['targets']:
                    await self._remove_native(current['profile_id'], current['native_snapshot'])
                if 'classroom' in current['targets']:
                    self.store.restore_harness_settings(current['route_id'], current['portal_snapshot'])
                await self.transport.host('DELETE', '/routes/' + current['route_id'])
                self.store.save_harness_state(current.get('previous'), 'current')
                op.update(status='rolled_back', applied_targets=[], recovery=None)
                return {'operation': public_operation(self._save(op, op['revision'])), 'current': self.current()}
            except HarnessError:
                op.update(status='rollback_required', error_code='rollback_failed', recovery=current)
                self._save(op, op['revision'])
                raise

    async def signout(self):
        # Restore only our account route before making that credential unavailable.
        current = self.store.harness_state('current')
        if current and current['route'] == 'account':
            op = self.store.harness_state()
            if not op or op['id'] != current['operation_id']:
                # A later cancelled draft must not make the earlier active
                # account impossible to disconnect. Journal a new logout txn.
                op = self._new('account')
                recovery = deepcopy(current)
                recovery['operation_id'] = op['id']
                op.update(status='rollback_required', recovery=recovery)
                op = self._save(op, op['revision'])
            await self.rollback(op['id'], op['revision'], True)
        result = await self.transport.host('POST', '/account/signout', {})
        return {'signed_out': bool(result.get('ok', result.get('signed_out', result.get('status') == 'signed-out'))),
                'operation': public_operation(self.store.harness_state()), 'current': self.current()}

    def provider(self, settings):
        if settings.get('connection_mode') == 'native':
            raise HarnessError('native_provider_resolution_required', 'The current learning model must be resolved by the desktop service.', 409)
        current = self.store.harness_state('current')
        if settings.get('harness_route_id'):
            if not current or settings['harness_route_id'] != current['route_id']:
                raise HarnessError('connection_unavailable', 'The model connection changed. Select a verified connection again.', 409)
            return {'base_url': GATEWAY + '/v1', 'model': current['route_id'],
                    'api_key': current['guard'], 'provider_type': 'openai',
                    **managed_model_limits(current['model'], current['route'])}
        if (settings.get('model_mode') == 'api' and
                (str(settings.get('base_url', '')).rstrip('/') == GATEWAY + '/v1'
                 or str(settings.get('model', '')).startswith('dsroute_'))):
            raise HarnessError('connection_selection_required', 'Choose the current connection. Internal model addresses do not require manual entry.', 409)
        from integration.local_qwen_defaults import execution_provider
        try:
            return execution_provider(settings)
        except ValueError as cause:
            raise HarnessError('model_selection_required', str(cause), 409) from cause

    async def execution_config(self, require_managed=False, llm_selection=_UNSET_SELECTION, execution_id=None, model_snapshot=None):
        settings = self.store.settings(secret=True)
        payload = {'surface': 'classroom',
            **({'execution_id': execution_id} if execution_id else {}),
            **({'model_snapshot': model_snapshot} if model_snapshot else {})}
        if llm_selection is not _UNSET_SELECTION:
            payload['llm_selection'] = llm_selection
        elif not model_snapshot and settings.get('connection_mode') in ('custom', 'local'):
            payload['legacy_provider'] = self.provider(settings)
        selected = await self.transport.native_service('POST', 'model-executions', payload)
        narration = dict(self.connection(settings)['narration'])
        if narration['mode'] == 'api':
            narration.update(base_url=settings.get('tts_base_url', ''), api_key=settings.get('tts_api_key', ''))
        selected['narration'] = narration
        selected['connection']['narration'] = {key: value for key, value in narration.items() if key not in ('base_url', 'api_key')}
        return selected

    async def legacy_execution_config(self, require_managed=False):
        settings = self.store.settings(secret=True)
        if settings.get('connection_mode') == 'native':
            result = await self._native_execution()
            provider, connection = result['provider'], result['connection']
            if not provider:
                raise HarnessError(connection.get('error_code') or 'native_provider_unsupported',
                                   connection.get('message') or 'The current learning model cannot be reused for classrooms.', 409)
        else:
            connection, provider = self.connection(settings), self.provider(settings)
        if require_managed and not connection['managed']:
            raise HarnessError('connection_selection_required', 'Enable a verified model connection first.', 409)
        narration = dict(connection['narration'])
        if narration['mode'] == 'api':
            narration.update(base_url=settings.get('tts_base_url', ''), api_key=settings.get('tts_api_key', ''))
        return {'provider': provider, 'connection': connection, 'narration': narration}

    async def selected_provider(self, settings):
        return (await self.execution_config())['provider']

    async def workspace_provider(self, llm_selection=None):
        selected = await self.transport.native_service('POST', 'model-executions',
            {'llm_selection': llm_selection, 'surface': 'workspace'})
        provider, public = selected['provider'], selected['resolved_model']
        return {'route_id': selected['execution_id'], 'provider': 'deepsteam-custom',
                'model': provider['model'], 'base_url': provider['base_url'], 'api_key': provider['api_key'],
                'resolved_model': public, 'llm_selection': selected.get('selection', llm_selection),
                'vision_verified': public.get('capabilities', {}).get('vision') is True,
                **{field: provider[field] for field in ('context_window', 'max_output_tokens', 'context_window_source') if field in provider}}

    async def legacy_workspace_provider(self):
        """Resolve only this application's active connection, inside the Host."""
        settings = self.store.settings(secret=True)
        selected = await self.execution_config()
        public = selected['connection']
        provider = selected['provider']
        if public['managed']:
            current = self._route(provider['model'])
            value = {'route_id': current['route_id'], 'provider': 'deepseek-account' if current['route'] == 'account' else 'deepseek-official',
                     'model': current['model'], 'vision_verified': public['vision']['verified'],
                     **managed_model_limits(current['model'], current['route'])}
            if current['route'] == 'apikey':
                value['api_key'] = self.secret(current['secret_ref'], current['route_id'])
            return value
        if provider.get('provider_type') != 'openai':
            raise HarnessError('workspace_provider_unsupported', 'This model protocol cannot be used by the file agent. Choose an OpenAI-compatible API.', 409)
        if not provider['base_url'] or not provider['model']:
            raise HarnessError('connection_unavailable', 'Configure a model connection for learning and classrooms first.', 409)
        # Stable nonsecret identity lets pending turns detect a changed custom
        # model without persisting its key in session options.
        import hashlib
        identity = hashlib.sha256((provider['base_url'] + '\n' + provider['model'] + '\n'
                                   + str(provider.get('api_key', ''))).encode()).hexdigest()[:24]
        return {'route_id': 'custom-' + identity, 'provider': 'deepsteam-custom', 'model': public['model'],
                'base_url': provider['base_url'], 'api_key': provider['api_key'], 'vision_verified': False,
                **{key: provider[key] for key in ('context_window', 'max_output_tokens', 'context_window_source')
                   if key in provider}}

    def secret(self, ref, route_id):
        current = self.store.harness_state('current')
        # A previous route can remain live while the user selects another model;
        # only application-created routes with matching opaque refs can resolve.
        while current:
            if current['route_id'] == route_id and current.get('secret_ref') == ref and current['route'] == 'apikey':
                return self.store.harness_secret(ref)
            current = current.get('previous')
        raise HarnessError('credential_unavailable', 'The connection key is unavailable.', 403)

    async def assistant(self, message, op_id=None):
        """Compatibility response for stale clients; never runs an onboarding model."""
        raise HarnessError('onboarding_assistant_removed', 'Use the sign-in or API key controls on the connection page.', 410)

    async def tool(self, name, arguments, op_id=None):
        raise HarnessError('onboarding_assistant_removed', 'Use the sign-in or API key controls on the connection page.', 410)

    def authenticate_internal(self, authorization):
        expected = 'Bearer ' + self.transport.token()
        return hmac.compare_digest(authorization or '', expected)
