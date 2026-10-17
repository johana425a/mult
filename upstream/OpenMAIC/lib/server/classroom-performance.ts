// DeepSteam modification: bounded content prefetch with ordered narration.
// This scheduler does not change prompts, model settings, source verification,
// retries, or page assembly. Only independent content calls may overlap.

type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown };

export function classroomPrefetchWindow(
  model: string | undefined,
  outlines: readonly { type: string }[],
  hasStageRoutes: boolean,
  configuredWindow = process.env.DEEPSTEAM_CLASSROOM_CONTENT_PREFETCH,
): number {
  return configuredWindow !== '1' && model === 'gpt-6.1-sol' &&
    !hasStageRoutes && outlines.length > 1 &&
    outlines.every(outline => ['slide', 'quiz', 'interactive'].includes(outline.type)) ? 2 : 1;
}

/**
 * At most one future content call overlaps the current content/action call.
 * A ready future result does not occupy a model call. In that case refill one
 * slot before narration, so a completed prefetch does not leave the model idle.
 * Never overlap two unfinished content calls with consumer narration.
 * Immediate rejection handlers prevent an early future failure from becoming
 * an unhandled rejection. Cancellation/error waits for owned work to settle.
 */
export async function* orderedPrefetch<T, R>(
  items: readonly T[],
  prepare: (item: T, index: number, signal: AbortSignal) => Promise<R>,
  options: { windowSize: number; signal?: AbortSignal },
): AsyncGenerator<{ index: number; value: R }> {
  const controller = new AbortController();
  const signal = options.signal
    ? AbortSignal.any([options.signal, controller.signal]) : controller.signal;
  const windowSize = options.windowSize === 2 ? 2 : 1;
  const pending = new Map<number, Promise<Settled<R>>>();
  const settled = new Map<number, Settled<R>>();
  let next = 0;
  const start = () => {
    const index = next++;
    pending.set(index, Promise.resolve().then(() => {
      signal.throwIfAborted();
      return prepare(items[index], index, signal);
    }).then(value => ({ ok: true, value } as const),
      error => ({ ok: false, error } as const)).then(result => {
        settled.set(index, result);
        return result;
      }));
  };
  try {
    signal.throwIfAborted();
    while (next < Math.min(items.length, windowSize)) start();
    for (let index = 0; index < items.length; index++) {
      const result = await pending.get(index)!;
      pending.delete(index);
      settled.delete(index);
      signal.throwIfAborted();
      if (!result.ok) throw result.error;
      // Keep at most two buffered future results and at most one unfinished
      // content call during narration. Known future failures stop new work.
      if (windowSize === 2 && next < items.length && pending.size < windowSize &&
        [...pending.keys()].every(key => settled.get(key)?.ok === true)) start();
      yield { index, value: result.value };
      signal.throwIfAborted();
      if (next < items.length && pending.size < windowSize &&
        ![...pending.keys()].some(key => settled.get(key)?.ok === false)) start();
    }
  } finally {
    controller.abort();
    await Promise.all(pending.values());
  }
}

interface PhaseRecord {
  phase: string;
  draft?: number;
  scene?: number;
  page?: number;
  attempt?: number;
  startedMs: number;
  durationMs?: number;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
}

/** Only timings and numeric indices are retained, never prompts or credentials. */
export function createClassroomTimings() {
  const started = performance.now();
  const startedAt = new Date().toISOString();
  const phases: PhaseRecord[] = [];
  let contentWindow = 1;
  return {
    setContentWindow(value: number) { contentWindow = value; },
    async measure<T>(phase: string,
      indices: Pick<PhaseRecord, 'draft' | 'scene' | 'page' | 'attempt'>,
      run: () => Promise<T>): Promise<T> {
      const begin = performance.now();
      const record: PhaseRecord = { phase, ...indices, startedMs: begin - started, status: 'running' };
      phases.push(record);
      try {
        const result = await run();
        record.status = 'completed';
        return result;
      } catch (error) {
        record.status = (error as { name?: string })?.name === 'AbortError' ? 'cancelled' : 'failed';
        throw error;
      } finally { record.durationMs = performance.now() - begin; }
    },
    snapshot() {
      return { version: 1, startedAt, elapsedMs: performance.now() - started,
        contentWindow, orderedActions: true, phases: phases.map(phase => ({ ...phase })) };
    },
  };
}
