/** EduAgent addition: durable, source-checked narration for an export-only clone. */
import { createHash } from 'node:crypto';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { Action, SpeechAction } from '@/lib/types/action';
import type { QuizQuestion, Scene } from '@/lib/types/stage';
import type { TTSModelConfig } from '@/lib/audio/types';
import { generateTTS } from '@/lib/audio/tts-providers';
import { splitLongSpeechText } from '@/lib/audio/tts-utils';
import { isServerTTSProviderDisabled } from '@/lib/server/provider-config';
import {
  CLASSROOMS_DIR, isValidClassroomId, readClassroom, writeJsonFileAtomic,
  type PersistedClassroomData,
} from '@/lib/server/classroom-storage';
import { inspectWindowsPcmWav } from '@/lib/server/windows-system-tts';
import type { ContestProviderOptions } from '@/lib/server/contest-provider';
import { withClassroomOperation, withClassroomWrite } from './classroom-lifecycle';

export const NARRATED_EXPORT_VERSION = 1;
export const EXPORT_PAUSE_MS = 5_000;
export type NarratedExportScene = Scene & {
  narratedExport?: { kind: 'question' | 'analysis'; sourceSceneId: string; questionId: string };
};
export type ExportSpeech = SpeechAction & { audioUrl?: string; narratedExportPauseMs?: number };

export class NarratedExportError extends Error {
  constructor(public readonly reason: string, message: string, public readonly status = 422) {
    super(message);
    this.name = 'NarratedExportError';
  }
}

export interface NarratedExportClip {
  sceneId: string;
  actionId: string;
  audioId: string;
  audioUrl?: string;
  characters: number;
  textSha256: string;
  durationSeconds?: number;
  generated: boolean;
}
export interface FullNarratedExport {
  version: 1;
  courseId: string;
  sourceSha256: string;
  exportSha256: string;
  originalCourseId?: string;
  provenance: { kind: 'saved-classroom' | 'export-snapshot'; sourceFidelity?: 'verified' | 'needs_review' };
  scenes: NarratedExportScene[];
  coverage: {
    sceneCount: number;
    voicedSceneCount: number;
    speechCount: number;
    voicedSpeechCount: number;
    spokenCharacters: number;
    quizQuestionCount: number;
    quizAnalysisCount: number;
    clips: NarratedExportClip[];
  };
}

function sha(value: string | Uint8Array): string {
  return createHash('sha256').update(value).digest('hex');
}
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
      .filter(([key]) => !['audioId', 'audioUrl', 'createdAt', 'updatedAt'].includes(key))
      .map(([key, item]) => [key, canonical(item)]));
  }
  return value;
}
export function narrationSourceHash(scenes: readonly Scene[]): string {
  return sha(JSON.stringify(canonical(scenes)));
}

function answerText(question: QuizQuestion): string {
  const answers = Array.isArray(question.answer)
    ? question.answer.filter((answer) => typeof answer === 'string' && answer.trim()) : [];
  if (!answers.length) return 'No reference answer was provided for this question.';
  return `Reference answer: ${answers.map((answer) => {
    const option = question.options?.find((item) => item.value === answer);
    return option ? `${answer}, ${option.label}` : answer;
  }).join('; ')}.`;
}

