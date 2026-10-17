"""DeepSteam's internal execution tool, available to learning and mastery turns."""
from __future__ import annotations

import json
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult


class ExecuteWorkspaceTaskTool(BaseTool):
    def get_definition(self):
        return ToolDefinition(name='execute_workspace_task', description=(
            'Execute a user-authorized file, program or document-processing task using the same DeepSteam Harness and currently selected model. '
            'Use when ordinary course tools cannot create/edit files, process a large workspace, run code, use a browser, or coordinate multiple steps. '
            'The task retains source coverage and progress across context compaction and reconnection. Do not ask the user to upload registered workspace files again.'),
            parameters=[ToolParameter(name='task', type='string', description='Self-contained task within the current user request; include exact known source paths and required output.')])

    async def execute(self, **kwargs: Any):
        from integration.harness_execution import execute_native_task, stable_task_key
        runtime = kwargs.get('_harness_task')
        if not isinstance(runtime, dict):
            return ToolResult(content='Continue this operation in a learning conversation.', success=False)
        text = str(kwargs.get('task') or '').strip()
        if not text:
            return ToolResult(content='Provide the task to perform.', success=False)
        prompt = ('Current user-authorized request:\n' + runtime['user_request'] + '\n\nCurrent step:\n' + text)
        result = await execute_native_task(prompt, workspace_id=runtime['workspace_id'],
            source=runtime['source'], task_key=stable_task_key(runtime['session_id'], runtime['turn_id'], text),
            model_config=runtime['model_config'])
        if result['status'] == 'awaiting_input':
            return ToolResult(content=json.dumps({
                'status': 'awaiting_input', 'id': result['id'], 'session_id': result.get('session_id'),
                'message': 'The file task is waiting for your answer in the displayed question or plan card. '
                    'It remains active in the same session. Answer or cancel the existing card; do not start the task again.'}, ensure_ascii=False),
                success=True, metadata={'execution_task': result})
        return ToolResult(content=result.get('result') if result['status'] == 'completed' else json.dumps({key: result.get(key) for key in ('id', 'status', 'error', 'error_code', 'recovery', 'result')}, ensure_ascii=False),
            success=result['status'] == 'completed', metadata={'execution_task': result})
