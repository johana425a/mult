"""Public desktop entry contracts; isolated records and no model requests."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from portal.storage import Store


class DesktopPublicNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='desktop-navigation-')
        self.addCleanup(self.temp.cleanup)
        with patch.dict(os.environ, {'EDUAGENT_DATA': self.temp.name}):
            self.api = importlib.import_module('portal.app')
        self.store_patch = patch.object(self.api, 'store', Store(Path(self.temp.name)))
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.client = TestClient(self.api.app)

    def test_service_status_exposes_names_without_internal_endpoints(self):
        with patch.object(self.api, 'healthy', new=AsyncMock(return_value=True)):
            response = self.client.get('/api/status')
        self.assertEqual(response.status_code, 200)
        value = response.json()
        self.assertTrue(value['services']['deeptutor']['ok'])
        self.assertEqual(value['services']['deeptutor']['entry'], 'learning')
        self.assertEqual(value['services']['openmaic']['entry'], 'classroom')
        self.assertNotIn('127.0.0.1', json.dumps(value))
        self.assertNotIn('localhost', json.dumps(value))
        self.assertEqual(value['counts'], {'materials': 0, 'lessons': 0, 'attempts': 0})

    def test_browser_development_entries_only_allow_known_destinations(self):
        for name, destination in [('learning', '/chat'), ('settings', '/settings'), ('classroom', '/')]:
            response = self.client.get('/open/' + name, follow_redirects=False)
            self.assertEqual(response.status_code, 307)
            self.assertTrue(response.headers['location'].endswith(destination))
        self.assertEqual(self.client.get('/open/untrusted.example', follow_redirects=False).status_code, 404)

    def test_public_errors_hide_managed_endpoint_but_keep_status_and_custom_provider(self):
        message = self.api.safe_error(RuntimeError('HTTP 404 url=http://127.0.0.1:3796/v1/embeddings body=NOT_FOUND'))
        self.assertIn('HTTP 404', message)
        self.assertIn('NOT_FOUND', message)
        self.assertNotIn('127.0.0.1', message)
        self.assertIn('DeepSteam internal service', message)
        custom = 'HTTP 401 https://provider.example/v1 http://localhost:9876/v1'
        self.assertEqual(self.api.safe_error(RuntimeError(custom)), custom)


if __name__ == '__main__':
    unittest.main()
