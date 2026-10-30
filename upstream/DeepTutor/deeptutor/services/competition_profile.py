"""Immutable shipping profile, separate from account permissions and user data."""
import json
from pathlib import Path
from urllib.parse import unquote

PROFILE_PATH = Path(__file__).resolve().parents[1] / 'config' / 'competition-features.json'
CORE = frozenset({'chat', 'reading', 'learning', 'questions', 'documents', 'classroom', 'video'})


def validate_profile(value):
    if value.get('schema') != 1 or not isinstance(value.get('features'), list):
        raise ValueError('Invalid shipping feature profile')
    rows = value['features']
    ids = [row['id'] for row in rows]
    if len(ids) != len(set(ids)) or not CORE.issubset(ids):
        raise ValueError('Missing or duplicate shipping feature')
    for row in rows:
        if not isinstance(row.get('enabled'), bool) or not isinstance(row.get('core'), bool):
            raise ValueError('Invalid feature state')
        if row['id'] in CORE and (row['core'] is not True or row['enabled'] is not True):
            raise ValueError('A required competition feature cannot be hidden')
        for key in ('pages', 'apis'):
            if not isinstance(row.get(key), list) or any(not p.startswith('/') or '?' in p or '#' in p for p in row[key]):
                raise ValueError('Invalid feature route')
    return value


def load_profile():
    return validate_profile(json.loads(PROFILE_PATH.read_text('utf-8')))


def blocked_feature(path, profile):
    path = unquote(path).split('?', 1)[0].rstrip('/') or '/'
    for row in profile['features']:
        if row['enabled']:
            continue
        if any(path == p or path.startswith(p + '/') for p in row['pages'] + row['apis']):
            return row['id']
    return None


class CompetitionProfileMiddleware:
    """Guard HTTP and WebSocket direct entry as well as the navigation links."""
    def __init__(self, app, profile=None):
        self.app = app
        self.profile = load_profile() if profile is None else validate_profile(profile)

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket') and blocked_feature(scope.get('path', '/'), self.profile):
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 1008, 'reason': 'Feature not included in this edition'})
            else:
                body = b'{"code":"feature_not_in_edition","message":"This feature is not included in this edition."}'
                await send({'type':'http.response.start','status':404,'headers':[(b'content-type',b'application/json'),(b'cache-control',b'no-store')]})
                await send({'type':'http.response.body','body':body})
            return
        await self.app(scope, receive, send)
