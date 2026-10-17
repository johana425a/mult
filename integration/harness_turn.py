"""Native teaching is a tool provider; Harness owns the conversation loop.

The registry is request scoped, authenticated and bound to the original user's
ContextVars. Historical messages are read-only context, never replayed actions.
"""
from __future__ import annotations
import asyncio
import contextvars
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from fastapi import Request, HTTPException

_contexts = {}
_health = (0.0, False)


def enabled():
    return os.environ.get('DEEPSTEAM_HARNESS_CORE') == '1'


def execution_available(kind='shell'):
    global _health
    if not enabled() or kind not in {'shell', 'python', 'node'}:
        return False
    if time.monotonic() - _health[0] > 3:
        import urllib.request
        try:
            url = os.environ.get('DEEPSTEAM_HARNESS_ORIGIN', 'http://127.0.0.1:3796') + '/health'
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=1) as response:
                okay = bool(json.load(response).get('healthy'))
        except Exception:
            okay = False
        _health = (time.monotonic(), okay)
    return _health[1]


def validate_file(path):
    """Validate bytes before native presentation; no empty-directory success."""
    path = Path(path)
    if os.name == 'nt' and path.is_absolute() and not str(path).startswith('\\\\?\\'):
        path = Path('\\\\?\\' + str(path))
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('Output file is missing or empty: ' + path.name)
    ext = path.suffix.lower()
    if ext in {'.md', '.txt', '.json', '.csv'}:
        path.read_text(encoding='utf-8-sig')
    elif ext == '.docx':
        from docx import Document
        Document(path)
    elif ext == '.pdf':
        from pypdf import PdfReader
        if not PdfReader(path).pages:
            raise ValueError('PDF has no pages')
    elif ext == '.xlsx':
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True); book.close()
    elif ext == '.pptx':
        from pptx import Presentation
        Presentation(path)
    with path.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    return {'filename': path.name, 'format': ext.lstrip('.'), 'size_bytes': path.stat().st_size, 'sha256': digest, 'verified': True}


def install_routes(app, authenticate):
    from fastapi import Request, HTTPException

    @app.post('/api/contest/internal/harness-surface-binding')
    async def surface_binding(request: Request):
        authenticate(request)
        body = await request.json()
        from integration.execution_workspace_binding import native_execution_owner
        from deeptutor.multi_user.models import LOCAL_ADMIN_ID
        from deeptutor.multi_user.paths import user_context
        from deeptutor.services.workspace import get_content_workspace_service
        from deeptutor.services.model_selection.runtime import resolve_model_selection
        surface = body.get('surface')
        if surface not in {'openmaic-workbench', 'openmaic-classroom'}:
            raise HTTPException(422, {'code': 'surface_invalid', 'message': 'Unknown interaction surface.'})
        user = native_execution_owner(LOCAL_ADMIN_ID)
        with user_context(user):
            try:
                _, concrete, snapshot = resolve_model_selection()
            except Exception as exc:
                from deeptutor.services.llm.request_compat import logged_error_text
                raise HTTPException(409, {'code':'model_selection_unavailable', 'phase':'model_binding',
                    'message':logged_error_text(exc)[:1200], 'trace_id':uuid.uuid4().hex, 'retryable':False}) from None
            try:
                runtime = get_content_workspace_service().create_runtime_context(capability=surface,
                    session_id=str(body.get('conversation_id') or 'classroom'),
                    turn_id=str(body.get('turn_id') or uuid.uuid4().hex))
            except OSError as exc:
                raise HTTPException(500, {'code':'workspace_output_unavailable','phase':'workspace_binding',
                    'message':str(exc)[:1200],'trace_id':uuid.uuid4().hex,'retryable':False}) from None
            return {'owner': user.id, 'native_workspace_id': runtime.workspace_id,
                'output_dir': str(runtime.output_dir), 'llm_selection': concrete,
                'resolved_model': snapshot}

    @app.post('/api/contest/internal/surface-tools/invoke')
    async def invoke(request: Request):
        authenticate(request)
        body = await request.json()
        if body.get('surface') == 'learning-records':
            return await _learning_record(body)
        entry = _contexts.get(body.get('context_ref'))
        if not entry or body.get('owner') != entry['owner'] or body.get('surface') != entry['surface']:
            raise HTTPException(409, {'code': 'surface_context_expired', 'message': 'The teaching context is no longer active. Continue in the original conversation to reconnect it.'})
        name = body.get('name')
        args = body.get('arguments')
        if name not in entry['names'] or not isinstance(args, dict) or any(k.startswith('_') for k in args):
            raise HTTPException(422, {'code': 'surface_tool_invalid', 'message': 'Use a registered tool and its public arguments.'})
        call_id = body.get('call_id') or uuid.uuid4().hex
        # Repeated HTTP delivery observes the same operation, never writes twice.
        if call_id not in entry['calls']:
            entry['calls'][call_id] = entry['vars'].run(asyncio.create_task, _invoke(entry, name, args, call_id))
        try:
            return await asyncio.shield(entry['calls'][call_id])
        except Exception as exc:
            from deeptutor.services.llm.request_compat import logged_error_text
            raise HTTPException(500, {'code': 'surface_tool_failed', 'phase': 'teaching_tool',
                'message': logged_error_text(exc)[:1600], 'trace_id': call_id, 'retryable': False}) from None


