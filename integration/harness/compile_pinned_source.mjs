/** Rebuild Harness exports from the versioned, modified public source tree. */
import { build } from 'esbuild';
import { readdir, readFile, writeFile, mkdir, stat, copyFile } from 'node:fs/promises';
import { join, resolve, dirname } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const base = dirname(fileURLToPath(import.meta.url));
const upstream = resolve(base, '../../upstream/DeepSeekHarness');
const pinned = 'd743267388641bc76f17c45ce8b4c231aed1d32c';
let publicSource = false;
try {
  const provenance = JSON.parse(await readFile(join(upstream, 'SOURCE-PROVENANCE.json'), 'utf8'));
  if (provenance.upstream_commit !== pinned || provenance.modified_public_source !== true) {
    throw new Error('Public Harness provenance does not match the required upstream version');
  }
  publicSource = true;
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
  if (execFileSync('git', ['-C', upstream, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim() !== pinned) {
    throw new Error('Harness upstream commit does not match the required version');
  }
}
const targets = []; const unusedGeneratedExports = [];
const digest = data => createHash('sha256').update(data).digest('hex');
const scope = join(base, 'node_modules/@deepseek-ai');
for (const name of await readdir(scope)) {
  const installed = join(scope, name);
  const manifest = JSON.parse(await readFile(join(installed, 'package.json'), 'utf8'));
  const directory = manifest.repository?.directory;
  if (!directory) continue;
  const sourceRoot = join(upstream, directory);
  let sourceManifest;
  try { sourceManifest = JSON.parse(await readFile(join(sourceRoot, 'package.json'), 'utf8')); } catch { continue; }
  if (sourceManifest.version !== manifest.version) throw new Error('Pinned package version mismatch: ' + name);
  const exports = manifest.exports ?? { '.': manifest.main };
  const seen = new Set(); const packageEntries = [];
  for (const [key, spec] of Object.entries(exports)) {
    const relative = typeof spec === 'string' ? spec : spec?.default;
    if (!relative || !relative.startsWith('./lib/') || !relative.endsWith('.js') || seen.has(relative)) continue;
    seen.add(relative);
    // Upstream publishes subprocess ./runner from src/bin.ts, not src/runner.ts.
    const sourceRelative = manifest.name === '@deepseek-ai/dsh-subprocess-local' && key === './runner'
      ? 'src/bin.ts'
      : relative.replace(/^\.\/lib\/types\//, 'src/').replace(/^\.\/lib\//, 'src/').replace(/\.js$/, '.ts');
    const source = join(sourceRoot, sourceRelative);
    try { await stat(source); } catch {
      if (key !== '.') { unusedGeneratedExports.push({ package: name, export: key, reason: 'Generated remote/type-graph metadata; this Host loads no Remote or Typert service.' }); continue; }
      throw new Error('Cannot establish pinned source for runtime export ' + name + ':' + key);
    }
    packageEntries.push({ key, relative, source, sourceRelative });
  }
  if (packageEntries.length) {
    const entries = Object.fromEntries(packageEntries.map(entry => [entry.relative.replace(/^\.\/lib\//, '').replace(/\.js$/, ''), entry.source]));
    const result = await build({ entryPoints: entries, bundle: true, splitting: true, format: 'esm', platform: 'node', target: 'es2024', packages: 'external', tsconfigRaw: { compilerOptions: {} }, outdir: join(installed, 'lib'), chunkNames: 'source-chunks/[name]-[hash]', metafile: true, logLevel: 'silent', nodePaths: [join(base, 'node_modules')] });
    const inputs = {};
    for (const file of Object.keys(result.metafile.inputs)) { const path = resolve(file); inputs[path.startsWith(upstream) ? path.slice(upstream.length + 1).replaceAll('\\', '/') : path] = digest(await readFile(path)); }
    for (const entry of packageEntries) targets.push({ package: manifest.name, version: manifest.version, export: entry.key, source: entry.sourceRelative, output: entry.relative, output_sha256: digest(await readFile(join(installed, entry.relative))), inputs });
  }
}
if (targets.length < 20) throw new Error('Incomplete Harness source rebuild');
await writeFile(join(base, 'pinned-source-build.json'), JSON.stringify({ upstream_commit: pinned, modified_public_source: publicSource, compiler: 'esbuild 0.28.2', targets, unusedGeneratedExports }, null, 2));
console.log(JSON.stringify({ ok: true, exports: targets.length, packages: new Set(targets.map(target => target.package)).size }));
