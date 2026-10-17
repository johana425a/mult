import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createExecutionTasks } from '../execution_tasks.mjs';
import { createTaskLedger } from '../task_ledger.mjs';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn) { for (let n = 0; n < 200; n++) { const result = await fn(); if (result) return result; await delay(10); } throw new Error('test_timeout'); }
async function fixture() {
  const profile = await mkdtemp(join(process.env.DEEPSTEAM_HARNESS_TEST_ROOT || tmpdir(), 'task-fixture-'));
  const sessions = new Map(), calls = [];
  const workspace = {
    async createSession() { const id = 'session-' + (sessions.size + 1); sessions.set(id, { events: [], status: 'idle' }); return { session: { id } }; },
    async events(id, { after_seq = -1 } = {}) { const s = sessions.get(id); return { session: { status: s.status }, events: s.events.filter(e => e.seq > after_seq), next_seq: s.events.length - 1 }; },
    async turn(id, payload) { const s = sessions.get(id); s.status = 'running'; calls.push({ id, payload }); return { run_id: 'run-' + calls.length, resolved_model: payload.llm_selection }; },
    async cancel(id) { this.finish(id, 'cancelled'); },
    finish(id, outcome = 'stop') { const s = sessions.get(id); s.events.push({ seq: s.events.length, type: 'assistant/message', text: 'Synthetic finished output' }); s.events.push({ seq: s.events.length, type: 'turn/end', outcome }); s.status = 'idle'; },
  };
  const tasks = await createExecutionTasks({ profile, workspaces: workspace, pollMs: 5 });
  return { profile, tasks, workspace, sessions, calls };
}

test('tasks deduplicate, isolate owners, freeze model, resume shared sessions and cancel children', async () => {
  const f = await fixture();
  try {
    const input = { owner: 'fixture', source: 'mastery', task_key: 'one', workspace_id: 'ws-one', text: 'Synthetic work', llm_selection: { model_id: 'chosen', profile_id: 'fixture' } };
    const first = await f.tasks.create(input);
    const duplicate = await f.tasks.create(input);
    assert.equal(first.task.id, duplicate.task.id); assert.equal(duplicate.reused, true);
    await assert.rejects(f.tasks.create({ ...input, text: 'Different' }), { code: 'execution_task_key_conflict' });
    await assert.rejects(f.tasks.get(first.task.id, 'other'), { code: 'execution_task_missing' });
    await until(() => f.calls.length === 1);
    assert.equal(f.calls[0].payload.llm_selection.model_id, 'chosen');
    const session = f.calls[0].id; f.workspace.finish(session);
    await until(async () => (await f.tasks.get(first.task.id, 'fixture')).task.status === 'completed');
    const followup = await f.tasks.create({ ...input, task_key: 'two', continuation_task_id: first.task.id });
    await until(() => f.calls.length === 2); assert.equal(f.calls[1].id, session);
    const child = await f.tasks.create({ ...input, task_key: 'child', parent_task_id: followup.task.id });
    await until(() => f.calls.length === 3);
    await f.tasks.cancel(followup.task.id, 'fixture');
    assert.equal((await f.tasks.get(child.task.id, 'fixture')).task.status, 'cancelled');
  } finally { await f.tasks.close(); }
});

test('restart pauses interrupted work and retains identity before explicit resume', async () => {
  const f = await fixture();
  const result = await f.tasks.create({ owner: 'fixture', source: 'books', task_key: 'saved', workspace_id: 'ws-one', text: 'Synthetic write' });
  await until(() => f.calls.length === 1); await f.tasks.close();
  const resumed = await createExecutionTasks({ profile: f.profile, workspaces: f.workspace, pollMs: 5 });
  try {
    assert.equal((await resumed.get(result.task.id, 'fixture')).task.status, 'interrupted');
    assert.equal(f.calls.length, 1);
    await resumed.resume(result.task.id, 'fixture'); await until(() => f.calls.length === 2);
    assert.equal(f.calls[0].id, f.calls[1].id); assert.match(f.calls[1].payload.text, /avoid repeating/i);
  } finally { await resumed.close(); }
});

