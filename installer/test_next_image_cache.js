// Validate the generated storage policy and the real installed Next cache.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');

async function main() {
  const root = path.resolve(process.argv[2]);
  const native = JSON.parse(fs.readFileSync(path.join(root, 'runtime/native-frontend.json'), 'utf8'));
  const entries = [path.join(root, native.root), path.join(root, 'runtime/openmaic-standalone')];
  const results = [];
  for (const entry of entries) {
    const source = fs.readFileSync(path.join(entry, 'server.js'), 'utf8');
    const configLine = source.match(/^const nextConfig = (.*)$/m);
    assert(configLine, 'Generated Next config line must exist');
    const base = JSON.parse(configLine[1]);
    const markers = ['// DeepSteam modification 2026-10-11: separate-storage image disk cache policy.',
      '// DeepSteam: keep image disk cache in the selected state directory.'];
    const anchor = 'process.env.__NEXT_PRIVATE_STANDALONE_CONFIG = JSON.stringify(nextConfig)';
    const starts = markers.map(marker => source.indexOf(marker)).filter(index => index >= 0);
    assert.equal(starts.length, 1, 'One reviewed cache policy must exist');
    const start = starts[0], end = source.indexOf(anchor);
    assert(end > start && source.indexOf(anchor, end + anchor.length) < 0);
    const policy = source.slice(start, end);
    const factory = { nextConfig: structuredClone(base), process: { env: { DEEPSTEAM_SEPARATE_STORAGE: '0' } } };
    vm.runInNewContext(policy, factory);
    assert.equal(JSON.stringify(factory.nextConfig), JSON.stringify(base));
    const separate = { nextConfig: structuredClone(base), process: { env: { DEEPSTEAM_SEPARATE_STORAGE: '1' } } };
    vm.runInNewContext(policy, separate);
    assert.equal(separate.nextConfig.images.maximumDiskCacheSize, 0);
    assert.equal(separate.nextConfig.images.unoptimized, base.images.unoptimized);
    assert.equal(separate.nextConfig.images.path, base.images.path);
    const runtimeRequire = createRequire(path.join(entry, 'server.js'));
    const { ImageOptimizerCache } = runtimeRequire('next/dist/server/image-optimizer');
    const originals = {}, calls = [];
    for (const name of ['mkdir', 'writeFile', 'readdir', 'readFile', 'unlink', 'stat', 'statfs', 'open', 'rename']) {
      if (typeof fs.promises[name] === 'function') {
        originals[name] = fs.promises[name];
        fs.promises[name] = async function () { calls.push(name); throw new Error('Unexpected cache disk IO'); };
      }
    }
    try {
      const cache = new ImageOptimizerCache({ distDir: path.join(entry, '.next'), nextConfig: separate.nextConfig });
      assert.equal(await cache.get('synthetic-cache-key'), null);
      await cache.set('synthetic-cache-key', { kind: 'IMAGE', buffer: Buffer.from('synthetic image bytes'),
        etag: 'test', upstreamEtag: 'test', extension: 'png' }, { cacheControl: { revalidate: 30 } });
      assert.equal(calls.length, 0, 'Disabled image cache must perform no disk IO');
    } finally {
      for (const [name, method] of Object.entries(originals)) fs.promises[name] = method;
    }
    results.push({ version: runtimeRequire('next/package.json').version, factoryConfigUnchanged: true, disabledCacheDiskCalls: calls.length });
  }
  console.log(JSON.stringify({ passed: true, results, modelCalls: 0, serversStarted: 0 }));
}
main().catch(error => { console.error(String(error.stack)); process.exitCode = 1; });
