import { promises as fs } from 'fs';
import path from 'path';
import { randomUUID } from 'node:crypto';
import type {
  ClassroomGenerationProgress,
  ClassroomGenerationStep,
  GenerateClassroomInput,
  GenerateClassroomResult,
} from '@/lib/server/classroom-generation';
import {
  CLASSROOM_JOBS_DIR,
  ensureClassroomJobsDir,
  writeJsonFileAtomic,
  writeJsonFileExclusive,
} from '@/lib/server/classroom-storage';
import { withClassroomJobWrite } from './classroom-lifecycle';

export type ClassroomGenerationJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'interrupted';

// DeepSteam: a process-wide identity survives Next's separate route bundles and
// module reloads, but not an actual service restart. Never persist credentials.
const runtimeGlobal = globalThis as typeof globalThis & {
  __deepsteamClassroomJobRuntime?: { id: string; locks: Map<string, Promise<void>> };
};
const runtime = runtimeGlobal.__deepsteamClassroomJobRuntime ??= {
  id: randomUUID(), locks: new Map(),
};
export const CLASSROOM_JOB_LEASE_MS = 90_000;
export const CLASSROOM_JOB_HEARTBEAT_MS = 10_000;

export class ClassroomJobRecoveryError extends Error {
  constructor(message: string, readonly status = 409) { super(message); }
}

type RecoverableInput = Omit<GenerateClassroomInput, 'webSearchApiKey'>;

/** A saved draft remains failed; this result only exposes its review location. */
export interface ClassroomReviewDraftResult {
  classroomId: string;
  url: string;
  scenesCount: number;
  reviewRequired: true;
  sourceFidelity: 'needs_review';
}

export interface ClassroomGenerationJob {
  id: string;
  status: ClassroomGenerationJobStatus;
  step: ClassroomGenerationStep | 'queued' | 'failed' | 'interrupted';
  progress: number;
  message: string;
  createdAt: string;
  updatedAt: string;
  startedAt?: string;
  completedAt?: string;
  inputSummary: {
    requirementPreview: string;
    hasPdf: boolean;
    pdfTextLength: number;
    pdfImageCount: number;
  };
  scenesGenerated: number;
  totalScenes?: number;
  result?: {
    classroomId: string;
    url: string;
    scenesCount: number;
    ttsCoverage?: GenerateClassroomResult['ttsCoverage'];
    warning?: string;
    reviewRequired?: true;
    sourceFidelity?: 'needs_review';
    resolvedModel?: GenerateClassroomResult['resolvedModel'];
    modelSnapshot?: GenerateClassroomResult['modelSnapshot'];
    stageModels?: GenerateClassroomResult['stageModels'];
  };
  error?: string;
  execution?: {
    attemptId: string;
    attempt: number;
    ownerId: string;
    ownerPid: number;
    heartbeatAt: string;
  };
  recovery?: { version: 1; input: RecoverableInput; requiresWebSearchCredential: boolean };
  lastAttempt?: {
    attemptId: string;
    step: ClassroomGenerationJob['step'];
    progress: number;
    scenesGenerated: number;
    stoppedAt: string;
  };
}

function jobFilePath(jobId: string) {
  return path.join(CLASSROOM_JOBS_DIR, `${jobId}.json`);
}

function buildInputSummary(input: GenerateClassroomInput): ClassroomGenerationJob['inputSummary'] {
  return {
    requirementPreview:
      input.requirement.length > 200 ? `${input.requirement.slice(0, 197)}...` : input.requirement,
    hasPdf: !!input.pdfContent,
    pdfTextLength: input.pdfContent?.text.length || 0,
    pdfImageCount: input.pdfContent?.images.length || 0,
  };
}

/** Simple per-job mutex to serialize read-modify-write on the same job file. */
const jobLocks = runtime.locks;

async function withJobLock<T>(jobId: string, fn: () => Promise<T>): Promise<T> {
  const key = jobFilePath(jobId);
  const prev = jobLocks.get(key) ?? Promise.resolve();
  let resolve: () => void;
  const next = new Promise<void>((r) => {
    resolve = r;
  });
  jobLocks.set(key, next);
  try {
    await prev;
    return await withClassroomJobWrite(jobId, fn);
  } finally {
    resolve!();
    if (jobLocks.get(key) === next) jobLocks.delete(key);
  }
}

