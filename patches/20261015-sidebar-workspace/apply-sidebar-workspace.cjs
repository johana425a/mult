#!/usr/bin/env node
// DeepSteam local patch: Harness-style "Add workspace" button in the sidebar.
//
// Usage: node apply-sidebar-workspace.cjs <copied-build-dir> <inject.js>
// The build dir must be a fresh copy of runtime/native-frontends/20261014-video-session.
// The patched chunk gets a new content-hash file name (same length), and every
// reference inside .next-video is rewritten, so no browser cache can serve the old one.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const [buildDir, injectFile] = process.argv.slice(2);
if (!buildDir || !injectFile) { console.error('usage: apply-sidebar-workspace.cjs <build-dir> <inject.js>'); process.exit(2); }

const DIST = path.join(buildDir, '.next-video');
const OLD_NAME = '8292-82a8696d27177bb1';
const OLD_SHA256 = process.env.DS_EXPECT_SHA256 || '';
const chunkPath = path.join(DIST, 'static', 'chunks', OLD_NAME + '.js');

if (!fs.existsSync(chunkPath)) throw new Error('Sidebar chunk not found (already patched or different build): ' + chunkPath);
let src = fs.readFileSync(chunkPath, 'utf8');
const srcSha = crypto.createHash('sha256').update(src).digest('hex');
if (OLD_SHA256 && srcSha !== OLD_SHA256) throw new Error('Unexpected sidebar chunk content ' + srcSha);

const inject = fs.readFileSync(injectFile, 'utf8')
  .replace(/^\/\*[\s\S]*?\*\/\s*/, '');   // drop the leading header comment only

const edits = [
  // 1. Helper components live at module scope, right before SidebarShell (eh).
  ['function eh({sessions:e=[],', inject + '\nfunction eh({sessions:e=[],'],
  // 2. Collapsed rail: button under Home.
  ['(0,a.jsx)(ed,{collapsed:!0,onHomeClick:G}),',
   '(0,a.jsx)(ed,{collapsed:!0,onHomeClick:G}),(0,a.jsx)(__dsWsRail,{onCreated:_}),'],
  // 3. Expanded sidebar: "Workspaces  +" header above the grouped history.
  ['children:[!P&&(0,a.jsx)("div",{className:"mb-2 px-2 text-xs text-[var(--muted-foreground)]",children:L("Recent")}),',
   'children:[P&&(0,a.jsx)(__dsWsHeader,{onCreated:_}),!P&&(0,a.jsx)("div",{className:"mb-2 px-2 text-xs text-[var(--muted-foreground)]",children:L("Recent")}),'],
];
for (const [from, to] of edits) {
  const count = src.split(from).length - 1;
  if (count !== 1) throw new Error('Anchor found ' + count + ' times: ' + from.slice(0, 60));
  src = src.replace(from, () => to);
}
// Syntax check before touching anything on disk.
new Function(src);

const newHash = crypto.createHash('sha256').update(src).digest('hex').slice(0, 16);
const NEW_NAME = '8292-' + newHash;
const newChunkPath = path.join(DIST, 'static', 'chunks', NEW_NAME + '.js');
fs.renameSync(chunkPath, newChunkPath);        // rename, not delete: works without delete rights
fs.writeFileSync(newChunkPath, src, 'utf8');

// Rewrite references (manifests, prerendered HTML/RSC). Same length, so RSC row sizes hold.
let rewritten = 0;
const oldBuf = Buffer.from(OLD_NAME), newBuf = Buffer.from(NEW_NAME);
(function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) { walk(full); continue; }
    if (!entry.isFile()) continue;
    const buf = fs.readFileSync(full);
    if (buf.indexOf(oldBuf) === -1) continue;
    const parts = [];
    let at = 0, i;
    while ((i = buf.indexOf(oldBuf, at)) !== -1) { parts.push(buf.subarray(at, i), newBuf); at = i + oldBuf.length; }
    parts.push(buf.subarray(at));
    fs.writeFileSync(full, Buffer.concat(parts));
    rewritten++;
  }
})(DIST);

const record = {
  patch: 'sidebar-add-workspace',
  date: '2026-10-15',
  base_build: '20261014-video-session',
  description: 'Harness-style add-workspace button in the sidebar (expanded header + collapsed rail, Ctrl+O). Pick a folder, register it as a workspace, open a new chat in it.',
  chunk_before: OLD_NAME + '.js', chunk_before_sha256: srcSha,
  chunk_after: NEW_NAME + '.js',
  chunk_after_sha256: crypto.createHash('sha256').update(src).digest('hex'),
  references_rewritten: rewritten,
};
fs.writeFileSync(path.join(buildDir, 'DEEPSTEAM-LOCAL-PATCH.json'), JSON.stringify(record, null, 2));
console.log(JSON.stringify(record, null, 2));
