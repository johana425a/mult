/** EduAgent original fixture adapter; calls upstream's real video compiler,
 * Hyperframes emitter and ZIP packager without a browser app store or model. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { compileVideoTimeline, emitHyperframes } from '../../lib/video-export/index.ts';
import { packageVideoZip } from '../../lib/video-export-app/package-zip.ts';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const app = path.join(root, 'upstream', 'OpenMAIC');
const out = path.join(root, 'reports', 'demo-native-export');
const input = JSON.parse(await fs.readFile(path.join(out, 'input.json'), 'utf8'));
const ir = compileVideoTimeline({ stage: input.stage, scenes: input.scenes }, {
  timing: { audioDurationMs: (action) => input.audio[action.id].durationMs, videoDurationMs: () => null },
  assets: { audio: (action) => ({ id: action.id, mimeType: 'audio/wav', format: 'wav', present: true }), media: () => null },
});
const project = emitHyperframes(ir, { width: 1280, height: 720, burnInSubtitles: true, locale: 'zh-CN', cta: null,
  labels: { quiz: '暂停思考', questions: '道题', points: '分', singleChoice: '单选', answerPlaceholder: '回到互动课堂作答' } });
const assets = new Map<string, Blob>();
for (const entry of ir.assets.entries) {
  if (entry.dedupOf) continue;
  let source: string;
  if (entry.kind === 'frame') source = input.frames[entry.assetId.slice('frame:'.length)];
  else if (entry.kind === 'audio') source = input.audio[entry.assetId].path;
  else throw new Error(`Unexpected asset kind ${entry.kind}`);
  assets.set(entry.path, new Blob([await fs.readFile(source)]));
}
const archive = await packageVideoZip(project, assets, {
  gsapSource: await fs.readFile(path.join(app, 'public', 'vendor', 'gsap.min.js'), 'utf8'),
  loadVendorAsset: async (url) => new Blob([await fs.readFile(path.join(app, 'public', url.replace(/^\//, '')))]),
});
await fs.writeFile(path.join(out, 'native-project.zip'), new Uint8Array(await archive.arrayBuffer()));
await fs.writeFile(path.join(out, 'timeline.json'), JSON.stringify(ir, null, 2));
await fs.writeFile(path.join(out, 'project-files.json'), JSON.stringify(project, null, 2));
await fs.writeFile(path.join(out, 'native-export-report.json'), JSON.stringify({ durationMs: ir.totalDurationMs,
  sceneCount: ir.scenes.length, assets: ir.assets.entries.length, diagnostics: ir.diagnostics,
  pipeline: ['OpenMAIC POST /preview for slide snapshots', 'compileVideoTimeline', 'emitHyperframes', 'packageVideoZip', 'POST /render pending'],
  excluded: ['browser store/Dexie collection', 'UI one-click export', 'live AI generation', 'cloud TTS'],
  fixture: 'Original authored lesson from demo/条件概率与信息更新.md, local Windows Huihui narration',
}, null, 2));
console.log(JSON.stringify({ durationMs: ir.totalDurationMs, diagnostics: ir.diagnostics, zipBytes: archive.size }));
