'use client';

/** EduAgent addition: full-video companions never enter the interactive store. */
import type { Scene, Stage } from '@/lib/types/stage';
import type { SpeechAction } from '@/lib/types/action';
import type { VideoTimeline, VideoTimelineScene } from '@/lib/video-export';
import type { VideoTimelineRecords } from './timeline-deps';
import type { FullNarratedExport, NarratedExportScene, ExportSpeech } from '@/lib/server/full-narrated-export';
import { useSettingsStore } from '@/lib/store/settings';

export function getNarratedExportTtsHeaders(): Record<string, string> {
  const settings = useSettingsStore.getState();
  const provider = settings.ttsProviderId;
  if (provider === 'windows-system-tts' || provider === 'browser-native-tts') {
    return { 'x-contest-tts-provider': 'windows-system-tts',
      'x-contest-tts-voice': provider === 'windows-system-tts' ? settings.ttsVoice || 'auto-zh' : 'auto-zh' };
  }
  if (provider !== 'openai-tts') return { 'x-contest-tts-provider': 'windows-system-tts', 'x-contest-tts-voice': 'auto-zh' };
  const config = settings.ttsProvidersConfig[provider];
  if (!config?.enabled || !config.apiKey || config.isServerConfigured || config.serverDisabled) {
    return { 'x-contest-tts-provider': 'windows-system-tts', 'x-contest-tts-voice': 'auto-zh' };
  }
  return { 'x-contest-tts-provider': 'openai-tts', 'x-contest-tts-api-key': config.apiKey,
    'x-contest-tts-model': config.modelId || 'tts-1', 'x-contest-tts-voice': settings.ttsVoice || 'alloy',
    ...(config.baseUrl ? { 'x-contest-tts-base-url': config.baseUrl } : {}) };
}

let cached: { signature: string; prepared: Promise<FullNarratedExport> } | undefined;
export async function prepareNarratedExport(input: {
  courseId: string; stage?: Stage; scenes: Scene[]; headers?: Record<string, string>; signal?: AbortSignal;
}): Promise<FullNarratedExport> {
  const headers = input.headers ?? getNarratedExportTtsHeaders();
  const snapshot = structuredClone(input.scenes);
  const signature = JSON.stringify({ courseId: input.courseId, scenes: snapshot, stage: input.stage,
    provider: headers['x-contest-tts-provider'], voice: headers['x-contest-tts-voice'],
    model: headers['x-contest-tts-model'], endpoint: headers['x-contest-tts-base-url'] });
  if (cached?.signature !== signature) {
    const prepared = (async () => {
      let courseId = input.courseId;
      let exportSource = snapshot;
      const submit = async () => {
        const response = await fetch('/api/education/narrated-export', {
          method: 'POST', headers: { 'content-type': 'application/json', ...headers },
          body: JSON.stringify({ courseId, scenes: exportSource }),
          signal: input.signal,
        });
        return { response, result: await response.json().catch(() => null) as
          (FullNarratedExport & { error?: string; reason?: string }) | null };
      };
      let submitted = await submit();
      if (!submitted.response.ok && (submitted.result?.reason === 'course_not_found' ||
        submitted.result?.reason === 'source_changed' ||
        (submitted.result?.reason === 'invalid_snapshot' && !/^[a-zA-Z0-9_-]{1,128}$/.test(courseId)))) {
        // Preserve browser-local/imported and edited classrooms: register a
        // separate export snapshot with a server-generated id, never overwrite
        // the source or copy an obsolete "verified" source-fidelity flag.
        const stage = input.stage;
        const registration = await fetch('/api/classroom', { method: 'POST',
          signal: input.signal,
          headers: { 'content-type': 'application/json' }, body: JSON.stringify({
            stage: { id: courseId, name: stage?.name || '课堂视频导出', description: stage?.description,
              sourceMaterial: stage?.sourceMaterial, exportSnapshot: { originalStageId: courseId } },
            scenes: snapshot,
          }) });
        const registered = await registration.json().catch(() => null) as { id?: string } | null;
        if (!registration.ok || !registered?.id) throw new Error('无法保存独立的导出课堂快照，请检查本机存储后重试。');
        courseId = registered.id;
        const read = await fetch(`/api/classroom?id=${encodeURIComponent(courseId)}`, {signal: input.signal});
        const saved = await read.json().catch(() => null) as { classroom?: { scenes: Scene[] } } | null;
        if (!read.ok || !Array.isArray(saved?.classroom?.scenes)) throw new Error('无法读取独立的导出课堂快照。');
        exportSource = saved.classroom.scenes;
        submitted = await submit();
      }
      const { response, result } = submitted;
      if (!response.ok || !result || result.version !== 1 || result.courseId !== courseId ||
        !Array.isArray(result.scenes) || result.scenes.some((scene) => scene.stageId !== courseId) ||
        result.coverage?.speechCount !== result.coverage?.voicedSpeechCount ||
        result.coverage?.sceneCount !== result.coverage?.voicedSceneCount) {
        // Only the route's curated user-facing messages enter the render dialog.
        throw new Error(result?.error || '完整导出配音未准备齐全，请检查课堂来源和语音服务。');
      }
      // Browser pools/media task ownership still belongs to the original UI
      // stage. Only new managed audio references use the snapshot's storage id.
      return { ...result, originalCourseId: input.courseId,
        scenes: result.scenes.map((scene) => ({ ...scene, stageId: input.courseId })) };
    })();
    cached = { signature, prepared };
    prepared.catch(() => { if (cached?.prepared === prepared) cached = undefined; });
  }
  return structuredClone(await cached!.prepared);
}

