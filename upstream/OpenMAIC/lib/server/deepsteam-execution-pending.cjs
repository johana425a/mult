'use strict';
// Coalesce only requests that are currently in flight. A later request always
// resolves the catalog again, so a changed model or login is never cached.
const pending = new Map();
function sharePendingExecution(options, create) {
  const key = JSON.stringify([process.env.DEEPSTEAM_HARNESS_TOKEN_FILE,
    process.env.DEEPSTEAM_STATE_ROOT, options]);
  if (pending.has(key)) return pending.get(key);
  const request = Promise.resolve().then(create);
  pending.set(key, request);
  const clear = () => { if (pending.get(key) === request) pending.delete(key); };
  request.then(clear, clear);
  return request;
}
module.exports = { sharePendingExecution };
