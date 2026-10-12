'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { applicationOrigin, serviceUrl, publicUrl, forwardRequest, socketUrl, websocketHeaders, sessionFetcher, verifyRetainedCookies, allowApplicationRequest, applicationHeaders } = require('./transport.cjs');

test('application destinations are fixed exact service authorities', () => {
  assert.equal(serviceUrl('deepsteam://app/chat?a=1').href, 'http://127.0.0.1:3792/chat?a=1');
  assert.equal(serviceUrl('deepsteam://classroom/lesson').port, '3793');
  for (const value of ['deepsteam://app:9999/', 'deepsteam://user@app/', 'deepsteam://app.evil.test/', 'deepsteam://app//example.org/x', 'deepsteam://portal//127.0.0.1:3796/api', 'deepsteam://classroom/\\example.org/x', 'http://127.0.0.1:3796/', 'file:///D:/secret']) assert.equal(serviceUrl(value), null);
  assert.equal(publicUrl('http://localhost:3791/open/learning'), 'deepsteam://portal/open/learning');
  assert.equal(publicUrl('/chat', 'http://127.0.0.1:3792/'), 'deepsteam://app/chat');
  assert.equal(applicationOrigin('deepsteam://app/connect'), 'deepsteam://app');
});

test('post upload body, range and application Origin/Referer reach only their exact service', async () => {
  const request = new Request('deepsteam://portal/api/materials', { method: 'POST', body: 'fixture upload', headers: { Origin: 'deepsteam://app', Referer: 'deepsteam://app/connect', Range: 'bytes=2-4' } });
  let called = false;
  const response = await forwardRequest(request, async (target, init) => {
    called = true;
    assert.equal(target, 'http://127.0.0.1:3791/api/materials');
    assert.equal(init.headers.get('origin'), 'http://127.0.0.1:3792');
    assert.equal(init.headers.get('referer'), 'http://127.0.0.1:3792/connect');
    assert.equal(init.headers.get('range'), 'bytes=2-4');
    assert.equal(await new Response(init.body).text(), 'fixture upload');
    assert.equal(init.signal, request.signal);
    assert.equal(init.redirect, 'manual');
    return new Response('nge', { status: 206, headers: { 'Content-Range': 'bytes 2-4/10', 'Content-Length': '3', 'access-control-allow-origin': 'http://127.0.0.1:3792', 'access-control-allow-credentials': 'true' } });
  });
  assert.equal(called, true); assert.equal(response.status, 206);
  assert.equal(response.headers.get('content-range'), 'bytes 2-4/10');
  assert.equal(response.headers.get('access-control-allow-origin'), 'deepsteam://app');
  assert.equal(response.headers.get('access-control-allow-credentials'), 'true');
  assert.equal(await response.text(), 'nge');
});

test('untrusted Origin and referrer never reach a service', async () => {
  for (const headers of [{ Origin: 'https://evil.test' }, { Origin: 'null' }, { Origin: 'deepsteam://app/extra' }, { Referer: 'https://evil.test/' }]) {
    const response = await forwardRequest(new Request('deepsteam://portal/api/test', { headers }), () => { throw new Error('must not run'); });
    assert.equal(response.status, 403);
  }
});

test('redirects and exact CSP origins become application links, external redirects rejected', async () => {
  const response = await forwardRequest(new Request('deepsteam://portal/'), async () => new Response(null, { status: 302, headers: { Location: 'http://127.0.0.1:3792/chat', 'Content-Security-Policy': "frame-ancestors 'self' http://127.0.0.1:3791 http://localhost:3792; img-src https://127.0.0.1.evil.test/" } }));
  assert.equal(response.headers.get('location'), 'deepsteam://app/chat');
  assert.equal(response.headers.get('content-security-policy'), "frame-ancestors 'self' deepsteam://portal deepsteam://app; img-src https://127.0.0.1.evil.test/");
  const rejected = await forwardRequest(new Request('deepsteam://portal/'), async () => new Response(null, { status: 302, headers: { Location: 'https://evil.test/' } }));
  assert.equal(rejected.status, 502);
});

