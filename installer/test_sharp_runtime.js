// Load the installed Sharp/native DLLs and round-trip a synthetic image in memory.
// Does not start servers, read learning data/settings, call a model, or use the network.
const path = require('node:path');
const fs = require('node:fs');
const { createRequire } = require('node:module');

async function main() {
  const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));
  const standalone = path.join(root, 'runtime', 'openmaic-standalone');
  if (!fs.existsSync(path.join(standalone, 'server.js'))) {
    throw new Error('Installed OpenMAIC standalone runtime is missing');
  }
  const runtimeRequire = createRequire(path.join(standalone, 'package.json'));
  const sharp = runtimeRequire('sharp');
  const width = 8, height = 8, channels = 3;
  const pixels = Buffer.alloc(width * height * channels);
  for (let offset = 0; offset < pixels.length; offset += channels) {
    pixels[offset] = 17; pixels[offset + 1] = 81; pixels[offset + 2] = 203;
  }
  const png = await sharp(pixels, { raw: { width, height, channels } }).png().toBuffer();
  const metadata = await sharp(png).metadata();
  const decoded = await sharp(png).raw().toBuffer({ resolveWithObject: true });
  if (metadata.width !== width || metadata.height !== height || metadata.format !== 'png'
      || decoded.info.channels !== channels || !decoded.data.equals(pixels)) {
    throw new Error('Synthetic PNG size or pixel round-trip mismatch');
  }
  console.log(JSON.stringify({ service: 'sharp_native', passed: true,
    sharp: sharp.versions.sharp, vips: sharp.versions.vips,
    width, height, channels, pngBytes: png.length, exactPixels: width * height,
    modelCalls: 0, networkCalls: 0 }));
}

main().catch((error) => {
  console.error(JSON.stringify({ service: 'sharp_native', passed: false,
    error: String(error.message), modelCalls: 0, networkCalls: 0 }));
  process.exitCode = 1;
});
