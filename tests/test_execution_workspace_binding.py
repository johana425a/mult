"""Synthetic account/workspace admission; no real accounts, files or services."""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from integration.execution_workspace_binding import (
    install_execution_workspace_binding, native_execution_owner, owner_workspace_binding,
)


class OwnerIdentityTests(unittest.TestCase):
    def resolve(self, owner, *, enabled=True, record=None):
        calls = []
        modules = {}
        definitions = {
            'deeptutor.services.auth': {'AUTH_ENABLED': enabled},
            'deeptutor.multi_user.models': {'LOCAL_ADMIN_ID': 'local-admin'},
            'deeptutor.multi_user.paths': {
                'local_admin_user': lambda: SimpleNamespace(id='local-admin', role='admin')},
            'deeptutor.multi_user.identity': {
                'get_user_by_id': lambda value: calls.append(value) or record},
            'deeptutor.multi_user.context': {'user_from_token_payload': lambda value: SimpleNamespace(
                id=value.user_id, role=value.role, username=value.username)},
        }
        for name, contents in definitions.items():
            modules[name] = ModuleType(name)
            modules[name].__dict__.update(contents)
        with patch.dict('sys.modules', modules):
            result = native_execution_owner(owner)
        return result, calls

    def test_current_account_record_owns_role_and_identity(self):
        user, calls = self.resolve('user_a', record=('Account A', {'id': 'user_a', 'role': 'user'}))
        self.assertEqual((user.id, user.role, calls), ('user_a', 'user', ['user_a']))

    def test_missing_disabled_and_mismatched_accounts_never_fall_back(self):
        for enabled in (False, True):
            for record in (None, ('A', {'id': 'user_a', 'disabled': True}),
                           ('A', {'id': 'different', 'role': 'admin'})):
                with self.subTest(enabled=enabled, record=record), self.assertRaises(HTTPException) as error:
                    self.resolve('user_a', enabled=enabled, record=record)
                self.assertEqual(error.exception.status_code, 403)

    def test_local_admin_is_only_synthetic_when_auth_is_disabled(self):
        user, calls = self.resolve('local-admin', enabled=False)
        self.assertEqual((user.id, calls), ('local-admin', []))
        with self.assertRaises(HTTPException):
            self.resolve('local-admin', enabled=True)


class WorkspaceBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='execution-binding-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.current = ContextVar('synthetic-execution-owner', default='ambient_admin')
        self.users = {owner: SimpleNamespace(id=owner) for owner in ('user_a', 'user_b')}
        self.rows = {}
        for owner in self.users:
            directory = self.directory / owner
            directory.mkdir()
            self.rows[owner] = [{'workspace_id': 'ws_' + owner, 'path': str(directory),
                                 'kind': 'workspace', 'archived': False, 'status': 'ready'}]
        self.checked = []
        self.deny_root = False
        self.mismatch = False
        fixture = self

        @contextmanager
        def context(user):
            token = fixture.current.set(user.id)
            try:
                yield
            finally:
                fixture.current.reset(token)
        self.context = context

        class Service:
            def list_workspaces(self):
                return copy.deepcopy(fixture.rows[fixture.current.get()])

            def binding_by_id(self, identity):
                row = next(row for row in fixture.rows[fixture.current.get()] if row['workspace_id'] == identity)
                return SimpleNamespace(workspace_id=identity,
                    root=fixture.directory if fixture.mismatch else Path(row['path']))

            def _assert_allowed_root(self, directory):
                fixture.checked.append((fixture.current.get(), directory))
                if fixture.deny_root:
                    raise RuntimeError('synthetic private directory exception')
                if directory != fixture.directory / fixture.current.get():
                    raise RuntimeError('outside owner root')
        self.service = Service

    def binding(self, owner='user_a', identity='ws_user_a'):
        return owner_workspace_binding(owner, identity, service_factory=self.service,
            owner_resolver=self.users.get, context_factory=self.context)

    def test_resolution_and_root_check_use_requested_owner_and_restore_context(self):
        result = self.binding()
        self.assertEqual(result, {'owner': 'user_a', 'native_workspace_id': 'ws_user_a',
            'path': str(self.directory / 'user_a'), 'kind': 'workspace', 'archived': False, 'ready': True})
        self.assertEqual(self.checked, [('user_a', self.directory / 'user_a')])
        self.assertEqual(self.current.get(), 'ambient_admin')

    def test_cross_user_workspace_and_unknown_owner_are_rejected(self):
        for owner, identity, code in [('user_a', 'ws_user_b', 404), ('unknown', 'ws_user_a', 403)]:
            with self.assertRaises(HTTPException) as error:
                self.binding(owner, identity)
            self.assertEqual(error.exception.status_code, code)
            self.assertEqual(self.current.get(), 'ambient_admin')

    def test_archived_builtin_missing_and_disallowed_directories_fail_closed(self):
        for key, value, code in [('archived', True, 409), ('kind', 'general', 403), ('status', 'invalid', 409)]:
            original = self.rows['user_a'][0][key]
            self.rows['user_a'][0][key] = value
            with self.assertRaises(HTTPException) as error:
                self.binding()
            self.assertEqual(error.exception.status_code, code)
            self.rows['user_a'][0][key] = original
        self.deny_root = True
        with self.assertRaises(HTTPException) as error:
            self.binding()
        self.assertEqual(error.exception.status_code, 409)
        self.assertNotIn('private directory', str(error.exception.detail))
        self.assertEqual(self.current.get(), 'ambient_admin')

    def test_directory_migration_mismatch_is_rejected(self):
        self.mismatch = True
        with self.assertRaises(HTTPException) as error:
            self.binding()
        self.assertEqual(error.exception.detail['code'], 'execution_workspace_changed')


class InternalRouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        def authenticate(request):
            if request.headers.get('origin'):
                raise HTTPException(403)
            if request.headers.get('authorization') != 'Bearer synthetic-service-test':
                raise HTTPException(401)
        install_execution_workspace_binding(app, authenticate)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.endpoint = '/api/contest/internal/workspace-binding'
        self.headers = {'Authorization': 'Bearer synthetic-service-test'}

    def test_authentication_precedes_body_and_owner_resolution(self):
        with patch('integration.execution_workspace_binding.owner_workspace_binding') as resolver:
            for headers in ({}, {'Authorization': 'Bearer wrong'},
                            {**self.headers, 'Origin': 'http://127.0.0.1:3792'}):
                response = self.client.post(self.endpoint, content=b'not-json', headers=headers)
                self.assertIn(response.status_code, (401, 403))
            resolver.assert_not_called()

    def test_strict_request_fields_and_bounded_identifiers(self):
        with patch('integration.execution_workspace_binding.owner_workspace_binding') as resolver:
            for body in ({}, {'owner': 'user_a'}, {'owner': 'user_a', 'native_workspace_id': '../private'},
                         {'owner': 'user_a', 'native_workspace_id': 'ws_user_a', 'role': 'admin'},
                         {'owner': 'user_a', 'native_workspace_id': 'ws_user_a', 'path': 'D:/anything'},
                         {'owner': None, 'native_workspace_id': 'ws_user_a'}, [], None):
                self.assertEqual(self.client.post(self.endpoint, json=body, headers=self.headers).status_code, 422)
            self.assertEqual(self.client.post(self.endpoint, content=b' ' * 4097, headers=self.headers).status_code, 413)
            resolver.assert_not_called()

    def test_success_preserves_only_server_resolved_result(self):
        result = {'owner': 'user_a', 'native_workspace_id': 'ws_user_a', 'path': 'synthetic-folder',
                  'kind': 'workspace', 'archived': False, 'ready': True}
        with patch('integration.execution_workspace_binding.owner_workspace_binding', return_value=result) as resolver:
            response = self.client.post(self.endpoint, json={'owner': 'user_a', 'native_workspace_id': 'ws_user_a'},
                                        headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), result)
            resolver.assert_called_once_with('user_a', 'ws_user_a', service_factory=None)


if __name__ == '__main__':
    unittest.main()