test('cancel during pre-admission I/O cannot start a model or write', async () => {
  const f = await fixture();
  const original = f.workspace.events;
  let release, entered = false;
  const gate = new Promise(resolve => { release=resolve; });
  f.workspace.events = async function(...args) { entered=true; await gate; return original.apply(this,args); };
  try {
    const value = await f.tasks.create({owner:'fixture',source:'chat',task_key:'cancel-race',workspace_id:'ws-one',text:'write'});
    await until(()=>entered);
    const cancelling = f.tasks.cancel(value.task.id,'fixture');
    release(); await cancelling;
    assert.equal(f.calls.length,0);
    assert.equal((await f.tasks.get(value.task.id,'fixture')).task.status,'cancelled');
  } finally { release(); await f.tasks.close(); }
});

test('lost admission response can be cancelled before the POST reaches create', async () => {
  const f = await fixture();
  try {
    const input={owner:'fixture',source:'chat',task_key:'lost-response',workspace_id:'ws-one',text:'write'};
    await f.tasks.cancelAdmission(input);
    const value=await f.tasks.create(input);
    assert.equal(value.task.status,'cancelled'); assert.equal(f.calls.length,0);
    await f.tasks.close();
    const next=await createExecutionTasks({profile:f.profile,workspaces:f.workspace,pollMs:5});
    try {assert.equal((await next.create(input)).task.status,'cancelled');assert.equal(f.calls.length,0);}
    finally {await next.close();}
  } finally {await f.tasks.close();}
});

test('completed tasks never expose later conversation events or live answers', async () => {
  const f=await fixture();
  try {
    const input={owner:'fixture',source:'chat',surface:'chat',conversation_id:'same',workspace_id:'ws-one',text:'first'};
    const a=await f.tasks.create({...input,task_key:'a'});
    await until(()=>f.calls.length===1); f.workspace.finish(f.calls[0].id);
    await until(async()=>(await f.tasks.get(a.task.id,'fixture')).task.status==='completed');
    const before=await f.tasks.get(a.task.id,'fixture');
    await f.tasks.create({...input,task_key:'b',text:'second'});
    await until(()=>f.calls.length===2); f.workspace.finish(f.calls[1].id);
    const after=await f.tasks.get(a.task.id,'fixture');
    assert.deepEqual(after.events,before.events); assert.equal(after.next_seq,before.next_seq); assert.equal(after.live_response,null);
  } finally {await f.tasks.close();}
});

test('children inherit the accepted parent model, workspace and source identity', async () => {
  const f=await fixture();
  try {
    const input={owner:'fixture',source:'classroom',workspace_id:'ws-one',native_workspace_id:'native-one',text:'parent',llm_selection:{model_id:'A'}};
    const p=await f.tasks.create({...input,task_key:'parent'}); await until(()=>f.calls.length===1);
    await f.tasks.create({...input,task_key:'child',parent_task_id:p.task.id,workspace_id:'ws-wrong',native_workspace_id:'native-wrong',llm_selection:{model_id:'B'}});
    await until(()=>f.calls.length===2);
    assert.equal(f.calls[1].payload.llm_selection.model_id,'A');
    assert.equal(f.calls[1].payload.task_context.native_workspace_id,'native-one');
    assert.equal(f.calls[1].payload.task_context.parent_task_id,p.task.id);
    await f.tasks.cancel(p.task.id,'fixture');
    await assert.rejects(f.tasks.create({...input,task_key:'late-child',parent_task_id:p.task.id}),{code:'execution_parent_not_running'});
  } finally {await f.tasks.close();}
});

test('restarted teaching tasks require a fresh same-catalog binding before resume', async () => {
  const f=await fixture();
  const interaction={surface:'learning',context_ref:'old',tools:[{name:'save_note'}]};
  const input={owner:'fixture',source:'learning',surface:'learning',task_key:'rebind',workspace_id:'ws-one',text:'resume',interaction};
  const value=await f.tasks.create(input); await until(()=>f.calls.length===1); await f.tasks.close();
  const next=await createExecutionTasks({profile:f.profile,workspaces:f.workspace,pollMs:5});
  try {
    await assert.rejects(next.resume(value.task.id,'fixture'),{code:'execution_context_rebind_required'});
    await assert.rejects(next.resume(value.task.id,'fixture',{...interaction,tools:[{name:'other'}]}),{code:'execution_tool_catalog_changed'});
    await next.resume(value.task.id,'fixture',{...interaction,context_ref:'fresh'});
    await until(()=>f.calls.length===2);
    assert.equal(f.calls[1].payload.task_context.interaction.context_ref,'fresh');
  } finally {await next.close();}
});