/** Answers enter only new, explicitly exported analysis cards, never interactive data. */
export function createNarratedExportScenes(source: readonly Scene[]): NarratedExportScene[] {
  const result: NarratedExportScene[] = [];
  const ordered = source.map((scene, index) => ({ scene, index }))
    .sort((a, b) => (a.scene.order ?? a.index) - (b.scene.order ?? b.index) || a.index - b.index);
  for (const { scene: original } of ordered) {
    const scene = structuredClone(original) as NarratedExportScene;
    if (scene.type !== 'quiz' || scene.content.type !== 'quiz') {
      result.push(scene);
      continue;
    }
    const questions = structuredClone(scene.content.questions);
    // The original introduction remains, but its questions are rendered once on
    // their individual cards, each followed by its independently timed analysis.
    scene.content = { ...scene.content, questions: [] };
    if (!(scene.actions ?? []).some((action) => action.type === 'speech' && action.text.trim())) {
      scene.actions = [...(scene.actions ?? []), {
        id: `export-intro-${sha(scene.id).slice(0, 20)}`, type: 'speech',
        text: `Next is the quiz: ${scene.title}. Answer independently before continuing to the provided answer and explanation.`,
      }];
    }
    result.push(scene);
    questions.forEach((question, index) => {
      const identity = sha(`${scene.id}\n${index}\n${question.id}`).slice(0, 24);
      const options = (question.options ?? []).map((option) => `Option ${option.value}. ${option.label}.`).join('\n');
      const questionSpeech = `Question ${index + 1}. ${question.question}\n${options}\nPause the video, think independently, and answer. Continue to the explanation when ready.`;
      const analysis = typeof question.analysis === 'string' && question.analysis.trim()
        ? `Provided explanation: ${question.analysis}` : 'No explanation was provided for this question.';
      const explanation = `${answerText(question)}\n${analysis}`;
      const card = (kind: 'question' | 'analysis', text: string, prompt: QuizQuestion): NarratedExportScene => ({
        ...structuredClone(original), id: `export-${identity}-${kind}`,
        title: `${original.title} · Question ${index + 1}${kind === 'analysis' ? ' explanation' : ''}`,
        content: { type: 'quiz', questions: [prompt] },
        actions: [{ id: `export-${identity}-${kind}-speech`, type: 'speech', text },
          ...(kind === 'question' ? [{ id: `export-${identity}-pause`, type: 'speech', text: '',
            narratedExportPauseMs: EXPORT_PAUSE_MS } as ExportSpeech] : [])],
        narratedExport: { kind, sourceSceneId: original.id, questionId: question.id },
      } as NarratedExportScene);
      result.push(card('question', questionSpeech, structuredClone(question)));
      result.push(card('analysis', `Question ${index + 1} explanation.\n${explanation}`, {
        id: `${question.id}-export-analysis`, type: 'short_answer',
        question: `${question.question}\n\n${explanation}`,
      }));
    });
  }
  const ids = new Set<string>();
  result.forEach((scene, order) => {
    if (ids.has(scene.id)) throw new NarratedExportError('duplicate_scene', 'Classroom scene identifiers are duplicated. The export cannot be compiled safely.');
    ids.add(scene.id);
    scene.order = order;
  });
  return result;
}

interface StoredAudio { audioId: string; audioUrl: string; durationSeconds?: number }
export interface NarratedExportDeps {
  readCourse: (id: string) => Promise<PersistedClassroomData | null>;
  loadAudio: (courseId: string, reference: string) => Promise<StoredAudio | null>;
  readCache: (courseId: string, key: string) => Promise<FullNarratedExport | null>;
  writeCache: (courseId: string, key: string, result: FullNarratedExport) => Promise<void>;
  synthesize: typeof generateTTS;
  saveAudio: (courseId: string, id: string, audio: Uint8Array, format: string) => Promise<StoredAudio>;
}

