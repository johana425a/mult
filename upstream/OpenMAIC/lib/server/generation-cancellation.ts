/** Keep cancellation distinct from a retryable generation or provider failure. */
export function isGenerationAbortError(error: unknown): error is Error {
  return error instanceof Error && error.name === 'AbortError';
}

export function throwIfGenerationAborted(signal?: AbortSignal): void {
  if (!signal?.aborted) return;
  throw isGenerationAbortError(signal.reason)
    ? signal.reason
    : new DOMException('Generation cancelled', 'AbortError');
}

/** A late provider failure must not turn a cancelled run into a fallback/retry. */
export function rethrowIfGenerationCancelled(error: unknown, signal?: AbortSignal): void {
  // Some generation/SDK boundaries wrap the original cancellation as a cause.
  const seen = new Set<unknown>();
  let current = error;
  while (current && typeof current === 'object' && !seen.has(current)) {
    if (isGenerationAbortError(current)) throw current;
    seen.add(current);
    const wrapped = current as { cause?: unknown; lastError?: unknown };
    current = wrapped.cause ?? wrapped.lastError;
  }
  throwIfGenerationAborted(signal);
}