test('723-source ledger and 13 fragmented units survive restart without pretending extraction is reading', async () => {
  const profile = await mkdtemp(join(process.env.DEEPSTEAM_HARNESS_TEST_ROOT || tmpdir(), 'ledger-fixture-'));
  let ledger = await createTaskLedger(profile);
  const entries = Array.from({ length: 723 }, (_, i) => ({ path: `source-${i}.pdf`, kind: 'file', supported: i !== 722, bytes: 100, mtime_ns: 123 }));
  for (let i = 0; i < 723; i += 200) await ledger.manifest('s', entries.slice(i, i + 200), i + 200 >= 723, i + 200 < 723 ? `cursor-${i + 200}` : null);
  let state = await ledger.read('s'); assert.equal(state.coverage.source_count, 723); assert.equal(state.coverage.unsupported_count, 1);
  assert.equal(state.coverage.reading_complete, false); assert.equal(state.sources.length, 30);
  function fragment(index, start, end, digest = 'source-hash') { return { ok: true, document: { sha256: digest, unit_count: 13 }, next_cursor: index === 13 ? null : 'opaque',
    coverage: { text_extraction_complete: true }, units: [{ unit_index: index, locator: { page: index }, char_start: start, char_end: end, total_chars: 100,
      unit_text_sha256: 'unit-' + index, text: 'x'.repeat(end - start), coverage: { unresolved: [] } }] }; }
  for (let index = 1; index <= 13; index++) await ledger.recordDocument('s', 'source-0.pdf', fragment(index, 50, 100));
  state = await ledger.source('s', 'source-0.pdf'); assert.equal(state.complete, false); assert.equal(state.units.length, 13);
  await ledger.update('s', { summary: 'First batch with source-0.pdf pages 1–13', next_steps: ['Read missing first halves'] });
  await ledger.update('s', { source_path: 'source-0.pdf', source_summary: 'Synthetic per-file findings: page 1 introduces alpha.', output_references: ['synthetic-notes.md#source-0'] });
  await assert.rejects(ledger.update('s', { summary: 'x'.repeat(12001) }), { code: 'task_progress_size_limit' });
  ledger = await createTaskLedger(profile);
  assert.match(await ledger.context('s'), /Read missing first halves/);
  assert.match((await ledger.source('s', 'source-0.pdf')).source_summary, /page 1/);
  assert.equal((await ledger.source('s', 'source-0.pdf')).output_references[0], 'synthetic-notes.md#source-0');
  assert.deepEqual((await ledger.source('s', 'source-0.pdf')).units[0].spans, [[50, 100]]);
  for (let index = 1; index <= 13; index++) {
    await ledger.recordDocument('s', 'source-0.pdf', fragment(index, 0, 50));
    await ledger.recordDocument('s', 'source-0.pdf', fragment(index, 0, 50));
  }
  state = await ledger.source('s', 'source-0.pdf'); assert.equal(state.complete, true); assert.deepEqual(state.units[0].spans, [[0, 100]]);
  assert.equal((await ledger.read('s')).coverage.complete_count, 1);
  await ledger.recordDocument('s', 'source-0.pdf', fragment(13, 50, 100, 'changed-source'));
  assert.equal((await ledger.source('s', 'source-0.pdf')).complete, false);
  assert.equal((await ledger.source('s', 'source-0.pdf')).source_summary, '');
});

test('trusted relative, absolute and material aliases share only their owner and workspace source',async()=>{
  const profile=await mkdtemp(join(tmpdir(),'ledger-alias-'));
  let owner='one';
  const ledger=await createTaskLedger(profile,{resolveSource:async(_id,path,result)=>({owner,scope:'workspace',source_id:'C:/book.pdf',
    aliases:['book.pdf','C:/book.pdf','reading:material@1'],sha256:result.document?.sha256 || 'hash'})});
  const result={ok:true,document:{sha256:'hash',unit_count:1},units:[]};
  await ledger.recordDocument('s','book.pdf',result);await ledger.recordDocument('s','C:/book.pdf',result);
  await ledger.recordTeaching('s',[{type:'reading',material_id:'material',material_revision:1,page:1}]);
  assert.equal((await ledger.read('s')).coverage.source_count,1);
  owner='two';await ledger.recordDocument('s','book.pdf',result);
  assert.equal((await ledger.read('s')).coverage.source_count,2);
});