async function checkedAudioDirectory(courseId: string): Promise<string> {
  const root = path.resolve(CLASSROOMS_DIR);
  const directory = path.join(root, courseId, 'audio');
  await withClassroomWrite(courseId, () => fs.mkdir(directory, { recursive: true }));
  const real = await fs.realpath(directory);
  if (!real.startsWith(path.join(root, courseId) + path.sep)) {
    throw new NarratedExportError('unsafe_audio_path', 'The classroom audio directory is outside the managed course directory.');
  }
  return real;
}
export async function loadNarratedExportManagedAudio(reference: string): Promise<StoredAudio | null> {
  let pathname: string;
  try { pathname = new URL(reference, 'http://local.invalid').pathname; } catch { return null; }
  const match = pathname.match(/^\/api\/classroom-media\/([a-zA-Z0-9_-]{1,128})\//);
  if (!match) return null;
  // A registered export snapshot can retain its original course's public,
  // managed media reference. Reading it never writes into that source course.
  const referenceCourseId = match[1];
  const prefix = `/api/classroom-media/${referenceCourseId}/`;
  let relative: string;
  try { relative = decodeURIComponent(pathname.slice(prefix.length)); } catch { return null; }
  if (!/^(audio|media)\/[^/\\\0]+\.(wav|mp3|ogg|aac)$/.test(relative) || relative.includes('..')) return null;
  const base = path.resolve(CLASSROOMS_DIR, referenceCourseId);
  try {
    const filename = await fs.realpath(path.join(base, relative));
    if (!filename.startsWith(base + path.sep)) return null;
    const bytes = await fs.readFile(filename);
    if (!bytes.length) return null;
    const durationSeconds = relative.endsWith('.wav') ? inspectWindowsPcmWav(bytes).durationSeconds : undefined;
    const audioUrl = `${prefix}${relative}`;
    return { audioId: audioUrl, audioUrl, ...(durationSeconds ? { durationSeconds } : {}) };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
}
const defaultDeps: NarratedExportDeps = {
  readCourse: readClassroom,
  loadAudio: (_courseId, reference) => loadNarratedExportManagedAudio(reference),
  synthesize: generateTTS,
  async readCache(courseId, key) {
    try { return JSON.parse(await fs.readFile(path.join(await checkedAudioDirectory(courseId), `narrated-${key}.json`), 'utf8')); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null; throw error; }
  },
  async writeCache(courseId, key, result) {
    const file = path.join(await checkedAudioDirectory(courseId), `narrated-${key}.json`);
    await withClassroomWrite(courseId, () => writeJsonFileAtomic(file, result));
  },
  async saveAudio(courseId, id, audio, format) {
    if (!['wav', 'mp3', 'ogg', 'aac'].includes(format) || !audio.length) {
      throw new NarratedExportError('invalid_audio', 'The speech service did not return complete audio suitable for export.');
    }
    const durationSeconds = format === 'wav' ? inspectWindowsPcmWav(audio).durationSeconds : undefined;
    const filename = `${id}.${format}`;
    const file = path.join(await checkedAudioDirectory(courseId), filename);
    await withClassroomWrite(courseId, () => fs.writeFile(file, audio, { flag: 'wx' }).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== 'EEXIST') throw error;
    }));
    const audioUrl = `/api/classroom-media/${courseId}/audio/${filename}`;
    return { audioId: audioUrl, audioUrl, ...(durationSeconds ? { durationSeconds } : {}) };
  },
};

