import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  isValidClassroomJobId,
  readClassroomGenerationJob,
} from '@/lib/server/classroom-job-store';
import { buildRequestOrigin } from '@/lib/server/classroom-storage';
import { createLogger } from '@/lib/logger';
import { deleteClassroomGenerationJob } from '@/lib/server/classroom-lifecycle';

const log = createLogger('ClassroomJob API');

export const dynamic = 'force-dynamic';

export async function DELETE(req: NextRequest, context: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await context.params;
  if (!isValidClassroomJobId(jobId) || jobId.length > 100) return apiError('INVALID_REQUEST', 400, 'Invalid job id');
  let protectedIds: string[] = [];
  try {
    const text = await req.text();
    const body = text ? JSON.parse(text) : {};
    protectedIds = body.preserveClassroomIds ?? [];
    if (!Array.isArray(protectedIds) || protectedIds.length > 10000 || protectedIds.some(id => typeof id !== 'string' || !/^[a-zA-Z0-9_-]{1,100}$/.test(id))) {
      return apiError('INVALID_REQUEST', 400, 'Invalid protected classroom ids');
    }
  } catch { return apiError('INVALID_REQUEST', 400, 'Invalid deletion request'); }
  try { await deleteClassroomGenerationJob(jobId, 15000, protectedIds); return apiSuccess({ deleted: true }); }
  catch { return apiError('INVALID_REQUEST', 409, 'Generation or file cleanup has not finished. Retry deletion.'); }
}

export async function GET(req: NextRequest, context: { params: Promise<{ jobId: string }> }) {
  let resolvedJobId: string | undefined;
  try {
    const { jobId } = await context.params;
    resolvedJobId = jobId;

    if (!isValidClassroomJobId(jobId)) {
      return apiError('INVALID_REQUEST', 400, 'Invalid classroom generation job id');
    }

    const job = await readClassroomGenerationJob(jobId);
    if (!job) {
      return apiError('INVALID_REQUEST', 404, 'Classroom generation job not found');
    }

    const pollUrl = `${buildRequestOrigin(req)}/api/generate-classroom/${jobId}`;

    return apiSuccess({
      jobId: job.id,
      status: job.status,
      step: job.step,
      progress: job.progress,
      message: job.message,
      pollUrl,
      pollIntervalMs: 5000,
      scenesGenerated: job.scenesGenerated,
      totalScenes: job.totalScenes,
      result: job.result,
      error: job.error,
      done: job.status === 'succeeded' || job.status === 'failed' || job.status === 'interrupted',
      attemptId: job.execution?.attemptId ?? 'legacy',
      attempt: job.execution?.attempt ?? 0,
      retryable: (job.status === 'interrupted' || job.status === 'failed') && !!job.recovery,
      retryMode: 'restart',
      lastAttempt: job.lastAttempt,
    });
  } catch (error) {
    log.error(`Classroom job retrieval failed [jobId=${resolvedJobId ?? 'unknown'}]:`, error);
    return apiError(
      'INTERNAL_ERROR',
      500,
      'Failed to retrieve classroom generation job',
      error instanceof Error ? error.message : String(error),
    );
  }
}