/** An intentional silent beat; it is separate from voiced-text readiness. */
export function exportPauseDurationMs(action: SpeechAction): number | null {
  const pause = (action as ExportSpeech).narratedExportPauseMs;
  return action.text === '' && action.id.startsWith('export-') && pause === 5_000 ? pause : null;
}

/** Overlap measured question/analysis visuals with their voice, instead of adding a second tail. */
export function alignNarratedExportTimeline(
  ir: VideoTimeline, scenes: readonly NarratedExportScene[],
): VideoTimeline {
  const sourceById = new Map(scenes.map((scene) => [scene.id, scene]));
  const offsets = new Map<string, number>();
  let shiftMs = 0;
  const shifted = ir.scenes.map((scene): VideoTimelineScene => {
    const offset = shiftMs;
    offsets.set(scene.id, offset);
    const startMs = scene.startMs + offset;
    const move = <T extends { startMs: number }>(item: T): T => ({ ...item, startMs: item.startMs + offset });
    let durationMs = scene.durationMs;
    let visuals = scene.visuals.map(move);
    if (sourceById.get(scene.id)?.narratedExport) {
      const list = scene.visuals.find((visual) => visual.kind === 'quiz-question-list');
      if (!list || list.kind !== 'quiz-question-list') {
        throw new Error(`测验场景“${scene.title}”的题目布局未完成，已停止完整视频导出。`);
      }
      const authoredDurationMs = scene.durationMs - list.durationMs;
      const topHoldDurationMs = 600;
      const bottomHoldDurationMs = 1_200;
      durationMs = Math.max(authoredDurationMs, topHoldDurationMs + list.scrollDurationMs + bottomHoldDurationMs);
      visuals = [{ ...list, startMs, durationMs, transitionDurationMs: 0,
        topHoldDurationMs, bottomHoldDurationMs }];
      shiftMs += durationMs - scene.durationMs;
    }
    return { ...scene, startMs, durationMs, visuals, narration: scene.narration.map(move),
      effects: scene.effects.map(move), videos: scene.videos.map(move), markers: scene.markers.map(move) };
  });
  return { ...ir, scenes: shifted, totalDurationMs: ir.totalDurationMs + shiftMs,
    subtitles: ir.subtitles.map((cue) => ({ ...cue,
      startMs: cue.startMs + (offsets.get(cue.sceneId) ?? 0),
      endMs: cue.endMs + (offsets.get(cue.sceneId) ?? 0) })) };
}

/** Actual media decoding is required; record/text estimates do not pass this gate. */
export function measureExportAudioDuration(blob: Blob): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const audio = document.createElement('audio');
    let settled = false;
    const done = (duration: number | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      URL.revokeObjectURL(url);
      audio.removeAttribute('src');
      resolve(duration);
    };
    const timer = setTimeout(() => done(null), 10_000);
    audio.preload = 'metadata';
    audio.onloadedmetadata = () => done(Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : null);
    audio.onerror = () => done(null);
    audio.src = url;
  });
}

export async function assertFullNarrationReady(
  ir: VideoTimeline, scenes: readonly Scene[], records: VideoTimelineRecords,
  measure: (blob: Blob) => Promise<number | null> = measureExportAudioDuration,
): Promise<{ sceneCount: number; speechCount: number; spokenCharacters: number; observedDurationSeconds: number }> {
  const forbidden = new Set(['missing-audio', 'skipped-media', 'estimated-duration',
    'quiz-layout-unavailable', 'unknown-action', 'invalid-action', 'unsupported-scene']);
  const diagnostic = ir.diagnostics.find((item) => forbidden.has(item.code));
  if (diagnostic) throw new Error('课堂配音、题目布局或场景资源不完整，已停止完整视频导出。');
  let speechCount = 0;
  let spokenCharacters = 0;
  let observedDurationSeconds = 0;
  const measured = new Map<string, number>();
  for (const source of scenes) {
    const scene = ir.scenes.find((candidate) => candidate.id === source.id);
    const speeches = (source.actions ?? []).map((action, actionIndex) => ({ action, actionIndex }))
      .filter(({ action }) => action.type === 'speech' && action.text.trim());
    if (!scene || !speeches.length || scene.durationMs <= 0) {
      throw new Error(`场景“${source.title}”没有完整讲解配音，已停止导出。`);
    }
    for (const { action, actionIndex } of speeches) {
      const segment = scene.narration.find((item) => item.actionIndex === actionIndex);
      const id = segment?.audio.assetId;
      const blob = id ? records.audioById.get(id)?.blob : undefined;
      if (!segment || !id || !blob?.size || !segment.audio.present || !segment.audio.assetRef ||
        segment.audio.source !== 'stored' || segment.durationMs <= 0) {
        throw new Error(`场景“${source.title}”的配音缺失或使用了估算时长，已停止导出。`);
      }
      let seconds = measured.get(id);
      if (seconds === undefined) {
        const decoded = await measure(blob);
        if (decoded === null || !Number.isFinite(decoded) || decoded <= 0) {
          throw new Error(`场景“${source.title}”的音频无法读取实际时长，已停止导出。`);
        }
        seconds = decoded;
        measured.set(id, seconds);
      }
      if (Math.abs(seconds * 1000 - segment.durationMs) > 20 ||
        segment.startMs + segment.durationMs > scene.startMs + scene.durationMs + 1) {
        throw new Error(`场景“${source.title}”的音频与时间轴不一致，已停止导出以避免截断。`);
      }
      speechCount += 1;
      spokenCharacters += (action as SpeechAction).text.length;
      observedDurationSeconds += seconds;
    }
  }
  return { sceneCount: scenes.length, speechCount, spokenCharacters, observedDurationSeconds };
}
