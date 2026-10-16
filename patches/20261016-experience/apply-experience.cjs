#!/usr/bin/env node
// DeepSteam local patch 2026-10-16: hands-on experience fixes for the learning UI.
// Usage: node apply-experience.cjs <build-dir>   (runtime/native-frontends/20261015-polish or a copy)
//
// 1. Dates and relative times follow the interface language (<html lang>) instead of
//    a hard-coded "en-US" ("1 minute ago" in the Chinese UI).
// 2. The "Browse Invidious" button is hidden in the add-material dialogs; video
//    links from YouTube and Bilibili are still pasted the same way.
// 3. Library row -> "New collection…" starts with that material already selected,
//    and opens the new collection even if the follow-up assignment is a no-op.
// Changed client files get new content-hash names; references are rewritten.
// Writes DEEPSTEAM-EXPERIENCE-20261016.json listing every changed and new file.
'use strict';
const fs = require('fs'); const path = require('path'); const crypto = require('crypto');
const buildDir = process.argv[2];
if (!buildDir) { console.error('usage: apply-experience.cjs <build-dir>'); process.exit(2); }
const DIST = path.join(buildDir, '.next-video');
const marker = path.join(buildDir, 'DEEPSTEAM-EXPERIENCE-20261016.json');
if (fs.existsSync(marker)) throw new Error('Already patched: ' + marker);
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');
const walk = (d, o = []) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const f = path.join(d, e.name); if (e.isDirectory()) walk(f, o); else if (e.isFile()) o.push(f); } return o; };
const files = new Map(); for (const p of walk(DIST)) files.set(p, fs.readFileSync(p));
const original = new Set(files.keys());
const dirty = new Set();
const isClient = (p) => p.startsWith(path.join(DIST, 'static') + path.sep);
const edit = (p, fn) => { const before = files.get(p).toString('utf8'); const after = fn(before); if (after !== before) { if (p.endsWith('.js')) new Function(after); files.set(p, Buffer.from(after, 'utf8')); dirty.add(p); return true; } return false; };

// ---- 1. locale ----------------------------------------------------------------
const LANG = '(globalThis.document?.documentElement?.lang||"en-US")';
let locales = 0;
for (const p of [...files.keys()]) {
  if (!isClient(p) || !p.endsWith('.js')) continue;
  edit(p, (t) => t.replace(/(Intl\.(?:RelativeTimeFormat|DateTimeFormat)\(|\.toLocale(?:Date|Time)?String\()"en-US"/g, (m, a) => { locales++; return a + LANG; }));
}
if (locales < 20) throw new Error('locale sites not found (' + locales + ')');

// ---- 2 + 3a. add-material dialog ------------------------------------------------
let dialog = null;
for (const p of files.keys()) if (isClient(p) && p.endsWith('.js') && files.get(p).includes('AddMaterialsDialog:()=>')) dialog = p;
if (!dialog) throw new Error('AddMaterialsDialog chunk not found');
edit(dialog, (t) => {
  const m = t.match(/AddMaterialsDialog:\(\)=>([A-Za-z_$][\w$]*)/); const name = m[1];
  const sig = new RegExp('function ' + name.replace('$', '\\$') + '\\(\\{mode:([\\w$]+),workspaceId:([\\w$]+),onClose:([\\w$]+),onDone:([\\w$]+)\\}\\)\\{');
  const s = t.match(sig); if (!s) throw new Error('dialog signature changed');
  const start = s.index;
  t = t.slice(0, start) + s[0].replace('onDone:' + s[4] + '})', 'onDone:' + s[4] + ',initialItems:__dsInit})') + t.slice(start + s[0].length);
  const st = /\[([\w$]+),([\w$]+)\]=\(0,([\w$]+)\.useState\)\(\[\]\)/g; st.lastIndex = start;
  const u = st.exec(t); if (!u || u.index - start > 600) throw new Error('dialog item state not found');
  t = t.slice(0, u.index) + `[${u[1]},${u[2]}]=(0,${u[3]}.useState)(()=>Array.isArray(__dsInit)?__dsInit:[])` + t.slice(u.index + u[0].length);
  const inv = /\(0,([\w$]+)\.jsxs\)\("button",\{type:"button",onClick:\(\)=>([\w$]+)\(!0\),className:"mt-3 flex w-full items-center gap-2 rounded-lg border[^"]*",children:\[\(0,\1\.jsx\)\([\w$.]+,\{size:13\}\),([\w$]+)\("Browse Invidious"\)\]\}\)/g;
  const n = (t.match(inv) || []).length; if (n !== 1) throw new Error('Invidious button count ' + n);
  return t.replace(inv, 'null');
});

// ---- 3b. library row -> new collection ------------------------------------------
let rowFixed = 0;
for (const p of files.keys()) {
  if (!isClient(p) || !p.endsWith('.js') || !files.get(p).includes('mode:"create",onClose:()=>')) continue;
  edit(p, (t) => {
    const re = /\(0,([\w$]+)\.jsx\)\(([\w$]+)\.AddMaterialsDialog,\{mode:"create",onClose:\(\)=>([\w$]+)\(!1\),onDone:\(\{workspace:([\w$]+)\}\)=>\{\4\?\(0,([\w$]+)\.mk\)\(\4\.workspace_id,([\w$]+)\.material_id,!0\)\.then\(\(\)=>([\w$]+)\.push\(\(0,([\w$]+)\.mg\)\(\4\.workspace_id\)\)\)\.catch\(\(\)=>\3\(!1\)\):\3\(!1\)\}\}\)/;
    const m = t.match(re); if (!m) return t;
    const [all, J, K, H, W, Wm, E, I, L] = m;
    rowFixed++;
    return t.replace(all, `(0,${J}.jsx)(${K}.AddMaterialsDialog,{mode:"create",initialItems:[{key:\`library:\${${E}.material_id}\`,kind:"library",label:${E}.title,material:${E},decision:"reuse"}],onClose:()=>${H}(!1),onDone:({workspace:${W}})=>{${W}?(0,${Wm}.mk)(${W}.workspace_id,${E}.material_id,!0).catch(()=>{}).then(()=>${I}.push((0,${L}.mg)(${W}.workspace_id))):${H}(!1)}})`);
  });
}
if (rowFixed !== 1) throw new Error('library row dialog count ' + rowFixed);

// ---- rehash (same scheme as the 2026-10-15 patches) ------------------------------
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
fs.writeFileSync(marker, JSON.stringify({ patch: 'experience-20261016', locale_sites: locales, created, modified,
  renamed: renames.map(([a, b]) => [path.relative(buildDir, a), path.relative(buildDir, b)]) }, null, 2));
console.log('ok', { locales, created: created.length, modified: modified.length });
