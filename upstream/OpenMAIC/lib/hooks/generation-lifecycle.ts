/** Frontend generation work owns only its current run, never a shared service. */
export function assertGenerationRunCurrent(
  controller: AbortController,
  currentController: AbortController | null,
): void {
  if (controller.signal.aborted || currentController !== controller) {
    throw new DOMException('Generation cancelled or superseded', 'AbortError');
  }
}

/** A UI choice must settle on cancellation and detach its listener on every path. */
export function waitForGenerationChoice<T>(
  signal: AbortSignal,
  installResolver: (resolve: (value: T) => void) => () => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    let settled = false;
    let cleanup = () => {};
    const finish = (value?: T, aborted = false) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener('abort', onAbort);
      cleanup();
      if (aborted) reject(new DOMException('Generation cancelled', 'AbortError'));
      else resolve(value as T);
    };
    const onAbort = () => finish(undefined, true);
    if (signal.aborted) {
      onAbort();
      return;
    }
    signal.addEventListener('abort', onAbort, { once: true });
    cleanup = installResolver((value) => finish(value));
    // Also handles cancellation or a synchronous choice inside the installer.
    if (settled) cleanup();
    else if (signal.aborted) onAbort();
  });
}

/** Keep recovery state and navigation behind both durability and run ownership. */
export async function finishGenerationWhenSaved(
  save: () => Promise<boolean>,
  assertCurrent: () => void,
  onSaved: () => void,
  saveFailedMessage: string,
): Promise<void> {
  assertCurrent();
  const saved = await save();
  assertCurrent();
  if (!saved) throw new Error(saveFailedMessage);
  onSaved();
}

/** Every timer in a reveal sequence belongs to the mounted modal. */
export function scheduleAgentReveal(
  count: number,
  reveal: (count: number) => void,
  complete: () => void,
): () => void {
  let active = true;
  let interval: ReturnType<typeof setInterval> | undefined;
  let completionTimer: ReturnType<typeof setTimeout> | undefined;
  const finish = () => {
    if (!active) return;
    completionTimer = setTimeout(() => {
      if (active) complete();
    }, 600);
  };
  const startTimer = setTimeout(() => {
    if (!active) return;
    if (count === 0) {
      complete();
      return;
    }
    let revealed = 1;
    reveal(revealed);
    if (count <= 1) {
      finish();
      return;
    }
    interval = setInterval(() => {
      if (!active) return;
      reveal(++revealed);
      if (revealed >= count) {
        clearInterval(interval);
        interval = undefined;
        finish();
      }
    }, 500);
  }, 400);
  return () => {
    active = false;
    clearTimeout(startTimer);
    clearInterval(interval);
    clearTimeout(completionTimer);
  };
}
