"""Actual profile loader and ASGI dispatch; no model or native UI evidence."""
import asyncio
import copy
import unittest
from deeptutor.services.competition_profile import (
    CORE, CompetitionProfileMiddleware, blocked_feature, load_profile, validate_profile,
)


class CompetitionProfileTests(unittest.IsolatedAsyncioTestCase):
    def test_required_features_cannot_be_hidden(self):
        for key in CORE:
            profile=copy.deepcopy(load_profile())
            next(row for row in profile['features'] if row['id']==key)['enabled']=False
            with self.assertRaisesRegex(ValueError,'cannot be hidden'):validate_profile(profile)

    def test_missing_duplicate_and_invalid_profile_fail(self):
        profile=load_profile()
        for mutate in (lambda rows:rows.pop(0),lambda rows:rows.append(rows[0]),lambda rows:rows[0].update(enabled='false')):
            bad=copy.deepcopy(profile);mutate(bad['features'])
            with self.assertRaises(ValueError):validate_profile(bad)

    async def test_hidden_routes_reject_http_and_websocket_but_not_neighbors(self):
        profile=copy.deepcopy(load_profile())
        next(row for row in profile['features'] if row['id']=='kanban')['enabled']=False
        forwarded=[]
        async def app(scope,receive,send):forwarded.append(scope['path'])
        guard=CompetitionProfileMiddleware(app,profile)
        for path in ('/kanban','/kanban/board','/api/task-board','/api/task-board/record','/%6banban'):
            events=[]
            async def send(event):events.append(event)
            await guard({'type':'http','path':path},None,send)
            self.assertEqual(events[0]['status'],404)
            self.assertIn(b'feature_not_in_edition',events[1]['body'])
        self.assertEqual(forwarded,[])
        events=[]
        async def send(event):events.append(event)
        await guard({'type':'websocket','path':'/api/task-board'},None,send)
        self.assertEqual(events[0]['code'],1008)
        for path in ('/chat','/learning/reading','/education','/api/reading/1','/kanban-other','/api/task-board-history'):
            self.assertIsNone(blocked_feature(path,profile))
            await guard({'type':'http','path':path},None,send)
        self.assertEqual(len(forwarded),6)

    async def test_enabled_profile_passes_through_and_preserves_lifespan(self):
        calls=[]
        async def app(scope,receive,send):calls.append(scope['type'])
        guard=CompetitionProfileMiddleware(app)
        for kind in ('http','websocket','lifespan'):
            await guard({'type':kind,'path':'/kanban'},None,None)
        self.assertEqual(calls,['http','websocket','lifespan'])

    async def test_unaccepted_partners_are_excluded_at_all_direct_entries(self):
        profile=load_profile()
        partner=next(row for row in profile['features'] if row['id']=='partners')
        self.assertFalse(partner['enabled'])
        called=[]
        async def app(scope,receive,send):called.append(scope)
        guard=CompetitionProfileMiddleware(app,profile)
        for path in ('/partners/new','/partners/groups/new','/api/partners/a',
                     '/api/partner-groups/a','/ws/partners/a','/ws/partner-groups/a'):
            events=[]
            async def send(event):events.append(event)
            kind='websocket' if path.startswith('/ws/') else 'http'
            await guard({'type':kind,'path':path},None,send)
            self.assertEqual(events[0]['code'] if kind=='websocket' else events[0]['status'],
                             1008 if kind=='websocket' else 404)
        self.assertEqual(called,[])
        for path in ('/agents','/chat','/learning','/education','/api/sessions'):
            self.assertIsNone(blocked_feature(path,profile))

    def test_excluded_authoring_cannot_offer_an_unusable_confirmation_card(self):
        from types import SimpleNamespace
        from deeptutor.capabilities.partner_authoring.binding import partner_authoring_trigger
        for mode in ('chat','partner_authoring'):
            context=SimpleNamespace(active_capability=mode,user_message='Create a partner',metadata={})
            self.assertIsNone(partner_authoring_trigger(context))


if __name__=='__main__':unittest.main(verbosity=2)
