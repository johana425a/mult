'use strict';

// Existing local links are upgraded before navigation; desktop documents use
// named application origins, never network addresses.
const { publicUrl } = require('./transport.cjs');
const DEEPSEEK_HOSTS = new Set(['chat.deepseek.com', 'platform.deepseek.com', 'api.deepseek.com', 'api-docs.deepseek.com', 'accounts.deepseek.com']);
function canonicalLocalPage(value) {
  return publicUrl(value);
}
function isLocalPage(value) { return canonicalLocalPage(value) !== null; }
function isOfficialLink(value) {
  try {
    const url = new URL(value);
    const official = DEEPSEEK_HOSTS.has(url.hostname) || (url.hostname === 'auth.openai.com' && url.pathname === '/oauth/authorize');
    return url.protocol === 'https:' && official && !url.username && !url.password && (!url.port || url.port === '443');
  } catch { return false; }
}
// Ordinary UI links open in the system browser, which owns authentication and
// browsing. This policy is intentionally not exposed through Harness tool IPC.
function isExternalPage(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password; }
  catch { return false; }
}
module.exports = { isLocalPage, canonicalLocalPage, isOfficialLink, isExternalPage };
