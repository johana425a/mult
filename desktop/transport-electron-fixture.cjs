'use strict';
// Real Chromium networking, synthetic data and isolated profile only.
const { app, BrowserWindow, protocol, session } = require('electron');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { SCHEME, PRIVILEGES, forwardRequest, websocketHeaders, sessionFetcher, allowApplicationRequest, applicationHeaders, applicationOrigin } = require('./transport.cjs');
const root = path.resolve(__dirname, '..');
const fixture = fs.mkdtempSync(path.join(root, 'runtime', 'temp', 'scheme-network-fixture-'));
for (const name of ['profile', 'session', 'cache', 'temp', 'logs', 'crash']) fs.mkdirSync(path.join(fixture, name));
app.setPath('userData', path.join(fixture, 'profile'));
app.setPath('sessionData', path.join(fixture, 'session'));
app.setPath('temp', path.join(fixture, 'temp'));
app.setPath('crashDumps', path.join(fixture, 'crash'));
app.setAppLogsPath(path.join(fixture, 'logs'));
app.commandLine.appendSwitch('disk-cache-dir', path.join(fixture, 'cache'));
protocol.registerSchemesAsPrivileged([{ scheme: SCHEME, privileges: PRIVILEGES }]);
let win;
const servers = [];
const sockets = new Set();
let abortedStreamClosed = false;
let wsOriginValid = false;
let wsCookieValid = false;
let requestOriginValid = false;
let responseCookieValid = false;
let rendererCookieValid = false;
let hostileRequestReached = false;
const diagnostics = {};

