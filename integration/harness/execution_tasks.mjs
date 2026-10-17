/** Durable bridge tasks share the existing Host; HTTP disconnects do not cancel work. */
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { executionError } from './execution_errors.mjs';

const active = new Set(['queued', 'running', 'cancelling']);
const terminal = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
const error = (code, status = 409) => Object.assign(new Error(code), { code, status });
const identity = value => typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,200}$/.test(value);
const canonical = value => JSON.stringify(value, (_key, row) => row && typeof row === 'object' && !Array.isArray(row)
  ? Object.fromEntries(Object.keys(row).sort().map(key => [key, row[key]])) : row);
const sourceSnapshot = task => canonical(task.interaction?.source_snapshot ?? task.source_references ?? []);
export const executionTaskId = (owner, source, key) => 'task-' + createHash('sha256').update(JSON.stringify([owner, source, key])).digest('hex').slice(0, 32);
const publicTask = task => structuredClone({...Object.fromEntries(Object.entries(task).filter(([key]) => !['prompt', 'fingerprint', 'interaction'].includes(key))),
  request_hash:createHash('sha256').update(task.prompt).digest('hex'),
  resume_binding:{owner:task.owner,workspace_id:task.workspace_id,native_workspace_id:task.native_workspace_id,
    llm_selection:task.llm_selection,resolved_model:task.resolved_model,output_dir:task.interaction?.output_dir}});

