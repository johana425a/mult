import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';
export default defineConfig({
  resolve: { alias: { '@': resolve(__dirname, '.') } },
  test: { include: ['tests/deepsteam-live-settings.test.ts', 'tests/deepsteam-desktop-return.test.ts', 'tests/deepsteam-video-controls.test.ts'] },
});
