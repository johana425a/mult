/** Durable bridge tasks share the existing Host; HTTP disconnects do not cancel work. */
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

const active = new Set(['queued', 'running', 'cancelling']);
const terminal = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
const error = (code, status = 409) => Object.assign(new Error(code), { code, status });
const identity = value => typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,200}$/.test(value);
const publicTask = task => structuredClone(Object.fromEntries(Object.entries(task).filter(([key]) => !['prompt', 'fingerprint'].includes(key))));

export async function createExecutionTasks({ profile, workspaces, interactions, pollMs = 200 }) {
  const root = join(profile, 'execution-tasks');
  const path = join(root, 'tasks.json');
  await mkdir(root, { recursive: true });
  let tasks = {};
  try { tasks = JSON.parse(await readFile(path, 'utf8')).tasks ?? {}; }
  catch (cause) { if (cause.code !== 'ENOENT') throw cause; }
  let saving = Promise.resolve();
  let closed = false;
  const drivers = new Map();
  const save = () => {
    const content = JSON.stringify({ schema: 1, tasks });
    const job = saving.then(async () => { const temp = path + '.' + randomUUID() + '.tmp'; await writeFile(temp, content, 'utf8'); await rename(temp, path); });
    saving = job.catch(() => {}); return job;
  };
  // An accepted write might have run before the process stopped. Explicit resume
  // inspects its persisted session; startup never replays the original prompt.
  for (const task of Object.values(tasks)) if (active.has(task.status)) {
    task.status = 'interrupted'; task.recovery = 'inspect_existing_results_before_continue';
    task.updated_at = new Date().toISOString();
  }
  await save();
  const find = (taskId, owner) => {
    const task = tasks[taskId];
    if (!task || task.owner !== owner) throw error('execution_task_missing', 404);
    return task;
  };
  function settle(task, events) {
    const recent = events.filter(event => event.seq > (task.start_seq ?? -1));
    const ending = recent.findLast(event => event.type === 'turn/end');
    if (!ending) return false;
    task.status = task.status === 'cancelling' || ['aborted', 'user', 'cancelled'].includes(ending.outcome)
      ? 'cancelled' : ending.outcome === 'error' ? 'failed' : 'completed';
    task.result = recent.filter(event => event.type === 'assistant/message').map(event => event.text).filter(Boolean).join('\n');
    task.artifacts = recent.filter(event => event.type === 'tool/result' && !event.is_error)
      .map(event => ({ seq: event.seq, tool_name: event.tool_name, call_id: event.call_id }));
    task.updated_at = new Date().toISOString();
    return true;
  }
  async function drive(task, text) {
    try {
      if (closed || task.status !== 'queued') return;
      if (!task.session_id) {
        const result = await workspaces.createSession({ workspace_id: task.workspace_id, title: task.source });
        task.session_id = result.session.id; await save();
      }
      if (closed || task.status !== 'queued') return;
      const previous = await workspaces.events(task.session_id);
      task.start_seq = previous.next_seq;
      // Save queued intent before admission. A crash here pauses rather than replays.
      await save();
      const result = await workspaces.turn(task.session_id, { text, llm_selection: task.llm_selection,
        task_context: { task_id: task.id, owner: task.owner, source: task.source, native_workspace_id: task.native_workspace_id, expected_model: task.resolved_model } });
      task.status = 'running'; task.run_id = result.run_id; task.resolved_model = result.resolved_model;
      task.llm_selection = result.llm_selection ?? task.llm_selection;
      task.updated_at = new Date().toISOString(); await save();
      while (!closed && active.has(task.status)) {
        const snapshot = await workspaces.events(task.session_id, { after_seq: task.start_seq });
        if (snapshot.session.status === 'idle' && !(snapshot.active_child_count > 0) && settle(task, snapshot.events)) { await save(); break; }
        await new Promise(resolve => setTimeout(resolve, pollMs));
      }
    } catch (cause) {
      task.status = closed ? 'interrupted' : task.status === 'cancelling' ? 'cancelled' : 'failed';
      task.error_code = /^[A-Za-z0-9_]{1,80}$/.test(cause.code ?? '') ? cause.code : 'execution_interrupted';
      task.updated_at = new Date().toISOString(); await save();
    }
  }
  function start(task, text) {
    const job = drive(task, text).finally(() => drivers.delete(task.id));
    drivers.set(task.id, job); job.catch(() => {});
  }
  return {
    async create(input) {
      if (closed) throw error('execution_host_closing', 503);
      if (!identity(input.owner) || !identity(input.task_key) || !identity(input.workspace_id)
        || typeof input.source !== 'string' || !input.source || input.source.length > 100
        || typeof input.text !== 'string' || !input.text.trim() || input.text.length > 200000) throw error('execution_task_invalid', 422);
      const id = 'task-' + createHash('sha256').update(JSON.stringify([input.owner, input.source, input.task_key])).digest('hex').slice(0, 32);
      const fingerprint = createHash('sha256').update(JSON.stringify([input.workspace_id, input.text, input.llm_selection ?? null, input.native_workspace_id ?? null, input.continuation_task_id ?? null])).digest('hex');
      if (tasks[id]) {
        if (tasks[id].fingerprint !== fingerprint) throw error('execution_task_key_conflict');
        return { task: publicTask(tasks[id]), reused: true };
      }
      const task = { id, owner: input.owner, source: input.source, task_key: input.task_key,
        workspace_id: input.workspace_id, native_workspace_id: input.native_workspace_id ?? null,
        llm_selection: input.llm_selection ?? null, source_references: input.source_references ?? [],
        parent_task_id: input.parent_task_id ?? null, prompt: input.text, fingerprint,
        status: 'queued', created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
      if (task.parent_task_id) find(task.parent_task_id, input.owner);
      if (input.continuation_task_id) {
        const previous = find(input.continuation_task_id, input.owner);
        if (previous.workspace_id !== input.workspace_id || !terminal.has(previous.status) || !previous.session_id)
          throw error('execution_continuation_not_ready');
        task.session_id = previous.session_id;
        task.continuation_task_id = previous.id;
      }
      tasks[id] = task; await save(); start(task, task.prompt);
      return { task: publicTask(task), reused: false };
    },
    async get(id, owner, afterSeq = -1) {
      const task = find(id, owner);
      const snapshot = task.session_id ? await workspaces.events(task.session_id, { after_seq: afterSeq }) : { events: [], next_seq: -1 };
      const capabilities = task.session_id && interactions ? await interactions.state(task.session_id) : null;
      const waiting = active.has(task.status) && capabilities?.pending_questions?.length > 0;
      return { task: { ...publicTask(task), ...(waiting ? { status: 'awaiting_input', runtime_status: task.status } : {}) },
        events: snapshot.events, next_seq: snapshot.next_seq, capabilities,
        ...(task.session_id ? { session_id_link: task.session_id } : {}) };
    },
    async list(owner) { return { tasks: Object.values(tasks).filter(task => task.owner === owner).map(publicTask) }; },
    async cancel(id, owner) {
      const task = find(id, owner);
      if (terminal.has(task.status)) return { task: publicTask(task) };
      task.status = 'cancelling'; await save();
      if (task.session_id) await workspaces.cancel(task.session_id);
      await drivers.get(id);
      task.status = 'cancelled'; task.updated_at = new Date().toISOString(); await save();
      for (const child of Object.values(tasks)) if (child.parent_task_id === id && active.has(child.status)) await this.cancel(child.id, owner);
      return { task: publicTask(task) };
    },
    async resume(id, owner) {
      const task = find(id, owner);
      if (active.has(task.status) || task.status === 'completed') return { task: publicTask(task), reused: true };
      task.status = 'queued'; delete task.error_code; await save();
      start(task, `Resume the previous task. Check existing tool results and generated files first. Avoid repeating writes, submissions, or commands that already completed. Handle only unfinished work. Original task:\n${task.prompt}`);
      return { task: publicTask(task), reused: false };
    },
    async close() {
      closed = true;
      await Promise.allSettled(Object.values(tasks).filter(task => active.has(task.status) && task.session_id).map(task => workspaces.cancel(task.session_id)));
      await Promise.allSettled([...drivers.values()]);
      for (const task of Object.values(tasks)) if (active.has(task.status)) task.status = 'interrupted';
      await save();
    },
  };
}

export async function executionTaskRequest(tasks, method, path, query, body) {
  if (!path.startsWith('/execution-tasks')) return null;
  const owner = method === 'GET' ? query.get('owner') : body.owner;
  if (!identity(owner)) throw error('execution_owner_required', 422);
  if (path === '/execution-tasks' && method === 'POST') return tasks.create(body);
  if (path === '/execution-tasks' && method === 'GET') return tasks.list(owner);
  const match = /^\/execution-tasks\/(task-[a-f0-9]{32})(?:\/(cancel|resume))?$/.exec(path);
  if (!match) throw error('execution_task_missing', 404);
  if (method === 'GET' && !match[2]) {
    const after = Number(query.get('after_seq') ?? -1);
    if (!Number.isSafeInteger(after) || after < -1) throw error('execution_cursor_invalid', 422);
    return tasks.get(match[1], owner, after);
  }
  if (method === 'POST' && match[2]) return tasks[match[2]](match[1], owner);
  throw error('execution_method_invalid', 405);
}