function active(job: ClassroomGenerationJob) {
  return job.status === 'queued' || job.status === 'running';
}

function execution(attempt: number): NonNullable<ClassroomGenerationJob['execution']> {
  return { attemptId: randomUUID(), attempt, ownerId: runtime.id, ownerPid: process.pid,
    heartbeatAt: new Date().toISOString() };
}

/** Explicit allowlist at every object level; signed URLs cannot be saved safely. */
function recoverableInput(input: GenerateClassroomInput): RecoverableInput | undefined {
  if (input.pdfContent?.images.some(src => {
    if (/^data:image\/[a-z0-9.+-]+;base64,[a-z0-9+/=\s]+$/i.test(src)) return false;
    try {
      const url = new URL(src, 'http://source.invalid');
      return !!(url.username || url.password || url.search || url.hash) || !['http:', 'https:'].includes(url.protocol);
    } catch { return true; }
  })) return undefined;
  const saved: RecoverableInput = { requirement: input.requirement };
  if (input.pdfContent) saved.pdfContent = {
    text: input.pdfContent.text, images: [...input.pdfContent.images],
    ...(input.pdfContent.image_sources ? { image_sources: input.pdfContent.image_sources.map(source => ({
      image_index: source.image_index, asset_id: source.asset_id,
      document_sha256: source.document_sha256,
      ...(source.source_document_name !== undefined ? { source_document_name: source.source_document_name } : {}),
      locator: Object.fromEntries(Object.entries(source.locator).filter(([key]) =>
        ['page', 'page_kind', 'slide', 'paragraph', 'table', 'line_start', 'line_end', 'row', 'sheet', 'image', 'part', 'section'].includes(key))),
    })) } : {}),
  };
  for (const key of ['enableWebSearch', 'enableImageGeneration', 'enableVideoGeneration', 'enableTTS', 'allowSupplementaryExamples'] as const) {
    if (typeof input[key] === 'boolean') saved[key] = input[key];
  }
  if (input.webSearchProviderId) saved.webSearchProviderId = input.webSearchProviderId;
  if (input.webSearchModelId) saved.webSearchModelId = input.webSearchModelId;
  if (input.agentMode) saved.agentMode = input.agentMode;
  if (input.baiduSubSources) saved.baiduSubSources = {
    webSearch: input.baiduSubSources.webSearch === true,
    baike: input.baiduSubSources.baike === true,
    scholar: input.baiduSubSources.scholar === true,
  };
  return saved;
}

function lostOwner(job: ClassroomGenerationJob): boolean {
  if (!job.execution) return true; // Legacy pending jobs have no resumable owner.
  const owner = job.execution;
  if (owner.ownerId !== runtime.id) {
    if (owner.ownerPid === process.pid) return true; // PID reuse is not ownership.
    try { process.kill(owner.ownerPid, 0); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === 'ESRCH') return true; }
  }
  const lastHeartbeat = Date.parse(owner.heartbeatAt);
  return !Number.isFinite(lastHeartbeat) || Date.now() - lastHeartbeat > CLASSROOM_JOB_LEASE_MS;
}

function reconcile(job: ClassroomGenerationJob): ClassroomGenerationJob {
  if (!active(job) || !lostOwner(job)) return job;
  const now = new Date().toISOString();
  return { ...job, status: 'interrupted', step: 'interrupted', completedAt: now, updatedAt: now,
    lastAttempt: { attemptId: job.execution?.attemptId ?? 'legacy', step: job.step,
      progress: job.progress, scenesGenerated: job.scenesGenerated, stoppedAt: now },
    message: job.recovery
      ? 'Generation was interrupted. Saved sources and settings are available for an explicit retry from the beginning.'
      : 'Generation was interrupted. No safe recovery input is available; submit the source again.',
    error: 'CLASSROOM_GENERATION_INTERRUPTED',
  };
}

