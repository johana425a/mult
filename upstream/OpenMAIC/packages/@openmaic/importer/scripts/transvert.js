#!/usr/bin/env tsx


import { parse } from '../src1/pptxtojson.js';
import fs from 'fs';
import path from 'path';

const pptxPath = process.argv[2];
const outputPath = process.argv[3];

if (!pptxPath) {
  console.error('Usage: node scripts/transvert.js <path-to.pptx> [output.json]');
  process.exit(1);
}

const resolved = path.resolve(process.cwd(), pptxPath);
if (!fs.existsSync(resolved)) {
  console.error('File not found:', resolved);
  process.exit(1);
}

const buf = fs.readFileSync(resolved);
const arrayBuffer = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);

parse(arrayBuffer, { mediaMode: 'blob' })
  .then((json) => {
    const text = JSON.stringify(json, null, 2);

    if (outputPath) {
      const outResolved = path.resolve(process.cwd(), outputPath);
      fs.writeFileSync(outResolved, text, 'utf-8');
      console.log(`Output written: ${outResolved} (${(text.length / 1024).toFixed(1)} KB)`);
    } else {
      console.log(text);
    }
  })
  .catch((err) => {
    console.error('Parsing failed:', err.message);
    process.exit(1);
  });
