import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createPackage, extractFile, listPackage } from './desktop-build-tools/node_modules/@electron/asar/lib/asar.js';

const [source, target] = process.argv.slice(2);
if (!source || !target || fs.existsSync(target)) throw new Error('A source and fresh ASAR target are required');
const packageInfo = JSON.parse(fs.readFileSync(new URL('./desktop-build-tools/node_modules/@electron/asar/package.json', import.meta.url)));
if (packageInfo.version !== '4.3.1') throw new Error('The pinned official ASAR build tool is required');
const names = fs.readdirSync(source).sort();
if (names.some(name => !fs.statSync(path.join(source, name)).isFile())) throw new Error('Only ordinary application files may be archived');
await createPackage(source, target);
const actual = listPackage(target).map(name => name.replaceAll('\\', '/').replace(/^\//, '')).sort();
if (JSON.stringify(actual) !== JSON.stringify(names)) throw new Error('ASAR entry list differs from the reviewed source');
const files = names.map(name => {
  const original = fs.readFileSync(path.join(source, name));
  const archived = extractFile(target, name);
  if (!original.equals(archived)) throw new Error('ASAR contents differ: ' + name);
  return { path: name, bytes: original.length, sha256: crypto.createHash('sha256').update(original).digest('hex') };
});
console.log(JSON.stringify({ asar_tool_version: packageInfo.version, archive: target, files, all_entry_bytes_verified: true }));
