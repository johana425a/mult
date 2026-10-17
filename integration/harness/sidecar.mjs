/** Authenticated loopback host entry for the DeepSteam external Harness integration. */
import { readFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { timingSafeEqual } from 'node:crypto';
import { createHost, COMMIT } from './host.mjs';
import { requestCredential } from './credentials.mjs';
import { convertRequest, failureInfo, openAiResponse } from './protocol.mjs';
import { workspaceRequest } from './workspace_http.mjs';
import { executionTaskRequest } from './execution_tasks.mjs';
import { interactionRequest } from './interaction_http.mjs';
import sharp from 'sharp';
import { deploymentProtectedPaths } from './deployment_policy.mjs';
import { executionError } from './execution_errors.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const profile = process.env.DEEPSTEAM_HARNESS_PROFILE;
const tokenFile = process.env.DEEPSTEAM_HARNESS_TOKEN_FILE;
if (!profile || !tokenFile || !process.env.DEEPSTEAM_HARNESS_PYTHON) throw new Error('Missing isolated Harness deployment settings');
const token = (await readFile(tokenFile, 'utf8')).trim();
if (token.length < 40) throw new Error('Invalid internal service token');
const port = Number(process.env.DEEPSTEAM_HARNESS_PORT ?? 3796);
const portal = process.env.DEEPSTEAM_PORTAL_ORIGIN ?? 'http://127.0.0.1:3791';
if (new URL(portal).hostname !== '127.0.0.1') throw new Error('Portal must be loopback');
await mkdir(profile, { recursive: true });
const routes = new Map(); const controllers = new Set(); const loginOperations = new Map();
const same = (left, right) => typeof left === 'string' && Buffer.byteLength(left) === Buffer.byteLength(right) && timingSafeEqual(Buffer.from(left), Buffer.from(right));
const bearer = req => String(req.headers.authorization ?? '').replace(/^Bearer /, '');
async function rpc(path, body, signal) {
  const timeout = AbortSignal.timeout(path.includes('surface-tools') ? 86400000 : 30000);
  const response = await fetch(portal + path, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }, body: JSON.stringify(body), signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.error ?? body.detail ?? {};
    throw Object.assign(new Error(typeof detail === 'string' ? detail : detail.message ?? `Application service returned HTTP ${response.status}`), {code: detail.code ?? body.code ?? 'PORTAL_OPERATION_FAILED', status: response.status});
  }
  return response.json();
}
const host = await createHost({ profile, sessions: join(profile, 'sessions'), port,
  python: process.env.DEEPSTEAM_HARNESS_PYTHON, credentialHelper: join(here, 'credential_store.py'),
  documentHelper: join(dirname(dirname(here)), 'scripts', 'workspace_document_reader.py'),
  chromium: process.env.DEEPSTEAM_CHROMIUM,
  protectedPaths: deploymentProtectedPaths(dirname(dirname(here)), process.env.DEEPSTEAM_STATE_ROOT, tokenFile),
  async resolveWorkspaceRoute(llm_selection = null) {
    const selected = await rpc('/api/harness/internal/workspace-provider', { llm_selection });
    return { provider: selected.provider, model: selected.model, route_id: selected.route_id,
      base_url: selected.base_url, vision_verified: selected.vision_verified, vision_supported: selected.vision_supported,
      context_window: selected.context_window, max_output_tokens: selected.max_output_tokens,
      context_window_source: selected.context_window_source,
      resolved_model: selected.resolved_model, llm_selection: selected.llm_selection ?? llm_selection,
      search_route: selected.search_route,
      runWithCredentials: callback => requestCredential.run({ apiKey: selected.api_key || 'no-key', searchRoute: selected.search_route }, callback) };
  },
  async resolveWorkspaceMetadata(path) {
    const result = await rpc('/api/harness/internal/workspace-metadata', { path });
    return result.workspace ?? null;
  },
  async resolveWorkspaceSearchStatus(llm_selection = null) {
    return rpc('/api/harness/internal/workspace-search-status', { llm_selection });
  },
  async invokeSurfaceTool(body, signal) {
    return rpc('/api/harness/internal/surface-tools/invoke', body, signal);
  } });
