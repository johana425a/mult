/** Synthetic documents and local Python only. No model, account, or user files. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, symlink } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readDocument, workspaceFileCatalog, runReaderProcess, packagedDependencies, documentModelView, documentPending } from '../documents.mjs';
import { checkedWorkspacePath } from '../workspaces.mjs';
import { workspaceRequest } from '../workspace_http.mjs';

const python = process.env.DEEPSTEAM_HARNESS_TEST_PYTHON;
const testRoot = process.env.DEEPSTEAM_HARNESS_TEST_ROOT;
const helper = join(dirname(fileURLToPath(import.meta.url)), '../../../scripts/workspace_document_reader.py');
test('document HTTP boundary rejects arbitrary roots and carries cancellation', async () => {
  const signal = new AbortController().signal; const calls = [];
  const adapter = { documents: async (...args) => { calls.push(args); return { ok: true }; } };
  await assert.rejects(workspaceRequest(adapter, 'POST', '/workspaces/w1/documents/read', new URLSearchParams(), { root: 'C:/', path: 'x.pdf' }, signal));
  const result = await workspaceRequest(adapter, 'POST', '/workspaces/w1/documents/read', new URLSearchParams(), { path: 'x.pdf', start_unit: 2, ocr: 'off' }, signal);
  assert.equal(result.value.ok, true); assert.deepEqual(calls[0].slice(0, 3), ['w1', 'read', { path: 'x.pdf', start_unit: 2, ocr: 'off' }]); assert.equal(calls[0][3], signal);
});

test('model view keeps the next position at both ends and drops duplicated text', () => {
  const units = [{ unit_index: 1, locator: { page: 1 }, text: 'A'.repeat(9000), unit_text_sha256: 'x' }];
  const view = documentModelView({ ok: true, text: 'A'.repeat(9000), units, truncated: true, next_cursor: 'abc', next_start_unit: 2,
    navigation: { next_cursor: 'abc', next_start_unit: 2, done: false } });
  const rendered = JSON.stringify(view);
  assert.equal(Object.keys(view)[0], 'navigation'); assert.equal(Object.keys(view).at(-1), 'navigation_end');
  assert.match(rendered.slice(0, 4096), /"next_cursor":"abc"/); assert.match(rendered.slice(-1024), /start_unit=2/);
  assert.equal(view.text, undefined); assert.equal(view.units[0].unit_text_sha256, undefined); assert.equal(view.units[0].text.length, 9000);
  assert.deepEqual(documentModelView({ ok: true, asset: {} }), { ok: true, asset: {} });
});

test('a read still waiting on local MinerU is shown as pending with how to come back', () => {
  const waiting = { ok: true, status: 'running', job_status: 'waiting', job_id: 'a'.repeat(32), retry_after_ms: 2000,
    parse: { state: 'parsing', pages: [5, 8], tier: 'advanced', eta_seconds: 240 }, message: 'Local MinerU (advanced tier) is parsing pages 5-8; about 4 min left.' };
  assert.equal(documentPending(waiting), true);
  const view = documentModelView(waiting);
  assert.equal(view.status, 'pending'); assert.equal(view.retry_after_ms, undefined);
  assert.deepEqual(view.parse.pages, [5, 8]);
  assert.match(view.how_to_continue, /parsing pages 5-8/); assert.match(view.how_to_continue, /read_document again with the same arguments/);
  assert.match(view.how_to_continue, new RegExp('a'.repeat(32)));
  assert.equal(documentPending({ ok: true, status: 'ready', units: [] }), false);
  assert.equal(documentPending({ ok: false, status: 'running', job_id: 'x' }), false);
});

test('placeholder cursors from a model start at the beginning instead of failing', { skip: !python || !testRoot }, async () => {
  const root = await mkdtemp(join(testRoot, 'document-cursor-'));
  await writeFile(join(root, 'notes.md'), 'Line\n'.repeat(4000));
  for (const cursor of ['', 'null', '0']) {
    const value = await readDocument(python, helper, root, 'read', { path: 'notes.md', cursor, start_unit: 0, max_chars: 300, engine: 'builtin' });
    assert.equal(value.ok, true, JSON.stringify(value.error)); assert.equal(value.units[0].unit_index, 1); assert.equal(value.navigation.next_start_unit, value.next_start_unit);
  }
  const first = await readDocument(python, helper, root, 'read', { path: 'notes.md', max_chars: 300, engine: 'builtin' });
  const repaired = await readDocument(python, helper, root, 'read', { path: 'notes.md', cursor: first.next_cursor.replace(/=+$/, ''), engine: 'builtin', max_chars: 300 });
  assert.equal(repaired.ok, true, JSON.stringify(repaired.error));
});

test('fixed isolated reader preserves Unicode, rejects outside paths and checks document versions', { skip: !python || !testRoot }, async () => {
  const root = await mkdtemp(join(testRoot, 'document-reader-'));
  await writeFile(join(root, 'notes.md'), '# Synthetic public fixture\n' + 'Boundary text\n'.repeat(1000));
  const first = await readDocument(python, helper, root, 'read', { path: 'notes.md', max_chars: 300, max_units: 4, engine: 'builtin' });
  assert.equal(first.ok, true); assert.match(first.text, /Synthetic public/); assert.equal(first.truncated, true); assert.ok(first.next_cursor); assert.doesNotMatch(JSON.stringify(first), /�/);
  const second = await readDocument(python, helper, root, 'read', { path: 'notes.md', cursor: first.next_cursor, engine: 'builtin' }); assert.equal(second.ok, true);
  await writeFile(join(root, 'notes.md'), 'changed');
  const changed = await readDocument(python, helper, root, 'read', { path: 'notes.md', cursor: first.next_cursor }); assert.equal(changed.ok, false);
  const outside = await readDocument(python, helper, root, 'read', { path: '../outside.md' }); assert.equal(outside.ok, false);
  const fake = await readDocument(python, helper, root, 'read', { path: 'notes.md', root: 'C:/' }); assert.equal(fake.ok, true); assert.equal(fake.text.includes('changed'), true);
});

test('catalog lists documents by name without reading bodies or following junctions', { skip: !testRoot }, async () => {
  const parent = await mkdtemp(join(testRoot, 'document-catalog-')); const root = join(parent, 'workspace'); const outside = join(parent, 'outside');
  await mkdir(root); await mkdir(outside); await writeFile(join(root, 'lesson.pdf'), 'synthetic not real PDF');
  await writeFile(join(root, 'notes.txt'), 'BODY_ONLY_MARKER'); await writeFile(join(outside, 'hidden.pdf'), 'not readable');
  await symlink(outside, join(root, 'linked'), 'junction');
  const check = path => checkedWorkspacePath(root, path);
  const all = await workspaceFileCatalog(root, {}, check); assert.ok(all.entries.some(row => row.path === 'lesson.pdf')); assert.ok(!all.entries.some(row => row.path.includes('hidden')));
  const query = await workspaceFileCatalog(root, { query: 'BODY_ONLY_MARKER' }, check); assert.equal(query.entries.length, 0); assert.match(query.search_scope, /filenames only/);
});

test('short waiters do not reject a third request and cancellation waits for local helper exit', { skip: !python }, async () => {
  const one = new AbortController(); const two = new AbortController();
  const a = runReaderProcess(python, ['-c', 'import time; time.sleep(30)'], undefined, one.signal);
  const b = runReaderProcess(python, ['-c', 'import time; time.sleep(30)'], undefined, two.signal);
  const third = await runReaderProcess(python, ['-c', 'import json; print(json.dumps(dict(ok=True)))']); assert.equal(third.ok, true);
  one.abort(); two.abort(); assert.equal((await a).error.code, 'document_cancelled'); assert.equal((await b).error.code, 'document_cancelled');
  await new Promise(resolve => setTimeout(resolve, 300));
  const failed = await runReaderProcess(python, ['-c', 'import sys; print("{}"); sys.exit(3)']); assert.equal(failed.ok, false);
});

test('directory browsing returns only direct children so earlier descendants cannot hide later siblings', { skip: !testRoot }, async () => {
  const root = await mkdtemp(join(testRoot, 'document-browse-'));
  const early = join(root, 'a-first'); await mkdir(early);
  for (let index = 0; index < 12; index++) await writeFile(join(early, `child-${index}.txt`), 'synthetic');
  await mkdir(join(early, 'nested')); await writeFile(join(early, 'nested', 'grandchild.txt'), 'synthetic');
  await writeFile(join(root, 'z-final.txt'), 'root sibling');
  const check = path => checkedWorkspacePath(root, path);
  const result = await workspaceFileCatalog(root, { limit: 5 }, check);
  assert.deepEqual(result.entries.map(row => row.path), ['a-first', 'z-final.txt']);
  assert.equal(result.truncated, false);
  const inside = await workspaceFileCatalog(root, { path: 'a-first', limit: 50 }, check);
  assert.ok(inside.entries.some(row => row.path === 'a-first/nested'));
  assert.ok(!inside.entries.some(row => row.path.endsWith('grandchild.txt')));
  const search = await workspaceFileCatalog(root, { query: 'grandchild', depth: 3 }, check);
  assert.deepEqual(search.entries.map(row => row.path), ['a-first/nested/grandchild.txt']);
  await mkdir(join(root, 'z-last-directory'));
  for (let index = 0; index < 10; index++) await writeFile(join(root, `a-file-${index}.txt`), 'synthetic');
  const bounded = await workspaceFileCatalog(root, { limit: 3 }, check);
  assert.deepEqual(bounded.entries.slice(0, 2).map(row => row.path), ['a-first', 'z-last-directory']);
  assert.equal(bounded.entries.length, 3); assert.equal(bounded.truncated, true);
});

test('dependency discovery reports the selected packaged executable and library metadata', { skip: !python }, async () => {
  const result = await packagedDependencies(python); assert.equal(result.ok, true); assert.equal(result.python.executable.toLowerCase(), python.toLowerCase());
  assert.ok(result.libraries.some(row => row.name === 'python-docx')); assert.ok(result.libraries.some(row => row.name === 'rapidocr'));
});
