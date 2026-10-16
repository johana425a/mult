#!/usr/bin/env node
// DeepSteam local patch 2026-10-16: dialogs no longer cut off at the top.
// Usage: node apply-dialog-fix.cjs <build-dir>   (runtime/native-frontends/20261016-experience)
//
// The page-entry animations kept their final frame ("both"), which leaves a
// transform on the page container. A transformed ancestor becomes the containing
// block of position:fixed overlays, so full-screen dialogs were sized to the page
// container (only part of the screen) and tall ones were pushed above the top.
// "backwards" keeps the identical entry motion but drops the transform afterwards.
'use strict';
const fs = require('fs'); const path = require('path'); const crypto = require('crypto');
const buildDir = process.argv[2];
if (!buildDir) { console.error('usage: apply-dialog-fix.cjs <build-dir>'); process.exit(2); }
const DIST = path.join(buildDir, '.next-video');
const marker = path.join(buildDir, 'DEEPSTEAM-DIALOG-FIX-20261016.json');
if (fs.existsSync(marker)) throw new Error('Already patched: ' + marker);
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');
const walk = (d, o = []) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const f = path.join(d, e.name); if (e.isDirectory()) walk(f, o); else if (e.isFile()) o.push(f); } return o; };
const files = new Map(); for (const p of walk(DIST)) files.set(p, fs.readFileSync(p));
const original = new Set(files.keys()); const dirty = new Set();
const isClient = (p) => p.startsWith(path.join(DIST, 'static') + path.sep);
const RULES = [
  ['[data-feature-page]>*{animation:ds-page-in var(--motion-slow) var(--motion-ease) both', '[data-feature-page]>*{animation:ds-page-in var(--motion-slow) var(--motion-ease) backwards'],
  ['.ds-rise{animation:ds-rise var(--motion-slow) var(--motion-ease) both', '.ds-rise{animation:ds-rise var(--motion-slow) var(--motion-ease) backwards'],
];
const hits = RULES.map(() => 0);
for (const [p, buf] of files) {
  if (!isClient(p) || !p.endsWith('.css')) continue;
  let t = buf.toString('utf8'); const before = t;
  RULES.forEach(([a, b], i) => { const n = t.split(a).length - 1; hits[i] += n; t = t.split(a).join(b); });
  if (t !== before) { files.set(p, Buffer.from(t, 'utf8')); dirty.add(p); }
}
if (hits.some((n) => n < 1)) throw new Error('rules not found ' + hits);
const HASHED = /^((?:.*[-.])?)([0-9a-f]{16})(\.(?:js|css))$/;
const renames = [];
const replaceEverywhere = (o, n) => { const ob = Buffer.from(o), nb = Buffer.from(n);
  for (const [p, buf] of files) { if (buf.indexOf(ob) === -1) continue; const parts = []; let at = 0, i;
    while ((i = buf.indexOf(ob, at)) !== -1) { parts.push(buf.subarray(at, i), nb); at = i + ob.length; }
    parts.push(buf.subarray(at)); files.set(p, Buffer.concat(parts)); dirty.add(p); } };
for (let round = 0; round < 8; round++) {
  let moved = false;
  for (const p of [...dirty]) {
    if (!isClient(p)) continue;
    const m = path.basename(p).match(HASHED); if (!m) continue;
    const buf = files.get(p); const want = sha(buf).slice(0, 16); if (m[2] === want) continue;
    const np = path.join(path.dirname(p), m[1] + want + m[3]);
    files.delete(p); files.set(np, buf); dirty.delete(p); dirty.add(np); renames.push([p, np]);
    replaceEverywhere(m[2], want); moved = true;
  }
  if (!moved) break;
}
const created = [], modified = [];
for (const p of dirty) { fs.writeFileSync(p, files.get(p)); (original.has(p) ? modified : created).push(path.relative(buildDir, p)); }
fs.writeFileSync(marker, JSON.stringify({ patch: 'dialog-fix-20261016', hits, created, modified,
  renamed: renames.map(([a, b]) => [path.relative(buildDir, a), path.relative(buildDir, b)]) }, null, 2));
console.log('ok', { hits, created: created.length, modified: modified.length });
