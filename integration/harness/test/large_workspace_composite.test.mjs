/** Real tool/reader/persistence composite. Only LLM transport and semantic summaries are scripted. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHost } from '../host.mjs';
import { requestCredential } from '../credentials.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const python = process.env.DEEPSTEAM_HARNESS_TEST_PYTHON;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn) {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) { const result = await fn(); if (result) return result; await delay(20); }
  throw new Error('composite_turn_timeout');
}

test('623 real sources: full inventory, batch read, source notes, official compaction and restart continuation', { skip: !python, timeout: 1800000 }, async () => {
  const started = Date.now();
  const resumedFixture = process.env.DEEPSTEAM_COMPOSITE_RESUME_ROOT;
  const root = resumedFixture || await mkdtemp(join(process.env.DEEPSTEAM_HARNESS_TEST_ROOT, 'large-composite-'));
  const profile = join(root, 'profile'), folder = join(root, 'workspace');
  await Promise.all([mkdir(profile, { recursive: true }), mkdir(join(folder, 'sources'), { recursive: true }), mkdir(join(folder, 'outputs'), { recursive: true })]);
  const names = Array.from({ length: 623 }, (_, i) => `sources/source-${String(i).padStart(4, '0')}.${i % 2 ? 'txt' : 'md'}`);
  if (!resumedFixture) await Promise.all(names.map((name, i) => writeFile(join(folder, name), `# Synthetic source ${i}\nUnique marker COMPOSITE_${String(i).padStart(4, '0')}\nIts measured value is ${i * 7}.\n`)));
  let requests = 0;
  const server = createServer(async (req, res) => {
    let raw = ''; for await (const part of req) raw += part;
    const input = JSON.parse(raw); requests++;
    const isCompact = !input.tools?.length;
    const content = isCompact ? 'Synthetic checkpoint: durable source ledger stores per-file notes and pending paths. Continue using read_task_progress.' : 'Synthetic batch checkpoint recorded in durable source ledger.';
    const chunk = (delta, finish_reason) => JSON.stringify({ id: 'composite-' + requests, object: 'chat.completion.chunk', created: 0, model: 'fixture-composite', choices: [{ index: 0, delta, finish_reason }] });
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.end('data: ' + chunk({ content }, null) + '\n\ndata: ' + chunk({}, 'stop') + '\n\ndata: [DONE]\n\n');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const options = { profile, sessions: join(profile, 'sessions'), permissionMode: 'authorized-task', port: 0, python,
    credentialHelper: join(here, '../credential_store.py'), documentHelper: join(here, '../../../scripts/workspace_document_reader.py'),
    resolveWorkspaceRoute: async selection => ({ route_id: 'fixture-composite', provider: 'deepsteam-custom', model: selection?.model_id || 'fixture-composite',
      base_url: `http://127.0.0.1:${server.address().port}/v1`, vision_verified: false,
      resolved_model: { provider: 'synthetic', model: 'fixture-composite', configuration_revision: 'fixture-composite-v1' },
      runWithCredentials: callback => requestCredential.run({ apiKey: 'synthetic-no-key' }, callback) }) };
  let host = await createHost(options), sessionId, toolCount = 0;
  const signal = new AbortController().signal;
  async function call(name, args) {
    const result = await host.ctx.tools.execute({ name, arguments: args, callId: 'composite-' + (++toolCount), agent: host.ctx.agents.get(sessionId), signal });
    assert.equal(result.isError, false, JSON.stringify(result));
    const value = result.value?.result ?? result.value;
    assert.notEqual(value?.ok, false, JSON.stringify(value));
    return value;
  }
  async function turn(text) {
    const before = (await host.workspaces.events(sessionId)).next_seq;
    await host.workspaces.turn(sessionId, { text });
    return until(async () => { const state = await host.workspaces.events(sessionId, { after_seq: before }); return state.session.status === 'idle' && state.events.some(e => e.type === 'turn/end') ? state : false; });
  }
  let totalPages = 0, readCalls = resumedFixture ? 300 : 0, batchCount = resumedFixture ? 10 : 0, reuseVerified = false, compactionResult;
  try {
    const workspace = resumedFixture ? (await host.workspaces.list()).workspaces[0]
      : (await host.workspaces.register({ path: folder, name: 'Synthetic 623 source composite' })).workspace;
    sessionId = resumedFixture ? workspace.session_ids[0] : (await host.workspaces.createSession({ workspace_id: workspace.id })).session.id;
    if (resumedFixture) await host.workspaces.events(sessionId);
    await turn('Synthetic task: organize every source under sources into outputs, retaining a note and source locator for every file.');
    let catalog;
    do { catalog = await call('catalog_workspace', { path: 'sources', ...(catalog?.next_cursor ? { cursor: catalog.next_cursor } : {}) }); totalPages++; } while (catalog.next_cursor);
    assert.equal(catalog.catalog_complete, true); assert.equal(catalog.coverage.source_count, 623); assert.equal(catalog.coverage.complete_count, resumedFixture ? 300 : 0);
    const expected = new Map(names.map((name, i) => [name, `COMPOSITE_${String(i).padStart(4, '0')}`]));
    async function processBatch(batch) {
      const findings = [];
      for (let i = 0; i < batch.length; i += 3) {
        const group = batch.slice(i, i + 3);
        const results = await Promise.all(group.map(path => { readCalls++; return call('read_document', { path, max_chars: 2000, max_units: 5, engine: 'builtin' }); }));
        for (let j = 0; j < group.length; j++) {
          const path = group[j], doc = results[j];
          assert.match(doc.text, new RegExp(expected.get(path))); assert.equal(doc.next_cursor, null);
          findings.push({ path, marker: expected.get(path), text: doc.text, locators: doc.units.map(u => u.locator) });
        }
      }
      const output = `outputs/batch-${String(batchCount++).padStart(3, '0')}.md`;
      await call('write', { file_path: output, content: findings.map(row => `## ${row.path}\n${row.text}\nSource locators: ${JSON.stringify(row.locators)}\n`).join('\n') });
      for (const row of findings) await call('save_task_progress', { source_path: row.path,
        source_summary: `Synthetic verified marker ${row.marker}; locators ${JSON.stringify(row.locators)}.`, output_references: [output + '#' + row.path] });
      return findings.length;
    }
    for (let offset = resumedFixture ? 300 : 0; offset < 300; offset += 30) {
      await processBatch(names.slice(offset, offset + 30));
      await call('save_task_progress', { summary: `Synthetic batch ${batchCount} persisted; completed ${offset + 30} of 623 sources.`, next_steps: ['Read remaining source paths using read_task_progress; reuse stored per-file notes.'] });
      await turn(`Batch ${batchCount} notes are persisted. ${'Synthetic history ballast retains no unique source facts. '.repeat(80)}`);
      console.log(JSON.stringify({ phase: 'first-half', completed: offset + 30, elapsed_seconds: Math.round((Date.now() - started) / 1000) }));
    }
    const preRestart = await call('read_task_progress', { offset: 0, limit: 100 });
    assert.equal(preRestart.coverage.complete_count, 300); assert.equal(preRestart.coverage.pending_count, 323); assert.equal(preRestart.coverage.reading_complete, false);
    const duplicate = await Promise.all(Array.from({ length: 3 }, () => call('read_document', { path: names[0], max_chars: 2000, max_units: 5, engine: 'builtin' })));
    assert.ok(duplicate.every(value => value.document.sha256 === duplicate[0].document.sha256));
    const afterRepeat = await call('read_task_progress', {}); assert.equal(afterRepeat.coverage.complete_count, 300); reuseVerified = true;
    compactionResult = await host.ctx.compaction.compactNow(host.ctx.agents.get(sessionId), signal);
    assert.ok(compactionResult, 'manual official compaction must replace history');
    await host.ctx.fiber.dispose();
    host = await createHost(options); await host.workspaces.events(sessionId);
    const restored = await call('read_task_progress', { offset: 300, limit: 100 });
    assert.equal(restored.coverage.complete_count, 300); assert.equal(restored.coverage.pending_count, 323);
    const sourceNote = await call('read_task_progress', { source_path: names[0] });
    assert.match(sourceNote.source_summary, /COMPOSITE_0000/); assert.equal(sourceNote.output_references.length, 1);
    assert.match(await readFile(join(folder, sourceNote.output_references[0].split('#')[0]), 'utf8'), /COMPOSITE_0000/);
    const pending = [];
    for (let offset = 0; ; ) {
      const page = await call('read_task_progress', { offset, limit: 100 });
      pending.push(...page.sources.filter(row => !row.complete).map(row => row.path));
      if (page.next_offset == null) break; offset = page.next_offset;
    }
    assert.equal(pending.length, 323); assert.equal(new Set(pending).size, 323);
    await turn('Resume only pending source paths from the persistent ledger after compaction and process restart.');
    for (let offset = 0; offset < pending.length; offset += 30) {
      await processBatch(pending.slice(offset, offset + 30));
      console.log(JSON.stringify({ phase: 'resumed-half', completed: 300 + Math.min(pending.length, offset + 30), elapsed_seconds: Math.round((Date.now() - started) / 1000) }));
    }
    const verified = [];
    for (const name of names) {
      const note = await call('read_task_progress', { source_path: name });
      assert.equal(note.complete, true); assert.match(note.source_summary, new RegExp(expected.get(name)));
      assert.equal(note.output_references.length, 1); verified.push({ source: name, output: note.output_references[0], source_summary: note.source_summary });
    }
    await call('write', { file_path: 'outputs/index.json', content: JSON.stringify(verified, null, 2) });
    await call('save_task_progress', { summary: 'All 623 synthetic sources were delivered through real read_document tools, with per-source notes and a persisted output index.', next_steps: [] });
    const final = await call('read_task_progress', {});
    assert.equal(final.coverage.source_count, 623); assert.equal(final.coverage.complete_count, 623); assert.equal(final.coverage.pending_count, 0); assert.equal(final.coverage.reading_complete, true);
    const report = { schema: 'deepsteam-large-workspace-composite-v1', passed: true, source_count: 623, real_read_document_calls: readCalls + 3,
      tool_calls: toolCount, output_batches: batchCount, catalog_tool_pages: totalPages, coverage: final.coverage,
      pre_restart: { complete: 300, pending: 323 }, resumed_pending_count: pending.length, per_source_notes_verified: verified.length,
      official_compaction: Boolean(compactionResult), host_restart: true, repeated_read_delivery_deduplicated: reuseVerified,
      concurrent_readers: 3, document_busy_errors: 0, mock_model_requests: requests, official_compaction_successes: compactionResult ? 1 : 0,
      cloud_calls: 0, fixture_root: root, resumed_fixture_after_first_300: Boolean(resumedFixture), elapsed_seconds_this_process: Number(((Date.now() - started) / 1000).toFixed(2)),
      limitations: ['Semantic source summaries are deterministic fixture assertions, not evidence of model understanding.', 'Read-result identity and ledger deduplication tested; broker computation reuse is covered separately by parser tests.', 'No private files or live provider credentials used.'] };
    await writeFile(join(here, '../../../reports/harness-large-workspace-composite.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally { await host.ctx.fiber.dispose(); await new Promise(resolve => server.close(resolve)); }
});
