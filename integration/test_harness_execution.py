"""Isolated native/Host delegation tests. No service or real model calls."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from integration.harness_execution import ExecutionClient, stable_task_key


class FakeClient(ExecutionClient):
    def __init__(self):
        self.calls = []

    async def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == 'POST':
            return {'task': {'id': 'task-fixture', 'status': 'queued'}}
        return {'task': {'id': 'task-fixture', 'status': 'completed', 'result': 'Synthetic output'},
                'events': [{'type': 'assistant/message', 'text': 'Synthetic output', 'seq': 0}], 'next_seq': 0}


class HarnessExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_client_only_sends_selection_references(self):
        client, event = FakeClient(), AsyncMock()
        result = await client.execute(text='Synthetic requested work', workspace_id='ws-fixture',
            source='mastery', task_key='stable', owner='fixture',
            llm_selection={'profile_id': 'profile', 'model_id': 'model'}, on_event=event,
            continuation_task_id='task-prior')
        self.assertEqual(result['result'], 'Synthetic output')
        payload = client.calls[0][2]
        self.assertEqual(payload['continuation_task_id'], 'task-prior')
        self.assertEqual(payload['native_workspace_id'], 'ws-fixture')
        self.assertNotIn('api_key', str(payload))
        event.assert_awaited_once()

    async def test_learning_tool_uses_server_owned_model_and_user_request(self):
        from deeptutor.tools.harness_execution import ExecuteWorkspaceTaskTool
        tool = ExecuteWorkspaceTaskTool()
        self.assertEqual(tool.get_definition().name, 'execute_workspace_task')
        denied = await tool.execute(task='Synthetic')
        self.assertFalse(denied.success)
        mock = AsyncMock(return_value={'id': 'task-fixture', 'status': 'completed', 'result': 'Created fixture'})
        with patch('integration.harness_execution.execute_native_task', mock):
            value = await tool.execute(task='Write synthetic note', _harness_task={
                'user_request': 'Please organize my fixture files', 'workspace_id': 'ws-fixture',
                'source': 'learning', 'session_id': 's', 'turn_id': 't', 'model_config': 'frozen-config'})
        self.assertTrue(value.success)
        self.assertIn('Please organize', mock.call_args.args[0])
        self.assertEqual(mock.call_args.kwargs['model_config'], 'frozen-config')
        self.assertEqual(mock.call_args.kwargs['task_key'], stable_task_key('s', 't', 'Write synthetic note'))


if __name__ == '__main__':
    unittest.main()
