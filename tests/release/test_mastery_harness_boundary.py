"""Card delivery must end a Harness turn without hiding its preceding lesson."""
import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from test_harness_answer import APP, Capture, harness_turn, _should_capture_assistant_content
from deeptutor.capabilities.mastery.loop import MasteryLoopCapability


class MasteryBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def make(self, posted=True):
        extensions = {}
        context = NS(active_capability='mastery', metadata={'mastery_mode': True},
            language='en', session_id='test-mastery', user_message='Teach then quiz.',
            knowledge_bases=[], capability_output=NS(answer_published=False),
            extension=lambda name: extensions.setdefault(name, {}),
            runtime=NS(turn_id='test-card', workspace=NS(workspace_id='test-only', output_dir=APP)))
        cap = MasteryLoopCapability()
        stream = Capture()

        async def dispatch(**kwargs):
            arguments = cap.augment_kwargs('mastery_quiz', {}, context)
            if posted:
                arguments['_end_turn_on_card']()
            return NS(pause=False, terminate=False, sources=[], model_messages=[],
                tool_metadata_by_id={'card': {'posted': posted}}, tool_messages=[])

        pipeline = NS(_prepare_deferred_tools=AsyncMock(), _prepare_kb_manifests=AsyncMock(),
            _compose_enabled_tools=Mock(return_value=['mastery_quiz']),
            _build_llm_tool_schemas=Mock(return_value=[]), _tool_view=None, _deferred_pool=[],
            _capability_pre_loop_seed=Mock(return_value=''), _active_loop_capabilities=Mock(return_value=[]),
            _build_loop_messages=Mock(return_value=[{'role': 'system', 'content': 'Test'}, {'role': 'user', 'content': 'Teach then quiz.'}]),
            _capability_buffers_visible_output=Mock(return_value=False),
            _has_capability_finish_guard=Mock(return_value=True),
            _capability_finish_instruction=cap.finish_instruction,
            _capability_final_text_override=cap.final_text_override,
            _dispatch_tool_calls=dispatch, llm_config=NS(), event_source='mastery')
        return pipeline, context, stream

    async def test_success_card_ends_turn_and_lesson_is_visible_before_card(self):
        pipeline, context, stream = self.make()
        calls = []

        async def execute(**kwargs):
            calls.append(kwargs)
            await kwargs['on_live']({'id': 'lesson', 'text': 'Km is the substrate concentration at half Vmax.'})
            shown = ''.join(e.content for e in stream.events if _should_capture_assistant_content(e))
            self.assertIn('substrate concentration', shown)
            entry = harness_turn._contexts[kwargs['interaction']['context_ref']]
            result = await harness_turn._invoke(entry, 'mastery_quiz', {}, 'test-card-call')
            self.assertTrue(result['terminate'], 'A registered card must prevent another model call')
            await kwargs['on_event']({'type': 'assistant/message', 'stream_id': 'lesson', 'text': shown})
            return {'id': 'card-task', 'status': 'completed', 'result': shown}

        with patch.object(harness_turn, 'execution_available', return_value=True), \
             patch('integration.execution_workspace_binding.owner_workspace_binding', return_value={'owner':'fixture','path':'synthetic-test-workspace'}), \
             patch('deeptutor.multi_user.context.get_current_user', return_value=NS(id='fixture')), \
             patch('integration.harness_execution.selection_for_config', return_value={}), \
             patch('deeptutor.services.model_selection.runtime.resolved_model_snapshot', return_value={}), \
             patch('integration.harness_execution.ExecutionClient.execute', side_effect=execute):
            result = await harness_turn.run_pipeline(pipeline, context, stream)
        self.assertTrue(result.completed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(''.join(e.content for e in stream.events if _should_capture_assistant_content(e)),
            'Km is the substrate concentration at half Vmax.')
        self.assertTrue(context.capability_output.answer_published)

    async def test_failed_registration_does_not_end_turn_or_bypass_guard(self):
        pipeline, context, stream = self.make(posted=False)
        entry = {'pipeline': pipeline, 'context': context, 'stream': stream, 'calls': {}}
        result = await harness_turn._invoke(entry, 'mastery_quiz', {}, 'failed-card')
        self.assertFalse(result['terminate'])
        self.assertNotIn('terminal_override', entry)
        self.assertIn('no question card', pipeline._capability_finish_instruction(context, ''))

    async def test_unrelated_tool_does_not_end_turn(self):
        pipeline, context, stream = self.make()
        pipeline._dispatch_tool_calls = AsyncMock(return_value=NS(pause=False, terminate=False,
            sources=[], model_messages=[], tool_messages=[], tool_metadata_by_id={}))
        entry = {'pipeline': pipeline, 'context': context, 'stream': stream, 'calls': {}}
        result = await harness_turn._invoke(entry, 'read_source', {}, 'source-call')
        self.assertFalse(result['terminate'])
        self.assertNotIn('terminal_override', entry)


if __name__ == '__main__':
    unittest.main(verbosity=2)