async function listen(port) {
  const server = http.createServer((req, res) => {
    const parsed = new URL(req.url, `http://127.0.0.1:${port}`);
    const origin = req.headers.origin;
    if (origin === 'http://127.0.0.1:3792') {
      res.setHeader('access-control-allow-origin', origin);
      res.setHeader('access-control-allow-credentials', 'true');
      res.setHeader('access-control-allow-methods', 'GET, POST, OPTIONS');
      res.setHeader('access-control-allow-headers', 'content-type, range');
    }
    if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }
    if (parsed.pathname === '/echo') {
      requestOriginValid = origin === 'http://127.0.0.1:3792';
      diagnostics.received_origin = origin || '(none)';
      rendererCookieValid = (req.headers.cookie || '').includes('fixture_auth=synthetic');
      let size = 0;
      req.on('data', chunk => { size += chunk.length; });
      req.on('end', () => { res.setHeader('set-cookie', 'fixture_next=synthetic-next; HttpOnly; Path=/; SameSite=Lax'); res.setHeader('content-type', 'application/json'); res.end(JSON.stringify({ size })); });
    } else if (parsed.pathname === '/catalog' || parsed.pathname === '/probe') {
      if (origin !== 'http://127.0.0.1:3792') { res.writeHead(403); res.end('required origin missing or wrong'); return; }
      res.end(req.method === 'GET' ? 'catalog' : 'probe');
    } else if (parsed.pathname === '/range') {
      res.writeHead(206, { 'content-type': 'application/octet-stream', 'content-range': 'bytes 2-4/10' }); res.end('234');
    } else if (parsed.pathname === '/sse') {
      res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
      res.write('data: first\n\n');
      const delay = setTimeout(() => res.end('data: second\n\n'), 500);
      res.on('close', () => clearTimeout(delay));
    } else if (parsed.pathname === '/cancel') {
      res.writeHead(200, { 'content-type': 'text/event-stream' }); res.write('data: ready\n\n');
      const interval = setInterval(() => res.write('data: tick\n\n'), 50);
      res.on('close', () => { abortedStreamClosed = true; clearInterval(interval); });
    } else if (parsed.pathname === '/status') { res.writeHead(422); res.end('fixture');
    } else if (parsed.pathname === '/logout') { res.setHeader('set-cookie', ['fixture_auth=; Path=/; Max-Age=0; HttpOnly', 'foreign_fixture=blocked; Domain=example.test', 'invalid_fixture=blocked; SameSite=None']); res.end('logged out');
    } else if (parsed.pathname === '/hostile-target') { hostileRequestReached = true; res.end('must not receive');
    } else if (parsed.pathname === '/download') { res.writeHead(200, { 'content-type': 'application/octet-stream', 'content-disposition': 'attachment; filename="fixture.txt"' }); res.end('synthetic download');
    } else if (parsed.pathname === '/redirect') { res.writeHead(302, { location: 'http://127.0.0.1:3792/redirected' }); res.end();
    } else if (parsed.pathname === '/redirected') { res.end('redirected');
    } else if (parsed.pathname === '/frame') {
      res.writeHead(200, { 'content-type': 'text/html', 'content-security-policy': "frame-ancestors http://127.0.0.1:3792" });
      res.end('<!doctype html><title>Synthetic classroom</title><script>fetch("deepsteam://portal/catalog").then(r=>parent.postMessage({fixtureFrame:true,classroomBlocked:r.status===403},"deepsteam://app")).catch(()=>parent.postMessage({fixtureFrame:true,classroomBlocked:true},"deepsteam://app"))</script>');
    } else {
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
      res.end('<!doctype html><html><head><title>DeepSteam isolated transport fixture</title></head><body>Fixture only</body></html>');
    }
  });
  server.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
  server.on('upgrade', (req, socket) => {
    wsOriginValid = req.headers.origin === 'http://127.0.0.1:3792';
    wsCookieValid = (req.headers.cookie || '').includes('fixture_auth=synthetic');
    const accept = crypto.createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    const message = Buffer.from('fixture-websocket');
    socket.write(Buffer.concat([Buffer.from([0x81, message.length]), message]));
    socket.on('data', data => { if ((data[0] & 0x0f) === 8) socket.end(Buffer.from([0x88, 0])); });
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  servers.push(server);
}

async function finish(report, code) {
  if (win && !win.isDestroyed()) win.destroy();
  for (const socket of sockets) socket.destroy();
  await Promise.all(servers.map(server => new Promise(resolve => server.close(resolve))));
  fs.writeFileSync(path.join(root, 'reports', 'desktop-scheme-network-fixture-20261012.json'), JSON.stringify({ ...report, fixture_profile_only: true, cloud_calls: 0, production_modified: false }, null, 2));
  app.exit(code);
}

app.whenReady().then(async () => {
  try {
    await Promise.all([3791, 3792, 3793].map(listen));
    const ownedFetch = sessionFetcher(session.defaultSession);
    session.defaultSession.webRequest.onBeforeRequest({ urls: ['deepsteam://*/*'] }, (details, callback) => callback({cancel:!allowApplicationRequest(details,win?.webContents)}));
    protocol.handle(SCHEME, request => forwardRequest(request, (target, init) => {
      if (target.endsWith('/echo')) { diagnostics.request_origin = request.headers.get('origin'); diagnostics.forward_origin = init.headers.get('origin'); }
      return ownedFetch(target, init);
    }));
    session.defaultSession.webRequest.onBeforeSendHeaders({ urls: ['deepsteam://*/*', 'ws://127.0.0.1/*'] }, async (details, callback) => {
      if (applicationOrigin(details.url)) { callback(applicationHeaders(details,win?.webContents)); return; }
      const result = websocketHeaders(details, win?.webContents);
      if (!result.cancel) result.requestHeaders.cookie = (await session.defaultSession.cookies.get({ url: details.url.replace(/^ws:/, 'http:') })).map(cookie => `${cookie.name}=${cookie.value}`).join('; ');
      callback(result);
    });
    await session.defaultSession.cookies.set({ url: 'http://127.0.0.1:3792', name: 'fixture_auth', value: 'synthetic', httpOnly: true, path: '/', sameSite: 'lax' });
    win = new BrowserWindow({ show: false, webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false } });
    await win.loadURL('deepsteam://app/');
    const checks = await win.webContents.executeJavaScript(`(async () => {
      const result = { document_origin: location.origin === 'deepsteam://app', document_url: location.href === 'deepsteam://app/' };
      const upload = await fetch('deepsteam://portal/echo', { method:'POST', credentials:'include', body: new Uint8Array(4096) });
      result.upload_and_cors = upload.ok && (await upload.json()).size === 4096;
      const catalog=await fetch('deepsteam://portal/catalog');result.required_origin_get=catalog.status===200&&await catalog.text()==='catalog';
      const probe=await fetch('deepsteam://portal/probe',{method:'POST',body:'synthetic fixture'});result.required_origin_post=probe.status===200&&await probe.text()==='probe';
      const range = await fetch('/range', {headers:{Range:'bytes=2-4'}});
      result.range = range.status === 206 && range.headers.get('content-range') === 'bytes 2-4/10' && await range.text() === '234';
      result.error_status = (await fetch('/status')).status === 422;
      const redirect = await fetch('deepsteam://portal/redirect');
      const redirectText = await redirect.text();
      result.redirect = redirect.url === 'deepsteam://app/redirected' && redirectText === 'redirected';
      result.redirect_observation = {status:redirect.status,url:redirect.url,body:redirectText};
      const stream = (await fetch('deepsteam://portal/sse')).body.getReader();
      result.sse_unbuffered = new TextDecoder().decode((await stream.read()).value) === 'data: first\\n\\n';
      await stream.cancel();
      const controller = new AbortController();
      const cancelled = await fetch('/cancel', {signal:controller.signal});
      await cancelled.body.getReader().read(); controller.abort();
      result.websocket = await new Promise((resolve) => { const ws = new WebSocket('ws://127.0.0.1:3792/ws?dt_workspace=fixture'); const timer=setTimeout(()=>{ ws.close(); resolve(false); },3000); ws.onmessage=event=>{clearTimeout(timer); ws.close();resolve(event.data==='fixture-websocket');}; ws.onerror=()=>{clearTimeout(timer);resolve(false);}; });
      result.iframe_and_csp = await new Promise(resolve => { const timer = setTimeout(()=>resolve(false),3000); const frame = document.createElement('iframe'); const receive=event=>{if(event.data?.fixtureFrame){clearTimeout(timer);removeEventListener('message',receive);result.classroom_not_promoted=event.data.classroomBlocked===true;resolve(event.origin==='deepsteam://classroom');}}; addEventListener('message',receive); frame.src='deepsteam://classroom/frame'; document.body.append(frame); });
      result.opaque_iframe_denied = await new Promise(resolve => { const timer=setTimeout(()=>resolve(false),3000); const receive=event=>{if(event.data?.hostileComplete){clearTimeout(timer);removeEventListener('message',receive);resolve(event.data.blocked===true);}};addEventListener('message',receive);const frame=document.createElement('iframe');frame.referrerPolicy='no-referrer';frame.src='data:text/html,'+encodeURIComponent('<script>fetch("deepsteam://portal/hostile-target",{credentials:"include",referrerPolicy:"no-referrer"}).then(()=>parent.postMessage({hostileComplete:true,blocked:false},"*")).catch(()=>parent.postMessage({hostileComplete:true,blocked:true},"*"))<'+ '/script>');document.body.append(frame); });
      return result;
    })()`);
    checks.download = await new Promise(async resolve => {
      const destination = path.join(fixture, 'synthetic-download.txt');
      const timeout = setTimeout(() => resolve(false), 3000);
      session.defaultSession.once('will-download', (_event, item) => {
        item.setSavePath(destination);
        item.once('done', (_done, state) => { clearTimeout(timeout); resolve(state === 'completed' && fs.readFileSync(destination, 'utf8') === 'synthetic download'); });
      });
      await win.webContents.executeJavaScript(`(() => { const link=document.createElement('a');link.href='deepsteam://portal/download';link.download='fixture.txt';document.body.append(link);link.click(); })()`);
    });
    await new Promise(resolve => setTimeout(resolve, 100));
    responseCookieValid = (await session.defaultSession.cookies.get({ url: 'http://127.0.0.1:3791' })).some(cookie => cookie.name === 'fixture_next');
    checks.logout_response_survives_invalid_cookie = await win.webContents.executeJavaScript(`fetch('/logout').then(async response=>response.status===200&&await response.text()==='logged out')`);
    checks.logout_cookie_removed = !(await session.defaultSession.cookies.get({url:'http://127.0.0.1:3792'})).some(cookie=>cookie.name==='fixture_auth');
    checks.foreign_cookie_denied = !(await session.defaultSession.cookies.get({})).some(cookie=>cookie.name==='foreign_fixture');
    diagnostics.redirect = checks.redirect_observation; delete checks.redirect_observation;
    const result = { ...checks, hostile_request_never_reached_service: !hostileRequestReached, request_origin_exact_owned_origin: requestOriginValid, request_owned_cookie_retained: rendererCookieValid, response_owned_cookie_retained: responseCookieValid, cancellation_reaches_server: abortedStreamClosed, websocket_origin_rewritten: wsOriginValid, websocket_owned_cookie_retained: wsCookieValid };
    await finish({ passed: Object.values(result).every(value => value === true), checks: result, diagnostics }, Object.values(result).every(value => value === true) ? 0 : 1);
  } catch (error) { await finish({ passed: false, error_code: error?.code || 'FIXTURE_FAILED', error_name: error?.name || 'Error' }, 1); }
});
app.on('window-all-closed', () => {});
