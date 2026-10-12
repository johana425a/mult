import { after, type NextRequest } from 'next/server';
import { nanoid } from 'nanoid';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { type GenerateClassroomInput } from '@/lib/server/classroom-generation';
import { runClassroomGenerationJob } from '@/lib/server/classroom-job-runner';
import { createClassroomGenerationJob, isValidClassroomJobId, readClassroomGenerationJob,
  retryClassroomGenerationJob, ClassroomJobRecoveryError,
  type ClassroomGenerationJob } from '@/lib/server/classroom-job-store';
import { buildRequestOrigin } from '@/lib/server/classroom-storage';
import { createLogger } from '@/lib/logger';
import { contestProviderFromHeaders } from '@/lib/server/contest-provider';
import { validClassroomImageSources } from '@/lib/server/classroom-image-sources';

const log = createLogger('GenerateClassroom API');

export const maxDuration = 30;

type PdfContent = NonNullable<GenerateClassroomInput['pdfContent']>;

function isValidPdfContent(value: unknown): value is PdfContent {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return false;
  }

  const { text, images, image_sources } = value as { text?: unknown; images?: unknown; image_sources?: unknown };
  return (
    typeof text === 'string' &&
    Array.isArray(images) &&
    images.every((item) => typeof item === 'string') &&
    (image_sources === undefined || validClassroomImageSources(image_sources, images.length))
  );
}

function jobResponse(job: ClassroomGenerationJob, baseUrl: string, status = 200) {
  return apiSuccess({ jobId: job.id, status: job.status, step: job.step,
    progress: job.progress, message: job.message, result: job.result, error: job.error,
    pollUrl: `${baseUrl}/api/generate-classroom/${job.id}`, pollIntervalMs: 5000,
    done: ['succeeded', 'failed', 'interrupted'].includes(job.status),
    attemptId: job.execution?.attemptId ?? 'legacy', attempt: job.execution?.attempt ?? 0,
    retryable: ['failed', 'interrupted'].includes(job.status) && !!job.recovery,
    retryMode: 'restart', lastAttempt: job.lastAttempt,
  }, status);
}

export async function POST(req: NextRequest) {
  let requirementSnippet: string | undefined;
  try {
    const rawBody = (await req.json()) as Partial<GenerateClassroomInput> & {
      jobId?: string; retry?: boolean; retryFromAttempt?: string;
    };
    if (!rawBody || typeof rawBody !== 'object' || Array.isArray(rawBody)) return apiError('INVALID_REQUEST', 400, 'Invalid request');
    if (rawBody.jobId !== undefined && (typeof rawBody.jobId !== 'string' || !isValidClassroomJobId(rawBody.jobId))) return apiError('INVALID_REQUEST', 400, 'Invalid job id');
    if (rawBody.retry !== undefined && typeof rawBody.retry !== 'boolean') return apiError('INVALID_REQUEST', 400, 'Invalid retry flag');
    const baseUrl = buildRequestOrigin(req);
    if (rawBody.retry === true) {
      if (!rawBody.jobId || typeof rawBody.retryFromAttempt !== 'string' || !/^[a-zA-Z0-9_-]{1,100}$/.test(rawBody.retryFromAttempt)) {
        return apiError('INVALID_REQUEST', 400, 'Explicit retry requires jobId and retryFromAttempt');
      }
      // The caller must explicitly opt in. Credentials are resolved afresh and
      // only the saved source/parameter allowlist is supplied to generation.
      const providerOptions = await contestProviderFromHeaders(req);
      const retried = await retryClassroomGenerationJob(rawBody.jobId, rawBody.retryFromAttempt,
        typeof rawBody.webSearchApiKey === 'string' ? rawBody.webSearchApiKey : undefined);
      if (retried.started) after(() => runClassroomGenerationJob(rawBody.jobId!, retried.input!, baseUrl,
        providerOptions, retried.job.execution!.attemptId));
      return jobResponse(retried.job, baseUrl, retried.started ? 202 : 200);
    }
    if (rawBody.jobId) {
      const existing = await readClassroomGenerationJob(rawBody.jobId);
      if (existing) return jobResponse(existing, baseUrl);
    }
    if (rawBody.requirement !== undefined && typeof rawBody.requirement !== 'string') return apiError('INVALID_REQUEST', 400, 'Invalid requirement');
    requirementSnippet = rawBody.requirement?.substring(0, 60);
    const pdfContent = rawBody.pdfContent;

    if (pdfContent !== undefined && !isValidPdfContent(pdfContent)) {
      return apiError(
        'INVALID_REQUEST',
        400,
        'Invalid pdfContent: expected { text: string; images: string[] }',
      );
    }

    const body: GenerateClassroomInput = {
      requirement: rawBody.requirement || '',
      ...(pdfContent !== undefined ? { pdfContent } : {}),

      ...(rawBody.enableWebSearch != null ? { enableWebSearch: rawBody.enableWebSearch } : {}),
      ...(rawBody.webSearchProviderId ? { webSearchProviderId: rawBody.webSearchProviderId } : {}),
      ...(rawBody.webSearchApiKey ? { webSearchApiKey: rawBody.webSearchApiKey } : {}),
      ...(rawBody.webSearchModelId ? { webSearchModelId: rawBody.webSearchModelId } : {}),
      ...(rawBody.baiduSubSources ? { baiduSubSources: rawBody.baiduSubSources } : {}),
      ...(rawBody.enableImageGeneration != null
        ? { enableImageGeneration: rawBody.enableImageGeneration }
        : {}),
      ...(rawBody.enableVideoGeneration != null
        ? { enableVideoGeneration: rawBody.enableVideoGeneration }
        : {}),
      ...(rawBody.enableTTS != null ? { enableTTS: rawBody.enableTTS } : {}),
      ...(rawBody.agentMode ? { agentMode: rawBody.agentMode } : {}),
      ...(typeof rawBody.allowSupplementaryExamples === 'boolean' ? { allowSupplementaryExamples: rawBody.allowSupplementaryExamples } : {}),
    };
    const { requirement } = body;

    if (!requirement) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'Missing required field: requirement');
    }

    // Competition addition: credentials stay in this closure, never in job storage.
    const providerOptions = await contestProviderFromHeaders(req);
    const jobId = rawBody.jobId || nanoid(10);
    let job: ClassroomGenerationJob;
    try { job = await createClassroomGenerationJob(jobId, body); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error;
      const existing = await readClassroomGenerationJob(jobId);
      if (!existing) throw error;
      return jobResponse(existing, baseUrl);
    }

    after(() => runClassroomGenerationJob(jobId, body, baseUrl, providerOptions, job.execution!.attemptId));
    return jobResponse(job, baseUrl, 202);
  } catch (error) {
    if (error instanceof ClassroomJobRecoveryError) return apiError('INVALID_REQUEST', error.status, error.message);
    log.error(
      `Classroom generation job creation failed [requirement="${requirementSnippet ?? 'unknown'}..."]:`,
      error,
    );
    return apiError(
      'INTERNAL_ERROR',
      500,
      'Failed to create classroom generation job',
      error instanceof Error ? error.message : 'Unknown error',
    );
  }
}