test('stream response stays unbuffered and cancellation reaches its body', async () => {
  let emit; let cancelled = false;
  const stream = new ReadableStream({ start(controller) { emit = controller; }, cancel() { cancelled = true; } });
  const response = await forwardRequest(new Request('deepsteam://portal/events'), async () => new Response(stream, { headers: { 'content-type': 'text/event-stream' } }));
  const reader = response.body.getReader();
  emit.enqueue(new TextEncoder().encode('data: one\n\n'));
  assert.equal(new TextDecoder().decode((await reader.read()).value), 'data: one\n\n');
  await reader.cancel(); assert.equal(cancelled, true);
});

test('request abort remains an abort and service errors expose no internal endpoint', async () => {
  const controller = new AbortController(); controller.abort();
  const request = new Request('deepsteam://app/api/test', { signal: controller.signal });
  await assert.rejects(forwardRequest(request, async () => { throw new Error('private'); }));
  const response = await forwardRequest(new Request('deepsteam://app/api/test'), async () => { throw new Error('connect http://127.0.0.1:3792 secret'); });
  assert.equal(response.status, 503); assert.doesNotMatch(await response.text(), /127\.0\.0\.1|secret|3792/);
});

test('socket capability accepts scoped native socket paths only', () => {
  for (const pathname of ['/ws', '/ws/chat?dt_workspace=fixture', '/api/ws/test']) assert.ok(socketUrl(pathname)?.startsWith('ws://127.0.0.1:3792/'));
  for (const value of ['//evil.test/ws', 'https://evil.test/ws', '/api/keys', '/ws/../../api', '/ws/#secret', '/ws/\\evil', null]) assert.equal(socketUrl(value), null);
});

test('WebSocket bridge requires owned window, mainframe, origin and native route', () => {
  const mainFrame = { url: 'deepsteam://app/chat' };
  const owner = { id: 7, mainFrame, isDestroyed: () => false, getURL: () => 'deepsteam://app/chat' };
  const details = { url: 'ws://127.0.0.1:3792/ws?dt_workspace=fixture', webContentsId: 7, frame: mainFrame, requestHeaders: { Origin: 'deepsteam://app', Cookie: 'synthetic=fixture' } };
  assert.equal(websocketHeaders(details, owner).requestHeaders.origin, 'http://127.0.0.1:3792');
  for (const patch of [{ webContentsId: 8 }, { frame: {} }, { frame: undefined }, { requestHeaders: { Origin: 'deepsteam://classroom' } }, { url: 'ws://127.0.0.1:3796/ws' }, { url: 'wss://127.0.0.1:3792/ws' }]) assert.equal(websocketHeaders({ ...details, ...patch }, owner).cancel, true);
});

test('owned cookie jar overrides injected Cookie and retains each valid service Set-Cookie privately', async () => {
  const set = [];
  const session = { cookies: { get: async ({url}) => { assert.equal(url, 'http://127.0.0.1:3792/api/login'); return [{ name: 'owned', value: 'fixture' }]; }, set: async value => set.push(value) } };
  const call = sessionFetcher(session, async (_url, init) => {
    assert.equal(init.headers.get('cookie'), 'owned=fixture');
    const headers = new Headers();
    headers.append('set-cookie', 'session=one==; Path=/api; HttpOnly; SameSite=Strict');
    headers.append('set-cookie', 'pref=two; Domain=127.0.0.1; Max-Age=600');
    headers.append('set-cookie', 'foreign=blocked; Domain=evil.test');
    return new Response('fixture', { headers });
  });
  await call('http://127.0.0.1:3792/api/login', { method: 'GET', headers: { cookie: 'injected=wrong' } });
  assert.equal(set.length, 2);
  assert.equal(set[0].name, 'session'); assert.equal(set[0].value, 'one=='); assert.equal(set[0].path, '/api'); assert.equal(set[0].httpOnly, true); assert.equal(set[0].sameSite, 'strict');
  assert.equal(set[1].path, '/api'); assert.equal(set[1].domain, undefined); assert.ok(set[1].expirationDate > Date.now()/1000);
  for (const target of ['http://evil.test:3792/', 'http://127.0.0.1:3796/', 'https://127.0.0.1:3792/', 'http://user@127.0.0.1:3792/']) await assert.rejects(call(target, {headers:{}}));
});