const { ctx } = host;
const metadata = { version: '0.2.1-alpha.2', locale: 'zh-CN', timezoneOffsetSeconds: -new Date().getTimezoneOffset() * 60 };
let closing = false;
const json = (res, value, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)); };
async function bodyOf(req) {
  let bytes = 0; const chunks = [];
  for await (const chunk of req) { bytes += chunk.length; if (bytes > 25 * 1024 * 1024) throw Object.assign(new Error('Request too large'), { status: 413 }); chunks.push(chunk); }
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}
const modelCatalog = [{ id: 'deepseek-flash', label: 'DeepSeek-V4.1-Flash', vision: true }, { id: 'deepseek-v4-pro', label: 'DeepSeek-V4-Pro', vision: false }];
async function visionProbe(provider, model, signal) {
  const pixels = Buffer.alloc(96 * 48 * 3);
  for (let y = 0; y < 48; y++) for (let x = 0; x < 96; x++) pixels[(y * 96 + x) * 3 + (x < 48 ? 0 : 2)] = 255;
  const data = await sharp(pixels, { raw: { width: 96, height: 48, channels: 3 } }).png().toBuffer();
  const attachment = await ctx.attachments.saveImage({ data, mediaType: 'image/png', name: 'connection-vision-test.png' });
  let answer = ''; let error;
  for await (const chunk of ctx.llm.stream({ provider, model, messages: [{ role: 'user', content: [{ type: 'text', text: 'Name the two colors from left to right. Return only their names in order.' }, { type: 'image', attachment }] }], maxTokens: 32, reasoningEffort: 'off', signal })) {
    if (chunk.type === 'text-delta') answer += chunk.text;
    if (chunk.type === 'finish' && ['error', 'aborted'].includes(chunk.reason.kind)) error = failureInfo(chunk.reason.failure);
  }
  return { verified: !error && /(?:red[\s\S]*blue|red[\s\S]*blue)/i.test(answer), error_code: error?.code ?? undefined, test: 'nonprivate_left_right_color_order' };
}
function accountView(state) {
  return { ...state, authenticated: state.status === 'credential-stored', login_pending: Boolean(state.attempt && ['initializing', 'waiting-browser', 'exchanging', 'committing'].includes(state.attempt.phase)), attempt_id: state.attempt?.id ?? null, authorization_url: state.attempt?.authorizeUrl, expires_at: state.attempt?.expiresAt, error_code: state.attempt?.errorCode };
}
async function route(req, res) {
  const path = new URL(req.url, 'http://127.0.0.1').pathname;
  if (path === '/health' && req.method === 'GET') return json(res, { healthy: !closing, protocol: 2, implementation: 'official-harness-plugins', version: '0.2.1-alpha.2', source_commit: COMMIT, port, active: ['cordis', 'deepseek-account-platform', 'llm-deepseek-account', 'llm-deepseek-api-key', 'llm-pi-ai', 'agent-loop', 'session-persistence-jsonl', 'workspace-files-search-shell', 'authorized-tasks', 'durable-execution-tasks', 'source-ledger', 'lazy-capabilities', 'tool-web', 'web-fetch-http', 'web-search-deepseek', 'user-questions', 'tool-ask-user', 'plan-mode', 'tool-present', 'workspace-changes'] });
  if (req.headers.origin !== undefined) return json(res, { error: { code: 'BROWSER_ORIGIN_DENIED', message: 'Use the local application gateway' } }, 403);
  let selected;
  const presented = bearer(req);
  if (path.startsWith('/v1/')) selected = [...routes.values()].find(value => same(presented, value.guard));
  if (!same(presented, token) && !selected) return json(res, { error: { code: 'UNAUTHORIZED', message: 'Internal authentication required' } }, 401);
  if (closing) return json(res, { error: { code: 'HOST_CLOSING' } }, 503);
  const controller = new AbortController(); controllers.add(controller);
  const disconnect = () => { if (!res.writableEnded) controller.abort(); };
  res.once('close', disconnect);
  try {
    const body = req.method === 'POST' ? await bodyOf(req) : {};
    const interaction = await interactionRequest(host.interactions, req.method, path,
      new URL(req.url, 'http://127.0.0.1').searchParams, body, controller.signal);
    if (interaction) {
      if (interaction.binary) {
        res.writeHead(200, { 'Content-Type': interaction.media_type, 'Content-Length': interaction.binary.byteLength,
          'Content-Disposition': interaction.disposition, 'Cache-Control': 'no-store',
          'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox" });
        res.end(Buffer.from(interaction.binary)); return;
      }
      return json(res, interaction.value);
    }
    const task = await executionTaskRequest(host.tasks, req.method, path,
      new URL(req.url, 'http://127.0.0.1').searchParams, body);
    if (task) return json(res, task);
    const workspace = await workspaceRequest(host.workspaces, req.method, path,
      new URL(req.url, 'http://127.0.0.1').searchParams, body, controller.signal);
    if (workspace) {
      if (workspace.binary) {
        res.writeHead(200, { 'Content-Type': workspace.media_type, 'Content-Length': workspace.binary.byteLength,
          'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
        res.end(Buffer.from(workspace.binary)); return;
      }
      return json(res, workspace.value, workspace.status ?? 200);
    }
    if (path === '/account/status' && req.method === 'GET') {
      const state = await ctx.deepseekAccount.getState();
      if (new URL(req.url, 'http://127.0.0.1').searchParams.get('refresh') === 'true' && state.status === 'credential-stored') {
        const [profileInfo, balance] = await Promise.all([ctx.deepseekAccount.getProfile(metadata), ctx.deepseekAccount.getBalance(metadata)]);
        return json(res, { ...accountView(await ctx.deepseekAccount.getState()), profile: profileInfo, balance, balance_status: balance?.status ?? 'unknown' });
      }
      return json(res, accountView(state));
    }
    if (path === '/account/login/start' && req.method === 'POST') {
      if (!/^[A-Za-z0-9_-]{1,100}$/.test(body.operation_id ?? '')) return json(res, { error: { code: 'INVALID_OPERATION' } }, 400);
      let state = await ctx.deepseekAccount.startSignIn(metadata, 'http://127.0.0.1:' + port, 'desktop');
      if (state.attempt) loginOperations.set(body.operation_id, state.attempt.id);
      if (state.attempt?.phase === 'initializing') {
        const initialAttempt = state.attempt.id;
        const initializationSignal = AbortSignal.any([controller.signal, AbortSignal.timeout(35000)]);
        try {
          for await (const changed of ctx.deepseekAccount.watch(initializationSignal)) {
            if (changed.attempt?.id !== initialAttempt || changed.attempt.phase !== 'initializing') { state = changed; break; }
          }
        } finally {
          // A disconnected or expired start request cannot leave a late authorization active.
          if (initializationSignal.aborted) {
            const current = await ctx.deepseekAccount.getState();
            if (current.attempt?.id === initialAttempt) state = await ctx.deepseekAccount.cancelSignIn(initialAttempt);
            loginOperations.delete(body.operation_id);
          }
        }
      }
      return json(res, accountView(state));
    }
    if (path === '/account/login/cancel' && req.method === 'POST') {
      const state = await ctx.deepseekAccount.getState();
      const attempt = loginOperations.get(body.operation_id);
      if (!attempt || attempt !== state.attempt?.id) return json(res, { ...accountView(state), ignored_stale_cancel: true });
      loginOperations.delete(body.operation_id);
      return json(res, accountView(await ctx.deepseekAccount.cancelSignIn(attempt)));
    }
    if (path === '/account/signout' && req.method === 'POST') return json(res, accountView(await ctx.deepseekAccount.signOut(metadata)));
    if (path === '/models' && req.method === 'GET') return json(res, { models: modelCatalog });
    if (path === '/v1/models' && req.method === 'GET') return json(res, { object: 'list', data: (selected ? [selected] : [...routes.values()]).map(value => ({ id: value.route_id, object: 'model', owned_by: 'DeepSteam', name: value.model })) });
    if (path === '/routes' && req.method === 'POST') {
      if (!/^[A-Za-z0-9_-]{1,100}$/.test(body.route_id ?? '') || !['account', 'apikey'].includes(body.route) || !modelCatalog.some(model => model.id === body.model) || typeof body.guard !== 'string' || body.guard.length < 32 || (body.route === 'apikey' && typeof body.secret_ref !== 'string')) return json(res, { error: { code: 'INVALID_ROUTE' } }, 400);
      routes.set(body.route_id, { route_id: body.route_id, route: body.route, model: body.model, guard: body.guard, secret_ref: body.secret_ref });
      return json(res, { registered: true, route_id: body.route_id });
    }
    if (path.startsWith('/routes/') && req.method === 'DELETE') { routes.delete(path.slice(8)); return json(res, { removed: true }); }
    if (path === '/probe' && req.method === 'POST') {
      if (!['account', 'apikey'].includes(body.route) || !modelCatalog.some(model => model.id === body.model)) return json(res, { ok: false, code: 'INVALID_MODEL' }, 400);
      if (body.route === 'apikey' && (typeof body.api_key !== 'string' || !body.api_key.trim())) return json(res, { ok: false, code: 'MISSING_CREDENTIAL' }, 400);
      const options = { provider: body.route === 'account' ? 'deepseek-account' : 'deepseek-official', model: body.model, messages: [{ role: 'user', content: [{ type: 'text', text: 'Reply with OK.' }] }], maxTokens: 32, reasoningEffort: 'off', signal: controller.signal };
      let answer = ''; let failure; let vision = { verified: false };
      await requestCredential.run({ apiKey: body.api_key }, async () => {
        for await (const chunk of ctx.llm.stream(options)) { if (chunk.type === 'text-delta') answer += chunk.text; if (chunk.type === 'finish' && ['error', 'aborted'].includes(chunk.reason.kind)) failure = failureInfo(chunk.reason.failure); }
        if (!failure && answer && body.verify_vision !== false && modelCatalog.find(model => model.id === body.model)?.vision) {
          try { vision = await visionProbe(options.provider, body.model, controller.signal); }
          catch { vision = { verified: false, error_code: 'VISION_PROBE_FAILED' }; }
          if (vision.error_code === 'ACCOUNT_TOKEN_INVALID') failure = { code: vision.error_code, status: 401 };
        }
      });
      return json(res, failure ? { ok: false, code: failure.code, error: failure, vision_verified: false } : { ok: Boolean(answer), route: body.route, model: body.model, vision_verified: vision.verified, vision_error_code: vision.error_code, vision_test: vision.test });
    }
    if (path === '/v1/chat/completions' && req.method === 'POST') {
      selected = selected ?? routes.get(body.model);
      if (!selected || (body.model !== selected.route_id && body.model !== selected.model)) return json(res, { error: { code: 'UNKNOWN_ROUTE' } }, 404);
      const secret = selected.route === 'apikey' ? await rpc('/api/harness/internal/secret', { secret_ref: selected.secret_ref, route_id: selected.route_id }, controller.signal) : {};
      const provider = selected.route === 'account' ? 'deepseek-account' : 'deepseek-official';
      const converted = await convertRequest({ ...body, provider, model: selected.model }, ctx);
      return await requestCredential.run({ apiKey: secret.api_key }, () => openAiResponse(ctx, { ...converted, provider, model: selected.model, publicModel: body.model, signal: controller.signal }, res, Boolean(body.stream)));
    }
    if (path === '/shutdown' && req.method === 'POST') { json(res, { stopping: true }); setImmediate(shutdown); return; }
    return json(res, { error: { code: 'NOT_FOUND' } }, 404);
  } catch (error) {
    const code = /^[A-Za-z0-9_]{1,80}$/.test(String(error?.code ?? '')) ? error.code : 'HOST_OPERATION_FAILED';
    // Provider and shell exceptions may include private request details. Only
    // a bounded error identity enters operational logs or the error response.
    console.warn('Harness operation failed:', code);
    if (!res.headersSent && !res.destroyed) json(res, { error: executionError(error, 'host_request') }, error.status ?? 502);
    else if (!res.writableEnded && !res.destroyed) res.end();
  } finally { controllers.delete(controller); res.removeListener('close', disconnect); }
}
ctx.effect(() => ctx.webServer.registerFallback(route));
async function shutdown() {
  if (closing) return; closing = true;
  for (const controller of controllers) controller.abort();
  await ctx.fiber.dispose(); process.exit(0);
}
process.once('SIGINT', shutdown); process.once('SIGTERM', shutdown);
console.log('DeepSteam Harness ready on loopback port ' + port);
