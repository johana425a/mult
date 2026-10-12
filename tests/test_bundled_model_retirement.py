"""Retirement fixtures only; no real provider, account, service, or user data."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'upstream' / 'DeepTutor')]
from integration.local_qwen_defaults import (LOCAL_PROFILE_ID, LOCAL_MODEL_ID, LOCAL_MODEL,
    LOCAL_BASE_URL, is_local_provider, execution_provider, retire_bundled_catalog,
    retire_native_local_model)
from portal.storage import Store
import portal_runtime


def old_profile():
    return {'id': LOCAL_PROFILE_ID, 'name': 'Built-in model fixture', 'binding': 'llama_cpp',
            'api_format': 'openai_chat', 'base_url': LOCAL_BASE_URL, 'api_key': '',
            'models': [{'id': LOCAL_MODEL_ID, 'name': 'Old model', 'model': LOCAL_MODEL}]}


def catalog(*, active_local=True):
    return {'services': {'llm': {
        'active_profile_id': LOCAL_PROFILE_ID if active_local else 'own',
        'active_model_id': LOCAL_MODEL_ID if active_local else 'own-model',
        'profiles': [old_profile(), {'id': 'own', 'name': 'User provider', 'binding': 'openai',
            'api_format': 'openai_chat', 'base_url': 'https://fixture.invalid/v1',
            'api_key': 'synthetic-not-a-key', 'models': [{'id': 'own-model', 'model': 'user-model'}]}]},
        'embedding': {'profiles': [{'id': 'existing-ocr-independent-embedding'}]}}}


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='retirement-fixture-', dir=ROOT / 'reports')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'DEEPTUTOR_HOME': str(self.home / 'home'),
                                          'DEEPTUTOR_WORKSPACE_ROOT': str(self.home / 'workspace')})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_fresh_catalog_never_seeds_model(self):
        fresh = {'services': {'llm': {'profiles': []}}}
        self.assertEqual(retire_bundled_catalog(fresh), fresh)
        with self.assertRaisesRegex(ValueError, 'choose a model'):
            execution_provider({})

    def test_active_retirement_is_idempotent_and_keeps_other_services(self):
        original = catalog()
        result = retire_bundled_catalog(original)
        service = result['services']['llm']
        self.assertIsNone(service['active_profile_id'])
        self.assertIsNone(service['active_model_id'])
        self.assertEqual(service['selection_required'], 'bundled_model_removed')
        self.assertEqual(service['profiles'], original['services']['llm']['profiles'][1:])
        self.assertEqual(result['services']['embedding'], original['services']['embedding'])
        self.assertEqual(retire_bundled_catalog(result), result)
        self.assertEqual(original, catalog())

    def test_valid_existing_default_is_preserved(self):
        result = retire_bundled_catalog(catalog(active_local=False))['services']['llm']
        self.assertEqual((result['active_profile_id'], result['active_model_id']), ('own', 'own-model'))
        self.assertNotIn('selection_required', result)

    def test_same_name_custom_provider_and_user_modified_tuple_not_removed(self):
        for field, value in [('id', 'user-created'), ('base_url', 'http://localhost:11434/v1')]:
            original = catalog()
            original['services']['llm']['profiles'][0][field] = value
            self.assertEqual(retire_bundled_catalog(original), original)
        original = catalog()
        original['services']['llm']['profiles'][0]['models'][0]['model'] = 'another-user-model'
        self.assertEqual(retire_bundled_catalog(original), original)

    def test_extra_user_model_in_owned_profile_is_preserved(self):
        original = catalog()
        extra = {'id': 'added-model', 'model': 'my-own-model'}
        original['services']['llm']['profiles'][0]['models'].append(extra)
        result = retire_bundled_catalog(original)
        self.assertEqual(result['services']['llm']['profiles'][0]['models'], [extra])

    def test_catalog_normalization_cannot_choose_another_account(self):
        from deeptutor.services.config.model_catalog import ModelCatalogService
        from deeptutor.services.model_selection.llm import apply_llm_selection_to_catalog, list_llm_options
        service = ModelCatalogService(self.home / 'catalog.json')
        service.apply(retire_bundled_catalog(catalog()))
        loaded = service.load()
        self.assertIsNone(service.get_active_profile(loaded, 'llm'))
        self.assertIsNone(service.get_active_model(loaded, 'llm'))
        self.assertIsNone(list_llm_options(loaded)['active'])
        # Per-operation choice works without mutating the unselected default.
        chosen = apply_llm_selection_to_catalog(loaded, {'profile_id': 'own', 'model_id': 'own-model'})
        self.assertNotIn('selection_required', chosen['services']['llm'])
        self.assertEqual(service.get_active_model(chosen, 'llm')['model'], 'user-model')
        self.assertIsNone(service.get_active_model(service.load(), 'llm'))
        # Explicitly saving a valid global selection clears the marker.
        service.apply(chosen)
        self.assertEqual(service.get_active_model(service.load(), 'llm')['model'], 'user-model')

    def test_provider_pool_is_not_a_fallback_for_retired_default(self):
        from deeptutor.services.config.model_catalog import ModelCatalogService
        from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
        service = ModelCatalogService(self.home / 'catalog.json')
        migrated = retire_bundled_catalog(catalog())
        with patch('deeptutor.services.config.provider_runtime._with_personal_llm_profiles', side_effect=lambda c: c), \
             patch('deeptutor.services.config.provider_runtime._collect_provider_pool', side_effect=AssertionError('No fallback lookup')):
            with self.assertRaisesRegex(ValueError, 'Select a global default or a model for this task'):
                resolve_llm_runtime_config(catalog=migrated, service=service)

    def test_native_repeated_initialization_does_not_restore_profile(self):
        from deeptutor.services.config.model_catalog import ModelCatalogService
        service = ModelCatalogService(self.home / 'catalog.json')
        service.apply(catalog())
        with patch('deeptutor.services.config.get_model_catalog_service', return_value=service):
            first, second = retire_native_local_model(), retire_native_local_model()
        self.assertTrue(first['changed'])
        self.assertFalse(second['changed'])
        self.assertIsNone(service.get_active_profile(service.load(), 'llm'))

    def test_startup_initialization_calls_retirement_not_model_installer(self):
        import initialize_deepsteam
        workspace = SimpleNamespace(create_workspace=lambda *a, **kw: {
            'workspace_id': 'fixture-workspace', 'display_name': 'DeepSteam', 'path': str(self.home / 'content')})
        with patch.object(initialize_deepsteam.runtime, 'HOME', self.home), \
             patch.object(initialize_deepsteam.runtime, 'CONTENT', self.home / 'content'), \
             patch.object(initialize_deepsteam.runtime, 'initialize'), \
             patch('deeptutor.services.settings.interface_settings.update_ui_settings'), \
             patch('deeptutor.services.workspace.get_content_workspace_service', return_value=workspace), \
             patch('integration.local_qwen_defaults.retire_native_local_model', return_value={'retired': True}) as retire:
            first = initialize_deepsteam.initialize()
            second = initialize_deepsteam.initialize()
        self.assertTrue(first['initialized']); self.assertFalse(second['initialized'])
        self.assertEqual(retire.call_count, 2)
        self.assertNotIn('local_model', first)

    def test_new_portal_is_unconfigured_and_retains_local_speech(self):
        settings = Store(self.home / 'data').settings()
        self.assertEqual(settings['connection_mode'], 'unconfigured')
        self.assertEqual(settings['model_mode'], 'api')
        self.assertEqual(settings['tts_mode'], 'local')

    def test_portal_migration_preserves_encrypted_setting_and_history(self):
        store = Store(self.home / 'data')
        raw = {'model_mode': 'local', 'base_url': 'https://saved.invalid/v1',
               'model': 'saved-cloud', 'api_key_protected': 'fixture-opaque-not-decrypted',
               'tts_mode': 'local'}
        history = {'id': 'old-lesson', 'title': 'Historical title', 'status': 'interrupted',
                   'resolved_model': json.dumps({'model': LOCAL_MODEL}),
                   'model_snapshot': json.dumps({'selection': {'profile_id': LOCAL_PROFILE_ID, 'model_id': LOCAL_MODEL_ID}})}
        store.insert('lessons', history)
        with store.connect() as db:
            db.execute('INSERT INTO settings VALUES(1,?)', (json.dumps(raw),))
        with patch('portal.storage.protect', side_effect=AssertionError('No decrypt during migration')):
            migrated = Store(self.home / 'data')
            settings = migrated.settings(secret=True)
        self.assertEqual(settings['connection_mode'], 'unconfigured')
        self.assertEqual(settings['api_key'], '')
        with migrated.connect() as db:
            stored = json.loads(db.execute('SELECT value FROM settings').fetchone()[0])
        self.assertEqual(stored['api_key_protected'], raw['api_key_protected'])
        self.assertEqual(stored['base_url'], raw['base_url'])
        self.assertEqual(migrated.get('lessons', 'old-lesson')['model_snapshot'], history['model_snapshot'])

    def test_manual_local_provider_remains_supported_and_old_mode_is_rejected(self):
        store = Store(self.home / 'data')
        setting = store.save_settings({'connection_mode': 'custom', 'base_url': 'http://localhost:11434/v1', 'model': 'user-qwen'})
        self.assertEqual(execution_provider(setting)['model'], 'user-qwen')
        with self.assertRaisesRegex(ValueError, 'removed'):
            store.save_settings({'model_mode': 'local'})
        self.assertEqual(store.settings()['model'], 'user-qwen')

    def test_old_rollback_cannot_reactivate_removed_model(self):
        store = Store(self.home / 'data')
        store.apply_harness_settings('fixture-route', 'fixture-model')
        snapshot = {key: {'present': True, 'value': value} for key, value in {
            'model_mode': 'local', 'connection_selection': 'local'}.items()}
        snapshot['harness_route_id'] = {'present': False, 'value': None}
        self.assertTrue(store.restore_harness_settings('fixture-route', snapshot))
        self.assertEqual(store.settings()['connection_mode'], 'unconfigured')

    def test_application_starts_without_model_listener_or_health(self):
        import test_portal_startup
        status = test_portal_startup.healthy_status()
        with patch.object(portal_runtime, 'harness_installed', return_value=True):
            self.assertTrue(portal_runtime.startup_ready(status))
            self.assertEqual(portal_runtime.missing_services(status, test_portal_startup.owned_processes()), [])
        self.assertNotIn(3795, portal_runtime.EXPECTED_PORTS)
        self.assertNotIn('local_model', portal_runtime.SERVICE_PORTS)
        with patch.object(portal_runtime, 'harness_installed', return_value=True), \
             patch.object(portal_runtime, '_start_upstream_service', side_effect=lambda name, *_: {'service': name}):
            started = portal_runtime.upstream('start')
        self.assertEqual({row['service'] for row in started}, {
            'deeptutor_runtime.py', 'harness_runtime.py', 'openmaic_runtime.py', 'render_runtime.py'})


if __name__ == '__main__':
    unittest.main()
