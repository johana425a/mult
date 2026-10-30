import asyncio, hashlib, importlib.util, sys, unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

APP = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).parent
sys.path[:0] = [str(APP), str(APP / 'upstream/DeepTutor')]

from integration import native_formula_review as native
from deeptutor.tools import builtin

class SourceAliasTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        source = NS(id='source_attached', kind=NS(value='workspace_file'),
                    metadata={'workspace_id': 'test-ws', 'path': 'formula.png'})
        grounded = NS(available=True, excerpt='Verified selected material',
                      metadata={**source.metadata, 'document_sha256': 'a' * 64})
        sid = 'wf-' + hashlib.sha256(('test-ws:formula.png:' + 'a' * 64).encode()).hexdigest()[:24]
        stack = ExitStack()
        stack.enter_context(patch('deeptutor.learning.storage.LearningStore',
                                 return_value=NS(get_topic=lambda _: NS(sources=[source]))))
        stack.enter_context(patch('deeptutor.learning.workspace_sources._trusted_workspace_id', return_value='test-ws'))
        stack.enter_context(patch('deeptutor.learning.workspace_sources.current_workspace_id', return_value='test-ws'))
        read = stack.enter_context(patch('deeptutor.learning.workspace_sources.ground_workspace_source',
                                         new=AsyncMock(return_value=grounded)))
        return stack, source, grounded, sid, read

    async def test_topic_row_resolves_to_current_verified_manifest(self):
        stack, _, _, sid, read = self.fixture()
        with stack:
            self.assertEqual(await native.resolve_mastery_source_id('topic', 'source_attached', {sid: 'text'}), sid)
            read.assert_awaited_once()

    async def test_other_topic_row_does_not_read_any_file(self):
        stack, _, _, sid, read = self.fixture()
        with stack:
            self.assertIsNone(await native.resolve_mastery_source_id('topic', 'source_other', {sid: 'text'}))
            read.assert_not_awaited()

    async def test_stale_document_version_does_not_resolve(self):
        stack, _, grounded, sid, _ = self.fixture()
        grounded.metadata['document_sha256'] = 'b' * 64
        with stack:
            self.assertIsNone(await native.resolve_mastery_source_id('topic', 'source_attached', {sid: 'text'}))

    async def test_foreign_workspace_is_rejected_before_grounding(self):
        stack, source, _, sid, read = self.fixture()
        source.metadata['workspace_id'] = 'different-workspace'
        with stack:
            with self.assertRaises(ValueError):
                await native.resolve_mastery_source_id('topic', 'source_attached', {sid: 'text'})
            read.assert_not_awaited()

    async def test_actual_tool_alias_still_delivers_original_visual_evidence(self):
        stack, _, grounded, sid, _ = self.fixture()
        visuals = NS(content=[{'type': 'text', 'text': 'Retained original pixels'}],
                     formula_review={'status': 'source_only'}, manifest=[{'path': 'formula.png'}])
        with stack, patch('integration.native_formula_review.resolve_mastery_source_id',
                           new=native.resolve_mastery_source_id, create=True), \
             patch('integration.native_formula_review.present_mastery_source',
                   new=AsyncMock(return_value=[{'workspace_item_id': 'item', 'generated': False}]), create=True), \
             patch('integration.native_formula_review.mastery_source_evidence',
                   new=AsyncMock(return_value=(grounded, visuals))) as evidence:
            result = await builtin.ReadSourceTool().execute(source_id='source_attached',
                source_index={sid: grounded.excerpt}, _mastery_path_id='topic')
            self.assertTrue(result.success)
            self.assertEqual(result.metadata['source_id'], sid)
            self.assertEqual(result.metadata['requested_source_id'], 'source_attached')
            self.assertEqual(result.model_message['content'], visuals.content)
            self.assertFalse(result.metadata['workspace_items'][0]['generated'])
            evidence.assert_awaited_once_with('topic', sid)

    async def test_source_preview_reuses_verified_snapshot_without_recopying(self):
        stack, _, grounded, _, _ = self.fixture()
        from unittest.mock import Mock
        row = {'workspace_id': 'test-ws', 'relative_path': 'formula.png', 'sha256': 'a' * 64}
        service = Mock()
        service.binding_by_id.return_value = NS(workspace_id='test-ws')
        service.resolve_published_item.return_value = (Path('unused'), NS(to_dict=lambda: row))
        with stack, patch('deeptutor.services.workspace.get_content_workspace_service', return_value=service):
            result = await native.present_mastery_source(grounded)
            self.assertFalse(result[0]['generated'])
            service.publish.assert_not_called()

    async def test_source_preview_rejects_a_changed_snapshot(self):
        stack, _, grounded, _, _ = self.fixture()
        from unittest.mock import Mock
        row = {'workspace_id': 'test-ws', 'relative_path': 'formula.png', 'sha256': 'b' * 64}
        service = Mock()
        service.binding_by_id.return_value = NS(workspace_id='test-ws')
        service.resolve_published_item.side_effect = ValueError('No published item')
        service.publish.return_value = [NS(to_dict=lambda: row)]
        with stack, patch('deeptutor.services.workspace.get_content_workspace_service', return_value=service):
            with self.assertRaises(ValueError):
                await native.present_mastery_source(grounded)

    async def test_cancellation_is_not_converted_to_unknown_source(self):
        with patch('integration.native_formula_review.resolve_mastery_source_id',
                   new=AsyncMock(side_effect=asyncio.CancelledError), create=True):
            with self.assertRaises(asyncio.CancelledError):
                await builtin.ReadSourceTool().execute(source_id='source_attached',
                    source_index={'wf-current': 'text'}, _mastery_path_id='topic')

if __name__ == '__main__':
    unittest.main(verbosity=2)
