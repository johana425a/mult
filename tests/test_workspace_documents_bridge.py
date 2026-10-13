"""Local mocked transport contract; no live services, models or personal state."""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from integration import workspace_documents as bridge


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_binding_uses_authenticated_host_and_safe_fields(self):
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        response = MagicMock()
        response.json.return_value = {'workspace_id': 'native1', 'harness_workspace_id': 'host1'}
        client.get = AsyncMock(return_value=response)
        transport = MagicMock()
        transport.token.return_value = 'fixture-only-control-token'
        transport.host = AsyncMock(return_value={'ok': True, 'text': 'page 2'})
        with patch.object(bridge.httpx, 'AsyncClient', return_value=client), patch.object(bridge, 'HarnessTransport', return_value=transport):
            value = await bridge.document_request('native1', 'read', path='book.pdf', start_unit=2, ocr='off')
        self.assertEqual(value['workspace_id'], 'native1')
        transport.host.assert_awaited_once_with('POST', '/workspaces/host1/documents/read', {'path': 'book.pdf', 'start_unit': 2, 'ocr': 'off'}, timeout=65)
        self.assertEqual(client.get.call_args.kwargs['headers']['Authorization'], 'Bearer fixture-only-control-token')

    async def test_invalid_root_or_traversal_never_reaches_transport(self):
        with patch.object(bridge, 'HarnessTransport') as transport:
            for payload in ({'path': '../private.pdf'}, {'path': 'C:/private.pdf'}, {'path': 'x.pdf', 'root': 'C:/'}, {'path': '\\server\\share\\x.pdf'}):
                self.assertFalse((await bridge.document_request('w1', 'read', **payload))['ok'])
            transport.assert_not_called()

    async def test_empty_catalog_path_normalized_and_binding_mismatch_rejected(self):
        self.assertEqual(bridge._payload('list', {'path': ''}), {'path': '.'})
        client = MagicMock(); client.__aenter__ = AsyncMock(return_value=client); client.__aexit__ = AsyncMock(return_value=None)
        response = MagicMock(); response.json.return_value = {'workspace_id': 'foreign', 'harness_workspace_id': 'h1'}; client.get = AsyncMock(return_value=response)
        transport = MagicMock(); transport.token.return_value = 'fixture'; transport.host = AsyncMock()
        with patch.object(bridge.httpx, 'AsyncClient', return_value=client), patch.object(bridge, 'HarnessTransport', return_value=transport):
            self.assertFalse((await bridge.document_request('w1', 'list', path=''))['ok'])
        transport.host.assert_not_called()

    async def test_cancel_propagates_without_fallback(self):
        client = MagicMock(); client.__aenter__ = AsyncMock(side_effect=asyncio.CancelledError); client.__aexit__ = AsyncMock()
        with patch.object(bridge.httpx, 'AsyncClient', return_value=client), patch.object(bridge, 'HarnessTransport'):
            with self.assertRaises(asyncio.CancelledError):
                await bridge.document_request('w1', 'read', path='a.pdf')

    async def test_managed_upload_uses_the_same_fixed_isolated_cli(self):
        python = Path(os.environ.get('DEEPSTEAM_TEST_PYTHON', sys.executable))
        if not python.is_file():
            self.skipTest('Packaged Python fixture runtime unavailable')
        helper = Path(__file__).resolve().parents[1] / 'scripts' / 'workspace_document_reader.py'
        with tempfile.TemporaryDirectory(prefix='managed-reader-', dir=helper.parents[1] / 'runtime') as directory:
            root = Path(directory); (root / 'fixture.md').write_text('# Synthetic uploaded material\nBody text', encoding='utf-8')
            with patch.object(bridge, '_runtime_paths', return_value=(python, helper)), patch.dict(os.environ, {'DEEPSTEAM_HARNESS_TEST_ROOT': str(root)}):
                result = await bridge.read_managed_document(root, 'fixture.md', engine='builtin')
                outside = await bridge.read_managed_document(root, '../not-allowed.md')
        self.assertTrue(result['ok']); self.assertIn('Synthetic uploaded material', result['text']); self.assertFalse(outside['ok'])

    async def test_inventory_and_coverage_keep_separate_bounded_fields(self):
        self.assertEqual(bridge._payload('inventory', {'path': '', 'cursor': 'next', 'limit': 80}), {'path': '.', 'cursor': 'next', 'limit': 80})
        self.assertEqual(bridge._payload('coverage', {'path': 'a.pdf', 'coverage_cursor': 'next', 'limit': 40})['limit'], 40)
        for action, value in [('inventory', {'root': 'C:/'}), ('coverage', {'path': 'a.pdf', 'cursor': 'read-cursor'})]:
            with self.assertRaises(ValueError):
                bridge._payload(action, value)

    async def test_native_owner_is_forwarded_and_pending_job_resumes(self):
        from deeptutor.multi_user import context
        client = MagicMock(); client.__aenter__ = AsyncMock(return_value=client); client.__aexit__ = AsyncMock(return_value=None)
        response = MagicMock(); response.json.return_value = {'workspace_id': 'w1', 'harness_workspace_id': 'h1'}
        client.get = AsyncMock(return_value=response)
        transport = MagicMock(); transport.token.return_value = 'fixture'
        transport.host = AsyncMock(side_effect=[{'ok': True, 'status': 'running', 'job_id': 'a' * 32}, {'ok': True, 'status': 'ready', 'text': 'finished'}])
        with patch.object(context, 'get_current_user_or_none', return_value=SimpleNamespace(id='user-1')), patch.object(bridge.httpx, 'AsyncClient', return_value=client), patch.object(bridge, 'HarnessTransport', return_value=transport), patch.object(bridge.asyncio, 'sleep', AsyncMock()):
            result = await bridge.document_request('w1', 'read', path='a.pdf', engine='builtin')
        self.assertEqual(client.get.call_args.kwargs['params'], {'owner': 'user-1'})
        self.assertEqual(transport.host.call_args.args[2]['job_id'], 'a' * 32)
        self.assertEqual(result['text'], 'finished')


    async def test_bounded_wait_returns_progress_instead_of_blocking(self):
        client = MagicMock(); client.__aenter__ = AsyncMock(return_value=client); client.__aexit__ = AsyncMock(return_value=None)
        response = MagicMock(); response.json.return_value = {'workspace_id': 'w1', 'harness_workspace_id': 'h1'}
        client.get = AsyncMock(return_value=response)
        transport = MagicMock(); transport.token.return_value = 'fixture'
        waiting = {'ok': True, 'status': 'running', 'job_status': 'waiting', 'job_id': 'b' * 32,
                   'parse': {'state': 'parsing', 'pages': [1, 4]}, 'message': 'Local MinerU (advanced tier) is parsing pages 1-4.'}
        transport.host = AsyncMock(return_value=waiting)
        with patch.object(bridge.httpx, 'AsyncClient', return_value=client), patch.object(bridge, 'HarnessTransport', return_value=transport):
            result = await bridge.document_request('w1', 'read', wait_seconds=0, path='scan.pdf', engine='mineru')
        transport.host.assert_awaited_once()
        self.assertEqual(transport.host.call_args.args[2]['wait_seconds'], 0)
        view = bridge.model_view(result)
        self.assertEqual(view['status'], 'pending')
        self.assertIn('parsing pages 1-4', view['how_to_continue'])
        self.assertIn('workspace_document_read again with the same arguments', view['how_to_continue'])

    async def test_background_preparation_payloads_are_bounded_relative_paths(self):
        self.assertEqual(bridge._payload('prepare', {'paths': ['a.pdf', 'b/c.pdf'], 'engine': 'mineru'}),
                         {'paths': ['a.pdf', 'b/c.pdf'], 'engine': 'mineru'})
        self.assertEqual(bridge._payload('queue', {}), {})
        for action, value in [('prepare', {}), ('prepare', {'paths': []}), ('prepare', {'paths': ['C:/x.pdf']}),
                              ('prepare', {'paths': ['../x.pdf']}), ('prepare', {'paths': 'a.pdf'}),
                              ('queue', {'paths': ['a.pdf'] * 51}), ('prepare', {'paths': ['a.pdf'], 'path': 'a.pdf'})]:
            with self.subTest(action=action, value=value), self.assertRaises(ValueError):
                bridge._payload(action, value)

class NativeToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_pdf_auto_dispatch_preserves_locator_hash_and_no_text_read(self):
        from deeptutor.tools import workspace
        service = MagicMock(); binding = SimpleNamespace(workspace_id='native1')
        result = {'ok': True, 'status': 'partial', 'path': 'book.pdf', 'text': 'evidence', 'document': {'sha256': 'a' * 64}, 'units': [{'locator': {'page': 3}, 'text': 'evidence'}], 'truncated': True, 'next_cursor': 'opaque'}
        with patch.object(workspace, '_binding', return_value=(service, binding)), patch.object(bridge, 'document_request', AsyncMock(return_value=result)) as request:
            value = await workspace.WorkspaceReadTool().execute(path='book.pdf', _workspace_id='native1')
        self.assertTrue(value.success); self.assertEqual(value.sources[0]['locator']['page'], 3)
        self.assertEqual(value.sources[0]['document_sha256'], 'a' * 64); self.assertIn('partial', value.content)
        service.read_text.assert_not_called(); request.assert_awaited_once()

    async def test_plain_text_keeps_existing_read_observation_path(self):
        from deeptutor.tools import workspace
        service = MagicMock(); service.read_text.return_value = {'content': 'text', 'path': 'notes.txt'}
        with patch.object(workspace, '_binding', return_value=(service, SimpleNamespace(workspace_id='w1'))), patch.object(bridge, 'document_request', AsyncMock()) as request:
            value = await workspace.WorkspaceReadTool().execute(path='notes.txt', offset=1, limit=20)
        self.assertEqual(value.content, 'text'); request.assert_not_called()

    async def test_image_requires_vision_and_base64_is_request_local_only(self):
        from deeptutor.tools import workspace
        from deeptutor.services.model_selection import runtime
        from deeptutor.services.llm import config
        service = MagicMock(); binding = SimpleNamespace(workspace_id='w1')
        result = {'ok': True, 'document_sha256': 'a' * 64, 'asset': {'id': 'pdf-page:1', 'base64': 'cGl4ZWxz', 'mime_type': 'image/png', 'locator': {'page': 1}}}
        with patch.object(workspace, '_binding', return_value=(service, binding)), patch.object(config, 'get_llm_config', return_value=object()), patch.object(runtime, 'resolved_model_snapshot', return_value={'capabilities': {'vision': False}}) as snapshot, patch.object(bridge, 'document_request', AsyncMock(return_value=result)) as request:
            denied = await workspace.WorkspaceDocumentImageTool().execute(path='book.pdf', asset_id='pdf-page:1', document_sha256='a' * 64)
            self.assertFalse(denied.success); request.assert_not_called()
            snapshot.return_value = {'capabilities': {'vision': True}}
            value = await workspace.WorkspaceDocumentImageTool().execute(path='book.pdf', asset_id='pdf-page:1', document_sha256='a' * 64)
        self.assertTrue(value.success); self.assertNotIn('cGl4ZWxz', value.content); self.assertNotIn('base64', str(value.metadata))
        self.assertIn('cGl4ZWxz', str(value.model_message)); self.assertEqual(value.sources[0]['locator']['page'], 1)

    async def test_prepare_tool_queues_documents_and_reports_progress(self):
        from deeptutor.tools import workspace
        service = MagicMock(); binding = SimpleNamespace(workspace_id='w1')
        accepted = {'ok': True, 'status': 'accepted', 'documents': [{'path': 'a.pdf', 'state': 'queued'}]}
        with patch.object(workspace, '_binding', return_value=(service, binding)), patch.object(bridge, 'document_request', AsyncMock(return_value=accepted)) as request:
            value = await workspace.WorkspaceDocumentPrepareTool().execute(paths=['a.pdf'], engine='mineru')
            self.assertTrue(value.success); self.assertIn('queued', value.content)
            request.assert_awaited_with('w1', 'prepare', paths=['a.pdf'], engine='mineru')
            await workspace.WorkspaceDocumentPrepareTool().execute(paths=['a.pdf'], operation='cancel')
            request.assert_awaited_with('w1', 'queue', paths=['a.pdf'], cancel=True)
            missing = await workspace.WorkspaceDocumentPrepareTool().execute(operation='prepare')
            self.assertFalse(missing.success)
        service.resolve.assert_called_with(binding, 'a.pdf')

    async def test_baseline_includes_documents_for_chat_and_mastery(self):
        from deeptutor.agents._shared.tool_composition import WORKSPACE_BASELINE_TOOLS
        self.assertTrue({'workspace_document_read', 'workspace_document_image', 'workspace_document_prepare', 'load_workspace_dependencies'}.issubset(WORKSPACE_BASELINE_TOOLS))


if __name__ == '__main__':
    unittest.main()
