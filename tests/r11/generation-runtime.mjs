// Use this checkout's build by default. An explicit override supports a paired,
// source-matched build; it must be disclosed in test results.
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const entry = process.env.DEEPSTEAM_GENERATION_DIST
  ? pathToFileURL(path.join(process.env.DEEPSTEAM_GENERATION_DIST, 'index.js'))
  : new URL('../../upstream/OpenMAIC/packages/@openmaic/generation/dist/index.js', import.meta.url);
const runtime = await import(entry.href);
export const {generateSceneContent, expandGeneratedSlidePages, layoutGeneratedSlidePages} = runtime;