export function isValidClassroomJobId(jobId: string): boolean {
  return /^[a-zA-Z0-9_-]{1,100}$/.test(jobId);
}

export async function createClassroomGenerationJob(
  jobId: string,
  input: GenerateClassroomInput,
): Promise<ClassroomGenerationJob> {
  const now = new Date().toISOString();
  const inputForRecovery = recoverableInput(input);
  const job: ClassroomGenerationJob = {
    id: jobId,
    status: 'queued',
    step: 'queued',
    progress: 0,
    message: 'Classroom generation job queued',
    createdAt: now,
    updatedAt: now,
    inputSummary: buildInputSummary(input),
    scenesGenerated: 0,
    execution: execution(1),
    ...(inputForRecovery ? { recovery: { version: 1, input: inputForRecovery,
      requiresWebSearchCredential: !!input.webSearchApiKey } } : {}),
  };

  await withClassroomJobWrite(jobId, async () => {
    await ensureClassroomJobsDir();
    await writeJsonFileExclusive(jobFilePath(jobId), job);
  });
  return job;
}

async function readRawJob(
  jobId: string,
): Promise<ClassroomGenerationJob | null> {
  try {
    const content = await fs.readFile(jobFilePath(jobId), 'utf-8');
    const job = JSON.parse(content) as ClassroomGenerationJob;
    return job;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return null;
    }
    throw error;
  }
}

/** Reconciliation is durable, including queued jobs; GET never starts generation. */
export async function readClassroomGenerationJob(jobId: string): Promise<ClassroomGenerationJob | null> {
  return withJobLock(jobId, async () => {
    const existing = await readRawJob(jobId);
    if (!existing) return null;
    const job = reconcile(existing);
    if (job !== existing) await writeJsonFileAtomic(jobFilePath(jobId), job);
    return job;
  });
}

/** Also used by lifecycle writes so late provider results cannot write classroom files. */
export async function assertClassroomGenerationAttempt(jobId: string, attemptId: string): Promise<void> {
  const job = await readRawJob(jobId);
  if (!job || !active(job) || job.execution?.attemptId !== attemptId || lostOwner(job)) {
    throw new DOMException('Classroom generation attempt is no longer active', 'AbortError');
  }
}

export async function retryClassroomGenerationJob(jobId: string, retryFromAttempt: string,
  webSearchApiKey?: string): Promise<{ job: ClassroomGenerationJob; input?: GenerateClassroomInput; started: boolean }> {
  return withJobLock(jobId, async () => {
    const existing = await readRawJob(jobId);
    if (!existing) throw new ClassroomJobRecoveryError('Classroom generation job not found', 404);
    const job = reconcile(existing);
    if (job !== existing) await writeJsonFileAtomic(jobFilePath(jobId), job);
    // A delayed duplicate retry refers to the old attempt even if the next one
    // has already ended. Return its state; never start another paid execution.
    if ((job.execution?.attemptId ?? 'legacy') !== retryFromAttempt || active(job) || job.status === 'succeeded') {
      return { job, started: false };
    }
    if (!job.recovery) throw new ClassroomJobRecoveryError('No safe saved input is available. Submit the source again.');
    if (job.recovery.requiresWebSearchCredential && !webSearchApiKey) {
      throw new ClassroomJobRecoveryError('A current web search credential is required to retry this job.');
    }
    const now = new Date().toISOString();
    const next: ClassroomGenerationJob = { ...job, status: 'queued', step: 'queued', progress: 0,
      message: 'Explicit retry queued using saved sources and settings', updatedAt: now,
      startedAt: undefined, completedAt: undefined, error: undefined, result: undefined,
      scenesGenerated: 0, totalScenes: undefined,
      lastAttempt: job.lastAttempt?.attemptId === retryFromAttempt ? job.lastAttempt : { attemptId: retryFromAttempt, step: job.step,
        progress: job.progress, scenesGenerated: job.scenesGenerated, stoppedAt: now },
      execution: execution((job.execution?.attempt ?? 0) + 1),
    };
    await writeJsonFileAtomic(jobFilePath(jobId), next);
    return { job: next, started: true, input: { ...job.recovery.input,
      ...(webSearchApiKey ? { webSearchApiKey } : {}) } };
  });
}

