/** Durable display/archive overlays. Never deletes an official workspace or session. */
import { readFile, writeFile, rename, mkdir } from 'node:fs/promises';
import { join, normalize } from 'node:path';
import { randomUUID } from 'node:crypto';

export const managementError = (code, status = 409) => Object.assign(new Error(code), { code, status });
const identity = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value);
const clone = value => structuredClone(value);
const pathKey = value => process.platform === 'win32' ? normalize(value).toLowerCase() : normalize(value);
export const validNativeSnapshot = row => row !== null && typeof row === 'object' && !Array.isArray(row)
  && Object.keys(row).length === 5 && ['workspace_id', 'name', 'archived', 'path', 'kind'].every(key => Object.hasOwn(row, key))
  && identity(row.workspace_id) && typeof row.name === 'string' && row.name.trim().length > 0 && row.name.length <= 100 && !/[\0\r\n]/.test(row.name)
  && typeof row.archived === 'boolean' && typeof row.path === 'string' && row.path.length > 0 && row.path.length <= 4000 && !/[\0\r\n]/.test(row.path)
  && ['workspace', 'general', 'system'].includes(row.kind);
export const sameNativeSnapshot = (row, expected) => Boolean(row && expected
  && row.workspace_id === expected.workspace_id && row.name === expected.name && row.archived === expected.archived
  && row.kind === expected.kind && pathKey(row.path) === pathKey(expected.path));

export async function createWorkspaceManagement(profile) {
  const path = join(profile, 'workspace-management.json');
  let state = { schema: 1, workspaces: {}, reservations: {} };
  try {
    const parsed = JSON.parse(await readFile(path, 'utf8'));
    if (parsed.schema !== 1 || !parsed.workspaces || !parsed.reservations
        || Array.isArray(parsed.workspaces) || Array.isArray(parsed.reservations)) throw managementError('workspace_management_corrupt');
    for (const [id, row] of Object.entries(parsed.workspaces)) {
      if (!identity(id) || typeof row !== 'object' || typeof row.archived !== 'boolean'
          || (row.name !== undefined && (typeof row.name !== 'string' || !row.name.trim() || row.name.length > 200))) {
        throw managementError('workspace_management_corrupt');
      }
    }
    for (const [id, row] of Object.entries(parsed.reservations)) {
      if (!identity(id) || !identity(row.transaction_id) || !row.patch || !row.before) throw managementError('workspace_management_corrupt');
    }
    state = parsed;
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  let queue = Promise.resolve();
  async function mutate(change) {
    const run = queue.then(async () => {
      const next = clone(state); const result = change(next);
      await mkdir(profile, { recursive: true });
      const temporary = path + '.' + randomUUID() + '.tmp';
      await writeFile(temporary, JSON.stringify(next), { mode: 0o600 });
      await rename(temporary, path);
      state = next; return result;
    });
    queue = run.catch(() => {}); return run;
  }
  return {
    view(id) { return clone(state.workspaces[id] ?? { archived: false }); },
    reservation(id) { return clone(state.reservations[id] ?? null); },
    async prepare(id, patch, nativeBefore = null) {
      if (!identity(id)) throw managementError('workspace_unknown', 404);
      return mutate(next => {
        if (next.reservations[id]) throw managementError('workspace_recovery_required');
        const before = clone(next.workspaces[id] ?? { archived: false });
        const reservation = { transaction_id: randomUUID(), before, patch: clone(patch), native_before: clone(nativeBefore), created_at: Date.now() };
        next.reservations[id] = reservation;
        return clone(reservation);
      });
    },
    async commit(id, transactionId) {
      return mutate(next => {
        if (!next.reservations[id]) {
          if (next.workspaces[id]?.last_transaction_id === transactionId) return clone(next.workspaces[id]);
          throw managementError('workspace_management_stale');
        }
        const reservation = next.reservations[id];
        if (reservation.transaction_id !== transactionId) throw managementError('workspace_management_stale');
        const row = { ...reservation.before, ...reservation.patch, last_transaction_id: transactionId, updated_at: Date.now() };
        next.workspaces[id] = row; delete next.reservations[id]; return clone(row);
      });
    },
    async abort(id, transactionId) {
      return mutate(next => {
        if (!next.reservations[id]) {
          if (next.workspaces[id]?.last_transaction_id === transactionId) throw managementError('workspace_management_committed');
          return { aborted: true };
        }
        if (next.reservations[id].transaction_id !== transactionId) throw managementError('workspace_management_stale');
        delete next.reservations[id]; return { aborted: true };
      });
    },
  };
}
