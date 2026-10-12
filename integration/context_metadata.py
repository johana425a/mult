"""Atomically patch managed-model capacities, never whole user catalogs."""
from integration.model_limits import managed_model_limits

GATEWAY_BASE = 'http://127.0.0.1:3796/v1'


def patch_context_metadata(catalog_service, body):
    """Read and merge under the catalog's own write lock.

    The internal authenticated caller supplies route identities only. Capacity
    values are derived here; selections, labels, credentials and other fields
    are neither accepted nor written.
    """
    if not isinstance(body, dict) or set(body) != {'routes'}:
        raise ValueError('Invalid managed model identities')
    routes = body['routes']
    if not isinstance(routes, list) or not 1 <= len(routes) <= 256:
        raise ValueError('Invalid managed model identities')
    owned = {}
    for route in routes:
        if (not isinstance(route, dict)
                or set(route) != {'profile_id', 'route_id', 'model', 'route'}
                or not all(isinstance(route[key], str) and 0 < len(route[key]) <= 200 for key in route)
                or not route['route_id'].startswith('dsroute_')
                or route['profile_id'] != 'deepsteam-harness-' + route['route_id']
                or route['route'] not in ('account', 'apikey')):
            raise ValueError('Invalid managed model identities')
        identity = (route['profile_id'], route['route_id'])
        if identity in owned and owned[identity] != route:
            raise ValueError('Conflicting managed model identities')
        owned[identity] = route
    result = {'matched': 0, 'updated': 0}

    def merge(catalog):
        for profile in catalog.get('services', {}).get('llm', {}).get('profiles', []):
            if (str(profile.get('base_url') or '').rstrip('/') != GATEWAY_BASE
                    or profile.get('managed_by') not in (None, '', 'deepsteam-harness')):
                continue
            for model in profile.get('models', []):
                route = owned.get((profile.get('id'), model.get('id')))
                if not route or model.get('model') != route['route_id']:
                    continue
                result['matched'] += 1
                metadata = {'actual_model': route['model'],
                            **managed_model_limits(route['model'], route['route'])}
                changed = False
                for key, value in metadata.items():
                    value = str(value) if key == 'context_window' else value
                    if model.get(key) != value:
                        model[key], changed = value, True
                result['updated'] += int(changed)

    # ModelCatalogService.update holds its RLock around both load and save.
    # Concurrent native saves cannot be overwritten by an earlier bridge GET.
    catalog_service.update(merge)
    return result
