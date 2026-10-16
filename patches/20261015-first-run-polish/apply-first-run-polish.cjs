#!/usr/bin/env node
// DeepSteam local patch 2026-10-15: first-run polish.
// Usage: node apply-first-run-polish.cjs <copied-build-dir>
//   (a fresh copy of runtime/native-frontends/20261015-ui-refresh)
//
// 1. Model pickers: when no model is connected yet, show a calm hint in the
//    muted colour instead of the red "model unavailable" error.
// 2. Starter suggestions: softer Chinese wording when nothing could be suggested.
// Changed client files get new content-hash names; references are rewritten.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const buildDir = process.argv[2];
if (!buildDir) { console.error('usage: apply-first-run-polish.cjs <build-dir>'); process.exit(2); }
const DIST = path.join(buildDir, '.next-video');
const marker = path.join(buildDir, 'DEEPSTEAM-FIRST-RUN-POLISH.json');
if (fs.existsSync(marker)) throw new Error('Already patched: ' + marker);
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');
const walk = (d, o = []) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const f = path.join(d, e.name); if (e.isDirectory()) walk(f, o); else if (e.isFile()) o.push(f); } return o; };

const files = new Map();
for (const p of walk(DIST)) files.set(p, fs.readFileSync(p));
const dirty = new Set();

// ---- 1. model picker hint -------------------------------------------------
const ERR = '"模型暂不可用，请检查连接或选择其他模型。"';
let pickers = 0;
for (const [p, buf] of files) {
  if (!p.endsWith('.js')) continue;
  let text = buf.toString('utf8');
  if (!text.includes(ERR)) continue;
  const zh = text.match(/error:([A-Za-z_$][\w$]*)\?"模型暂不可用/);
  const hook = text.match(/options:([A-Za-z_$][\w$]*)\.options,activeDefault:\1\.activeDefault/);
  const render = /([A-Za-z_$][\w$]*)&&\(0,([A-Za-z_$][\w$]*)\.jsx\)\("p",\{role:"status",className:"text-xs text-\[var\(--destructive\)\]",children:\1\}\)/;
  const r = text.match(render);
  if (!zh || !hook || !r) continue; // the zh resource chunk only holds the string
  if ((text.match(new RegExp(render.source, 'g')) || []).length !== 1) throw new Error('render ambiguous in ' + p);
  const none = `(${hook[1]}.options&&${hook[1]}.options.length===0&&!${hook[1]}.loading)`;
  const hint = `(${zh[1]}?"还没有连接模型。到左侧「连接模型」选一个服务商、填好密钥，就能开始。":"No model is connected yet. Open Connect model, pick a provider and add its key to get started.")`;
  text = text.replace(render, `${r[1]}&&(0,${r[2]}.jsx)("p",{role:"status",className:${none}?"text-xs text-[var(--muted-foreground)]":"text-xs text-[var(--destructive)]",children:${none}?${hint}:${r[1]}})`);
  new Function(text);
  files.set(p, Buffer.from(text, 'utf8')); dirty.add(p); pickers++;
}
if (pickers < 2) throw new Error('model picker not found (' + pickers + ')');

// ---- 2. suggestion wording ----------------------------------------------
const OLD = '"Suggestions could not be generated. Please try again.":"暂时无法生成探索方向，请重试。"';
const NEW = '"Suggestions could not be generated. Please try again.":"暂时没有推荐方向。连接好模型后，点上面再试一次。"';
let wording = 0;
for (const [p, buf] of files) {
  if (!p.endsWith('.js')) continue;
  const text = buf.toString('utf8');
  if (!text.includes(OLD)) continue;
  files.set(p, Buffer.from(text.split(OLD).join(NEW), 'utf8')); dirty.add(p); wording++;
}

// ---- rehash -----------------------------------------------------------------
const HASHED = /^((?:.*[-.])?)([0-9a-f]{16})(\.(?:js|css))$/;
const isClient = (p) => p.startsWith(path.join(DIST, 'static') + path.sep);
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
for (const [from] of renames) if (fs.existsSync(from)) fs.renameSync(from, renames.reduce((c, [f, t]) => (f === c ? t : c), from));
for (const p of dirty) fs.writeFileSync(p, files.get(p));
const record = { patch: 'first-run-polish', date: '2026-10-15', base_build: '20261015-ui-refresh', model_pickers: pickers, wording_files: wording,
  renamed: renames.map(([f, t]) => [path.relative(DIST, f), path.relative(DIST, t)]), files_written: dirty.size };
fs.writeFileSync(marker, JSON.stringify(record, null, 2));
console.log(JSON.stringify(record, null, 2));
