// Exercise the shipped stream forwarder with a real >210 MiB HTTP upload.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {Module, createRequire} = require('node:module');
const web = path.resolve(__dirname, '../../upstream/DeepTutor/web');
const req = createRequire(process.env.DEEPSTEAM_WEB_TEST_DEPENDENCIES || path.join(web, 'package.json'));
const ts = req('typescript');
const modules = new Map();
function load(filename) {
  if (filename.endsWith('.json')) return JSON.parse(fs.readFileSync(filename, 'utf8'));
  if (!fs.existsSync(filename)) filename += '.ts';
  if (modules.has(filename)) return modules.get(filename).exports;
  const mod = new Module(filename); modules.set(filename, mod); mod.filename = filename;
  mod.require = id => id.startsWith('.') ? load(path.resolve(path.dirname(filename), id))
    : id.startsWith('@/') ? load(path.join(web, id.slice(2))) : req(id);
  mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, esModuleInterop: true}
  }).outputText, filename);
  return mod.exports;
}
const {forwardBackendUpload} = load(path.join(web, 'lib/streaming-upload-proxy.ts'));
globalThis.AsyncLocalStorage = require('node:async_hooks').AsyncLocalStorage;
const {unstable_doesMiddlewareMatch} = req('next/experimental/testing/server');
const proxy = fs.readFileSync(path.join(web, 'proxy.ts'), 'utf8');
const matcher = JSON.parse(proxy.match(/matcher:\s*\[\s*("[^"]+")/)[1]);
const matches = url => unstable_doesMiddlewareMatch({config: {matcher: [matcher]}, url});
for (const suffix of ['', '/', '?dt_workspace=ws-fixture']) {
  assert.equal(matches('http://app.test/api/reading/materials' + suffix), false);
}
for (const suffix of ['/mid/page/1', '-extra']) {
  assert.equal(matches('http://app.test/api/reading/materials' + suffix), true);
}
const route = load(path.join(web, 'app/api/reading/materials/route.ts'));
assert.equal(route.runtime, 'nodejs');
assert.equal(typeof route.GET, 'function'); assert.equal(typeof route.POST, 'function');

(async () => {
  const chunk = new Uint8Array(64 * 1024).fill(73), count = 3408;
  const total = chunk.byteLength * count; assert.ok(total > 210 * 1024 * 1024);
  let produced = 0, received = 0, receivedHeaders, receivedUrl, firstReceivedAt;
  const server = http.createServer(async (request, response) => {
    receivedHeaders = request.headers; receivedUrl = request.url;
    for await (const data of request) {
      firstReceivedAt ??= produced; received += data.length;
      assert.equal(data[0], 73); assert.equal(data.at(-1), 73);
    }
    response.writeHead(200, {'content-type': 'application/json'});
    response.end(JSON.stringify({bytes: received}));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const request = new Request('http://frontend.test/api/reading/materials?dt_workspace=ws-fixture', {
      method: 'POST', duplex: 'half', headers: {
        'content-type': 'multipart/form-data; boundary=fixture', 'content-length': String(total),
        cookie: 'dt_token=fixture', host: 'frontend.test', 'x-forwarded-host': 'untrusted.test'
      }, body: new ReadableStream({pull(controller) {
        if (produced === count) controller.close(); else {produced++; controller.enqueue(chunk);}
      }})
    });
    const response = await forwardBackendUpload(request, {apiBaseUrl: 'http://127.0.0.1:' + server.address().port});
    assert.equal(response.status, 200); assert.deepEqual(await response.json(), {bytes: total});
    assert.ok(firstReceivedAt < count, 'Do not buffer the entire upload before sending');
    assert.equal(receivedUrl, '/api/reading/materials?dt_workspace=ws-fixture');
    assert.equal(receivedHeaders.cookie, 'dt_token=fixture');
    assert.equal(receivedHeaders['x-forwarded-host'], undefined);
    assert.equal(receivedHeaders['x-deeptutor-frontend-host'], 'frontend.test');
    const aborted = new AbortController(); aborted.abort();
    await assert.rejects(forwardBackendUpload(new Request('http://app.test/api/reading/materials', {signal: aborted.signal}),
      {apiBaseUrl: 'http://127.0.0.1:' + server.address().port}), {name: 'AbortError'});
    for (const status of [401, 413, 503]) {
      const denied = await forwardBackendUpload(new Request('http://app.test/api/reading/materials'), {
        fetchImpl: async () => Response.json({detail: 'fixture'}, {status})
      });
      assert.equal(denied.status, status); assert.deepEqual(await denied.json(), {detail: 'fixture'});
    }
    console.log(JSON.stringify({passed: true, bytes: received, streaming: true, cancelled: true, backendErrorsPreserved: true}));
    console.log('DEEPSTEAM_ASSERTIONS=26');
  } finally {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