async def _learning_record(body):
    from integration.execution_workspace_binding import owner_workspace_binding, native_execution_owner
    from deeptutor.multi_user.paths import user_context
    from deeptutor.services.notebook import get_notebook_manager
    args = body.get('arguments') or {}
    owner_workspace_binding(body['owner'], args.get('workspace_id'))
    user = native_execution_owner(body['owner'])
    with user_context(user):
        manager = get_notebook_manager()
        notebook = manager.get_or_create_notebook('Learning records · ' + args['workspace_id'],
            description='Conversation archives and learning summaries. These records do not assert mastery.')
        records = manager.get_records(notebook['id'])
        if args.get('action') == 'list':
            return {'notebook_id': notebook['id'], 'records': records}
        for record in records:
            if body.get('call_id') in (record.get('metadata') or {}).get('harness_calls', []):
                return {'notebook_id': notebook['id'], 'record': record, 'reused': True}
        content = str(args.get('content') or '')
        if args.get('action') == 'archive_chat':
            if str(args.get('conversation_id') or '').startswith('unified_'):
                from deeptutor.services.session import get_session_store
                history = await get_session_store().get_messages(args['conversation_id'])
            else:
                history = json.loads(args.get('history') or '[]')
            chunks = []
            for row in history:
                if row.get('role') not in {'user', 'assistant'}:
                    continue
                value = row.get('content', '')
                if isinstance(value, list):
                    value = '\n'.join(p.get('text', '') for p in value if p.get('type') == 'text')
                chunks.append('## ' + row['role'] + '\n\n' + str(value))
            content = '\n\n'.join(chunks)
        if not content.strip():
            raise HTTPException(422, {'code':'record_empty','message':'No content was supplied for this record.'})
        if args.get('action') == 'append':
            record = next((r for r in records if r['id'] == args.get('record_id')), None)
            if not record:
                raise HTTPException(404, {'code':'record_missing','message':'The original record was not found.'})
            if (record.get('metadata') or {}).get('record_kind') == 'chat_archive':
                raise HTTPException(422, {'code':'archive_is_source_snapshot','message':'Conversation archives contain actual messages only. Save an added summary as a separate learning_summary record.'})
            metadata = {**(record.get('metadata') or {})}
            metadata['harness_calls'] = [*metadata.get('harness_calls', []), body['call_id']]
            manager.update_record(notebook['id'],record['id'],output=record.get('output','')+'\n\n'+content,metadata=metadata)
            return {'notebook_id':notebook['id'],'record_id':record['id'],'updated':True}
        if args.get('action') not in {'save_summary','archive_chat'}:
            raise HTTPException(422, {'code':'record_action_invalid','message':'Unknown record action.'})
        result = manager.add_record([notebook['id']], 'chat', str(args.get('title') or 'Learning record'), '', content,
            metadata={'record_kind':'chat_archive' if args['action']=='archive_chat' else 'learning_summary',
                'workspace_id':args['workspace_id'],'conversation_id':args.get('conversation_id'),
                'source':args.get('source'),'source_references':args.get('source_references',[]),
                'harness_calls':[body['call_id']], 'captured_at':time.time(), 'mastery_asserted':False})
        return {'notebook_id':notebook['id'],**result}