export async function createExecutionTasks({ profile, workspaces, interactions, pollMs = 200 }) {
  const root = join(profile, 'execution-tasks');
  const path = join(root, 'tasks.json');
  await mkdir(root, { recursive: true });
  let tasks = {}, cancellations = {};
  try { const saved = JSON.parse(await readFile(path, 'utf8')); tasks = saved.tasks ?? {}; cancellations = saved.cancellations ?? {}; }
  catch (cause) { if (cause.code !== 'ENOENT') throw cause; }
  let saving = Promise.resolve();
  let closed = false;
  const drivers = new Map();
  const controllers = new Map();
  let admitting = Promise.resolve();
  const save = () => {
    const content = JSON.stringify({ schema: 2, tasks, cancellations });
    const job = saving.then(async () => { const temp = path + '.' + randomUUID() + '.tmp'; await writeFile(temp, content, 'utf8'); await rename(temp, path); });
    saving = job.catch(() => {}); return job;
  };
  // An accepted write might have run before the process stopped. Explicit resume
  // inspects its persisted session; startup never replays the original prompt.
  function cancelled(task, seen = new Set()) {
    if (!task || seen.has(task.id)) return false;
    seen.add(task.id);
    return Boolean(task.cancel_requested_at || ['cancelling','cancelled'].includes(task.status)
      || cancellations[task.id]?.owner === task.owner || cancelled(tasks[task.parent_task_id], seen));
  }
  function rememberCancellation(task) {
    task.cancel_requested_at ??= cancellations[task.id]?.cancelled_at ?? new Date().toISOString();
    cancellations[task.id] = {owner:task.owner, cancelled_at:task.cancel_requested_at};
  }
  for (const task of Object.values(tasks)) {
    if (cancelled(task) && task.status !== 'completed') {
      if (task.status !== 'cancelled') task.updated_at = new Date().toISOString();
      rememberCancellation(task); task.status = 'cancelled';
    } else if (active.has(task.status)) {
      task.status = 'interrupted'; task.recovery = 'inspect_existing_results_before_continue';
      task.requires_context_rebind = Boolean(task.interaction?.tools?.length);
      task.updated_at = new Date().toISOString();
    }
  }
  await save();
  const find = (taskId, owner) => {
    const task = tasks[taskId];
    if (!task || task.owner !== owner) throw error('execution_task_missing', 404);
    return task;
  };
  function settle(task, events) {
    const recent = events.filter(event => event.seq > (task.start_seq ?? -1));
    const ending = recent.findLast(event => event.type === 'turn/end' && (!event.run_id || event.run_id === task.run_id));
    if (!ending) return false;
    task.end_seq = ending.seq;
    const scoped = recent.filter(event => event.seq <= task.end_seq);
    task.status = cancelled(task) || ['aborted', 'user', 'cancelled'].includes(ending.outcome)
      ? 'cancelled' : ['error', 'blocked'].includes(ending.outcome) ? 'failed' : 'completed';
    task.result = scoped.filter(event => event.type === 'assistant/message').map(event => event.text).filter(Boolean).join('\n');
    if (task.status === 'failed') task.error = ending.error ?? executionError({ message: 'The agent ended before completing the task.' }, 'agent', task.id);
    task.artifacts = scoped.filter(event => event.type === 'deliverables/presented')
      .flatMap(event => (event.files ?? []).map((file, index) => ({ ...file, seq: event.seq, index,
        session_id: task.session_id, url: `/api/harness/sessions/${task.session_id}/deliverables/${event.seq}/files/${index}?mode=download` })));
    task.updated_at = new Date().toISOString();
    return true;
  }
  async function drive(task, text) {
    const controller = controllers.get(task.id);
    const check = () => { if (closed || cancelled(task)) controller.abort(); controller.signal.throwIfAborted(); };
    try {
      if (closed || task.status !== 'queued') return;
      if (!task.session_id) {
        const result = await workspaces.createSession({ workspace_id: task.workspace_id, title: task.source });
        task.session_id = result.session.id; await save();
        check();
      }
      if (closed || task.status !== 'queued') return;
      const previous = await workspaces.events(task.session_id);
      check();
      task.start_seq = previous.next_seq;
      delete task.end_seq;
      // Save queued intent before admission. A crash here pauses rather than replays.
      await save();
      check();
      const result = await workspaces.turn(task.session_id, { text, llm_selection: task.llm_selection,
        task_context: { task_id: task.id, owner: task.owner, source: task.source, native_workspace_id: task.native_workspace_id,
          expected_model: task.resolved_model, interaction: task.interaction, source_references: task.source_references,
          conversation_id: task.conversation_id, parent_task_id: task.parent_task_id,
          provider_call_budget: task.provider_call_budget } }, controller.signal);
      task.run_id = result.run_id; task.resolved_model = result.resolved_model;
      check();
      task.status = 'running';
      task.llm_selection = result.llm_selection ?? task.llm_selection;
      task.updated_at = new Date().toISOString(); await save();
      while (!closed && active.has(task.status)) {
        const snapshot = await workspaces.events(task.session_id, { after_seq: task.start_seq });
        if (snapshot.session.status === 'idle' && !(snapshot.active_child_count > 0) && settle(task, snapshot.events)) { await save(); break; }
        await new Promise(resolve => setTimeout(resolve, pollMs));
      }
    } catch (cause) {
      task.status = cancelled(task) ? 'cancelled' : closed ? 'interrupted' : controller.signal.aborted ? 'cancelled' : 'failed';
      task.error_code = /^[A-Za-z0-9_]{1,80}$/.test(cause.code ?? '') ? cause.code : 'execution_interrupted';
      task.error = executionError(cause, task.run_id ? 'execution' : 'admission', task.id);
      task.updated_at = new Date().toISOString(); await save();
    } finally {
      if (task.session_id && !Number.isSafeInteger(task.end_seq)) {
        const end = await workspaces.events(task.session_id).catch(() => null);
        if (end && terminal.has(task.status)) { task.end_seq = end.next_seq; await save(); }
      }
    }
  }
  function start(task, text) {
    controllers.set(task.id, new AbortController());
    const job = drive(task, text).finally(() => { drivers.delete(task.id); controllers.delete(task.id); });
    drivers.set(task.id, job); job.catch(() => {});
  }
  const api = {
    async create(input) {
      const job = admitting.then(() => api.admit(structuredClone(input)));
      admitting = job.catch(() => {}); return job;
    },
    async admit(input) {
      if (closed) throw error('execution_host_closing', 503);
      if (!identity(input.owner) || !identity(input.task_key) || !identity(input.workspace_id)
        || typeof input.source !== 'string' || !input.source || input.source.length > 100
        || typeof input.text !== 'string' || !input.text.trim() || input.text.length > 200000) throw error('execution_task_invalid', 422);
      const id = executionTaskId(input.owner, input.source, input.task_key);
      if (input.parent_task_id) {
        const parent = find(input.parent_task_id, input.owner);
        if (!active.has(parent.status) || cancelled(parent)) throw error('execution_parent_not_running');
        input = {...input, workspace_id:parent.workspace_id, native_workspace_id:parent.native_workspace_id,
          llm_selection:parent.llm_selection, expected_model:parent.resolved_model, source_references:parent.source_references,
          interaction:input.interaction ? {...input.interaction, source_snapshot:parent.interaction?.source_snapshot ?? parent.source_references ?? []} : input.interaction};
      }
      const fingerprint = createHash('sha256').update(JSON.stringify([input.workspace_id, input.text, input.llm_selection ?? null, input.native_workspace_id ?? null, input.continuation_task_id ?? null, input.conversation_id ?? null, input.surface ?? null])).digest('hex');
      if (tasks[id]) {
        if (tasks[id].fingerprint !== fingerprint) throw error('execution_task_key_conflict');
        if (sourceSnapshot(tasks[id]) !== sourceSnapshot(input)) throw error('execution_source_context_changed');
        return { task: publicTask(tasks[id]), reused: true };
      }
      const task = { id, owner: input.owner, source: input.source, task_key: input.task_key,
        workspace_id: input.workspace_id, native_workspace_id: input.native_workspace_id ?? null,
        llm_selection: input.llm_selection ?? null, resolved_model: input.expected_model ?? null, source_references: input.source_references ?? [],
        parent_task_id: input.parent_task_id ?? null, provider_call_budget: input.provider_call_budget ?? null, prompt: input.text, fingerprint,
        conversation_id: input.conversation_id ?? null, surface: input.surface ?? null, interaction: input.interaction ?? null,
        status: cancellations[id]?.owner === input.owner ? 'cancelled' : 'queued', created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
      if (input.conversation_id) {
        if (!identity(input.conversation_id)) throw error('execution_conversation_invalid', 422);
        const previous = Object.values(tasks).filter(t => t.owner === input.owner && t.workspace_id === input.workspace_id
          && t.surface === input.surface && t.conversation_id === input.conversation_id).at(-1);
        if (previous && active.has(previous.status)) throw error('execution_conversation_busy');
        if (previous?.session_id) task.session_id = previous.session_id;
      }
      if (task.parent_task_id) find(task.parent_task_id, input.owner);
      if (input.continuation_task_id) {
        const previous = find(input.continuation_task_id, input.owner);
        if (previous.workspace_id !== input.workspace_id || !terminal.has(previous.status) || !previous.session_id)
          throw error('execution_continuation_not_ready');
        task.session_id = previous.session_id;
        task.continuation_task_id = previous.id;
      }
      tasks[id] = task; await save();
      if (task.parent_task_id) {
        const parent=find(task.parent_task_id,input.owner);
        if(!active.has(parent.status)||cancelled(parent)){rememberCancellation(task);task.status='cancelled';await save();}
      }
      if (task.status === 'queued') start(task, task.prompt);
      return { task: publicTask(task), reused: false };
    },
    async get(id, owner, afterSeq = -1) {
      const task = find(id, owner);
      const snapshot = task.session_id && task.start_seq !== undefined ? await workspaces.events(task.session_id, { after_seq: Math.max(afterSeq, task.start_seq) }) : { events: [], next_seq: -1 };
      const end = Number.isSafeInteger(task.end_seq) ? task.end_seq : Infinity;
      const capabilities = task.session_id && interactions ? await interactions.state(task.session_id, {after_seq:task.start_seq ?? -1, before_seq:end, active:active.has(task.status)}) : null;
      const waiting = active.has(task.status) && !cancelled(task) && capabilities?.pending_questions?.length > 0;
      // Admission can await model resolution before turn() clears the session's
      // previous live buffer. Never replay that prior answer into a new task.
      const live = snapshot.live_response;
      const liveResponse = live && Number.isSafeInteger(task.start_seq)
        && active.has(task.status) && Number.isSafeInteger(live.start_seq) && live.start_seq > task.start_seq && live.start_seq <= end ? live : null;
      return { task: { ...publicTask(task), ...(waiting ? { status: 'awaiting_input', runtime_status: task.status } : {}) },
        events: snapshot.events.filter(event => event.seq <= end && (!task.run_id || !event.run_id || event.run_id === task.run_id)),
        next_seq: Math.min(snapshot.next_seq, end), live_response: liveResponse, capabilities,
        ...(task.session_id ? { session_id_link: task.session_id } : {}) };
    },
    async list(owner) { return { tasks: Object.values(tasks).filter(task => task.owner === owner).map(publicTask) }; },
    async cancelAdmission(input) {
      if (!identity(input.owner) || !identity(input.task_key) || typeof input.source !== 'string' || !input.source || input.source.length > 100) throw error('execution_task_invalid',422);
      const id = executionTaskId(input.owner,input.source,input.task_key);
      cancellations[id] = {owner:input.owner, cancelled_at:new Date().toISOString()};
      if (tasks[id]) return api.cancel(id,input.owner);
      await save(); return {task:{id,status:'cancelled'},pending_admission_cancelled:true};
    },
    async cancel(id, owner) {
      const task = find(id, owner);
      if (task.status === 'completed') {await save();return { task: publicTask(task) };}
      const wasActive = active.has(task.status);
      rememberCancellation(task);
      task.status = 'cancelling'; controllers.get(id)?.abort(); await save();
      await Promise.all(Object.values(tasks).filter(child => child.parent_task_id === id && child.status !== 'completed').map(child => api.cancel(child.id,owner)));
      // A past task may share a session with a newer turn. Persist its cancelled
      // intent without aborting that newer turn on a repeated cancel request.
      if (wasActive && task.session_id) await workspaces.cancel(task.session_id);
      if (wasActive) await drivers.get(id);
      task.status = 'cancelled'; task.updated_at = new Date().toISOString(); await save();
      return { task: publicTask(task) };
    },
    async rebind(id, owner, interaction) {
      const task = find(id,owner);
      if (cancelled(task)) throw error('execution_task_cancelled');
      if (!interaction || interaction.surface !== task.surface || typeof interaction.context_ref !== 'string'
        || !Array.isArray(interaction.tools)) throw error('execution_context_invalid',422);
      if(canonical(task.interaction?.binding_identity??null)!==canonical(interaction.binding_identity??null)
        || sourceSnapshot(task) !== sourceSnapshot({interaction}))
        throw error('execution_source_context_changed');
      const catalog = tools => tools.map(({name,parameters})=>({name,parameters})).sort((a,b)=>a.name.localeCompare(b.name));
      if (JSON.stringify(catalog(task.interaction?.tools ?? [])) !== JSON.stringify(catalog(interaction.tools))) throw error('execution_tool_catalog_changed');
      task.interaction = {...task.interaction, context_ref:interaction.context_ref};
      task.requires_context_rebind = false;
      if (task.session_id) await workspaces.rebind?.(task.session_id,task.id,task.interaction);
      await save(); return {task:publicTask(task)};
    },
    async resume(id, owner, interaction) {
      const task = find(id, owner);
      if (cancelled(task)) throw error('execution_task_cancelled');
      if (interaction) await api.rebind(id,owner,interaction);
      if (active.has(task.status) || task.status === 'completed') return { task: publicTask(task), reused: true };
      if (task.requires_context_rebind || task.interaction?.tools?.length && !interaction) throw error('execution_context_rebind_required');
      task.runs = [...(task.runs ?? []), {run_id:task.run_id,start_seq:task.start_seq,end_seq:task.end_seq,status:task.status}];
      task.status = 'queued'; delete task.error_code; delete task.error; await save();
      start(task, `Resume the previous task. Check existing tool results and generated files first. Avoid repeating writes, submissions, or commands that already completed. Handle only unfinished work. Original task:\n${task.prompt}`);
      return { task: publicTask(task), reused: false };
    },
    async close() {
      closed = true;
      for (const controller of controllers.values()) controller.abort();
      await Promise.allSettled(Object.values(tasks).filter(task => active.has(task.status) && task.session_id).map(task => workspaces.cancel(task.session_id)));
      await Promise.allSettled([...drivers.values()]);
      for (const task of Object.values(tasks)) if (active.has(task.status)) task.status = cancelled(task) ? 'cancelled' : 'interrupted';
      await save();
    },
  };
  return api;
}

export async function executionTaskRequest(tasks, method, path, query, body) {
  if (!path.startsWith('/execution-tasks')) return null;
  const owner = method === 'GET' ? query.get('owner') : body.owner;
  if (!identity(owner)) throw error('execution_owner_required', 422);
  if (path === '/execution-tasks' && method === 'POST') return tasks.create(body);
  if (path === '/execution-tasks/cancel-admission' && method === 'POST') return tasks.cancelAdmission(body);
  if (path === '/execution-tasks' && method === 'GET') return tasks.list(owner);
  const match = /^\/execution-tasks\/(task-[a-f0-9]{32})(?:\/(cancel|resume|rebind))?$/.exec(path);
  if (!match) throw error('execution_task_missing', 404);
  if (method === 'GET' && !match[2]) {
    const after = Number(query.get('after_seq') ?? -1);
    if (!Number.isSafeInteger(after) || after < -1) throw error('execution_cursor_invalid', 422);
    return tasks.get(match[1], owner, after);
  }
  if (method === 'POST' && match[2]) return tasks[match[2]](match[1], owner, body.interaction);
  throw error('execution_method_invalid', 405);
}
