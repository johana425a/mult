"""Internal task wiring fixtures; no provider, credentials or user workspace."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_data = tempfile.TemporaryDirectory()
os.environ['EDUAGENT_DATA'] = str(Path(_data.name) / 'data')

from fastapi.testclient import TestClient
from portal import app as api
from integration.harness_bridge import HarnessError


class ExecutionPortalTests(unittest.TestCase):
    def setUp(self):
        self.host = AsyncMock()
        self.native = AsyncMock(return_value={'owner': 'student', 'native_workspace_id': 'native_1',
            'path': str(Path(_data.name) / 'workspace'), 'kind': 'workspace', 'ready': True, 'archived': False})
        self.bridge = api.harness_bridge()
        self.host_patch = patch.object(self.bridge.transport, 'host', self.host)
        self.native_patch = patch.object(self.bridge.transport, 'native_service', self.native)
        self.auth_patch = patch.object(self.bridge, 'authenticate_internal', side_effect=lambda value: value == 'Bearer fixture-service-token')
        for item in (self.host_patch, self.native_patch, self.auth_patch):
            item.start()
        self.client = TestClient(api.app)
        self.headers = {'authorization': 'Bearer fixture-service-token'}

    def tearDown(self):
        for item in (self.host_patch, self.native_patch, self.auth_patch):
            item.stop()

    def payload(self):
        return {'owner': 'student', 'native_workspace_id': 'native_1', 'text': 'Read fixture material',
                'source': 'learning', 'task_key': 'stable-key', 'source_references': []}

    def test_creation_uses_registered_owner_scope(self):
        self.host.side_effect = [{'workspaces': []}, {'workspace': {'id': 'harness_1'}},
                                 {'task': {'id': 'task_1', 'status': 'queued'}}]
        result = self.client.post('/api/harness/internal/execution-tasks', headers=self.headers, json=self.payload())
        self.assertEqual(result.status_code, 200, result.text)
        self.native.assert_awaited_once_with('POST', 'workspace-binding', {'owner': 'student', 'native_workspace_id': 'native_1'})
        args = self.host.await_args_list[-1].args
        self.assertEqual(args[:2], ('POST', '/execution-tasks'))
        self.assertEqual(args[2]['workspace_id'], 'harness_1')

    def test_credentials_and_browser_requests_cannot_create(self):
        response = self.client.post('/api/harness/internal/execution-tasks', json=self.payload())
        self.assertEqual(response.status_code, 401)
        response = self.client.post('/api/harness/internal/execution-tasks',
            headers={**self.headers, 'origin': 'http://testserver'}, json=self.payload())
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/api/harness/internal/execution-tasks', headers=self.headers,
            json={**self.payload(), 'path': 'C:/', 'api_key': 'fixture-not-secret'})
        self.assertEqual(response.status_code, 422)
        self.host.assert_not_awaited()

    def test_owner_mismatch_rejected_before_host(self):
        self.native.return_value['owner'] = 'other-user'
        response = self.client.post('/api/harness/internal/execution-tasks', headers=self.headers, json=self.payload())
        self.assertEqual(response.status_code, 403)
        self.host.assert_not_awaited()

    def test_events_cancel_resume_forward_identity(self):
        self.host.return_value = {'task': {'id': 'task_1', 'status': 'running'}, 'events': []}
        for action in ('cancel', 'resume'):
            response = self.client.post('/api/harness/internal/execution-tasks/task_1/' + action,
                headers=self.headers, json={'owner': 'student'})
            self.assertEqual(response.status_code, 200)
        response = self.client.get('/api/harness/internal/execution-tasks/task_1?owner=student&after_seq=4', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.host.await_args.args[:2], ('GET', '/execution-tasks/task_1?owner=student&after_seq=4'))
        response = self.client.post('/api/harness/internal/execution-tasks/task_1/delete', headers=self.headers, json={'owner': 'student'})
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
