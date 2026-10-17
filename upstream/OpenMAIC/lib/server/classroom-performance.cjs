"use strict";
// DeepSteam modification: bounded content prefetch with ordered narration.
// This scheduler does not change prompts, model settings, source verification,
// retries, or page assembly. Only independent content calls may overlap.
Object.defineProperty(exports, "__esModule", { value: true });
exports.classroomPrefetchWindow = classroomPrefetchWindow;
exports.orderedPrefetch = orderedPrefetch;
exports.createClassroomTimings = createClassroomTimings;
function classroomPrefetchWindow(model, outlines, hasStageRoutes, configuredWindow = process.env.DEEPSTEAM_CLASSROOM_CONTENT_PREFETCH) {
    return configuredWindow !== '1' && model === 'gpt-6.1-sol' &&
        !hasStageRoutes && outlines.length > 1 &&
        outlines.every(outline => ['slide', 'quiz', 'interactive'].includes(outline.type)) ? 2 : 1;
}
/**
 * At most one future content call overlaps the current content/action call.
 * Refilling happens after the consumer finishes a page, never before yield.
 * Immediate rejection handlers prevent an early future failure from becoming
 * an unhandled rejection. Cancellation/error waits for owned work to settle.
 */
async function* orderedPrefetch(items, prepare, options) {
    const controller = new AbortController();
    const signal = options.signal
        ? AbortSignal.any([options.signal, controller.signal]) : controller.signal;
    const windowSize = options.windowSize === 2 ? 2 : 1;
    const pending = new Map();
    let next = 0;
    const start = () => {
        const index = next++;
        pending.set(index, Promise.resolve().then(() => {
            signal.throwIfAborted();
            return prepare(items[index], index, signal);
        }).then(value => ({ ok: true, value }), error => ({ ok: false, error })));
    };
    try {
        signal.throwIfAborted();
        while (next < Math.min(items.length, windowSize))
            start();
        for (let index = 0; index < items.length; index++) {
            const result = await pending.get(index);
            pending.delete(index);
            signal.throwIfAborted();
            if (!result.ok)
                throw result.error;
            yield { index, value: result.value };
            signal.throwIfAborted();
            if (next < items.length)
                start();
        }
    }
    finally {
        controller.abort();
        await Promise.all(pending.values());
    }
}
/** Only timings and numeric indices are retained, never prompts or credentials. */
function createClassroomTimings() {
    const started = performance.now();
    const startedAt = new Date().toISOString();
    const phases = [];
    let contentWindow = 1;
    return {
        setContentWindow(value) { contentWindow = value; },
        async measure(phase, indices, run) {
            const begin = performance.now();
            const record = { phase, ...indices, startedMs: begin - started, status: 'running' };
            phases.push(record);
            try {
                const result = await run();
                record.status = 'completed';
                return result;
            }
            catch (error) {
                record.status = error?.name === 'AbortError' ? 'cancelled' : 'failed';
                throw error;
            }
            finally {
                record.durationMs = performance.now() - begin;
            }
        },
        snapshot() {
            return { version: 1, startedAt, elapsedMs: performance.now() - started,
                contentWindow, orderedActions: true, phases: phases.map(phase => ({ ...phase })) };
        },
    };
}