/** No implicit cloud fallback: only a request-scoped explicit provider can replace Windows. */
export interface FullNarratedExportInput {
  courseId: string;
  scenes: Scene[];
  ttsConfig?: ContestProviderOptions['ttsConfig'];
  signal?: AbortSignal;
}
const preparing = new Map<string, Promise<FullNarratedExport>>();
export async function prepareFullNarratedExport(
  input: FullNarratedExportInput, deps: NarratedExportDeps = defaultDeps,
): Promise<FullNarratedExport> {
  const course = await readCheckedExportCourse(input, deps);
  const key = sha(JSON.stringify({ courseId: input.courseId, scenes: input.scenes,
    provider: input.ttsConfig?.providerId, voice: input.ttsConfig?.voice,
    model: input.ttsConfig?.modelId, endpoint: input.ttsConfig?.baseUrl }));
  let pending = preparing.get(key);
  if (!pending) {
    pending = withClassroomOperation(input.courseId, input.signal,
      signal => prepareFullNarratedExportOnce({ ...input, signal }, deps, course));
    preparing.set(key, pending);
    const release = () => { if (preparing.get(key) === pending) preparing.delete(key); };
    pending.then(release, release);
  }
  const result = await pending;
  input.signal?.throwIfAborted();
  // A saved audit may have been invalidated while shared preparation was pending.
  await readCheckedExportCourse(input, deps);
  return structuredClone(result);
}
async function readCheckedExportCourse(input: FullNarratedExportInput, deps: NarratedExportDeps): Promise<PersistedClassroomData> {
  if (!isValidClassroomId(input.courseId) || input.courseId.length > 128 || !input.scenes.length ||
    input.scenes.length > 200 || input.scenes.some((scene) => scene.stageId !== input.courseId)) {
    throw new NarratedExportError('invalid_snapshot', 'The course identifier does not match the export scenes, or the classroom snapshot exceeds the limit.', 400);
  }
  const course = await deps.readCourse(input.courseId);
  if (!course || course.stage.id !== input.courseId) {
    throw new NarratedExportError('course_not_found', 'The saved source classroom was not found. Save the classroom before exporting.', 404);
  }
  await assertSourceReviewComplete(course, deps);
  return course;
}
async function prepareFullNarratedExportOnce(
  input: FullNarratedExportInput, deps: NarratedExportDeps, course: PersistedClassroomData,
): Promise<FullNarratedExport> {
  const sourceSha256 = narrationSourceHash(input.scenes);
  if (sourceSha256 !== narrationSourceHash(course.scenes)) {
    throw new NarratedExportError('source_changed', 'The classroom snapshot differs from the saved source. Save again and restart the export.', 409);
  }
  const config: TTSModelConfig = input.ttsConfig ?? {
    providerId: 'windows-system-tts', modelId: 'system-speech', voice: 'auto-en',
  };
  if (!['windows-system-tts', 'openai-tts'].includes(config.providerId)) {
    throw new NarratedExportError('unsupported_provider', 'Complete export does not support this speech provider.', 400);
  }
  const key = sha(JSON.stringify({ version: NARRATED_EXPORT_VERSION, sourceSha256,
    transport: input.scenes.map((scene) => (scene.actions ?? []).filter((a) => a.type === 'speech')
      .map((a) => ({ id: a.id, audioId: (a as ExportSpeech).audioId, audioUrl: (a as ExportSpeech).audioUrl }))),
    provider: config.providerId, model: config.modelId, voice: config.voice, endpoint: config.baseUrl }));
  const cached = await deps.readCache(input.courseId, key);
  if (cached?.version === 1 && cached.sourceSha256 === sourceSha256 && cached.courseId === input.courseId) {
    // Even a valid persistent manifest must not advertise an evicted/corrupt file.
    for (const clip of cached.coverage.clips) {
      if (clip.generated && !(await deps.loadAudio(input.courseId, clip.audioUrl ?? clip.audioId))) {
        throw new NarratedExportError('cached_audio_missing', 'Cached export narration files are missing. Restore classroom audio and retry.');
      }
    }
    return { ...structuredClone(cached), provenance: exportProvenance(course) };
  }
  const scenes = createNarratedExportScenes(input.scenes);
  for (const scene of scenes) {
    if (!(scene.actions ?? []).some((a) => a.type === 'speech' && a.text.trim())) {
      throw new NarratedExportError('missing_scene_narration', `Scene: ${scene.title} has no narration text. A complete narrated video cannot be generated.`);
    }
  }
  const clips: NarratedExportClip[] = [];
  for (const scene of scenes) {
    input.signal?.throwIfAborted();
    scene.actions = (scene.actions ?? []).flatMap((action): Action[] => {
      if (action.type !== 'speech' || !action.text.trim() || action.audioId || (action as ExportSpeech).audioUrl) return [action];
      return splitLongSpeechText(action.text, 1_000).map((text, index) => ({
        ...action, text, id: `${action.id}-export-part-${index + 1}`,
      }));
    });
    for (const action of scene.actions) {
      if (action.type !== 'speech' || !action.text.trim()) continue;
      const speech = action as ExportSpeech;
      const reference = speech.audioUrl || speech.audioId;
      let audio: StoredAudio | null = null;
      let generated = false;
      if (reference) {
        audio = await deps.loadAudio(input.courseId, reference);
        if (!audio && reference.includes('/api/classroom-media/')) {
          throw new NarratedExportError('source_audio_missing', `Scene: ${scene.title} source narration could not be read.`);
        }
        // Browser-owned pool/Dexie and remote references are validated against
        // their actual bytes by the client before compiling the complete IR.
        if (!audio) audio = { audioId: speech.audioId || reference, audioUrl: speech.audioUrl || reference };
      } else {
        const id = `export-${sha(`${key}\n${scene.id}\n${speech.id}\n${speech.text}`).slice(0, 40)}`;
        for (const format of ['wav', 'mp3', 'ogg', 'aac']) {
          audio = await deps.loadAudio(input.courseId, `/api/classroom-media/${input.courseId}/audio/${id}.${format}`);
          if (audio) break;
        }
        if (!audio) {
          if (isServerTTSProviderDisabled(config.providerId)) {
            throw new NarratedExportError('provider_disabled', 'The selected speech provider is disabled.', 403);
          }
          if (config.providerId !== 'windows-system-tts' && !config.apiKey) {
            throw new NarratedExportError('missing_api_key', 'Cloud narration requires your API key for this request.', 400);
          }
          const result = await deps.synthesize({ ...config, speed: 1, managed: false,
            publicOnly: Boolean(config.baseUrl), signal: input.signal }, speech.text);
          input.signal?.throwIfAborted();
          audio = await deps.saveAudio(input.courseId, id, result.audio, result.format);
        }
        generated = true;
      }
      speech.audioId = audio.audioId;
      speech.audioUrl = audio.audioUrl;
      clips.push({ sceneId: scene.id, actionId: speech.id, ...audio,
        characters: speech.text.length, textSha256: sha(speech.text), generated });
    }
  }
  const result: FullNarratedExport = {
    version: 1, courseId: input.courseId, sourceSha256, exportSha256: sha(JSON.stringify(scenes)), scenes,
    provenance: exportProvenance(course),
    coverage: { sceneCount: scenes.length, voicedSceneCount: scenes.length,
      speechCount: clips.length, voicedSpeechCount: clips.length,
      spokenCharacters: clips.reduce((sum, clip) => sum + clip.characters, 0),
      quizQuestionCount: scenes.filter((scene) => scene.narratedExport?.kind === 'question').length,
      quizAnalysisCount: scenes.filter((scene) => scene.narratedExport?.kind === 'analysis').length, clips },
  };
  await deps.writeCache(input.courseId, key, result);
  return result;
}

