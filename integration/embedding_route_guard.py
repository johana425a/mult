"""Keep chat-only local gateways out of the native embedding runtime."""
from __future__ import annotations

from functools import wraps
from urllib.parse import urlsplit

MESSAGE = 'This is a chat connection, not an embedding API. Select a separate embedding service in embedding settings; DeepSeek sign-in does not provide one automatically.'


def chat_only_endpoint(value):
    try:
        parsed = urlsplit(str(value or ''))
        return parsed.hostname in ('127.0.0.1', 'localhost', '::1') and parsed.port in (3795, 3796)
    except ValueError:
        return False


def embedding_status(catalog, resolve_profile=None):
    bucket = (catalog.get('services') or {}).get('embedding') or {}
    profile = next((item for item in bucket.get('profiles', []) if item.get('id') == bucket.get('active_profile_id')), {})
    model = next((item for item in profile.get('models', []) if item.get('id') == bucket.get('active_model_id')), {})
    name = str(model.get('model') or '')[:200]
    effective = resolve_profile(catalog, 'embedding', profile, model) if resolve_profile and profile else profile
    endpoint = effective.get('base_url') or ''
    connection_id = model.get('provider_ref') or profile.get('provider_ref')
    if isinstance(connection_id, dict):
        connection_id = connection_id.get('connection_id') or connection_id.get('id')
    if connection_id and not resolve_profile:
        linked = next((item for item in catalog.get('connections', []) if item.get('id') == connection_id), {})
        endpoint = endpoint or linked.get('base_url') or ''
    if chat_only_endpoint(endpoint) or name.startswith('dsroute_'):
        return {'status': 'unsupported_chat_gateway', 'configured': False, 'available': False, 'verified': False,
            'provider': str(effective.get('binding') or 'chat_gateway')[:100], 'model': name, 'message': MESSAGE}
    configured = bool(profile and name and endpoint)
    return {'status': 'configured_unverified' if configured else 'missing', 'configured': configured,
        'available': None if configured else False, 'verified': False,
        'provider': str(effective.get('binding') or '')[:100], 'model': name,
        'message': 'The separate embedding configuration is retained. Its connection has not been verified.' if configured else 'No separate embedding model is configured or bundled.'}


def guarded_embedding_resolver(resolve):
    @wraps(resolve)
    def guarded(*args, **kwargs):
        value = resolve(*args, **kwargs)
        if (chat_only_endpoint(getattr(value, 'effective_url', None) or getattr(value, 'base_url', None))
                or str(getattr(value, 'model', '')).startswith('dsroute_')):
            raise ValueError(MESSAGE)
        return value
    return guarded


def install_embedding_guard():
    from deeptutor.services.config import provider_runtime
    current = provider_runtime.resolve_embedding_runtime_config
    if getattr(current, '_deepsteam_embedding_guard', False):
        return
    guarded = guarded_embedding_resolver(current)
    guarded._deepsteam_embedding_guard = True
    provider_runtime.resolve_embedding_runtime_config = guarded
    # Consumers imported during initialization keep direct function aliases.
    # Replace aliases only when they still point to the exact original, leaving
    # other extensions and native configuration untouched.
    import sys
    for name in ('deeptutor.services.config', 'deeptutor.services.embedding.config', 'deeptutor.services.config.test_runner'):
        module = sys.modules.get(name)
        if module and getattr(module, 'resolve_embedding_runtime_config', None) is current:
            module.resolve_embedding_runtime_config = guarded
