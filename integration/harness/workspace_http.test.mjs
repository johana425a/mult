import test from 'node:test';
import assert from 'node:assert/strict';
import { workspaceRequest } from './workspace_http.mjs';

const fixture = () => {
  const calls = [];
  const adapter = Object.fromEntries(['list', 'register', 'createSession', 'listSessions', 'events', 'turn', 'cancel', 'approve', 'manage', 'managementStatus']
    .map(name => [name, async (...args) => { calls.push([name, ...args]); return { fixture: true, name }; }]));
  return { adapter, calls };
};
const query = new URLSearchParams();

test('HTTP dispatch passes only selected directory, task and exact approval identity', async () => {
  const { adapter, calls } = fixture();
  assert.equal((await workspaceRequest(adapter, 'POST', '/workspaces', query, { path: 'D:\\synthetic', name: 'Fixture' })).value.name, 'register');
  await workspaceRequest(adapter, 'POST', '/workspaces/workspace_fixture/sessions', query, { title: 'Task' });
  await workspaceRequest(adapter, 'GET', '/sessions/session_fixture/events', new URLSearchParams('after_seq=7'), {});
  await workspaceRequest(adapter, 'POST', '/sessions/session_fixture/turn', query, { text: 'Read fixture' });
  await workspaceRequest(adapter, 'POST', '/sessions/session_fixture/cancel', query, {});
  await workspaceRequest(adapter, 'POST', '/approvals/approval_fixture', query, { session_id: 'session_fixture', decision: 'allow' });
  assert.deepEqual(calls[2], ['events', 'session_fixture', { after_seq: 7 }]);
  assert.deepEqual(calls.at(-1), ['approve', { approval_id: 'approval_fixture', session_id: 'session_fixture', decision: 'allow' }]);
});

test('management dispatch accepts narrow reversible metadata phases and rejects injected fields', async () => {
  const { adapter, calls } = fixture();
  await workspaceRequest(adapter, 'GET', '/workspaces/one/management', query, {});
  await workspaceRequest(adapter, 'POST', '/workspaces/one/manage', query, { phase: 'prepare', archived: true, name: 'Retained' });
  await workspaceRequest(adapter, 'POST', '/workspaces/one/manage', query, { phase: 'commit', transaction_id: 'transaction_one' });
  assert.deepEqual(calls[1], ['manage', 'one', { phase: 'prepare', archived: true, name: 'Retained' }]);
  for (const body of [
    { phase: 'prepare' }, { phase: 'prepare', archived: 'true' }, { phase: 'prepare', name: ' ' },
    { phase: 'prepare', archived: true, delete_files: true },
    { phase: 'commit', transaction_id: 'one', archived: false },
    { phase: 'prepare', archived: true, native_before: {} },
    { phase: 'prepare', archived: true, native_workspace_id: 'without-snapshot' },
    { phase: 'prepare', name: 'x'.repeat(101) },
  ]) await assert.rejects(workspaceRequest(adapter, 'POST', '/workspaces/one/manage', query, body));
  assert.equal(calls.length, 3);
});

test('management requires a full canonical native identity snapshot when linked', async () => {
  const { adapter, calls } = fixture();
  const body = { phase: 'prepare', archived: true, native_workspace_id: 'native_one',
    native_before: { workspace_id: 'native_one', name: 'Fixture', archived: false, path: 'D:\\fixture', kind: 'workspace' } };
  await workspaceRequest(adapter, 'POST', '/workspaces/one/manage', query, body);
  for (const [key, value] of [['workspace_id', 'other'], ['archived', 0], ['path', ''], ['kind', 'unexpected']]) {
    await assert.rejects(workspaceRequest(adapter, 'POST', '/workspaces/one/manage', query,
      { ...body, native_before: { ...body.native_before, [key]: value } }));
  }
  assert.equal(calls.length, 1);
});

