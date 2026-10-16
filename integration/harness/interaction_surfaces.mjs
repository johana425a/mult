/** DeepSteam adapter for the pinned official web, questions, plans and deliveries. */
import UserQuestions, { UserQuestionError } from '@deepseek-ai/dsh-user-questions';
import * as AskUser from '@deepseek-ai/dsh-tool-ask-user';
import PlanMode from '@deepseek-ai/dsh-plan-mode';
import * as Present from '@deepseek-ai/dsh-tool-present';
import * as WorkspaceChanges from '@deepseek-ai/dsh-workspace-changes';
import WebRuntime, { WebError } from '@deepseek-ai/dsh-web';
import * as HttpFetch from './public_web_fetch.mjs';
import * as WebTools from '@deepseek-ai/dsh-tool-web';
import { DeepSeekSearchProvider, DEEPSEEK_DEFAULT_BASE_URL, DEEPSEEK_DEFAULT_API_VERSION } from '@deepseek-ai/dsh-web-search-deepseek';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import { readFile, writeFile, mkdir, rename, stat } from 'node:fs/promises';
import { join, basename, extname } from 'node:path';
import { homedir } from 'node:os';
import { randomUUID } from 'node:crypto';
import { checkedTaskPath, checkedWorkspacePath } from './workspaces.mjs';
import { requestCredential } from './credentials.mjs';

const PLAN_READ_TOOLS = new Set(['read', 'read_image', 'read_document', 'read_document_image', 'document_engine_status',
  'catalog_workspace', 'read_task_progress', 'load_workspace_dependencies', 'load_harness_tools', 'glob', 'grep',
  'web_search', 'web_fetch', 'ask_user_question', 'exit_plan_mode', 'present', 'todo_write', 'job_list', 'job_output']);
const error = (code, status = 409) => Object.assign(new Error(code), { code, status });
const now = () => new Date().toISOString();
const clone = value => structuredClone(value);
const mime = path => ({ '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
  '.gif': 'image/gif', '.pdf': 'application/pdf', '.txt': 'text/plain; charset=utf-8', '.md': 'text/plain; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8', '.json': 'application/json', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  '.mp4': 'video/mp4' }[extname(path).toLowerCase()] ?? 'application/octet-stream');

export function validateAnswers(questions, answers) {
  if (!Array.isArray(answers) || answers.length !== questions.length) throw error('QUESTION_ANSWER_INVALID', 422);
  const seen = new Set();
  for (const answer of answers) {
    const question = questions.find(item => item.id === answer?.id);
    if (!question || seen.has(answer.id) || Object.keys(answer).some(key => !['id', 'selected', 'custom'].includes(key))
      || !Array.isArray(answer.selected) || answer.selected.some(label => typeof label !== 'string'
        || !(question.options ?? []).some(option => option.label === label))
      || new Set(answer.selected).size !== answer.selected.length
      || (!question.multiSelect && (answer.selected.length > 1 || (answer.custom !== undefined && answer.selected.length)))
      || (answer.custom !== undefined && (typeof answer.custom !== 'string' || answer.custom.length > 24000))) {
      throw error('QUESTION_ANSWER_INVALID', 422);
    }
    seen.add(answer.id);
  }
  return { answers: clone(answers) };
}

