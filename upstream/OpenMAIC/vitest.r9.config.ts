import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';

/** Focused offline DeepSteam bridge tests, independent of upstream fixtures. */
export default defineConfig({
  resolve: { alias: { '@': resolve(__dirname, '.') } },
  test: { include: ['tests/r9-*.test.ts'] },
});