async def _invoke(entry, name, args, call_id):
    pipeline, context, stream = entry['pipeline'], entry['context'], entry['stream']
    if name in entry.get('deferred', set()):
        await pipeline._execute_tool_call('load_tools', pipeline._augment_tool_kwargs('load_tools', {'names':[name]}, context), stream=stream)
        entry['deferred'].discard(name)
    if name == 'workspace_present':
        from deeptutor.services.workspace import get_content_workspace_service
        service = get_content_workspace_service()
        binding = service.binding_by_id(context.runtime.workspace.workspace_id)
        for item in args.get('items', []):
            path = (Path(binding.root) / item['path']).resolve()
            if not path.is_relative_to(Path(binding.root).resolve()):
                raise ValueError('Presentation path must be in the current workspace')
            await asyncio.to_thread(validate_file, path)
    dispatch = await pipeline._dispatch_tool_calls(tool_calls=[{'id': call_id, 'name': name,
        'arguments': json.dumps(args, ensure_ascii=False)}], context=context, stream=stream,
        iteration_index=len(entry['calls']), stage='executing')
    if dispatch.pause:
        await pipeline._await_user_reply_and_resolve(context=context, stream=stream, dispatch=dispatch)
    # A successfully posted assessment card is this turn's final artefact.
    # Honour the same post-tool hook as AgentLoop before asking the model for
    # another round. The hook may consume its marker, so retain its decision.
    final_override = pipeline._capability_final_text_override(context, '')
    if final_override is not None:
        entry['terminal_override'] = final_override
    if name == 'workspace_present' and not any(
        value.get('workspace_items') for value in dispatch.tool_metadata_by_id.values()
        if isinstance(value, dict)
    ):
        detail = '\n'.join(str(m.get('content') or '') for m in dispatch.tool_messages)
        raise RuntimeError('FILE_DELIVERY_FAILED: ' + detail[:1500])
    return {'content': '\n'.join(str(m.get('content') or '') for m in dispatch.tool_messages),
        'sources': dispatch.sources, 'model_messages': dispatch.model_messages,
        'metadata': dispatch.tool_metadata_by_id,
        'terminate': dispatch.terminate or final_override is not None}