test('migration cookie bridge verifies exact retained cookies including non-root paths', async () => {
  const cookie = { name: 'fixture', value: 'secret-fixture', domain:'127.0.0.1', path:'/api', httpOnly:true };
  const session = { cookies:{ get: async filter => { assert.deepEqual(filter, {domain:'127.0.0.1'});return[cookie]; } } };
  assert.equal(await verifyRetainedCookies({session,from:'http://127.0.0.1:3792',cookies:[cookie]}),1);
  await assert.rejects(verifyRetainedCookies({session,from:'http://127.0.0.1:3792',cookies:[{...cookie,value:'wrong'}]}));
});

test('desktop request authority is pinned to owned contents and trusted initiator, not missing headers', () => {
  const frame = {url:'deepsteam://app/chat'};
  const owner = {id:7,mainFrame:frame,isDestroyed:()=>false};
  const request = {url:'deepsteam://portal/api/test',method:'GET',webContentsId:7,frame,initiatorOrigin:'deepsteam://app',resourceType:'xhr'};
  assert.equal(allowApplicationRequest(request,owner),true);
  for (const patch of [{webContentsId:8},{initiatorOrigin:'null'},{initiatorOrigin:undefined},{initiatorOrigin:'https://evil.test'},{initiatorOrigin:'http://127.0.0.1:3792'}]) assert.equal(allowApplicationRequest({...request,...patch},owner),false);
  assert.equal(allowApplicationRequest({...request,initiatorOrigin:undefined,resourceType:'mainFrame'},owner),true);
  assert.equal(allowApplicationRequest({...request,webContentsId:9,initiatorOrigin:undefined,resourceType:'mainFrame',url:'deepsteam://app/__deepsteam_storage_migration__'},owner,new Set([9])),true);
  assert.equal(allowApplicationRequest({...request,webContentsId:9},owner,new Set([9])),false);
});

test('invalid browser cookie rejection does not replace valid HTTP status',async()=>{
  const call=sessionFetcher({cookies:{get:async()=>[],set:async()=>{throw new Error('fixture invalid cookie');}}},async()=>new Response('ok',{headers:{'set-cookie':'bad=value; SameSite=None'}}));
  assert.equal(await(await call('http://127.0.0.1:3792/api',{headers:{}})).text(),'ok');
});

test('missing custom-scheme Origin is supplied from trusted initiator and spoofed Origin is overwritten', () => {
  const owner={id:7,isDestroyed:()=>false};
  const details={url:'deepsteam://portal/api/harness/workspace-management/catalog',method:'GET',webContentsId:7,initiatorOrigin:'deepsteam://app',resourceType:'xhr',requestHeaders:{Origin:'deepsteam://classroom'}};
  assert.equal(applicationHeaders(details,owner).requestHeaders.origin,'deepsteam://app');
  assert.equal(applicationHeaders({...details,initiatorOrigin:'deepsteam://classroom',requestHeaders:{Origin:'deepsteam://app'}},owner).requestHeaders.origin,'deepsteam://classroom');
  assert.equal(applicationHeaders({...details,initiatorOrigin:'https://evil.test',requestHeaders:{Origin:'deepsteam://app'}},owner).cancel,true);
  assert.equal(applicationHeaders({...details,initiatorOrigin:undefined,requestHeaders:{Origin:'deepsteam://app'}},owner).cancel,true);
  assert.equal(applicationHeaders({...details,webContentsId:8},owner).cancel,true);
});
