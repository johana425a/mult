/** Scripted model transport fixture; filesystem/search/PowerShell execute on the real local OS. No cloud inference. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, writeFile, readFile, symlink, rmdir } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHost } from '../host.mjs';
import { checkedWorkspacePath, WORKSPACE_TOOLS } from '../workspaces.mjs';
import { requestCredential } from '../credentials.mjs';
import { runReaderProcess } from '../documents.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const python = process.env.DEEPSTEAM_HARNESS_TEST_PYTHON;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const value = await fn(); if (value) return value; await delay(30); }
  throw new Error('fixture_wait_timeout');
}
async function fixture(permissionMode = 'exact-action-once') {
  const root = await mkdtemp(join(process.env.DEEPSTEAM_HARNESS_TEST_ROOT, 'workspace-real-os-'));
  const profile = join(root, 'profile'); const folder = join(root, 'selected-folder'); const outside = join(root, 'outside');
  await Promise.all([mkdir(folder), mkdir(outside), mkdir(profile)]);
  await writeFile(join(folder, 'notes.txt'), 'alpha\nbeta\n');
  await writeFile(join(folder, 'AGENTS.md'), 'Fixture instruction: use only the selected folder.');
  await mkdir(join(folder, '.agents', 'skills', 'fixture'), { recursive: true });
  await writeFile(join(folder, '.agents', 'skills', 'fixture', 'SKILL.md'), '# Fixture skill\nRead notes.txt.');
  await writeFile(join(outside, 'secret.txt'), 'OUTSIDE_FIXTURE_NOT_TO_READ');
  await symlink(outside, join(folder, 'linked-outside'), 'junction');
  const sharp = (await import('sharp')).default;
  await sharp({ create: { width: 8, height: 8, channels: 3, background: { r: 200, g: 0, b: 0 } } }).png().toFile(join(folder, 'fixture.png'));
  let requests = 0; const receivedTools = []; const prompts = [];
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const chunk of req) raw += chunk;
    const input = JSON.parse(raw); requests++; receivedTools.push(input.tools?.map(tool => tool.function.name)); prompts.push(JSON.stringify(input.messages));
    const messageText = message => typeof message.content === 'string' ? message.content : message.content?.find(item => item.type === 'text')?.text ?? '';
    const userIndex = input.messages.findLastIndex(message => message.role === 'user' && messageText(message).startsWith('FIXTURE_TOOL:'));
    const user = input.messages[userIndex]; const text = messageText(user);
    const rawCommand = text.slice('FIXTURE_TOOL:'.length); let command;
    for (let end = rawCommand.indexOf('}'); end >= 0; end = rawCommand.indexOf('}', end + 1)) {
      try { command = JSON.parse(rawCommand.slice(0, end + 1)); break; } catch {}
    }
    if (!command) throw new Error('fixture_command_missing');
    const finished = input.messages.slice(userIndex + 1).some(message => message.role === 'tool');
    const delta = finished ? { content: 'FIXTURE: observed tool result.' } : { tool_calls: [{ index: 0, id: 'fixture-call-' + requests, type: 'function', function: { name: command.name, arguments: JSON.stringify(command.arguments) } }] };
    const chunk = (value, finishReason) => JSON.stringify({ id: 'fixture', object: 'chat.completion.chunk', created: 0, model: 'fixture-workspace', choices: [{ index: 0, delta: value, finish_reason: finishReason }] });
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.end('data: ' + chunk(delta, null) + '\n\ndata: ' + chunk({}, finished ? 'stop' : 'tool_calls') + '\n\ndata: [DONE]\n\n');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let routeGate; let nativeMetadata = null;
  const options = { profile, sessions: join(profile, 'sessions'), permissionMode, chromium: process.env.DEEPSTEAM_TEST_CHROMIUM, port: 0, python, credentialHelper: join(here, '../credential_store.py'),
    documentHelper: join(here, '../../../scripts/workspace_document_reader.py'),
    resolveWorkspaceRoute: async (selection) => {
      if (routeGate) await routeGate;
      return { route_id: 'fixture-selected', provider: 'deepsteam-custom', model: selection?.model_id || 'fixture-workspace', base_url: `http://127.0.0.1:${server.address().port}/v1`, vision_verified: true,
        resolved_model: { provider: 'fixture', model: selection?.model_id || 'fixture-workspace', selection_source: selection ? 'override' : 'default' },
        runWithCredentials: callback => requestCredential.run({ apiKey: 'fixture-no-secret' }, callback) };
    }, resolveWorkspaceMetadata: async path => nativeMetadata?.path === path ? structuredClone(nativeMetadata) : null };
  const host = await createHost(options);
  const { workspace } = await host.workspaces.register({ path: folder, name: 'Real OS fixture' });
  const { session } = await host.workspaces.createSession({ workspace_id: workspace.id });
  async function command(name, arguments_, decision = 'allow') {
    const before = (await host.workspaces.events(session.id)).next_seq;
    await host.workspaces.turn(session.id, { text: 'FIXTURE_TOOL:' + JSON.stringify({ name, arguments: arguments_ }) });
    let approval;
    if (permissionMode === 'exact-action-once' && ['write', 'edit', 'pwsh'].includes(name)) {
      approval = await until(async () => (await host.workspaces.events(session.id)).pending_approvals[0]);
      assert.deepEqual(approval.exact_action.arguments, arguments_);
      await host.workspaces.approve({ approval_id: approval.id, session_id: session.id, decision });
    }
    const events = await until(async () => { const value = await host.workspaces.events(session.id, { after_seq: before }); return value.session.status === 'idle' && value.events.some(event => event.type === 'turn/end') ? value : false; });
    return { result: events.events.findLast(event => event.type === 'tool/result'), events, approval };
  }
  return { host, options, root, profile, folder, outside, workspace, session, command, receivedTools, prompts, requestCount: () => requests,
    setNativeMetadata(value) { nativeMetadata = value; },
    holdRoute() { let release; routeGate = new Promise(resolve => { release = resolve; }); return () => { release(); routeGate = undefined; }; },
    async close() { await host.ctx.fiber.dispose(); await new Promise(resolve => server.close(resolve)); } };
}

test('shared document tools return PDF page evidence and model-visible image in the official agent loop', { skip: !python, timeout: 30000 }, async () => {
  const f = await fixture();
  try {
    const generated = await runReaderProcess(python, ['-c', 'import sys,json,runpy,pathlib; p=json.load(sys.stdin); helpers=runpy.run_path(p["helper"]); helpers["create_fixtures"](pathlib.Path(p["root"])); print(json.dumps({"ok":True}))'], { root: f.folder, helper: join(here, '../../../reports/smoke_workspace_documents.py') });
    assert.equal(generated.ok, true);
    const read = await f.command('read_document', { path: 'fixture.pdf', max_units: 1 });
    assert.equal(read.result.is_error, false); assert.match(read.result.text, /Synthetic PDF page 1/);
    const evidence = JSON.parse(read.result.text); assert.equal(evidence.units[0].locator.page, 1);
    const page = await f.command('read_document_image', { path: 'fixture.pdf', asset_id: 'pdf-page:1', document_sha256: evidence.document.sha256 });
    assert.equal(page.result.is_error, false); assert.ok(page.result.content.some(block => block.type === 'image'));
    assert.doesNotMatch(page.result.text, /base64/); assert.match(f.prompts.at(-1), /image_url/);
    const deps = await f.command('load_workspace_dependencies', {}); assert.match(deps.result.text, /python-docx/);
    await writeFile(join(f.folder, 'legacy.doc'), 'synthetic unsupported legacy format');
    const unsupported = await f.command('read_document', { path: 'legacy.doc' }); assert.equal(unsupported.result.is_error, true); assert.match(unsupported.result.text, /not read|UNSUPPORTED_FORMAT/);
    await assert.rejects(f.host.workspaces.documents(f.workspace.id, 'read', { path: '../outside/secret.txt' }));
    const list = await f.host.workspaces.documents(f.workspace.id, 'list', { path: '.', limit: 20 }); assert.ok(list.entries.some(row => row.path === 'fixture.pdf' && row.supported));
    await mkdir(join(f.folder, 'nested-documents')); await writeFile(join(f.folder, 'nested-documents', 'needle.txt'), 'synthetic');
    const direct = await f.host.workspaces.documents(f.workspace.id, 'list', { path: '.', limit: 50 });
    assert.ok(!direct.entries.some(row => row.path.includes('/')));
    const searched = await f.host.workspaces.documents(f.workspace.id, 'search', { path: '.', query: 'needle' });
    assert.ok(searched.entries.some(row => row.path === 'nested-documents/needle.txt'));
    for (const [name, marker] of [['fixture.docx', /Synthetic Word/], ['fixture.pptx', /Synthetic PPT/], ['fixture.md', /Synthetic Markdown/], ['fixture.xlsx', /Synthetic sheet/]]) {
      const document = await f.host.workspaces.documents(f.workspace.id, 'read', { path: name });
      assert.equal(document.ok, true); assert.match(document.text, marker);
      if (name.endsWith('.pptx')) assert.ok(document.units.some(unit => unit.locator.slide === 2 && marker.test(unit.text)));
    }
  } finally { await f.close(); }
});

test('authorized task tools write explicit outside paths without per-action approval and load official tools lazily', { skip: !python, timeout: 60000 }, async () => {
  const f = await fixture('authorized-task');
  try {
    // Workspace access is the default: outside paths are refused until the
    // user switches on Full computer access.
    assert.equal(f.host.workspaces.access().default_access, 'workspace');
    const blocked = await f.command('write', { file_path: join(f.outside, 'blocked.txt'), content: 'NOT_WRITTEN' });
    assert.equal(blocked.result.is_error, true); assert.match(blocked.result.text, /Full computer/);
    await f.host.workspaces.setAccess({ default_access: 'full' });
    assert.equal((await f.host.workspaces.events(f.session.id)).session.access_level, 'workspace'); // recorded until the next turn
    const outsideFile = join(f.outside, 'authorized-output.txt');
    const write = await f.command('write', { file_path: outsideFile, content: 'AUTHORIZED_TASK_OUTPUT' });
    assert.equal(write.result.is_error, false); assert.equal(write.approval, undefined);
    assert.equal(await readFile(outsideFile, 'utf8'), 'AUTHORIZED_TASK_OUTPUT');
    for (const capability of ['skills', 'goals', 'schedule', 'subagents', 'mcp']) {
      const loaded = await f.command('load_harness_tools', { capability });
      assert.equal(loaded.result.is_error, false, loaded.result.text);
      const state = JSON.parse(loaded.result.text);
      assert.equal(state.status, capability === 'mcp' ? 'configuration_required' : 'ready');
    }
    const agent = f.host.ctx.agents.get(f.session.id);
    const tools = f.host.ctx.tools.schemas(agent).map(value => value.name);
    assert.ok(tools.some(name => name.includes('skill')));
    assert.ok(tools.includes('subagent'));
    assert.ok(tools.some(name => name.includes('goal')));
    assert.ok(tools.some(name => name.includes('schedule')));
    assert.ok(!f.host.ctx.llm.listProviders().some(row => row.id === 'deepsteam-local'));
    const protectedWrite = await f.command('write', { file_path: join(f.profile, 'no.txt'), content: 'DENIED' });
    assert.equal(protectedWrite.result.is_error, true);
    const spawned = await f.command('subagent', { description: 'Read a synthetic note', prompt: 'FIXTURE_TOOL:' + JSON.stringify({ name: 'read', arguments: { file_path: 'notes.txt' } }) });
    assert.equal(spawned.result.is_error, false, spawned.result.text);
    const childId = /started subagent (\S+)/.exec(spawned.result.text)?.[1];
    assert.ok(childId);
    const child = await until(async () => {
      const snapshot = await f.host.workspaces.events(childId);
      return snapshot.events.some(event => event.type === 'turn/end') && snapshot.events.some(event => event.type === 'tool/result' && !event.is_error && /alpha/.test(event.text)) ? snapshot : false;
    });
    assert.ok(child.events.some(event => event.type === 'turn/end'));
    await until(async () => (await f.host.workspaces.events(f.session.id)).session.status === 'idle');
    await f.host.ctx.fiber.dispose();
    const resumed = await createHost(f.options);
    try {
      await resumed.workspaces.events(f.session.id);
      const schemas = resumed.ctx.tools.schemas(resumed.ctx.agents.get(f.session.id));
      assert.ok(schemas.some(tool => tool.name === 'subagent'));
    } finally { await resumed.ctx.fiber.dispose(); }
  } finally { await f.close(); }
});

test('real inventory protocol catalogs more than 600 files through the agent tool without a hidden list cap', { skip: !python, timeout: 60000 }, async () => {
  const f = await fixture('authorized-task');
  try {
    await mkdir(join(f.folder, 'catalog'));
    await Promise.all(Array.from({ length: 623 }, (_, i) => writeFile(join(f.folder, 'catalog', `source-${i}.md`), '# Synthetic source ' + i)));
    const catalog = await f.command('catalog_workspace', { path: 'catalog' });
    assert.equal(catalog.result.is_error, false, catalog.result.text);
    let state = JSON.parse(catalog.result.text);
    while (state.next_cursor) {
      const next = await f.command('catalog_workspace', { path: 'catalog', cursor: state.next_cursor });
      assert.equal(next.result.is_error, false, next.result.text); state = JSON.parse(next.result.text);
    }
    assert.equal(state.catalog_complete, true, JSON.stringify(state)); assert.equal(state.coverage.source_count, 623);
    assert.equal(state.coverage.complete_count, 0); assert.equal(state.coverage.reading_complete, false);
    const tail = await f.command('read_task_progress', { offset: 600, limit: 100 });
    assert.equal(JSON.parse(tail.result.text).sources.length, 23);
  } finally { await f.close(); }
});

test('Host-root compaction resolves only the exact session model credential route', { skip: !python, timeout: 60000 }, async () => {
  const f = await fixture('authorized-task');
  try {
    await f.command('read', { file_path: 'notes.txt' });
    await f.command('read', { file_path: 'AGENTS.md' });
    const agent = f.host.ctx.agents.get(f.session.id), before = f.requestCount();
    const compacted = await f.host.ctx.compaction.compactNow(agent, new AbortController().signal);
    assert.ok(compacted); assert.ok(f.requestCount() > before);
    const provider = f.host.ctx.llm.listProviders().find(row => row.id.startsWith('deepsteam-workspace-'));
    assert.ok(provider);
    async function consume(options) {
      for await (const _chunk of f.host.ctx.llm.stream({ provider: provider.id, model: 'fixture-workspace',
        messages: [{ role: 'user', content: [{ type: 'text', text: 'Synthetic route boundary test' }] }], ...options })) {}
    }
    const guarded = f.requestCount();
    await assert.rejects(consume({ sessionId: f.session.id, model: 'foreign-model' }), /workspace_model_route_mismatch/);
    await assert.rejects(consume({ sessionId: 'foreign-session' }), /workspace_session_unknown|unknown/);
    assert.equal(f.requestCount(), guarded, 'invalid model/session must never reach the transport');
  } finally { await f.close(); }
});

test('pinned browser and native computer tool catalogs load on demand without reading any desktop content', { skip: !python || !process.env.DEEPSTEAM_TEST_CHROMIUM, timeout: 60000 }, async () => {
  const f = await fixture('authorized-task');
  try {
    for (const capability of ['browser', 'computer']) {
      const result = await f.command('load_harness_tools', { capability });
      assert.equal(result.result.is_error, false, result.result.text);
      const loaded = JSON.parse(result.result.text); assert.equal(loaded.status, 'ready');
      assert.ok(loaded.tools.some(name => name.startsWith(capability === 'browser' ? 'mcp__playwright-mcp__' : 'cua_driver_native__')), JSON.stringify(loaded.tools));
    }
  } finally { await f.close(); }
});

test('official workspace tool loop executes real local files/image/search/approved PowerShell and resumes durable history', { skip: !python, timeout: 60000 }, async () => {
  const f = await fixture();
  try {
    assert.equal(f.session.cwd, await import('node:fs/promises').then(fs => fs.realpath(f.folder)));
    assert.deepEqual(f.host.ctx.tools.schemas(f.host.ctx.agents.get(f.session.id)).map(item => item.name).sort(), [...WORKSPACE_TOOLS].sort());
    const pruned = f.host.ctx.toolResultPruner.pruneContent([{ type: 'text', text: 'x'.repeat(12000) }]);
    assert.ok(pruned.some(block => block.type === 'text' && block.text.includes('tool result middle pruned')));
    assert.ok(pruned.reduce((count, block) => count + (block.text?.length ?? 0), 0) < 12000);
    const read = await f.command('read', { file_path: 'notes.txt' }); assert.equal(read.result.is_error, false); assert.match(read.result.text, /alpha/);
    const image = await f.command('read_image', { file_path: 'fixture.png' }); assert.equal(image.result.is_error, false); assert.ok(image.result.content.some(item => item.type === 'image'));
    const imageRef = image.result.content.find(item => item.type === 'image').attachment;
    const loadedImage = await f.host.workspaces.readAttachment(f.session.id, imageRef.attachmentId); assert.ok(loadedImage.data.length); assert.equal(loadedImage.media_type, 'image/png');
    await assert.rejects(f.host.workspaces.readAttachment(f.session.id, 'foreign-image'), /unknown/);
    const write = await f.command('write', { file_path: 'created.txt', content: 'created by real tool\n' }); assert.equal(write.result.is_error, false); assert.match(await readFile(join(f.folder, 'created.txt'), 'utf8'), /real tool/);
    const edit = await f.command('edit', { file_path: 'notes.txt', old_string: 'beta', new_string: 'gamma' }); assert.equal(edit.result.is_error, false); assert.match(await readFile(join(f.folder, 'notes.txt'), 'utf8'), /gamma/);
    const glob = await f.command('glob', { pattern: '**/*.txt' }); assert.equal(glob.result.is_error, false); assert.match(glob.result.text, /notes.txt/);
    const grep = await f.command('grep', { pattern: 'gamma' }); assert.equal(grep.result.is_error, false); assert.match(grep.result.text, /gamma/); assert.doesNotMatch(grep.result.text, /OUTSIDE_FIXTURE/);
    const shell = await f.command('pwsh', { description: 'Fixture exact approved output', command: "Write-Output 'DEEPSTEAM_REAL_POWERSHELL_OK'" }); assert.equal(shell.result.is_error, false); assert.match(shell.result.text, /DEEPSTEAM_REAL_POWERSHELL_OK/);
    process.env.DEEPSTEAM_FIXTURE_TOKEN = 'synthetic-value-only';
    try {
      const scrubbed = await f.command('pwsh', { description: 'Fixture child environment check', command: "if (Test-Path Env:DEEPSTEAM_FIXTURE_TOKEN) { Write-Output 'ENV_LEAKED' } else { Write-Output 'ENV_SCRUBBED' }" });
      assert.match(scrubbed.result.text, /ENV_SCRUBBED/); assert.doesNotMatch(scrubbed.result.text, /ENV_LEAKED|synthetic-value/);
    } finally { delete process.env.DEEPSTEAM_FIXTURE_TOKEN; }
    const background = await f.command('pwsh', { description: 'Fixture cancellable background command', command: "Start-Sleep -Seconds 30; Write-Output 'SHOULD_NOT_RUN'", run_in_background: true }); assert.equal(background.result.is_error, false);
    const jobs = f.host.ctx.jobs.list(f.session.id); assert.ok(jobs.some(job => job.status === 'running'));
    await assert.rejects(f.host.workspaces.manage(f.workspace.id, { phase: 'prepare', archived: true }), { code: 'workspace_busy' });
    const second = await f.host.workspaces.createSession({ workspace_id: f.workspace.id });
    await assert.rejects(f.host.workspaces.readAttachment(second.session.id, imageRef.attachmentId), /unknown/);
    assert.throws(() => f.host.ctx.jobs.get(jobs[0].id, second.session.id));
    await f.host.workspaces.cancel(f.session.id); await until(() => !f.host.ctx.jobs.list(f.session.id).some(job => ['running', 'stopping'].includes(job.status)));
    await f.host.workspaces.turn(f.session.id, { text: 'FIXTURE_TOOL:' + JSON.stringify({ name: 'pwsh', arguments: { description: 'Fixture foreground cancellation', command: "Start-Sleep -Seconds 30; Write-Output 'CANCEL_FAILED'" } }) });
    const runningApproval = await until(async () => (await f.host.workspaces.events(f.session.id)).pending_approvals[0]);
    await assert.rejects(f.host.workspaces.manage(f.workspace.id, { phase: 'prepare', archived: true }), { code: 'workspace_busy' });
    await f.host.workspaces.approve({ approval_id: runningApproval.id, session_id: f.session.id, decision: 'allow' });
    await until(() => f.host.ctx.jobs.list(f.session.id).some(job => job.status === 'running'));
    const cancelStart = Date.now(); await f.host.workspaces.cancel(f.session.id);
    await until(async () => (await f.host.workspaces.events(f.session.id)).session.status === 'idle'); assert.ok(Date.now() - cancelStart < 5000);
    assert.ok(!f.host.ctx.jobs.list(f.session.id).some(job => ['running', 'stopping'].includes(job.status)));
    const rejected = await f.command('write', { file_path: 'rejected.txt', content: 'must not exist' }, 'deny'); assert.equal(rejected.result.is_error, true); await assert.rejects(readFile(join(f.folder, 'rejected.txt')));
    await assert.rejects(f.host.workspaces.approve({ approval_id: rejected.approval.id, session_id: f.session.id, decision: 'allow' }), /stale/);
    const escape = await f.command('read', { file_path: '../outside/secret.txt' }); assert.equal(escape.result.is_error, true); assert.doesNotMatch(escape.result.text, /OUTSIDE_FIXTURE/);
    const junction = await f.command('read', { file_path: 'linked-outside/secret.txt' }); assert.equal(junction.result.is_error, true); assert.doesNotMatch(junction.result.text, /OUTSIDE_FIXTURE/);
    const swappable = join(f.folder, 'swappable'); await mkdir(swappable);
    const swappedBefore = (await f.host.workspaces.events(f.session.id)).next_seq;
    await f.host.workspaces.turn(f.session.id, { text: 'FIXTURE_TOOL:' + JSON.stringify({ name: 'write', arguments: { file_path: 'swappable/publish.txt', content: 'must not publish outside' } }) });
    const swapApproval = await until(async () => (await f.host.workspaces.events(f.session.id)).pending_approvals[0]);
    await rmdir(swappable); await symlink(f.outside, swappable, 'junction');
    await f.host.workspaces.approve({ approval_id: swapApproval.id, session_id: f.session.id, decision: 'allow' });
    await until(async () => (await f.host.workspaces.events(f.session.id)).session.status === 'idle');
    const swapped = await f.host.workspaces.events(f.session.id, { after_seq: swappedBefore }); assert.equal(swapped.events.findLast(event => event.type === 'tool/result').is_error, true);
    await assert.rejects(readFile(join(f.outside, 'publish.txt')));
    await f.command('read', { file_path: 'notes.txt' }); await writeFile(join(f.folder, 'notes.txt'), 'external concurrent change\n');
    const stale = await f.command('edit', { file_path: 'notes.txt', old_string: 'gamma', new_string: 'delta' }); assert.equal(stale.result.is_error, true); assert.equal(await readFile(join(f.folder, 'notes.txt'), 'utf8'), 'external concurrent change\n');
    const before = (await f.host.workspaces.events(f.session.id)).next_seq;
    await f.host.workspaces.turn(f.session.id, { text: 'FIXTURE_TOOL:' + JSON.stringify({ name: 'write', arguments: { file_path: 'cancelled.txt', content: 'must not exist' } }) });
    const pending = await until(async () => (await f.host.workspaces.events(f.session.id)).pending_approvals[0]);
    await f.host.workspaces.cancel(f.session.id);
    await until(async () => (await f.host.workspaces.events(f.session.id)).session.status === 'idle');
    await assert.rejects(f.host.workspaces.approve({ approval_id: pending.id, session_id: f.session.id, decision: 'allow' }), /stale/);
    await assert.rejects(readFile(join(f.folder, 'cancelled.txt')));
    const cancelled = await f.host.workspaces.events(f.session.id, { after_seq: before }); assert.ok(cancelled.events.some(event => event.type === 'approval/decided' && event.outcome === 'cancelled'));
    await assert.rejects(f.host.workspaces.events('onboarding-private'), /unknown/);
    await assert.rejects(f.host.workspaces.register({ path: f.profile }), /private/);
    assert.ok(f.prompts.some(prompt => String(prompt).includes(f.folder.replaceAll('\\', '\\\\')) && String(prompt).includes('Fixture instruction')));
    assert.ok(f.prompts.some(prompt => String(prompt).includes('SKILL.md')));
    assert.ok(f.receivedTools.every(names => names?.every(name => WORKSPACE_TOOLS.includes(name))));
    const releaseRoute = f.holdRoute(); const countBefore = f.requestCount();
    const delayedTurn = f.host.workspaces.turn(f.session.id, { text: 'FIXTURE_TOOL:' + JSON.stringify({ name: 'read', arguments: { file_path: 'notes.txt' } }) });
    await until(async () => (await f.host.workspaces.events(f.session.id)).session.status === 'running');
    await assert.rejects(f.host.workspaces.turn(f.session.id, { text: 'Duplicate turn must reject' }), /busy/);
    await f.host.workspaces.cancel(f.session.id); releaseRoute(); await assert.rejects(delayedTurn);
    assert.equal(f.requestCount(), countBefore);
    await f.host.ctx.sessionPersistence.flush();
    const summary = JSON.parse(await readFile(join(f.profile, 'workspace-folders.json'), 'utf8')); assert.ok(summary.folders.includes(f.folder));
  } finally { await f.close(); }
  const resumed = await createHost({ ...f.options, localBase: 'http://127.0.0.1:1/v1' });
  try {
    const list = await resumed.workspaces.list(); assert.ok(list.workspaces.some(item => item.id === f.workspace.id));
    const simultaneous = await Promise.all([resumed.workspaces.events(f.session.id, { after_seq: -1 }), resumed.workspaces.events(f.session.id, { after_seq: -1 })]);
    const events = simultaneous[0]; assert.equal(events.session.cwd, f.folder); assert.ok(events.events.some(event => event.type === 'tool/result' && /REAL_POWERSHELL_OK/.test(event.text)));
  } finally { await resumed.ctx.fiber.dispose(); }
  console.log(JSON.stringify({ fixture_model_transport_requests: f.requestCount(), real_os_tools: ['read', 'read_image', 'write', 'edit', 'glob', 'grep', 'pwsh'], real_cloud_model_calls: 0, real_local_model_inference_calls: 0, durable_resume: true }));
});

