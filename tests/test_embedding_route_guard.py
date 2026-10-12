"""No model or network calls: native effective endpoint and role-default rules."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from integration.embedding_route_guard import embedding_status, guarded_embedding_resolver
from integration.learning_defaults import snapshot_defaults, select_defaults, restore_defaults


class EmbeddingGuardTests(unittest.TestCase):
    def catalog(self, base='http://127.0.0.1:3796/v1/embeddings'):
        return {'services': {'embedding': {'active_profile_id': 'embedding-fixture', 'active_model_id': 'model-fixture',
            'profiles': [{'id': 'embedding-fixture', 'binding': 'openai_compat', 'base_url': base,
                'api_key': 'fixture-only-private-value', 'models': [{'id': 'model-fixture', 'model': 'JJ'}]}]}}}

    def test_existing_chat_gateway_embedding_gets_explanation_without_mutating_profile(self):
        catalog = self.catalog(); original = deepcopy(catalog)
        status = embedding_status(catalog)
        self.assertEqual(status['status'], 'unsupported_chat_gateway')
        self.assertFalse(status['configured'])
        self.assertNotIn('fixture-only-private-value', str(status))
        self.assertNotIn('127.0.0.1', str(status))
        self.assertEqual(catalog, original)

    def test_guard_stops_wrong_local_chat_endpoint_before_client_can_call(self):
        for endpoint in ('http://127.0.0.1:3796/v1/embeddings', 'http://localhost:3796/v1', 'http://127.0.0.1:3795/v1/embeddings'):
            wrapped = guarded_embedding_resolver(lambda: SimpleNamespace(effective_url=endpoint, model='JJ'))
            with self.assertRaisesRegex(ValueError, 'separate'):
                wrapped()
        valid = SimpleNamespace(effective_url='https://embedding.invalid/v1/embeddings', model='embedding-fixture')
        self.assertIs(guarded_embedding_resolver(lambda: valid)(), valid)

    def test_effective_service_override_takes_precedence_for_status(self):
        catalog = self.catalog()
        status = embedding_status(catalog, lambda _c, _s, _p, _m: {'base_url': 'https://embedding.invalid/v1/embeddings', 'binding': 'openai'})
        self.assertEqual(status['status'], 'configured_unverified')
        self.assertIsNone(status['available'])
        valid_catalog = self.catalog('https://embedding.invalid/v1/embeddings')
        status = embedding_status(valid_catalog, lambda _c, _s, _p, _m: {'base_url': 'http://127.0.0.1:3796/v1/embeddings', 'binding': 'openai'})
        self.assertEqual(status['status'], 'unsupported_chat_gateway')

    def test_opaque_chat_route_is_not_an_embedding_model(self):
        catalog = self.catalog('https://embedding.invalid/v1/embeddings')
        catalog['services']['embedding']['profiles'][0]['models'][0]['model'] = 'dsroute_fixture'
        self.assertEqual(embedding_status(catalog)['status'], 'unsupported_chat_gateway')
        with self.assertRaises(ValueError):
            guarded_embedding_resolver(lambda: SimpleNamespace(base_url='https://embedding.invalid/v1/embeddings', model='dsroute_fixture'))()


class LearningDefaultTests(unittest.TestCase):
    def setUp(self):
        self.owner = 'deepsteam-harness-dsroute_fixture'
        self.catalog = {'services': {'llm': {'active_profile_id': self.owner}, 'task': {'mode': 'reference',
            'selection': {'profile_id': 'old-provider', 'model_id': 'old-model'},
            'overrides': {'summary': {'mode': 'inherit'}},
            'profiles': [{'id': 'old-provider', 'api_key': 'private-untouched-fixture'}]},
            'embedding': {'profiles': [{'id': 'independent-embedding'}]}}}
        self.parsing = {'image_description_model': {'profile_id': 'old-vision', 'model_id': 'old-image'}, 'image_caption': False, 'other': 'preserved'}

    def test_global_text_and_verified_vision_inherit_but_other_providers_remain(self):
        snapshot = snapshot_defaults(self.catalog, self.parsing)
        self.assertNotIn('private-untouched-fixture', str(snapshot))
        proposed, parsing = select_defaults(self.catalog, self.parsing, self.owner, True)
        self.assertEqual(proposed['services']['task']['mode'], 'inherit')
        self.assertNotIn('selection', proposed['services']['task'])
        self.assertNotIn('overrides', proposed['services']['task'])
        self.assertEqual(proposed['services']['task']['profiles'], self.catalog['services']['task']['profiles'])
        self.assertEqual(proposed['services']['embedding'], self.catalog['services']['embedding'])
        self.assertIsNone(parsing['image_description_model'])
        self.assertFalse(parsing['image_caption'])
        restored, document, ok = restore_defaults(proposed, parsing, self.owner, snapshot)
        self.assertTrue(ok)
        self.assertEqual(restored, self.catalog)
        self.assertEqual(document, self.parsing)

    def test_unverified_vision_keeps_independent_image_selection(self):
        _, parsing = select_defaults(self.catalog, self.parsing, self.owner, False)
        self.assertEqual(parsing['image_description_model'], self.parsing['image_description_model'])

    def test_later_manual_task_or_model_choice_is_not_undone(self):
        snapshot = snapshot_defaults(self.catalog, self.parsing)
        proposed, parsing = select_defaults(self.catalog, self.parsing, self.owner, True)
        proposed['services']['task']['mode'] = 'reference'
        proposed['services']['task']['selection'] = {'profile_id': 'later-provider', 'model_id': 'later-model'}
        restored, document, ok = restore_defaults(proposed, parsing, self.owner, snapshot)
        self.assertTrue(ok)
        self.assertEqual(restored['services']['task']['mode'], 'reference')
        self.assertEqual(restored['services']['task']['selection'], proposed['services']['task']['selection'])
        self.assertEqual(document['image_description_model'], self.parsing['image_description_model'])
        self.assertNotIn('deepsteam_default_owner', restored['services']['task'])
        proposed['services']['llm']['active_profile_id'] = 'later-global-model'
        with self.assertRaises(ValueError):
            select_defaults(proposed, parsing, self.owner, True)

    def test_explicit_later_image_choice_is_preserved_independently(self):
        snapshot = snapshot_defaults(self.catalog, self.parsing)
        proposed, parsing = select_defaults(self.catalog, self.parsing, self.owner, True)
        parsing['image_description_model'] = {'profile_id': 'later-vision', 'model_id': 'later-image'}
        restored, document, ok = restore_defaults(proposed, parsing, self.owner, snapshot)
        self.assertTrue(ok)
        self.assertEqual(restored, self.catalog)
        self.assertEqual(document['image_description_model'], parsing['image_description_model'])


if __name__ == '__main__':
    unittest.main()
