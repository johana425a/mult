/** Authenticated Host routes, reached only behind the desktop application gateway. */
const fail = (code, status = 422) => { throw Object.assign(new Error(code), { code, status }); };
const id = value => /^[A-Za-z0-9_-]{1,100}$/.test(value ?? '') ? value : fail('INVALID_IDENTITY', 400);
const integer = value => /^\d{1,10}$/.test(value) && Number(value) <= 1000000000 ? Number(value) : fail('INVALID_CURSOR', 400);
const fields = (body, allowed) => {
  if (!body || Array.isArray(body) || typeof body !== 'object' || Object.keys(body).some(key => !allowed.includes(key))) fail('INVALID_FIELDS', 400);
};
export async function interactionRequest(surface, method, path, query, body, signal) {
  let match = /^\/sessions\/([^/]+)\/capabilities-state$/.exec(path);
  if (match && method === 'GET') return { value: await surface.state(id(match[1])) };
  match = /^\/sessions\/([^/]+)\/questions\/([^/]+)$/.exec(path);
  if (match && method === 'POST') {
    fields(body, ['answers', 'cancel']);
    if (body.cancel !== undefined && body.cancel !== true || body.cancel === true && body.answers !== undefined) fail('QUESTION_ANSWER_INVALID');
    return { value: await surface.answer(id(match[1]), id(match[2]), body) };
  }
  match = /^\/sessions\/([^/]+)\/plan$/.exec(path);
  if (match && method === 'POST') {
    fields(body, ['active']);
    if (typeof body.active !== 'boolean') fail('PLAN_MODE_INVALID');
    return { value: await surface.plan(id(match[1]), body.active) };
  }
  match = /^\/sessions\/([^/]+)\/changes\/(\d+)\/diff\/(\d+)$/.exec(path);
  if (match && method === 'GET') return { value: await surface.diff(id(match[1]), integer(match[2]), integer(match[3]), signal) };
  match = /^\/sessions\/([^/]+)\/deliverables\/(\d+)\/files\/(\d+)$/.exec(path);
  if (match && method === 'GET') {
    const mode = query.get('mode') ?? 'preview';
    if (!['preview', 'download'].includes(mode)) fail('DELIVERABLE_MODE_INVALID');
    return await surface.deliveredFile(id(match[1]), integer(match[2]), integer(match[3]), mode, signal);
  }
  return null;
}
