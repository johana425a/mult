#!/usr/bin/env node


import JSZip from 'jszip';
import fs from 'fs';
import path from 'path';

const args = process.argv.slice(2);
const pptxPath = args[0];
const outDir = args[1] || null;

if (!pptxPath) {
  console.error('Usage: node scripts/extract-pptx-structure.js <pptxpath> [output directory]');
  process.exit(1);
}

const resolvedPath = path.resolve(pptxPath);
if (!fs.existsSync(resolvedPath)) {
  console.error('File not found:', resolvedPath);
  process.exit(1);
}


function pathsToTree(paths) {
  const tree = {};
  for (const p of paths) {
    const parts = p.split('/').filter(Boolean);
    let current = tree;
    for (let i = 0; i < parts.length; i++) {
      const name = parts[i];
      const isLast = i === parts.length - 1;
      if (!current[name]) {
        current[name] = isLast ? null : {};
      }
      if (!isLast) {
        current = current[name];
      }
    }
  }
  return tree;
}


function printTree(obj, prefix = '') {
  const entries = Object.entries(obj).sort((a, b) => {
    const aIsFile = a[1] === null;
    const bIsFile = b[1] === null;
    if (aIsFile !== bIsFile) return aIsFile ? 1 : -1;
    return a[0].localeCompare(b[0]);
  });
  for (let i = 0; i < entries.length; i++) {
    const [name, value] = entries[i];
    const isLast = i === entries.length - 1;
    const branch = isLast ? '└── ' : '├── ';
    const nextPrefix = isLast ? '    ' : '│   ';
    if (value === null) {
      console.log(prefix + branch + name);
    } else {
      console.log(prefix + branch + name + '/');
      printTree(value, prefix + nextPrefix);
    }
  }
}

async function main() {
  console.log('Reading:', resolvedPath);
  const buffer = fs.readFileSync(resolvedPath);
  const zip = await JSZip.loadAsync(buffer);

  const filePaths = [];
  zip.forEach((relativePath) => {
    filePaths.push(relativePath);
  });
  filePaths.sort();

  console.log('\n========== PPTX internal file structure ==========\n');
  const tree = pathsToTree(filePaths);
  printTree(tree);

  console.log('\n---------- flat file list ----------');
  filePaths.forEach((p) => console.log(p));
  console.log('\ntotal file count:', filePaths.length);

  if (outDir) {
    const outResolved = path.resolve(outDir);
    fs.mkdirSync(outResolved, { recursive: true });
    console.log('\nExtracting to:', outResolved);
    for (const relativePath of filePaths) {
      const file = zip.file(relativePath);
      if (!file) continue;
      const fullPath = path.join(outResolved, relativePath);
      const dir = path.dirname(fullPath);
      fs.mkdirSync(dir, { recursive: true });
      const content = await file.async('nodebuffer');
      fs.writeFileSync(fullPath, content);
    }
    console.log('Extraction complete.');
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