async function assertSourceReviewComplete(course: PersistedClassroomData, deps: NarratedExportDeps): Promise<void> {
  const visited = new Set<string>();
  let saved: PersistedClassroomData | null = course;
  while (saved && !visited.has(saved.stage.id)) {
    visited.add(saved.stage.id);
    if (saved.stage.sourceFidelity?.status === 'needs_review') {
      throw new NarratedExportError('source_review_required', 'Classroom source review has not passed. Complete source review before exporting the full narrated video.', 409);
    }
    // Export snapshots deliberately do not copy an audit verdict. Read their
    // actual saved origin instead, including an origin that is itself a snapshot.
    // A missing/unknown legacy verdict is not promoted to verified or rejected.
    const originalStageId = (saved.stage as { exportSnapshot?: { originalStageId?: unknown } })
      .exportSnapshot?.originalStageId;
    if (typeof originalStageId !== 'string' || originalStageId.length > 128 ||
      !isValidClassroomId(originalStageId) || visited.has(originalStageId)) break;
    saved = await deps.readCourse(originalStageId);
    if (saved && saved.stage.id !== originalStageId) break;
  }
}

function exportProvenance(course: PersistedClassroomData): FullNarratedExport['provenance'] {
  return { kind: (course.stage as { exportSnapshot?: unknown }).exportSnapshot ? 'export-snapshot' : 'saved-classroom',
    ...(course.stage.sourceFidelity ? { sourceFidelity: course.stage.sourceFidelity.status } : {}) };
}
