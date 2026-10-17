"""DeepSteam delegates through its existing authenticated, durable Harness Host."""
from __future__ import annotations
from pathlib import Path
from deeptutor.services.subagent.base import OnEvent, SubagentBackend
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.types import (
    EVENT_TEXT, EVENT_TOOL, EVENT_TOOL_RESULT, ConsultResult, DetectResult, SubagentEvent,
)


class DeepSeekHarnessBackend(SubagentBackend):
    kind = "deepseek_harness"
    display_name = "DeepSteam"
    cli_command = ""

    async def detect(self) -> DetectResult:
        from integration.harness_execution import ExecutionClient
        try:
            await ExecutionClient().transport.host("GET", "/workspace-dependencies", timeout=20)
            ok = True
        except Exception:
            ok = False
        return DetectResult(kind=self.kind, display_name=self.display_name, available=ok,
            version="DeepSteam shared Host" if ok else "",
            detail="" if ok else "")

    async def consult(
        self,
        question: str,
        *,
        on_event: OnEvent,
        cwd: str | None = None,
        session_id: str | None = None,
        config: BackendConfig | None = None,
        images: list[str] | None = None,
        partner_id: str | None = None,  # noqa: ARG002 — partner-only
    ) -> ConsultResult:
        from integration.harness_execution import execute_native_task, stable_task_key
        from deeptutor.services.workspace import get_content_workspace_service
        service = get_content_workspace_service()
        binding = service.current_binding()
        if cwd:
            wanted = Path(cwd).resolve()
            for row in service._catalog():
                candidate = service.binding_by_id(row['workspace_id'])
                if candidate.root.resolve() == wanted:
                    binding = candidate
                    break
            else:
                if binding.root.resolve() != wanted:
                    return ConsultResult(success=False, error='Select the workspace for this task first.')
        prompt = question
        if config and config.system_prompt.strip():
            prompt = config.system_prompt.strip() + '\n\n' + prompt
        if images:
            prompt += '\n\nUser-selected image files:\n' + '\n'.join(images)
        event_count = 0

        async def event(value):
            nonlocal event_count
            kind = {'assistant/message': EVENT_TEXT, 'tool/call': EVENT_TOOL, 'tool/result': EVENT_TOOL_RESULT}.get(value.get('type'))
            if kind:
                event_count += 1
                await on_event(SubagentEvent(kind=kind, text=value.get('text') or value.get('tool_name') or '', raw=value))

        task = await execute_native_task(prompt, workspace_id=binding.workspace_id,
            source='subagent', task_key=stable_task_key(session_id or binding.workspace_id, 'consult', prompt), on_event=event,
            continuation_task_id=session_id if session_id and session_id.startswith('task-') else None)
        return ConsultResult(session_id=task['id'], final_text=task.get('result', ''),
            success=task['status'] == 'completed', event_count=event_count,
            error='' if task['status'] == 'completed' else '')


# DeepSteam 2026-10-16 subagent options: settings code asks whether a Python SDK fallback exists. DeepSteam
# always goes through the shared Harness Host, so there is none.
def _sdk_available() -> bool:
    return False