test('model preference and per-turn provenance survive reload without private credentials', { skip: !python, timeout: 15000 }, async () => {
  const f = await fixture();
  const selected = { profile_id: 'fixture-profile', model_id: 'fixture-selected-model' };
  try {
    const first = await f.command('read', { file_path: 'notes.txt' });
    assert.equal(first.result.resolved_model.model, 'fixture-workspace');
    await f.host.workspaces.turn(f.session.id, { text: 'FIXTURE_TOOL:' + JSON.stringify({ name: 'read', arguments: { file_path: 'notes.txt' } }), llm_selection: selected });
    await until(async () => (await f.host.workspaces.events(f.session.id)).session.status === 'idle');
    const all = await f.host.workspaces.events(f.session.id);
    const results = all.events.filter(event => event.type === 'tool/result');
    assert.equal(results[0].resolved_model.model, 'fixture-workspace');
    assert.equal(results.at(-1).resolved_model.model, 'fixture-selected-model');
    assert.deepEqual(all.session.llm_selection, selected);
    const saved = await readFile(join(f.profile, 'workspace-model-selections.json'), 'utf8');
    assert.doesNotMatch(saved, /api_key|base_url|fixture-no-secret/);
    await f.host.ctx.sessionPersistence.flush();
  } finally { await f.close(); }
  const resumed = await createHost(f.options);
  try {
    const all = await resumed.workspaces.events(f.session.id);
    assert.deepEqual(all.session.llm_selection, selected);
    const results = all.events.filter(event => event.type === 'tool/result');
    assert.equal(results[0].resolved_model.model, 'fixture-workspace');
    assert.equal(results.at(-1).resolved_model.model, 'fixture-selected-model');
  } finally { await resumed.ctx.fiber.dispose(); }
});

