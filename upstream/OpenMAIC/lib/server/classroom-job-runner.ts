import { createLogger, registerTransientLogSecrets } from '@/lib/logger';
import { redactContestSecrets, type ContestProviderOptions } from '@/lib/server/contest-provider';
import { generateClassroom, type GenerateClassroomInput } from '@/lib/server/classroom-generation';
import { SourceFidelityError } from '@/lib/server/source-grounding';
import { isValidClassroomId, readClassroom } from '@/lib/server/classroom-storage';
import { registerClassroomRunner, withClassroomJob } from './classroom-lifecycle';
import {
  markClassroomGenerationJobFailed,
  markClassroomGenerationJobRunning,
  markClassroomGenerationJobSucceeded,
  updateClassroomGenerationJobProgress,
  readClassroomGenerationJob,
  assertClassroomGenerationAttempt,
  heartbeatClassroomGenerationJob,
  CLASSROOM_JOB_HEARTBEAT_MS,
  type ClassroomReviewDraftResult,
} from '@/lib/server/classroom-job-store';

const log = createLogger('ClassroomJob');
const runnerGlobal = globalThis as typeof globalThis & { __deepsteamClassroomRunners?: Map<string, Promise<void>> };
const runningJobs = runnerGlobal.__deepsteamClassroomRunners ??= new Map<string, Promise<void>>();

export function runClassroomGenerationJob(
  jobId: string,
  input: GenerateClassroomInput,
  baseUrl: string,
  providerOptions: ContestProviderOptions = {},
  attemptId?: string,
): Promise<void> {
  const runKey = `${jobId}:${attemptId ?? 'initial'}`;
  const existing = runningJobs.get(runKey);
  if (existing) {
    return existing;
  }

  const controller = new AbortController();
  const jobPromise = (async () => {
    const ownedAttempt = attemptId ?? (await readClassroomGenerationJob(jobId))?.execution?.attemptId;
    if (!ownedAttempt) return;
    return withClassroomJob(jobId, controller.signal, async () => {
    const releaseSecrets = registerTransientLogSecrets([
      providerOptions.modelConfig?.apiKey, providerOptions.ttsConfig?.apiKey, input.webSearchApiKey,
    ]);
    let heartbeat: ReturnType<typeof setInterval> | undefined;
    let heartbeatPending = false;
    try {
      // Claim queued -> running once before any model request, including when
      // multiple route bundles schedule the same persisted attempt.
      if (!await markClassroomGenerationJobRunning(jobId, ownedAttempt)) return;
      heartbeat = setInterval(() => {
        if (heartbeatPending) return;
        heartbeatPending = true;
        void heartbeatClassroomGenerationJob(jobId, ownedAttempt)
          .catch(() => controller.abort())
          .finally(() => { heartbeatPending = false; });
      }, CLASSROOM_JOB_HEARTBEAT_MS);
      heartbeat.unref?.();

      const result = await generateClassroom(input, {
        baseUrl,
        signal: controller.signal,
        ...providerOptions,
        onProgress: async (progress) => {
          await updateClassroomGenerationJobProgress(jobId, progress, ownedAttempt);
        },
      });

      await markClassroomGenerationJobSucceeded(jobId, result, ownedAttempt);
    } catch (error) {
      if (controller.signal.aborted || (error instanceof Error && error.name === 'AbortError')) return;
      const safeMessage = redactContestSecrets(error instanceof Error ? error.message : String(error), providerOptions);
      const message = input.webSearchApiKey ? safeMessage.split(input.webSearchApiKey).join('[REDACTED]') : safeMessage;
      log.error(`Classroom generation job ${jobId} failed:`, message);
      try {
        let reviewDraft: ClassroomReviewDraftResult | undefined;
        if (error instanceof SourceFidelityError && error.classroomId
            && isValidClassroomId(error.classroomId)) {
          // The exception names a persisted draft. Verify the actual saved
          // document before presenting any review link; placeholders and
          // unrelated failures must keep their original no-draft behavior.
          try {
            const saved = await readClassroom(error.classroomId);
            if (saved && saved.id === error.classroomId && saved.stage.id === error.classroomId
                && saved.reserved !== true && saved.stage.sourceFidelity?.status === 'needs_review'
                && Array.isArray(saved.scenes) && saved.scenes.length > 0) {
              reviewDraft = {
                classroomId: saved.id,
                url: new URL(`/classroom/${encodeURIComponent(saved.id)}`, baseUrl).toString(),
                scenesCount: saved.scenes.length,
                reviewRequired: true,
                sourceFidelity: 'needs_review',
              };
            }
          } catch {
            log.error(`Could not verify retained review draft for job ${jobId}`);
          }
        }
        await markClassroomGenerationJobFailed(jobId, message, reviewDraft, ownedAttempt);
      } catch (markFailedError) {
        log.error(`Failed to persist failed status for job ${jobId}:`, markFailedError);
      }
    } finally {
      releaseSecrets();
      clearInterval(heartbeat);
    }
    }, () => assertClassroomGenerationAttempt(jobId, ownedAttempt));
  })().catch(error => {
    if (controller.signal.aborted || (error instanceof Error && error.name === 'AbortError')) return;
    throw error;
  });

  runningJobs.set(runKey, jobPromise);
  void jobPromise.finally(() => { if (runningJobs.get(runKey) === jobPromise) runningJobs.delete(runKey); }).catch(() => {});
  registerClassroomRunner(jobId, controller, jobPromise);
  return jobPromise;
}
