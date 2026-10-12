import { NextRequest } from 'next/server';
import { apiError, apiSuccess, type ApiErrorCode } from '@/lib/server/api-response';
import { contestProviderFromHeaders } from '@/lib/server/contest-provider';
import { registerTransientLogSecrets } from '@/lib/logger';
import { NarratedExportError, prepareFullNarratedExport } from '@/lib/server/full-narrated-export';
import { WindowsTtsError } from '@/lib/server/windows-system-tts';
import type { Scene } from '@/lib/types/stage';

export const maxDuration = 300;
const MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024;

/** Prepare only an export clone; this route never changes classroom JSON or original actions. */
export async function POST(req: NextRequest) {
  let releaseSecrets: (() => void) | undefined;
  try {
    if (Number(req.headers.get('content-length') || 0) > MAX_SNAPSHOT_BYTES || !req.body) {
      return apiError('INVALID_REQUEST', 413, 'The classroom export snapshot is too large or empty.');
    }
    const reader = req.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_SNAPSHOT_BYTES) {
          await reader.cancel();
          return apiError('INVALID_REQUEST', 413, 'The classroom export snapshot is too large.');
        }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    let body: { courseId?: unknown; scenes?: unknown };
    try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
    catch { return apiError('INVALID_REQUEST', 400, 'The classroom export snapshot is not valid JSON.'); }
    if (!body || typeof body !== 'object' || typeof body.courseId !== 'string' || !Array.isArray(body.scenes) ||
      body.scenes.some((scene) => !scene || typeof scene !== 'object' || typeof scene.id !== 'string' ||
        typeof scene.stageId !== 'string' || typeof scene.title !== 'string' || !scene.content ||
        !['slide', 'quiz', 'interactive', 'pbl'].includes(scene.type) || scene.content.type !== scene.type ||
        !Array.isArray(scene.actions ?? []) || (scene.actions ?? []).some((action: unknown) =>
          !action || typeof action !== 'object' || typeof (action as { type?: unknown }).type !== 'string' ||
          ((action as { type?: unknown }).type === 'speech' && typeof (action as { text?: unknown }).text !== 'string')) ||
        (scene.type === 'quiz' && (!Array.isArray(scene.content.questions) || scene.content.questions.some((question: unknown) =>
          !question || typeof question !== 'object' || typeof (question as { question?: unknown }).question !== 'string'))))) {
      return apiError('INVALID_REQUEST', 400, 'A source course identifier and complete scene snapshot are required.');
    }
    const options = await contestProviderFromHeaders(req);
    releaseSecrets = registerTransientLogSecrets([options.ttsConfig?.apiKey]);
    const prepared = await prepareFullNarratedExport({
      courseId: body.courseId, scenes: body.scenes as Scene[], ttsConfig: options.ttsConfig, signal: req.signal,
    });
    return apiSuccess({ ...prepared });
  } catch (error) {
    if (error instanceof NarratedExportError) {
      return apiError('INVALID_REQUEST', error.status, error.message, undefined, error.reason);
    }
    if (error instanceof WindowsTtsError) {
      return apiError(error.code as ApiErrorCode, error.httpStatus, error.message);
    }
    // Never return arbitrary provider error text or request-scoped credentials.
    return apiError('GENERATION_FAILED', 502, 'Narration preparation for complete export failed. Check local voices or the speech service configuration.');
  } finally { releaseSecrets?.(); }
}
