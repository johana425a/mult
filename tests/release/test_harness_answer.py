"""Regression: native answer rendering and persisted content use the same contract."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

APP = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(APP), str(APP / 'upstream/DeepTutor')]
from integration import harness_turn
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.turns.executor import _should_capture_assistant_content


class Capture:
    def __init__(self):
        self.events = []

    async def content(self, text, **kwargs):
        self.events.append(StreamEvent(type=StreamEventType.CONTENT, content=text, **kwargs))

    async def progress(self, text, **kwargs):
        self.events.append(StreamEvent(type=StreamEventType.PROGRESS, content=text, **kwargs))

    async def emit(self, event):
        self.events.append(event)


class AnswerTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, buffered=False, live=True, failed=False):
        pipeline = NS(
            _prepare_deferred_tools=AsyncMock(), _prepare_kb_manifests=AsyncMock(),
            _compose_enabled_tools=Mock(return_value=[]), _build_llm_tool_schemas=Mock(return_value=[]),
            _tool_view=None, _deferred_pool=[], _capability_pre_loop_seed=Mock(return_value=''),
            _active_loop_capabilities=Mock(return_value=[]),
            _build_loop_messages=Mock(return_value=[{'role': 'system', 'content': 'Test'}, {'role': 'user', 'content': 'Question'}]),
            _capability_buffers_visible_output=Mock(return_value=buffered),
            _has_capability_finish_guard=Mock(return_value=False),
            _capability_finish_instruction=Mock(return_value=''),
            _capability_final_text_override=Mock(return_value=None),
            llm_config=NS(), event_source='chat',
        )
        context = NS(active_capability='chat', metadata={}, language='en', session_id='test-only',
            user_message='Question', capability_output=NS(answer_published=False),
            runtime=NS(turn_id='test-turn', workspace=NS(workspace_id='test-only', output_dir=APP)))
        stream = Capture()

        async def execute(**kwargs):
            if live:
                await kwargs['on_live']({'id': 'answer1', 'text': 'Half'})
                await kwargs['on_live']({'id': 'answer1', 'text': 'Half maximum.'})
                await kwargs['on_event']({'type': 'assistant/message', 'stream_id': 'answer1', 'text': 'Half maximum.'})
            return {'id': 'task-test', 'status': 'failed' if failed else 'completed',
                'result': 'Half maximum.', 'error': {'code': 'TEST_FAILURE', 'message': 'Fixture failed'}}

        with patch.object(harness_turn, 'execution_available', return_value=True), \
             patch('integration.execution_workspace_binding.owner_workspace_binding', return_value={'owner':'fixture','path':'synthetic-test-workspace'}), \
             patch('deeptutor.multi_user.context.get_current_user', return_value=NS(id='fixture')), \
             patch('integration.harness_execution.selection_for_config', return_value={}), \
             patch('deeptutor.services.model_selection.runtime.resolved_model_snapshot', return_value={}), \
             patch('integration.harness_execution.ExecutionClient.execute', side_effect=execute):
            result = await harness_turn.run_pipeline(pipeline, context, stream)
        # The actual persisted-answer filter is the regression assertion;
        # a mere content event was never sufficient in the failing build.
        answer = ''.join(e.content for e in stream.events if _should_capture_assistant_content(e))
        return answer, result, stream.events, context

    async def test_streamed_cumulative_and_final_event_not_duplicated(self):
        answer, result, events, _ = await self.exercise()
        self.assertEqual(answer, 'Half maximum.')
        self.assertTrue(result.completed)
        self.assertEqual([e.content for e in events if e.type == StreamEventType.CONTENT], ['Half', ' maximum.'])

    async def test_buffered_teaching_output_publishes_once(self):
        answer, _, events, _ = await self.exercise(buffered=True)
        self.assertEqual(answer, 'Half maximum.')
        self.assertEqual(sum(e.type == StreamEventType.CONTENT for e in events), 1)

    async def test_terminal_reply_without_live_updates_persists(self):
        answer, _, _, _ = await self.exercise(live=False)
        self.assertEqual(answer, 'Half maximum.')

    async def test_failure_is_not_reported_as_a_completed_answer(self):
        answer, result, events, context = await self.exercise(live=False, failed=True)
        self.assertEqual(answer, '')
        self.assertFalse(result.completed)
        self.assertFalse(context.capability_output.answer_published)
        self.assertTrue(any(e.type == StreamEventType.ERROR for e in events))


if __name__ == '__main__':
    unittest.main(verbosity=2)