test('path containment uses complete boundaries and refuses junction escapes', { skip: !python }, async () => {
  const root = await mkdtemp(join(process.env.DEEPSTEAM_HARNESS_TEST_ROOT, 'workspace-path-'));
  const selected = join(root, 'selected'); const other = join(root, 'selected-other'); await Promise.all([mkdir(selected), mkdir(other)]);
  await assert.rejects(checkedWorkspacePath(selected, '../selected-other/new.txt'), /outside/);
  assert.equal(await checkedWorkspacePath(selected, 'new.txt'), join(selected, 'new.txt'));
  await symlink(other, join(selected, 'junction'), 'junction'); await assert.rejects(checkedWorkspacePath(selected, 'junction/new.txt'), /outside|link/);
});

test('workspace management retains folders/session IDs, persists restore and rejects busy/reserved operations', { skip: !python, timeout: 60000 }, async () => {
  const f = await fixture();
  const id = f.workspace.id;
  try {
    const held = f.holdRoute();
    const delayed = f.host.workspaces.turn(f.session.id, { text: 'FIXTURE_TOOL:' + JSON.stringify({ name: 'read', arguments: { file_path: 'notes.txt' } }) });
    await until(async () => (await f.host.workspaces.events(f.session.id)).session.status === 'running');
    await assert.rejects(f.host.workspaces.manage(id, { phase: 'prepare', archived: true }), { code: 'workspace_busy', status: 409 });
    await f.host.workspaces.cancel(f.session.id); held(); await assert.rejects(delayed);
    const prepared = await f.host.workspaces.manage(id, { phase: 'prepare', archived: true, name: 'Keep custom name' });
    await assert.rejects(f.host.workspaces.createSession({ workspace_id: id }), { code: 'workspace_recovery_required' });
    await assert.rejects(f.host.workspaces.turn(f.session.id, { text: 'Never submit' }), { code: 'workspace_recovery_required' });
    await f.host.workspaces.manage(id, { phase: 'commit', transaction_id: prepared.reservation.transaction_id });
    await assert.rejects(f.host.workspaces.createSession({ workspace_id: id }), { code: 'workspace_archived' });
    await assert.rejects(f.host.workspaces.turn(f.session.id, { text: 'Never submit' }), { code: 'workspace_archived' });
    await assert.rejects(f.host.workspaces.approve({ approval_id: 'stale', session_id: f.session.id, decision: 'allow' }), { code: 'workspace_archived' });
    assert.equal((await f.host.workspaces.events(f.session.id)).session.id, f.session.id);
    const row = (await f.host.workspaces.list()).workspaces.find(item => item.id === id);
    assert.equal(row.archived, true); assert.equal(row.title, 'Keep custom name'); assert.ok(row.session_ids.includes(f.session.id));
    assert.match(await readFile(join(f.folder, 'notes.txt'), 'utf8'), /alpha/);
    assert.ok(JSON.parse(await readFile(join(f.profile, 'workspace-folders.json'), 'utf8')).folders.includes(f.folder));
    assert.equal(f.requestCount(), 0);
  } finally { await f.close(); }
  const resumed = await createHost({ ...f.options, localBase: 'http://127.0.0.1:1/v1' });
  try {
    assert.equal((await resumed.workspaces.list()).workspaces.find(item => item.id === id).archived, true);
    const prepare = await resumed.workspaces.manage(id, { phase: 'prepare', archived: false });
    await resumed.workspaces.manage(id, { phase: 'commit', transaction_id: prepare.reservation.transaction_id });
    const reopened = (await resumed.workspaces.register({ path: f.folder, name: 'Ignore replacement' })).workspace;
    assert.equal(reopened.id, id); assert.equal(reopened.title, 'Keep custom name'); assert.ok(reopened.session_ids.includes(f.session.id));
    assert.equal((await resumed.workspaces.events(f.session.id)).session.id, f.session.id);
  } finally { await resumed.ctx.fiber.dispose(); }
});