async def run_pipeline(pipeline, context, stream):
    from deeptutor.agents.loop.agent_loop import LoopOutcome
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.core.stream import StreamEvent, StreamEventType
    from integration.harness_execution import ExecutionClient, selection_for_config, stable_task_key
    from deeptutor.services.model_selection.runtime import resolved_model_snapshot
    if not execution_available():
        raise RuntimeError('HARNESS_UNAVAILABLE: The shared execution service is not running. Start the DeepSteam runtime and retry this turn.')
    await pipeline._prepare_deferred_tools(context)
    await pipeline._prepare_kb_manifests(context)
    pipeline._exec_enabled = True
    names = [n for n in pipeline._compose_enabled_tools(context) if n not in {'exec', 'execute_workspace_task', 'workspace_export'}]
    schemas = pipeline._build_llm_tool_schemas(names, context)
    if pipeline._tool_view is not None:
        pipeline._tool_view.attach(schemas)
    # Advertise scoped external tools without eagerly connecting every provider.
    deferred = set()
    for tool in pipeline._deferred_pool:
        definition = tool.get_definition()
        if definition.name in {'exec', 'execute_workspace_task', 'workspace_export'}:
            continue
        if definition.name not in names:
            names.append(definition.name)
            schemas.append(definition.to_openai_schema())
            deferred.add(definition.name)
    reading = context.active_capability in {'reading', 'watching'} or context.metadata.get('reading_material_id') or context.metadata.get('immersive_reading_mode')
    learning = context.metadata.get('mastery_path_id') or context.metadata.get('mastery_mode') or context.active_capability in {'mastery', 'mastery_path', 'course'}
    surface = 'reading' if reading else 'learning' if learning else 'chat'
    seed = pipeline._capability_pre_loop_seed(context)
    # These hooks fetch existing state only. The optional explore_context hook
    # starts another agent loop, so discovery now belongs to Harness itself.
    for capability in pipeline._active_loop_capabilities(context):
        hook = getattr(capability, 'pre_loop', None)
        if callable(hook) and capability.__class__.__module__.split('.')[-2] != 'explore_context':
            block = await hook(context, stream, usage=pipeline._usage)
            if block and getattr(block, 'content', ''):
                seed += '\n\n' + block.content
    messages = pipeline._build_loop_messages(context=context, enabled_tools=names, kb_seed=seed)
    images = []
    def textual(message, *, current=False):
        value = message.get('content', '')
        if not isinstance(value, list):
            return value
        text = []
        for part in value:
            if part.get('type') == 'text':
                text.append(part.get('text', ''))
            elif part.get('type') == 'image_url':
                if current:
                    images.append(part['image_url']['url'])
                text.append('[Source image attached to this turn]' if current else '[Historical image; retrieve original if needed]')
        return '\n'.join(text)
    system = '\n\n'.join(str(m.get('content', '')) for m in messages if m.get('role') == 'system')
    history = [{'role': m['role'], 'content': textual(m)} for m in messages[1:-1] if m.get('role') in {'user', 'assistant'}]
    current_messages = [{**m, 'content': textual(m, current=True)} for m in messages[-1:]]
    owner = get_current_user().id
    ref = uuid.uuid4().hex
    entry = {'pipeline': pipeline, 'context': context, 'stream': stream, 'owner': owner,
        'surface': surface, 'names': set(names), 'deferred': deferred, 'vars': contextvars.copy_context(), 'calls': {}}
    _contexts[ref] = entry
    interaction = {'surface': surface, 'context_ref': ref, 'tools': [s['function'] for s in schemas],
        'system_prompt': system, 'history': json.dumps(history, ensure_ascii=False),
        'context': json.dumps({'messages': current_messages, 'source_references': context.metadata.get('source_references', [])}, ensure_ascii=False),
        'images': images,
        'language': context.language or 'en', 'output_dir': str(context.runtime.workspace.output_dir)}
    started = time.monotonic()
    events = []
    visible = {}
    # A finish guard is not a request to hide normal teaching. Mastery streams
    # its explanation before posting a question; only private protocol surfaces
    # explicitly declare buffers_visible_output.
    buffer_answer = pipeline._capability_buffers_visible_output(context)

    async def emit_text(stream_id, text):
        if buffer_answer:
            return
        previous = visible.get(stream_id, '')
        if text.startswith(previous) and len(text) > len(previous):
            await stream.content(text[len(previous):], source=pipeline.event_source, stage='responding',
                metadata={'call_id': stream_id, 'call_kind': 'agent_loop_round',
                    'trace_role': 'response', 'trace_kind': 'llm_chunk', 'execution_engine': 'harness'})
            visible[stream_id] = text

    async def on_live(response):
        await emit_text(response['id'], response.get('text', ''))

    async def on_question(record):
        from deeptutor.agents.loop.pipeline import _normalise_user_reply
        replies = []
        questions = record.get('questions', [])
        for start in range(0, len(questions), 4):
            batch = questions[start:start+4]
            captured = []
            waiter = context.runtime.wait_for_user_reply
            if not callable(waiter):
                raise RuntimeError('USER_INPUT_UNAVAILABLE: Reopen this conversation to answer the pending question.')
            async def capture_reply():
                reply = await waiter()
                captured.append(reply)
                return reply
            context.runtime.wait_for_user_reply = capture_reply
            try:
                await _invoke(entry, 'ask_user', {'questions':[
                    {'id':q['id'], 'prompt':q.get('question') or q.get('prompt'),
                     'header':q.get('header'), 'options':q.get('options', []),
                     'multi_select':bool(q.get('multiSelect')), 'allow_free_text':True} for q in batch]},
                    record['id'] + ':' + str(start))
            finally:
                context.runtime.wait_for_user_reply = waiter
            if not captured or captured[0] is None:
                return {'cancel': True}
            text, answers = _normalise_user_reply(captured[0])
            by_id = {a['questionId']:a['text'] for a in answers or []}
            for q in batch:
                answer = by_id.get(q['id'], text if len(batch) == 1 else '')
                exact = any(o.get('label') == answer for o in q.get('options', []))
                replies.append({'id':q['id'], 'selected':[answer] if exact else [],
                    **({} if exact else {'custom':answer})})
        return {'answers':replies}

    async def on_event(event):
        events.append(event)
        typ = event.get('type', '')
        # Domain operations already emit native tool cards; core operations use
        # the same event protocol so each entry retains live execution progress.
        if typ == 'tool/call' and event.get('tool_name') != 'invoke_surface_tool':
            await stream.tool_call(event.get('tool_name', 'Harness'), event.get('arguments') or {}, source=pipeline.event_source, stage='executing')
        elif typ == 'tool/result' and event.get('tool_name') != 'invoke_surface_tool':
            await stream.emit(StreamEvent(type=StreamEventType.TOOL_RESULT, source=pipeline.event_source,
                stage='executing', content=str(event.get('text') or event.get('result') or ''), metadata={'harness_event': event}))
        elif typ == 'assistant/message':
            await emit_text(event.get('stream_id') or str(event.get('seq')), event.get('text', ''))
        elif typ == 'deliverables/presented':
            from deeptutor.services.workspace import get_content_workspace_service
            service = get_content_workspace_service()
            binding = service.binding_by_id(context.runtime.workspace.workspace_id)
            items = []
            for item in event.get('files', []):
                path = Path(item['path']).resolve()
                await asyncio.to_thread(validate_file, path)
                if path.is_relative_to(Path(binding.root).resolve()):
                    items.append({'path': path.relative_to(binding.root).as_posix()})
            if items:
                # Dispatch owns native tool_result metadata and attachment cards.
                # Calling the low-level executor alone silently drops that UI
                # contract even though the Host has validated the actual file.
                await _invoke(entry, 'workspace_present', {'items':items}, 'harness-delivery-' + str(event['seq']))

    try:
        selection = selection_for_config(pipeline.llm_config)
        task = None
        for correction in range(2):
            text = (current_messages[-1].get('content') or context.user_message) if correction == 0 else pipeline._capability_finish_instruction(context, task.get('result', ''))
            if not text:
                break
            task = await ExecutionClient().execute(text=text, workspace_id=context.runtime.workspace.workspace_id,
                source=surface, task_key=stable_task_key(context.session_id, context.runtime.turn_id, text),
                llm_selection=selection, owner=owner, on_event=on_event, conversation_id=context.session_id,
                surface=surface, interaction=interaction, on_live=on_live, on_question=on_question,
                source_references=context.metadata.get('source_references', []),
                expected_model=resolved_model_snapshot(pipeline.llm_config))
            if task['status'] != 'completed':
                error = task.get('error') or {'code': task.get('error_code') or task['status'], 'message': task.get('recovery') or 'Execution stopped.'}
                await stream.emit(StreamEvent(type=StreamEventType.ERROR, source=pipeline.event_source,
                    content=error.get('message', 'Execution failed'), metadata={'execution_error': error, 'task_id': task['id'],
                        'turn_terminal': True, 'status': 'cancelled' if task['status'] == 'cancelled' else 'failed',
                        'error_code': error.get('code', 'HARNESS_FAILED'), 'retryable': bool(error.get('retryable', False))}))
                return LoopOutcome(final_text=error.get('message', ''), completed=False)
            if 'terminal_override' in entry or not pipeline._capability_finish_instruction(context, task.get('result', '')):
                break
        final = task.get('result', '') if task else ''
        if 'terminal_override' not in entry and pipeline._capability_finish_instruction(context, final):
            raise RuntimeError('CAPABILITY_FINISH_REJECTED: Required teaching or reading steps have not completed.')
        override = entry['terminal_override'] if 'terminal_override' in entry else pipeline._capability_final_text_override(context, final)
        if override is not None:
            final = override
        if buffer_answer or not visible:
            await stream.content(final, source=pipeline.event_source, stage='responding',
                metadata={'call_id': 'harness-final-' + task['id'], 'call_kind': 'llm_final_response',
                    'trace_role': 'response', 'trace_kind': 'llm_output', 'execution_engine': 'harness'})
        context.capability_output.answer_published = True
        await stream.progress('', source=pipeline.event_source, stage='responding', metadata={
            'harness_task_id': task['id'], 'harness_session_id': task.get('session_id'),
            'execution_engine': 'harness', 'total_seconds': round(time.monotonic() - started, 3)})
        return LoopOutcome(final_text=final, completed=True)
    finally:
        _contexts.pop(ref, None)
        for operation in entry['calls'].values():
            if not operation.done():
                operation.cancel()
