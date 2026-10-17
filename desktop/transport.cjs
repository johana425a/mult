'use strict';

// DeepSteam follows the upstream Harness desktop pattern: application origins
// are separate from the private, loopback-only HTTP services they represent.
const SERVICES = Object.freeze({ app: 3792, portal: 3791, classroom: 3793, gateway: 3794 });
const SCHEME = 'deepsteam';
const PRIVILEGES = Object.freeze({ standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true, codeCache: true });
const HOP_HEADERS = ['connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'];
const http = require('node:http');
const { Readable } = require('node:stream');
const { pipeline } = require('node:stream/promises');
const zlib = require('node:zlib');

// The bundled global fetch can throw an uncaught Undici parser assertion when
// a slow consumer meets a closing socket. Use Node's HTTP stream for our fixed
// loopback services only; retain streaming, backpressure and explicit redirects.
async function loopbackFetch(value, init = {}) {
  const target = new URL(value instanceof Request ? value.url : value);
  if (target.protocol !== 'http:' || target.hostname !== '127.0.0.1' ||
      ![...Object.values(SERVICES), 8011].includes(Number(target.port)) || target.username || target.password)
    throw new TypeError('Invalid internal service');
  const request = new Request(value, init);
  request.signal.throwIfAborted();
  const headers = new Headers(request.headers);
  headers.delete('host'); headers.delete('connection'); headers.delete('content-length');
  headers.set('accept-encoding', 'identity');
  return new Promise((resolve, reject) => {
    let responseStream;
    const outgoing = http.request(target, { method: request.method, headers: Object.fromEntries(headers), agent: false });
    const abort = () => {
      const reason = request.signal.reason instanceof Error ? request.signal.reason : new DOMException('Aborted', 'AbortError');
      responseStream?.destroy(reason); outgoing.destroy(reason);
    };
    request.signal.addEventListener('abort', abort, { once: true });
    outgoing.on('close', () => { if (!responseStream) request.signal.removeEventListener('abort', abort); });
    outgoing.on('error', error => { responseStream?.destroy(error); reject(error); });
    outgoing.on('response', incoming => {
      const status = incoming.statusCode;
      const responseHeaders = new Headers();
      for (let i = 0; i < incoming.rawHeaders.length; i += 2) responseHeaders.append(incoming.rawHeaders[i], incoming.rawHeaders[i + 1]);
      if ([301, 302, 303, 307, 308].includes(status) && request.redirect !== 'manual') {
        incoming.resume(); reject(new TypeError('Internal redirects require manual handling')); return;
      }
      const empty = request.method === 'HEAD' || [204, 205, 304].includes(status);
      if (empty) { incoming.on('error', reject); incoming.resume(); resolve(new Response(null, { status, headers: responseHeaders })); return; }
      responseStream = incoming;
      const encoding = responseHeaders.get('content-encoding')?.trim().toLowerCase();
      const decoder = encoding === 'gzip' ? zlib.createGunzip() : encoding === 'deflate' ? zlib.createInflate() : encoding === 'br' ? zlib.createBrotliDecompress() : null;
      if (decoder) {
        responseStream = decoder;
        void pipeline(incoming, decoder).catch(error => decoder.destroy(error));
        decoder.on('close', () => { if (!incoming.complete) incoming.destroy(); });
        responseHeaders.delete('content-encoding'); responseHeaders.delete('content-length');
      }
      responseStream.on('close', () => request.signal.removeEventListener('abort', abort));
      const body = Readable.toWeb(responseStream, { strategy: { highWaterMark: 65536, size: chunk => chunk.byteLength } });
      try { resolve(new Response(body, { status, statusText: incoming.statusMessage || '', headers: responseHeaders })); }
      catch (error) { responseStream.destroy(); reject(error); }
    });
    if (request.body) void pipeline(Readable.fromWeb(request.body), outgoing).catch(error => { outgoing.destroy(error); reject(error); });
    else outgoing.end();
    if (request.signal.aborted) abort();
  });
}

function applicationUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== `${SCHEME}:` || !Object.hasOwn(SERVICES, url.hostname) || url.port || url.username || url.password || url.pathname.startsWith('//') || url.pathname.includes('\\')) return null;
    return url;
  } catch { return null; }
}
function applicationOrigin(value) {
  const url = applicationUrl(value);
  return url ? `${SCHEME}://${url.hostname}` : null;
}
function serviceUrl(value) {
  const url = applicationUrl(value);
  if (!url) return null;
  const target = new URL(`http://127.0.0.1:${SERVICES[url.hostname]}/`);
  // Assign path fields, never resolve renderer-provided text as an authority.
  target.pathname = url.pathname || '/';
  target.search = url.search;
  return target;
}
function publicUrl(value, base) {
  try {
    const url = new URL(value, base);
    if (applicationUrl(url.href)) return url.href;
    if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) || url.username || url.password) return null;
    const service = Object.keys(SERVICES).find(name => String(SERVICES[name]) === url.port);
    const logical = service ? `${SCHEME}://${service}${url.pathname || '/'}${url.search}${url.hash}` : null;
    return logical && applicationUrl(logical) ? logical : null;
  } catch { return null; }
}
function internalOrigin(value) {
  const appOrigin = applicationOrigin(value);
  return appOrigin ? serviceUrl(`${appOrigin}/`).origin : null;
}
function rewritePolicy(value) {
  // Header grammar has whitespace/semicolon-separated sources. Exact origins
  // only: never rewrite an external hostname merely containing a local string.
  return value.replace(/http:\/\/(?:127\.0\.0\.1|localhost):(3791|3792|3793|3794)(?=[\s;'"/]|$)/g,
    (_match, port) => `${SCHEME}://${Object.keys(SERVICES).find(name => String(SERVICES[name]) === port)}`);
}

function cookieOptions(value, target) {
  const parts = value.split(';');
  const first = parts.shift();
  const index = first.indexOf('=');
  if (index <= 0) return null;
  const name = first.slice(0, index).trim();
  const cookieValue = first.slice(index + 1).trim();
  if (!/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(name) || /[\r\n]/.test(cookieValue)) return null;
  const options = { url: target.href, name, value: cookieValue, path: target.pathname.slice(0, target.pathname.lastIndexOf('/')) || '/' };
  let maxAge;
  for (const part of parts) {
    const split = part.indexOf('=');
    const key = (split < 0 ? part : part.slice(0, split)).trim().toLowerCase();
    const setting = split < 0 ? '' : part.slice(split + 1).trim();
    if (key === 'domain') {
      if (setting.replace(/^\./, '').toLowerCase() !== target.hostname) return null;
      // Host-only is sufficient and prevents moving a cookie to another realm.
    } else if (key === 'path' && setting.startsWith('/')) options.path = setting;
    else if (key === 'secure') options.secure = true;
    else if (key === 'httponly') options.httpOnly = true;
    else if (key === 'samesite') options.sameSite = ({ strict: 'strict', lax: 'lax', none: 'no_restriction' })[setting.toLowerCase()] || 'unspecified';
    else if (key === 'max-age' && /^-?\d+$/.test(setting)) maxAge = Number(setting);
    else if (key === 'expires' && Number.isFinite(Date.parse(setting))) options.expirationDate = Date.parse(setting) / 1000;
  }
  if (Number.isFinite(maxAge)) options.expirationDate = Math.max(0, Date.now() / 1000 + maxAge);
  return options;
}

function sessionFetcher(ownedSession, networkFetch = loopbackFetch) {
  // The local transport supports manual redirects and streaming cancellation. Only the
  // product-owned Chromium cookie jar supplies cookies; no renderer can inject
  // a Cookie header or obtain authentication values through this API.
  return async (value, init) => {
    const target = new URL(value);
    if (target.protocol !== 'http:' || target.hostname !== '127.0.0.1' || !Object.values(SERVICES).some(port => String(port) === target.port) || target.username || target.password) throw new Error('Invalid internal service');
    const headers = new Headers(init.headers);
    headers.delete('cookie');
    const cookies = await ownedSession.cookies.get({ url: target.href });
    if (cookies.length) headers.set('cookie', cookies.map(cookie => `${cookie.name}=${cookie.value}`).join('; '));
    const response = await networkFetch(target.href, { ...init, headers });
    for (const value of response.headers.getSetCookie?.() || []) {
      const options = cookieOptions(value, target);
      // Match browser cookie handling: a rejected cookie does not replace an
      // otherwise valid HTTP response. The next authenticated request still
      // determines whether a login is actually usable.
      if (options) { try { await ownedSession.cookies.set(options); } catch {} }
    }
    return response;
  };
}

async function verifyRetainedCookies({ session: ownedSession, from, cookies }) {
  const target = new URL(from);
  if (target.protocol !== 'http:' || target.hostname !== '127.0.0.1' || !Object.values(SERVICES).some(port => String(port) === target.port)) throw new Error('MIGRATION_COOKIE_BRIDGE_FAILED');
  const retained = await ownedSession.cookies.get({ domain: target.hostname });
  const identity = cookie => JSON.stringify(['name', 'value', 'domain', 'path', 'secure', 'httpOnly', 'sameSite', 'session', 'expirationDate'].map(key => cookie[key]));
  const present = new Set(retained.map(identity));
  if (!cookies.every(cookie => present.has(identity(cookie)))) throw new Error('MIGRATION_COOKIE_BRIDGE_FAILED');
  return cookies.length;
}

async function forwardRequest(request, fetcher = loopbackFetch) {
  const source = applicationUrl(request.url);
  const target = serviceUrl(request.url);
  if (!source || !target) return new Response(null, { status: 404 });
  const headers = new Headers(request.headers);
  const origin = headers.get('origin');
  const referrer = headers.get('referer');
  // External documents must not acquire local service authority through this
  // scheme. Main-frame navigations without Origin/Referer are handled by the
  // desktop's strict navigation policy.
  if (origin !== null && (!applicationOrigin(origin) || origin !== applicationOrigin(origin))) return new Response(null, { status: 403 });
  if (referrer && !applicationUrl(referrer)) return new Response(null, { status: 403 });
  for (const name of [...HOP_HEADERS, 'host', 'content-length', 'cookie']) headers.delete(name);
  if (origin) headers.set('origin', internalOrigin(origin));
  if (referrer) headers.set('referer', serviceUrl(referrer).href);
  headers.set('sec-fetch-site', origin && applicationOrigin(origin) !== applicationOrigin(source.href) ? 'same-site' : 'same-origin');
  const init = { method: request.method, headers, redirect: 'manual', signal: request.signal };
  if (!['GET', 'HEAD'].includes(request.method)) { init.body = request.body; init.duplex = 'half'; }
  let response;
  try { response = await fetcher(target.href, init); }
  catch (error) {
    if (request.signal?.aborted) throw error;
    return new Response('DeepSteam service is unavailable. Please retry from the desktop.', { status: 503, headers: { 'content-type': 'text/plain; charset=utf-8' } });
  }
  const outgoing = new Headers(response.headers);
  for (const name of [...HOP_HEADERS, 'content-encoding', 'content-length']) outgoing.delete(name);
  const location = outgoing.get('location');
  if (location) {
    const translated = publicUrl(location, target.href);
    // A service cannot use an automatic redirect to proxy arbitrary external
    // destinations. Official login links are opened through the explicit IPC.
    if (!translated) { await response.body?.cancel(); return new Response(null, { status: 502 }); }
    outgoing.set('location', translated);
  }
  for (const name of ['content-security-policy', 'content-security-policy-report-only']) {
    const value = outgoing.get(name);
    if (value) outgoing.set(name, rewritePolicy(value));
  }
  const allowedOrigin = outgoing.get('access-control-allow-origin');
  if (allowedOrigin && origin && allowedOrigin === internalOrigin(origin)) outgoing.set('access-control-allow-origin', origin);
  // Native cookies are host-only. Restrict a legacy loopback Domain attribute
  // to the new owning application host; do not combine multiple cookies.
  // The session fetcher owns the original service cookie jar. Do not expose
  // service authentication as a second, possibly unsupported scheme cookie.
  outgoing.delete('set-cookie');
  return new Response(['HEAD'].includes(request.method) || [204, 205, 304].includes(response.status) ? null : response.body,
    { status: response.status, statusText: response.statusText, headers: outgoing });
}

function socketUrl(value) {
  if (typeof value !== 'string' || value.length > 16384 || !value.startsWith('/') || value.startsWith('//') || /[\\\r\n#]/.test(value)) return null;
  try {
    const parsed = new URL(value, 'http://127.0.0.1:3792');
    if (!/^\/(?:api\/)?ws(?:\/|$)/.test(parsed.pathname)) return null;
    return `ws://127.0.0.1:3792${parsed.pathname}${parsed.search}`;
  } catch { return null; }
}

function allowApplicationRequest(details, ownedContents, migrationContents = new Set(), migrationPath = '/__deepsteam_storage_migration__') {
  try {
    const target = applicationUrl(details.url);
    if (!target) return false;
    if (migrationContents.has(details.webContentsId)) return details.method === 'GET' && details.resourceType === 'mainFrame' && target.pathname === migrationPath && !target.search;
    if (!ownedContents || ownedContents.isDestroyed() || details.webContentsId !== ownedContents.id) return false;
    const initiator = details.initiatorOrigin;
    if (initiator !== undefined && initiator !== '') return applicationOrigin(initiator) === initiator;
    // Shell-initiated navigation has no initiator. Fetches from an opaque or
    // external frame cannot obtain application authority by dropping Referer.
    return details.resourceType === 'mainFrame' && (!details.frame || details.frame === ownedContents.mainFrame);
  } catch { return false; }
}

function applicationHeaders(details, ownedContents, migrationContents = new Set(), migrationPath = '/__deepsteam_storage_migration__') {
  if (!allowApplicationRequest(details, ownedContents, migrationContents, migrationPath)) return { cancel: true };
  const headers = Object.fromEntries(Object.entries(details.requestHeaders).map(([name, value]) => [name.toLowerCase(), value]));
  // Chromium omits Origin from custom-scheme requests. Only the browser's
  // verified initiator may supply the missing origin; renderer headers cannot
  // choose a different application realm. Main-frame boot uses its fixed target.
  const origin = applicationOrigin(details.initiatorOrigin) || (details.resourceType === 'mainFrame' ? applicationOrigin(details.url) : null);
  if (!origin) return { cancel: true };
  headers.origin = origin;
  return { requestHeaders: headers };
}

function websocketHeaders(details, ownedContents) {
  try {
    const target = new URL(details.url);
    const headers = Object.fromEntries(Object.entries(details.requestHeaders).map(([name, value]) => [name.toLowerCase(), value]));
    const owner = ownedContents;
    if (!owner || owner.isDestroyed() || details.webContentsId !== owner.id || applicationOrigin(owner.getURL()) !== 'deepsteam://app'
      || target.protocol !== 'ws:' || target.hostname !== '127.0.0.1' || target.port !== '3792' || target.username || target.password
      || !/^\/(?:api\/)?ws(?:\/|$)/.test(target.pathname) || headers.origin !== 'deepsteam://app') return { cancel: true };
    // Electron supplies the initiating WebFrameMain; require it when supplied.
    if (details.frame !== owner.mainFrame) return { cancel: true };
    return { requestHeaders: { ...headers, origin: 'http://127.0.0.1:3792', 'sec-fetch-site': 'same-origin' } };
  } catch { return { cancel: true }; }
}

module.exports = { SCHEME, SERVICES, PRIVILEGES, applicationUrl, applicationOrigin, serviceUrl, publicUrl, forwardRequest, socketUrl, websocketHeaders, sessionFetcher, verifyRetainedCookies, allowApplicationRequest, applicationHeaders, loopbackFetch };
