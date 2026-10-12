import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createWorkspaceManagement } from './workspace_management.mjs';

test('archive overlay and prepared reservation survive restart without removing records', async () => {
  const profile = await mkdtemp(join(tmpdir(), 'deepsteam-management-'));
  const first = await createWorkspaceManagement(profile);
  const native = { workspace_id: 'native_one', name: 'Old name', path: 'D:\\fixture', kind: 'workspace', archived: false };
  const reservation = await first.prepare('harness_one', { name: 'New name', archived: true }, native);
  const reopened = await createWorkspaceManagement(profile);
  assert.equal(reopened.reservation('harness_one').transaction_id, reservation.transaction_id);
  assert.equal(reopened.view('harness_one').archived, false);
  await reopened.commit('harness_one', reservation.transaction_id);
  await reopened.commit('harness_one', reservation.transaction_id);
  assert.equal(reopened.reservation('harness_one'), null);
  assert.equal(reopened.view('harness_one').name, 'New name');
  assert.equal(reopened.view('harness_one').archived, true);
  const restored = await createWorkspaceManagement(profile);
  assert.equal(restored.view('harness_one').last_transaction_id, reservation.transaction_id);
  const restore = await restored.prepare('harness_one', { archived: false }, { ...native, name: 'New name', archived: true });
  await restored.commit('harness_one', restore.transaction_id);
  assert.equal(restored.view('harness_one').name, 'New name');
  assert.equal(restored.view('harness_one').archived, false);
});

test('prepare and stale commit/abort are serialized and original metadata remains', async () => {
  const profile = await mkdtemp(join(tmpdir(), 'deepsteam-management-'));
  const store = await createWorkspaceManagement(profile);
  const reservation = await store.prepare('one', { archived: true });
  await assert.rejects(store.prepare('one', { name: 'Race' }), { code: 'workspace_recovery_required' });
  await assert.rejects(store.commit('one', 'other'), { code: 'workspace_management_stale' });
  await assert.rejects(store.abort('one', 'other'), { code: 'workspace_management_stale' });
  await store.abort('one', reservation.transaction_id);
  assert.equal(store.view('one').archived, false);
});

test('failed atomic destination replacement leaves the previous durable metadata and reservation', async () => {
  const profile = await mkdtemp(join(tmpdir(), 'deepsteam-management-'));
  // A directory occupying the durable JSON destination simulates an I/O save
  // failure without deleting or changing any user file.
  const store = await createWorkspaceManagement(profile);
  await mkdir(join(profile, 'workspace-management.json'));
  await assert.rejects(store.prepare('one', { archived: true }));
  assert.equal(store.reservation('one'), null);
  assert.equal(store.view('one').archived, false);
});
