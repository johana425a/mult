#!/usr/bin/env node
// DeepSteam local patch 2026-10-15: UI refresh + provider icons.
//
// Usage: node apply-ui-refresh.cjs <copied-build-dir> <patch-dir>
//   <copied-build-dir>  fresh copy of runtime/native-frontends/20261015-sidebar-workspace
//   <patch-dir>         this folder (theme.css, icons/, icon-map.txt)
//
// 1. Appends theme.css to the global stylesheet (the one defining :root tokens).
// 2. Adds icon-map entries for the newly registered providers to every chunk
//    (client and server) that carries the provider icon table.
// 3. Copies the new provider icons into public/provider-icons and records them
//    in sources.json.
// 4. Every changed client file gets a new content hash in its name and every
//    reference to the old hash is rewritten (repeated until stable, so the
//    webpack runtime that maps lazy chunk hashes is renamed too). Nothing is
//    deleted; old names are renamed, so no browser cache can serve old bytes.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const [buildDir, patchDir] = process.argv.slice(2);
if (!buildDir || !patchDir) { console.error('usage: apply-ui-refresh.cjs <build-dir> <patch-dir>'); process.exit(2); }
const DIST = fs.existsSync(path.join(buildDir, '.next-video')) ? path.join(buildDir, '.next-video') : null;
if (!DIST) throw new Error('No .next-video directory in ' + buildDir);
const marker = path.join(buildDir, 'DEEPSTEAM-UI-REFRESH.json');
if (fs.existsSync(marker)) throw new Error('Already patched: ' + marker);

const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const walk = (dir, out = []) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) walk(full, out); else if (e.isFile()) out.push(full);
  }
  return out;
};
const changed = new Map(); // absolute path -> new content (Buffer)
const read = (p) => changed.get(p) || fs.readFileSync(p);

// ---- 1. theme CSS -----------------------------------------------------------
const cssDir = path.join(DIST, 'static', 'css');
const tokenCss = fs.readdirSync(cssDir).filter(f => f.endsWith('.css'))
  .map(f => path.join(cssDir, f))
  .filter(p => /:root\{color-scheme:light;--background:/.test(fs.readFileSync(p, 'utf8')));
if (tokenCss.length !== 1) throw new Error('Expected one token stylesheet, found ' + tokenCss.length);
const theme = fs.readFileSync(path.join(patchDir, 'theme.css'), 'utf8');
changed.set(tokenCss[0], Buffer.concat([fs.readFileSync(tokenCss[0]), Buffer.from('\n' + theme + '\n')]));

// ---- 2. provider icon map ------------------------------------------------------
const ICON_ANCHOR = 'siliconflow:{file:"siliconcloud-color.svg"}';
const iconEntries = fs.readFileSync(path.join(patchDir, 'icon-map.txt'), 'utf8').trim();
let iconFiles = 0;
for (const p of walk(DIST).filter(f => f.endsWith('.js'))) {
  const text = read(p).toString('utf8');
  if (!text.includes(ICON_ANCHOR)) continue;
  const n = text.split(ICON_ANCHOR).length - 1;
  if (n !== 1) throw new Error('Icon anchor found ' + n + ' times in ' + p);
  if (text.includes('siliconflow_global:{')) throw new Error('Icon map already extended in ' + p);
  changed.set(p, Buffer.from(text.replace(ICON_ANCHOR, ICON_ANCHOR + ',' + iconEntries), 'utf8'));
  iconFiles++;
}
if (iconFiles < 2) throw new Error('Provider icon map not found');

// syntax check every edited script before writing anything
for (const [p, buf] of changed) if (p.endsWith('.js')) new Function(buf.toString('utf8'));

// ---- 3. icons -----------------------------------------------------------------------
const iconSrc = path.join(patchDir, 'icons');
const iconDst = path.join(buildDir, 'public', 'provider-icons');
const sourcesPath = path.join(iconDst, 'sources.json');
const sources = JSON.parse(fs.readFileSync(sourcesPath, 'utf8'));
for (const f of fs.readdirSync(iconSrc)) {
  const buf = fs.readFileSync(path.join(iconSrc, f));
  fs.writeFileSync(path.join(iconDst, f), buf);
  sources.assets[f] = {
    url: 'https://unpkg.com/@lobehub/icons-static-svg@1.95.1/icons/' + f,
    sha256: sha(buf),
    source: '@lobehub/icons-static-svg 1.95.1 (MIT)',
  };
}
fs.writeFileSync(sourcesPath, JSON.stringify(sources, null, 2) + '\n');

// ---- 4. write + rehash (in memory first, then one pass to disk) -------------
const HASHED = /^((?:.*[-.])?)([0-9a-f]{16})(\.(?:js|css))$/;
const files = new Map(); // current relative path -> Buffer
for (const p of walk(DIST)) files.set(p, changed.get(p) || fs.readFileSync(p));
const dirty = new Set(changed.keys());
const renames = []; // [oldAbs, newAbs]
const isClient = (p) => p.startsWith(path.join(DIST, 'static') + path.sep);
const replaceEverywhere = (oldTok, newTok) => {
  const o = Buffer.from(oldTok), n = Buffer.from(newTok);
  for (const [p, buf] of files) {
    if (buf.indexOf(o) === -1) continue;
    const parts = []; let at = 0, i;
    while ((i = buf.indexOf(o, at)) !== -1) { parts.push(buf.subarray(at, i), n); at = i + o.length; }
    parts.push(buf.subarray(at));
    files.set(p, Buffer.concat(parts)); dirty.add(p);
  }
};
for (let round = 0; round < 8; round++) {
  let progressed = false;
  for (const p of [...dirty]) {
    if (!isClient(p)) continue;
    const m = path.basename(p).match(HASHED);
    if (!m) continue;
    const buf = files.get(p);
    const want = sha(buf).slice(0, 16);
    if (m[2] === want) continue;
    const np = path.join(path.dirname(p), m[1] + want + m[3]);
    files.delete(p); files.set(np, buf); dirty.delete(p); dirty.add(np);
    renames.push([p, np]);
    replaceEverywhere(m[2], want);
    progressed = true;
  }
  if (!progressed) break;
}
for (const [from, to] of renames) {
  // a chain a->b->c only exists on disk as a
  if (fs.existsSync(from)) fs.renameSync(from, renames.reduce((cur, [f, t]) => (f === cur ? t : cur), from));
}
for (const p of dirty) fs.writeFileSync(p, files.get(p));
const changedCount = dirty.size;

const record = {
  patch: 'ui-refresh-amber-he', date: '2026-10-15', base_build: '20261015-sidebar-workspace',
  description: 'Amber-specimen neutrals with H&E icon colours, inset canvas, CJK font fallbacks, provider icons for newly registered providers.',
  token_stylesheet: path.relative(DIST, tokenCss[0]), icon_map_files: iconFiles,
  renamed: renames.map(([f, t]) => [path.relative(DIST, f), path.relative(DIST, t)]), files_written: changedCount,
};
fs.writeFileSync(marker, JSON.stringify(record, null, 2));
console.log(JSON.stringify(record, null, 2));
