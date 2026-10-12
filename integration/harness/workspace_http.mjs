/** HTTP shapes for the owned workspace adapter; no browser credential fields. */
import { validNativeSnapshot } from './workspace_management.mjs';
const id = value => {
  if (!/^[A-Za-z0-9_-]{1,100}$/.test(value ?? '')) throw Object.assign(new Error('Invalid identity'), { code: 'INVALID_IDENTITY', status: 400 });
  return value;
};
const fields = (body, names) => {
  if (!body || Array.isArray(body) || typeof body !== 'object' || Object.keys(body).some(key => !names.includes(key))) {
    throw Object.assign(new Error('Invalid fields'), { code: 'INVALID_FIELDS', status: 400 });
  }
};

export async function workspaceRequest(adapter, method, path, query, body, signal) {
  if (path === '/workspace-dependencies' && method === 'GET') return { value: await adapter.dependencies(signal) };
  const documentMatch = /^\/workspaces\/([^/]+)\/documents\/(read|asset|list|search|status|cancel|inventory|coverage)$/.exec(path);
  if (documentMatch && method === 'POST') {
    const action = documentMatch[2];
    fields(body, ['list', 'search'].includes(action) ? ['path', 'depth', 'limit', 'query'] : ['path', 'cursor', 'start_unit', 'ocr', 'max_chars', 'max_units', 'asset_id', 'document_sha256', 'max_dimension', 'engine', 'job_id', 'tier', 'coverage_cursor', 'limit', 'refresh']);
    if (body.path !== undefined && (typeof body.path !== 'string' || body.path.length > 2048)) throw Object.assign(new Error('Invalid document path'), { code: 'document_path_invalid', status: 422 });
    if (['read', 'asset'].includes(action) && !body.path) throw Object.assign(new Error('Missing document path'), { code: 'document_path_invalid', status: 422 });
    return { value: await adapter.documents(id(documentMatch[1]), action, body, signal) };
  }
  if (path === '/workspaces' && method === 'GET') return { value: await adapter.list() };
  if (path === '/workspaces' && method === 'POST') {
    fields(body, ['path', 'name']);
    if (typeof body.path !== 'string' || !body.path || body.path.length > 4000 || /[\0\r\n]/.test(body.path)
      || (body.name !== undefined && (typeof body.name !== 'string' || body.name.length > 200))) {
      throw Object.assign(new Error('Invalid workspace'), { code: 'INVALID_WORKSPACE', status: 400 });
    }
    return { value: await adapter.register(body) };
  }
  let match = /^\/workspaces\/([^/]+)\/management$/.exec(path);
  if (match && method === 'GET') return { value: await adapter.managementStatus(id(match[1])) };
  match = /^\/workspaces\/([^/]+)\/manage$/.exec(path);
  if (match && method === 'POST') {
    fields(body, ['phase', 'transaction_id', 'name', 'archived', 'native_workspace_id', 'native_before']);
    if (!['prepare', 'commit', 'abort'].includes(body.phase)
        || (body.name !== undefined && (typeof body.name !== 'string' || !body.name.trim() || body.name.length > 100 || /[\0\r\n]/.test(body.name)))
        || (body.archived !== undefined && typeof body.archived !== 'boolean')
        || (body.native_workspace_id !== undefined && !/^[A-Za-z0-9_-]{1,100}$/.test(body.native_workspace_id))) {
      throw Object.assign(new Error('Invalid management request'), { code: 'workspace_management_invalid', status: 422 });
    }
    if (body.phase === 'prepare') {
      if (body.name === undefined && body.archived === undefined) throw Object.assign(new Error('Empty management request'), { code: 'workspace_management_invalid', status: 422 });
      if (body.transaction_id !== undefined || (body.native_before != null && !validNativeSnapshot(body.native_before))
          || (body.native_workspace_id !== undefined && body.native_before?.workspace_id !== body.native_workspace_id)
          || (body.native_before != null && body.native_workspace_id !== body.native_before.workspace_id)) {
        throw Object.assign(new Error('Invalid management snapshot'), { code: 'workspace_management_invalid', status: 422 });
      }
    } else {
      id(body.transaction_id);
      if (Object.keys(body).some(key => !['phase', 'transaction_id'].includes(key))) throw Object.assign(new Error('Invalid completion'), { code: 'workspace_management_invalid', status: 422 });
    }
    return { value: await adapter.manage(id(match[1]), body) };
  }
  match = /^\/workspaces\/([^/]+)\/sessions$/.exec(path);
  if (match && method === 'GET') return { value: await adapter.listSessions(id(match[1])) };
  if (match && method === 'POST') {
    fields(body, ['title']);
    if (body.title !== undefined && (typeof body.title !== 'string' || body.title.length > 200)) {
      throw Object.assign(new Error('Invalid session title'), { code: 'INVALID_SESSION', status: 400 });
    }
    return { value: await adapter.createSession({ workspace_id: id(match[1]), title: body.title }) };
  }
  match = /^\/sessions\/([^/]+)\/attachments\/([^/]+)$/.exec(path);
  if (match && method === 'GET') {
    const attachment = await adapter.readAttachment(id(match[1]), id(match[2]));
    if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(attachment.media_type)
      || !(attachment.data instanceof Uint8Array) || attachment.data.byteLength > 25 * 1024 * 1024) {
      throw Object.assign(new Error('Invalid attachment'), { code: 'INVALID_ATTACHMENT', status: 422 });
    }
    return { binary: attachment.data, media_type: attachment.media_type };
  }
  match = /^\/sessions\/([^/]+)\/events$/.exec(path);
  if (match && method === 'GET') {
    const cursor = query.get('after_seq') ?? '-1';
    if (!/^(?:-1|\d{1,10})$/.test(cursor) || Number(cursor) > 1000000000) throw Object.assign(new Error('Invalid cursor'), { code: 'INVALID_CURSOR', status: 400 });
    return { value: await adapter.events(id(match[1]), { after_seq: Number(cursor) }) };
  }
  match = /^\/sessions\/([^/]+)\/turn$/.exec(path);
  if (match && method === 'POST') {
    fields(body, ['text', 'llm_selection']);
    if (typeof body.text !== 'string' || !body.text.trim() || body.text.length > 24000) throw Object.assign(new Error('Invalid task'), { code: 'INVALID_TASK', status: 400 });
    const selection = body.llm_selection;
    if (selection !== undefined && selection !== null && (typeof selection !== 'object' || Array.isArray(selection)
      || Object.keys(selection).some(key => !['profile_id', 'model_id', 'reasoning_effort'].includes(key))
      || typeof selection.profile_id !== 'string' || !selection.profile_id || typeof selection.model_id !== 'string' || !selection.model_id
      || (selection.reasoning_effort !== undefined && typeof selection.reasoning_effort !== 'string'))) throw Object.assign(new Error('Invalid model selection'), { code: 'INVALID_MODEL_SELECTION', status: 400 });
    return { value: await adapter.turn(id(match[1]), { text: body.text, ...(selection !== undefined ? { llm_selection: selection } : {}) }, signal) };
  }
  match = /^\/sessions\/([^/]+)\/cancel$/.exec(path);
  if (match && method === 'POST') { fields(body, []); return { value: await adapter.cancel(id(match[1])) }; }
  match = /^\/approvals\/([^/]+)$/.exec(path);
  if (match && method === 'POST') {
    fields(body, ['session_id', 'decision']);
    if (!['allow', 'deny'].includes(body.decision)) throw Object.assign(new Error('Invalid decision'), { code: 'INVALID_APPROVAL', status: 400 });
    return { value: await adapter.approve({ approval_id: id(match[1]), session_id: id(body.session_id), decision: body.decision }) };
  }
  return null;
}
