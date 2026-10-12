"""Internal workspace metadata contract; synthetic data, no model calls."""
import copy
from contextlib import contextmanager
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from integration.deeptutor_shared_provider import install_routes


class NativeWorkspaceManagementTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {'workspace_id': 'folder_one', 'kind': 'workspace', 'display_name': 'Original',
             'path': 'D:/synthetic-folder', 'archived': False, 'status': 'ready',
             'resources': {'skills': ['fixture-skill']}, 'session_ids': ['saved-session']},
            {'workspace_id': 'missing_folder', 'kind': 'workspace', 'display_name': 'Missing',
             'path': 'D:/not-present-fixture', 'archived': True, 'status': 'invalid'},
            {'workspace_id': 'general', 'kind': 'general', 'display_name': 'General', 'archived': False},
            {'workspace_id': 'system', 'kind': 'system', 'display_name': 'System', 'archived': False},
        ]
        self.lease = False
        self.busy = False
        self.recovery = False
        self.calls = []
        owner = self

        class Service:
            def list_workspaces(self):
                return copy.deepcopy(owner.rows)

            def update_workspace(self, identity, **patch):
                assert owner.lease
                row = next(item for item in owner.rows if item['workspace_id'] == identity)
                if 'name' in patch:
                    row['display_name'] = patch['name'].strip()
                if 'archived' in patch:
                    row['archived'] = patch['archived']
                owner.calls.append((identity, patch))
                return copy.deepcopy(row)

        @contextmanager
        def activity(*, exclusive):
            assert exclusive
            if owner.busy:
                raise RuntimeError('fixture busy')
            owner.lease = True
            try:
                yield
            finally:
                owner.lease = False

        def guard():
            assert owner.lease
            if owner.recovery:
                raise RuntimeError('fixture pending recovery')

        app = FastAPI()
        install_routes(app, token_loader=lambda: 'synthetic-local-token',
                       workspace_service_factory=Service,
                       workspace_activity_factory=activity, workspace_recovery_guard=guard)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {'Authorization': 'Bearer synthetic-local-token'}
        self.endpoint = '/api/contest/internal/workspaces'

    def patch(self, identity='folder_one', **payload):
        return self.client.patch(self.endpoint + '/' + identity, json=payload, headers=self.headers)

    def test_authentication_and_origin_before_catalog_or_mutation(self):
        before = copy.deepcopy(self.rows)
        for headers in ({}, {'Authorization': 'Bearer wrong'},
                        {**self.headers, 'Origin': 'http://127.0.0.1:3792'}):
            self.assertIn(self.client.get(self.endpoint, headers=headers).status_code, (401, 403))
            response = self.client.patch(self.endpoint + '/folder_one',
                                         json={'archived': True}, headers=headers)
            self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.rows, before)
        self.assertEqual(self.calls, [])

    def test_catalog_contains_archived_and_missing_folders_for_restore(self):
        result = self.client.get(self.endpoint, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['workspaces'], self.rows)

    def test_rename_archive_restore_preserves_path_resources_and_sessions(self):
        before = copy.deepcopy(self.rows[0])
        self.assertEqual(self.patch(name='  Renamed  ').status_code, 200)
        self.assertEqual(self.patch(archived=True).status_code, 200)
        self.assertEqual(self.patch(archived=False).status_code, 200)
        row = self.rows[0]
        self.assertEqual(row['display_name'], 'Renamed')
        self.assertFalse(row['archived'])
        for field in ('path', 'resources', 'session_ids'):
            self.assertEqual(row[field], before[field])

    def test_restore_missing_path_changes_registration_only(self):
        response = self.patch('missing_folder', archived=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['workspace']['status'], 'invalid')

    def test_protected_unknown_and_invalid_input_do_not_mutate(self):
        for identity in ('general', 'system'):
            self.assertEqual(self.patch(identity, archived=True).status_code, 403)
        self.assertEqual(self.patch('unknown', name='Any').status_code, 404)
        for payload in ({}, {'archived': 'true'}, {'archived': 1}, {'name': ''},
                        {'name': ' '}, {'name': 'x' * 101}, {'path': 'D:/anything'},
                        {'resources': {}}, {'expected': {'name': 'Original', 'archived': False}},
                        {'archived': True, 'expected': {'name': 'Original', 'archived': 0}}):
            self.assertEqual(self.patch(**payload).status_code, 422)
        self.assertEqual(self.calls, [])

    def test_compare_and_swap_prevents_rollback_over_later_rename(self):
        self.assertEqual(self.patch(name='New', expected={'name': 'Original', 'archived': False}).status_code, 200)
        response = self.patch(name='Original', expected={'name': 'Different', 'archived': False})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['code'], 'workspace_revision_changed')
        self.assertEqual(self.rows[0]['display_name'], 'New')

    def test_compare_and_swap_rejects_directory_identity_changed_by_migration(self):
        snapshot = {'name': 'Original', 'archived': False, 'path': 'D:/synthetic-folder', 'kind': 'workspace'}
        self.rows[0]['path'] = 'D:/synthetic-migrated-folder'
        self.assertEqual(self.patch(archived=True, expected=snapshot).status_code, 409)
        self.assertFalse(self.rows[0]['archived'])
        snapshot['path'] = self.rows[0]['path']
        snapshot['kind'] = 'general'
        self.assertEqual(self.patch(archived=True, expected=snapshot).status_code, 409)
        snapshot['kind'] = 'workspace'
        self.assertEqual(self.patch(archived=True, expected=snapshot).status_code, 200)

    def test_busy_or_pending_recovery_rejects_without_changes(self):
        before = copy.deepcopy(self.rows)
        self.busy = True
        self.assertEqual(self.patch(archived=True).status_code, 409)
        self.busy = False
        self.recovery = True
        self.assertEqual(self.patch(name='Changed').status_code, 409)
        self.assertEqual(self.rows, before)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.lease)


class ProviderContextMetadataTests(unittest.TestCase):
    def test_public_real_model_and_internal_transport_keep_current_limits(self):
        from types import SimpleNamespace
        from integration.deeptutor_shared_provider import provider_payload
        resolved = SimpleNamespace(model='dsroute_synthetic', display_model='deepseek-flash',
            base_url='http://127.0.0.1:3796/v1', binding='custom', api_format='openai_chat',
            provider_mode='api', provider_name='openai_compat', extra_headers={}, capabilities={},
            context_window=1000000, max_output_tokens=384000, context_window_source='official-catalog')
        payload = provider_payload(resolved, 'synthetic-key', 'Fixture')
        self.assertEqual(payload['connection']['model'], 'deepseek-flash')
        self.assertNotIn('dsroute_', str(payload['connection']))
        self.assertNotIn('synthetic-key', str(payload['connection']))
        self.assertEqual(payload['provider']['model'], 'dsroute_synthetic')
        for section in ('provider', 'connection'):
            self.assertEqual(payload[section]['context_window'], 1000000)
            self.assertEqual(payload[section]['max_output_tokens'], 384000)
            self.assertEqual(payload[section]['context_window_source'], 'official-catalog')


if __name__ == '__main__':
    unittest.main()