/** These services do not alter credentials, permission levels or model selection. */
export async function createInteractionSurfaces(ctx, options) {
  const journalPath = join(options.profile, 'interaction-state.json');
  let journal = { schema: 1, questions: {}, changes: {} };
  try {
    const loaded = JSON.parse(await readFile(journalPath, 'utf8'));
    if (loaded?.schema !== 1 || !loaded.questions || !loaded.changes) throw error('INTERACTION_STATE_INVALID', 503);
    journal = loaded;
  } catch (cause) { if (cause.code !== 'ENOENT') throw cause; }
  for (const question of Object.values(journal.questions)) {
    if (question.status === 'open') question.status = 'continued';
  }
  const liveQuestions = new Map();
  let writes = Promise.resolve();
  const save = () => {
    const data = JSON.stringify(journal);
    const operation = writes.then(async () => {
      await mkdir(options.profile, { recursive: true });
      const temporary = journalPath + '.' + randomUUID() + '.tmp';
      await writeFile(temporary, data, { mode: 0o600 }); await rename(temporary, journalPath);
    });
    writes = operation.catch(() => {}); return operation;
  };
  const protectedPaths = [options.profile, ...(options.protectedPaths ?? []),
    ...['.dsh', '.codex', '.ssh', '.claude', '.gemini', '.aws', '.azure', '.kube'].map(path => join(homedir(), path)),
    join(homedir(), 'AppData', 'Roaming', 'Claude'), join(homedir(), 'AppData', 'Local', 'Claude')];
  async function agentFor(sessionId) {
    // The existing adapter owns workspace membership and safe session resume.
    await options.workspaces.events(sessionId, { after_seq: 1000000000 });
    const agent = ctx.agents.get(sessionId);
    if (!agent || !ctx.agents.roots().includes(agent)) throw error('INTERACTION_SESSION_INVALID', 403);
    return agent;
  }
  async function fileFor(agent, path) {
    const session = (await options.workspaces.events(agent.id, { after_seq: 1000000000 })).session;
    const check = session.access_level === 'full' ? checkedTaskPath : checkedWorkspacePath;
    return check(session.cwd, path, protectedPaths);
  }

  await ctx.plugin(UserQuestions);
  await ctx.plugin(AskUser, { mode: 'timed', timeout: -1 });
  await ctx.plugin(PlanMode, { section: 'You are in plan mode. Explore and design, then submit the complete plan through exit_plan_mode for human approval. The deployment enforces read-only tools until approval. Do not modify user files, run commands, or schedule work. A timeout, closing a panel, or a cancelled question is never approval.' });
  await ctx.plugin(Present, { maxFiles: 8 });
  await ctx.plugin(WorkspaceChanges, { maxFiles: 100, maxFileBytes: 512 * 1024 });
  await ctx.plugin(WebRuntime, { searchProvider: 'deepseek-official', fetchProvider: 'http' });
  await ctx.plugin(HttpFetch);
  const searchRoute = () => {
    const route = requestCredential.getStore()?.searchRoute;
    if (route?.eligible !== true || !['account', 'apikey'].includes(route.kind)) throw new WebError(
      'Web search needs an explicitly selected DeepSeek account or API connection. Public webpage fetch is available without a search key.', 'WEB_PROVIDER_CREDENTIAL_MISSING');
    return route;
  };
  const searchProvider = new DeepSeekSearchProvider(() => {
    const route = searchRoute();
    return { baseURL: DEEPSEEK_DEFAULT_BASE_URL, model: route.model ?? 'deepseek-v4-flash',
      apiVersion: DEEPSEEK_DEFAULT_API_VERSION, maxTokens: 1024, maxUses: 2,
      resolveAccountToken: async endpoint => route.kind === 'account' ? await ctx.deepseekAccount.resolveToken(endpoint) : undefined,
      resolveApiKey: async () => route.kind === 'apikey' ? route.api_key : undefined,
      recordRequest: request => ctx.agents.currentInitiator()?.session.append('web/deepseek-search-llm-request', request) };
  });
  // The official provider normally advertises endpoint availability before
  // credentials are checked; a request without a selected route reports its
  // precise configuration error, never guessed search results.
  const registeredSearch = { id: 'deepseek-official', available: () => true,
    search: (request, signal) => searchProvider.search(request, signal) };
  ctx.web.registerSearchProvider(registeredSearch);
  await ctx.plugin(WebTools, { searchMaxQueries: 4, searchMaxResults: 8, fetchMaxOutputChars: 100_000 });

  function planActive(agent) {
    const seen = new Set();
    while (agent && !seen.has(agent.id)) {
      seen.add(agent.id);
      if (ctx.planMode.get(agent).active || ctx.planMode.get(agent).pending === true) return true;
      agent = ctx.agents.get(agent.session.header.parentSession);
    }
    return false;
  }
  ctx.on('tools/pre-execute', async (exec, next) => {
    if (exec.agent && planActive(exec.agent) && !PLAN_READ_TOOLS.has(exec.name)) {
      return { kind: 'deny', reason: 'Plan mode is read-only. Present the plan with exit_plan_mode and wait for explicit user approval before executing this tool.' };
    }
    return next();
  }, { prepend: true });
  ctx.on('tools/execute', async (exec, next) => {
    // An exact-action approval may wait for minutes, while the user enters
    // plan mode. Recheck the current official plan state at the final boundary.
    if (exec.agent && planActive(exec.agent) && !PLAN_READ_TOOLS.has(exec.name)) {
      throw error('PLAN_MODE_READ_ONLY', 403);
    }
    return next();
  }, { prepend: true });

  ctx.on('user-questions/request', async (request, next) => {
    const agent = request.agent;
    if (!agent) return next();
    const callId = request.wait?.callId ?? request.questions.find(item => item.intent?.callId)?.intent.callId
      ?? agent.session.snapshotEvents().findLast(event => event.type === 'tool/call')?.data.callId;
    if (!callId) throw error('QUESTION_IDENTITY_MISSING');
    if (!Array.isArray(request.questions) || request.questions.length < 1 || request.questions.length > 16) throw error('QUESTION_BATCH_INVALID', 422);
    let record = Object.values(journal.questions).find(item => item.session_id === agent.id && item.call_id === callId);
    record ??= { id: 'question_' + randomUUID().replaceAll('-', ''), session_id: agent.id,
      call_id: callId, tool_name: request.questions.some(item => item.intent?.kind === 'plan-review') ? 'exit_plan_mode' : 'ask_user_question',
      questions: clone(request.questions), status: 'open', created_at: now() };
    journal.questions[record.id] = record; record.status = 'open';
    await save();
    return new Promise((resolve, reject) => {
      let finished = false;
      const close = (value, cause) => {
        if (finished) return; finished = true;
        liveQuestions.delete(record.id); request.signal?.removeEventListener('abort', abort);
        if (cause) reject(cause); else resolve(value);
      };
      const abort = () => {
        // Preserve the question after a process/foreground wait interruption.
        // A user cancellation uses answer() below and records cancelled.
        if (record.status === 'open') record.status = 'continued';
        // The timed/turn signal has already ended the foreground wait. Late
        // replies must become a new human message, not resolve that old call.
        liveQuestions.delete(record.id);
        void save().catch(() => {}).finally(() => close(undefined, new UserQuestionError('Question wait interrupted; the question remains in session history.', 'ASK_ABORTED')));
      };
      liveQuestions.set(record.id, { record, finish: close });
      request.signal?.addEventListener('abort', abort, { once: true });
      if (request.signal?.aborted) abort();
    });
  }, { global: true });

  const captureJobs = new Set();
  ctx.on('session/event', (session, event) => {
    if (event.type !== 'workspace/changes') return;
    const job = (async () => {
      // The official recorder publishes the event synchronously and then
      // installs its corresponding summary before returning to the loop.
      await Promise.resolve();
      const summary = ctx.workspaceChanges.summary(session.id, event.seq);
      const agent = ctx.agents.get(session.id);
      if (!summary || !agent) return;
      const record = { session_id: session.id, seq: event.seq, ...clone(summary), files: [], diffs: {}, status: 'ready' };
      let budget = 8 * 1024 * 1024;
      for (let index = 0; index < summary.files.length; index++) {
        const file = summary.files[index];
        try { await fileFor(agent, file.path); } catch { continue; }
        const outputIndex = record.files.length; record.files.push(clone(file));
        const diff = await ctx.workspaceChanges.diff(session.id, event.seq, index, new AbortController().signal);
        if (!diff) continue;
        const bytes = Buffer.byteLength(JSON.stringify(diff));
        if (bytes <= budget) { record.diffs[outputIndex] = clone(diff); budget -= bytes; }
      }
      // A recorder may include files blocked by the task's current access
      // level; do not expose their paths or their counts through this surface.
      record.total = record.files.length;
      record.added = record.files.reduce((sum, file) => sum + file.added, 0);
      record.deleted = record.files.reduce((sum, file) => sum + file.deleted, 0);
      journal.changes[`${session.id}:${event.seq}`] = record; await save();
    })();
    captureJobs.add(job); job.catch(() => {}).finally(() => captureJobs.delete(job));
  }, { global: true });

  async function webStatus(agent) {
    let eligible = false;
    // This metadata request does not make a model/search call. It resolves the
    // session's explicit selection and only reports a masked availability state.
    const wire = (await options.workspaces.events(agent.id, { after_seq: 1000000000 })).session;
    try { eligible = (await options.resolveWorkspaceSearchStatus?.(wire.llm_selection ?? null))?.eligible === true; }
    catch { /* A missing model connection does not disable anonymous fetch. */ }
    return { fetch: { status: 'ready', provider: 'http' }, search: { status: eligible ? 'ready' : 'configuration_required',
      provider: 'deepseek-official', consumes_model_quota: true,
      ...(eligible ? {} : { message: 'Select a verified DeepSeek connection for native web search. Public webpage fetch is already available.' }) } };
  }
  const surface = {
    async state(sessionId) {
      const agent = await agentFor(sessionId);
      await Promise.allSettled([...captureJobs]);
      const events = agent.session.snapshotEvents();
      // A newly journaled question is not yet answerable while its initial
      // durable write is in flight. Publish it only after the waiter exists;
      // recovered/continued questions intentionally have no live waiter.
      const questions = Object.values(journal.questions).filter(item => item.session_id === sessionId
        && (item.status === 'continued' || item.status === 'open' && liveQuestions.has(item.id)));
      const deliveries = [];
      for (const event of events.filter(event => event.type === 'deliverables/presented')) {
        const files = [];
        for (const file of event.data.files) {
          let available = false, size = null;
          try { const info = await stat(await fileFor(agent, file.path)); available = info.isFile(); size = info.size; } catch {}
          files.push({ ...file, available, bytes: size, mime_type: mime(file.path) });
        }
        deliveries.push({ seq: event.seq, turn: event.data.turn, call_id: event.data.callId, files });
      }
      return { session_id: sessionId, plan: { ...ctx.planMode.get(agent), readonly: true },
        pending_questions: clone(questions), deliverables: deliveries,
        workspace_changes: Object.values(journal.changes).filter(item => item.session_id === sessionId).map(({ diffs, ...item }) => clone(item)),
        web: await webStatus(agent) };
    },
    async answer(sessionId, questionId, input) {
      const agent = await agentFor(sessionId); const record = journal.questions[questionId];
      if (!record || record.session_id !== sessionId || !['open', 'continued'].includes(record.status)) throw error('QUESTION_STALE');
      const answer = input.cancel === true ? null : validateAnswers(record.questions, input.answers);
      const live = liveQuestions.get(questionId);
      if (input.cancel === true) {
        const previous = clone(record);
        record.status = 'cancelled'; record.updated_at = now();
        try { await save(); } catch (cause) { Object.assign(record, previous); throw cause; }
        if (live) live.finish(undefined, new UserQuestionError('The user cancelled this question.', 'ASK_CANCELLED'));
        else agent.followup(createUserMessage({ source: { kind: 'user-question-reply', callId: record.call_id, outcome: 'answered' },
          content: [{ type: 'text', text: JSON.stringify({ kind: 'cancelled_pending_question', callId: record.call_id,
            message: 'The user cancelled this question. This is not permission; do not execute the proposed action.' }) }] }));
      } else {
        // Validate and durably settle before releasing a live tool. Double
        // submissions cannot execute the same plan twice.
        const previous = clone(record);
        record.status = 'answered'; record.answers = answer.answers; record.updated_at = now();
        try { await save(); } catch (cause) { delete record.answers; Object.assign(record, previous); throw cause; }
        if (live) live.finish(answer);
        else {
          const question = record.questions.find(item => item.intent?.kind === 'plan-review');
          const item = question && answer.answers.find(item => item.id === question.id);
          const approved = question && item?.selected.length === 1 && item.selected[0] === question.intent.approve && item.custom === undefined;
          if (approved) ctx.planMode.set(agent, false);
          // No return is fabricated for an interrupted tool call. Resume with
          // a new human message containing the exact old question and answer.
          agent.followup(createUserMessage({ source: { kind: 'user-question-reply', callId: record.call_id, outcome: 'answered' },
            content: [{ type: 'text', text: JSON.stringify({ kind: 'answer_to_pending_question', tool: record.tool_name,
              callId: record.call_id, questions: record.questions, answers: answer.answers,
              ...(approved ? { plan_approved: true, note: 'The user approved this exact restored plan. Plan mode is now off.' } : {}) }) }] }));
        }
      }
      await ctx.sessionPersistence.flush(sessionId);
      return { accepted: true, session_id: sessionId, question_id: questionId, cancelled: input.cancel === true };
    },
    async plan(sessionId, active) {
      if (typeof active !== 'boolean') throw error('PLAN_MODE_INVALID', 422);
      const agent = await agentFor(sessionId);
      if (Object.values(journal.questions).some(item => item.session_id === sessionId && item.tool_name === 'exit_plan_mode'
          && ['open', 'continued'].includes(item.status))) throw error('PLAN_REVIEW_PENDING');
      const outcome = ctx.planMode.set(agent, active); await ctx.sessionPersistence.flush(sessionId);
      return { session_id: sessionId, plan: { ...ctx.planMode.get(agent), readonly: true }, outcome };
    },
    async diff(sessionId, seq, index) {
      const agent = await agentFor(sessionId); const record = journal.changes[`${sessionId}:${seq}`];
      if (!record || !record.files[index]) throw error('WORKSPACE_DIFF_UNAVAILABLE', 404);
      await fileFor(agent, record.files[index].path);
      const diff = record.diffs[index];
      if (!diff) return { session_id: sessionId, seq, status: 'unavailable', message: 'This file comparison exceeded the retained comparison budget.' };
      return { session_id: sessionId, seq, status: 'ready', diff: clone(diff) };
    },
    async deliveredFile(sessionId, seq, index, mode = 'preview') {
      const agent = await agentFor(sessionId);
      const event = agent.session.snapshotEvents().find(event => event.seq === seq && event.type === 'deliverables/presented');
      const file = event?.data.files[index];
      if (!file) throw error('DELIVERABLE_NOT_FOUND', 404);
      const path = await fileFor(agent, file.path); const info = await stat(path);
      if (!info.isFile()) throw error('DELIVERABLE_NOT_FOUND', 404);
      if (info.size > 64 * 1024 * 1024) throw error('DELIVERABLE_TOO_LARGE', 413);
      const type = mime(path);
      const inline = mode === 'preview' && /^(?:image\/(?:png|jpeg|webp|gif)|application\/pdf|text\/plain)/.test(type);
      return { binary: await readFile(path), media_type: type,
        disposition: `${inline ? 'inline' : 'attachment'}; filename*=UTF-8''${encodeURIComponent(basename(path))}` };
    },
  };
  ctx.effect(() => async () => {
    // Persist unresolved requests, then terminate in-memory waits. A new Host
    // reconstructs the cards and follows up on a human answer.
    for (const { record, finish } of liveQuestions.values()) {
      if (record.status === 'open') record.status = 'continued';
      finish(undefined, new UserQuestionError('Host stopped; question remains pending.', 'ASK_ABORTED'));
    }
    await Promise.allSettled([...captureJobs]); await save(); await writes;
  });
  return surface;
}