test('credential, route overrides and broad approval values never reach tools', async () => {
  const { adapter, calls } = fixture();
  for (const [path, body] of [
    ['/workspaces', { path: 'D:\\synthetic', api_key: 'fixture-only-key' }],
    ['/sessions/session_fixture/turn', { text: 'Task', route_id: 'stale' }],
    ['/sessions/session_fixture/cancel', { force: true }],
    ['/approvals/approval_fixture', { session_id: 'session_fixture', decision: 'always' }],
  ]) await assert.rejects(workspaceRequest(adapter, 'POST', path, query, body));
  assert.equal(calls.length, 0);
});

test('invalid event cursor and identity fail without dispatch', async () => {
  const { adapter, calls } = fixture();
  await assert.rejects(workspaceRequest(adapter, 'GET', '/sessions/session_fixture/events', new URLSearchParams('after_seq=-2'), {}));
  await assert.rejects(workspaceRequest(adapter, 'POST', '/approvals/approval_fixture', query, { session_id: '../other', decision: 'allow' }));
  assert.equal(calls.length, 0);
});

test('first event poll accepts the minus-one sentinel and includes event zero', async () => {
  const { adapter, calls } = fixture();
  await workspaceRequest(adapter, 'GET', '/sessions/session_fixture/events', new URLSearchParams('after_seq=-1'), {});
  assert.deepEqual(calls[0], ['events', 'session_fixture', { after_seq: -1 }]);
});

test('adapter cancellation and stale errors propagate as failures', async () => {
  const { adapter } = fixture();
  adapter.approve = async () => { throw Object.assign(new Error('Stale'), { code: 'STALE_APPROVAL', status: 409 }); };
  await assert.rejects(workspaceRequest(adapter, 'POST', '/approvals/approval_fixture', query, { session_id: 'session_fixture', decision: 'allow' }), { code: 'STALE_APPROVAL' });
  assert.equal(await workspaceRequest(adapter, 'GET', '/health', query, {}), null);
});

test('image previews pass exact session and attachment identity as binary without another tool call', async () => {
  const { adapter, calls } = fixture();
  adapter.readAttachment = async (sessionId, attachmentId) => {
    calls.push(['readAttachment', sessionId, attachmentId]);
    return { data: new Uint8Array([137, 80, 78, 71]), media_type: 'image/png' };
  };
  const result = await workspaceRequest(adapter, 'GET', '/sessions/session_fixture/attachments/attachment_fixture', query, {});
  assert.equal(result.media_type, 'image/png');
  assert.deepEqual(Array.from(result.binary), [137, 80, 78, 71]);
  assert.deepEqual(calls, [['readAttachment', 'session_fixture', 'attachment_fixture']]);
  adapter.readAttachment = async () => ({ data: new Uint8Array([1]), media_type: 'text/html' });
  await assert.rejects(workspaceRequest(adapter, 'GET', '/sessions/session_fixture/attachments/attachment_fixture', query, {}));
});

test('access level routes validate values and turns carry an optional access level', async () => {
  const calls = [];
  const adapter = { access: () => ({ default_access: 'workspace', levels: ['workspace', 'full'] }),
    setAccess: async input => { calls.push(['set', input]); return { default_access: input.default_access }; },
    turn: async (...args) => { calls.push(['turn', ...args]); return { status: 'running' }; } };
  assert.equal((await workspaceRequest(adapter, 'GET', '/workspace-access', new URLSearchParams(), undefined)).value.default_access, 'workspace');
  assert.equal((await workspaceRequest(adapter, 'POST', '/workspace-access', new URLSearchParams(), { default_access: 'full' })).value.default_access, 'full');
  await assert.rejects(workspaceRequest(adapter, 'POST', '/workspace-access', new URLSearchParams(), { default_access: 'full', extra: 1 }));
  await workspaceRequest(adapter, 'POST', '/sessions/s1/turn', new URLSearchParams(), { text: 'Find my notes', access_level: 'full' });
  assert.deepEqual(calls.at(-1).slice(0, 3), ['turn', 's1', { text: 'Find my notes', access_level: 'full' }]);
  await assert.rejects(workspaceRequest(adapter, 'POST', '/sessions/s1/turn', new URLSearchParams(), { text: 'x', access_level: 'root' }), /Invalid access level/);
});