export async function updateClassroomGenerationJob(
  jobId: string,
  patch: Partial<ClassroomGenerationJob>,
  attemptId?: string,
): Promise<ClassroomGenerationJob> {
  return withJobLock(jobId, async () => {
    const existing = await readRawJob(jobId);
    if (!existing) {
      throw new Error(`Classroom generation job not found: ${jobId}`);
    }
    if (attemptId) await assertClassroomGenerationAttempt(jobId, attemptId);
    if (!active(existing)) throw new DOMException('Classroom job is terminal', 'AbortError');

    const updated: ClassroomGenerationJob = {
      ...existing,
      ...patch,
      updatedAt: new Date().toISOString(),
    };

    await writeJsonFileAtomic(jobFilePath(jobId), updated);
    return updated;
  });
}

export async function markClassroomGenerationJobRunning(
  jobId: string,
  attemptId?: string,
): Promise<ClassroomGenerationJob | null> {
  return withJobLock(jobId, async () => {
    const existing = await readRawJob(jobId);
    if (!existing) {
      throw new Error(`Classroom generation job not found: ${jobId}`);
    }
    if (attemptId) await assertClassroomGenerationAttempt(jobId, attemptId);
    if (existing.status !== 'queued') return null;

    const updated: ClassroomGenerationJob = {
      ...existing,
      status: 'running',
      startedAt: existing.startedAt || new Date().toISOString(),
      message: 'Classroom generation started',
      updatedAt: new Date().toISOString(),
    };

    await writeJsonFileAtomic(jobFilePath(jobId), updated);
    return updated;
  });
}

export async function heartbeatClassroomGenerationJob(jobId: string, attemptId: string): Promise<void> {
  await withJobLock(jobId, async () => {
    await assertClassroomGenerationAttempt(jobId, attemptId);
    const job = (await readRawJob(jobId))!;
    job.execution!.heartbeatAt = new Date().toISOString();
    await writeJsonFileAtomic(jobFilePath(jobId), job);
  });
}

export async function updateClassroomGenerationJobProgress(
  jobId: string,
  progress: ClassroomGenerationProgress,
  attemptId?: string,
): Promise<ClassroomGenerationJob> {
  return updateClassroomGenerationJob(jobId, {
    status: 'running',
    step: progress.step,
    progress: progress.progress,
    message: progress.message,
    scenesGenerated: progress.scenesGenerated,
    totalScenes: progress.totalScenes,
  }, attemptId);
}

export async function markClassroomGenerationJobSucceeded(
  jobId: string,
  result: GenerateClassroomResult,
  attemptId?: string,
): Promise<ClassroomGenerationJob> {
  return updateClassroomGenerationJob(jobId, {
    status: 'succeeded',
    step: 'completed',
    progress: 100,
    message: result.warning ?? 'Classroom generation completed',
    completedAt: new Date().toISOString(),
    scenesGenerated: result.scenesCount,
    result: {
      classroomId: result.id,
      resolvedModel: result.resolvedModel,
      modelSnapshot: result.modelSnapshot,
      stageModels: result.stageModels,
      url: result.url,
      scenesCount: result.scenesCount,
      ...(result.ttsCoverage ? { ttsCoverage: result.ttsCoverage } : {}),
      ...(result.warning ? { warning: result.warning } : {}),
    },
  }, attemptId);
}

export async function markClassroomGenerationJobFailed(
  jobId: string,
  error: string,
  reviewDraft?: ClassroomReviewDraftResult,
  attemptId?: string,
): Promise<ClassroomGenerationJob> {
  return updateClassroomGenerationJob(jobId, {
    status: 'failed',
    step: 'failed',
    message: reviewDraft ? 'Classroom generation failed; a source-unverified draft is retained for review' : 'Classroom generation failed',
    completedAt: new Date().toISOString(),
    error,
    // No success, TTS coverage, or READY state is inferred from retained scenes.
    result: reviewDraft,
    ...(reviewDraft ? { scenesGenerated: reviewDraft.scenesCount } : {}),
  }, attemptId);
}
