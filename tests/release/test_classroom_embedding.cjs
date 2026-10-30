const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '../..');
const dependency = process.env.DEEPSTEAM_GENERATION_DEPENDENCIES || path.join(root, 'upstream/OpenMAIC/packages/@openmaic/generation');
const ts = createRequire(path.join(dependency, 'package.json'))('typescript');
const code = ts.transpileModule(fs.readFileSync(path.join(root, 'upstream/OpenMAIC/next.config.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

async function headers(env) {
  const sandbox = { exports: {}, process: { env } };
  vm.runInNewContext(code, sandbox);
  return Object.fromEntries((await sandbox.exports.default.headers())[0].headers.map(h => [h.key, h.value]));
}

(async () => {
  const publicHeaders = await headers({});
  assert.equal(publicHeaders['Content-Security-Policy'], "frame-ancestors 'self'");
  assert.equal(publicHeaders['X-Frame-Options'], 'SAMEORIGIN');
  const standalone = await headers({ DEEPSTEAM_HARNESS_CORE: '1' });
  for (const port of [3791, 3792]) {
    assert.ok(standalone['Content-Security-Policy'].includes(`http://127.0.0.1:${port}`));
    assert.ok(standalone['Content-Security-Policy'].includes(`http://localhost:${port}`));
  }
  assert.equal(standalone['X-Frame-Options'], undefined);
  assert.ok(!standalone['Content-Security-Policy'].includes('*'));
  const configured = await headers({ DEEPSTEAM_HARNESS_CORE: '1', ALLOWED_FRAME_ANCESTORS: 'https://school.example' });
  assert.equal(configured['Content-Security-Policy'], "frame-ancestors 'self' https://school.example");
  assert.equal(configured['X-Frame-Options'], undefined);
  console.log('Classroom embedding policy passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