test('linked native metadata is rechecked before durable prepare and commit and preserves changed directories', { skip: !python, timeout: 60000 }, async () => {
  const f = await fixture();
  const before = { workspace_id: 'native_fixture', name: 'Original', path: f.folder, kind: 'workspace', archived: false };
  const prepare = { phase: 'prepare', archived: true, native_workspace_id: before.workspace_id, native_before: before };
  try {
    f.setNativeMetadata(before);
    await assert.rejects(f.host.workspaces.manage(f.workspace.id, { phase: 'prepare', archived: true }), { code: 'workspace_revision_changed' });
    await assert.rejects(f.host.workspaces.manage(f.workspace.id,
      { ...prepare, native_before: { ...before, name: 'Stale' } }), { code: 'workspace_revision_changed' });
    f.setNativeMetadata({ ...before, kind: 'general' });
    await assert.rejects(f.host.workspaces.manage(f.workspace.id, prepare), { code: 'workspace_protected' });
    await assert.rejects(f.host.workspaces.register({ path: f.folder }), { code: 'workspace_protected' });
    const protectedPath = join(f.root, 'built-in-fixture');
    await mkdir(protectedPath);
    f.setNativeMetadata({ ...before, path: protectedPath, kind: 'system' });
    await assert.rejects(f.host.workspaces.register({ path: protectedPath }), { code: 'workspace_protected' });
    assert.equal((await f.host.workspaces.list()).workspaces.length, 1);
    f.setNativeMetadata(before);
    const pending = await f.host.workspaces.manage(f.workspace.id, prepare);
    const commit = { phase: 'commit', transaction_id: pending.reservation.transaction_id };
    await assert.rejects(f.host.workspaces.manage(f.workspace.id, commit), { code: 'workspace_revision_changed' });
    f.setNativeMetadata({ ...before, path: f.outside, archived: true });
    await assert.rejects(f.host.workspaces.manage(f.workspace.id, commit), { code: 'workspace_revision_changed' });
    assert.ok((await f.host.workspaces.managementStatus(f.workspace.id)).reservation);
    f.setNativeMetadata({ ...before, archived: true });
    await f.host.workspaces.manage(f.workspace.id, commit);
    const status = await f.host.workspaces.managementStatus(f.workspace.id);
    assert.equal(status.reservation, null);
    assert.equal(status.workspace.archived, true);
    assert.ok(status.workspace.session_ids.includes(f.session.id));
    assert.match(await readFile(join(f.folder, 'notes.txt'), 'utf8'), /alpha/);
    assert.equal(f.requestCount(), 0);
  } finally { await f.close(); }
});
