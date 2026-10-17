/** Classroom-owned callbacks must never act on a later course or player. */
export interface PlaybackOwner {
  readonly stageId: string;
  readonly sceneId: string;
  readonly engine: object | null;
}

export interface PlaybackLease extends PlaybackOwner {
  readonly epoch: number;
}

export class ClassroomPlaybackLifetime {
  private epoch = 0;
  private active = false;
  private advanceTimer: ReturnType<typeof setTimeout> | null = null;

  beginScene(): number {
    this.invalidate();
    this.active = true;
    return this.epoch;
  }

  lease(epoch: number, owner: PlaybackOwner): PlaybackLease {
    return { ...owner, epoch };
  }

  isCurrent(lease: PlaybackLease | undefined, current: PlaybackOwner): boolean {
    return Boolean(
      lease &&
      this.active &&
      lease.epoch === this.epoch &&
      lease.engine &&
      lease.engine === current.engine &&
      lease.stageId === current.stageId &&
      lease.sceneId === current.sceneId,
    );
  }

  scheduleAdvance(
    lease: PlaybackLease,
    current: () => PlaybackOwner,
    advance: () => void,
    delayMs = 1500,
  ): void {
    this.clearAdvance();
    if (!this.isCurrent(lease, current())) return;
    this.advanceTimer = setTimeout(() => {
      this.advanceTimer = null;
      if (this.isCurrent(lease, current())) advance();
    }, delayMs);
  }

  clearAdvance(): void {
    if (this.advanceTimer !== null) clearTimeout(this.advanceTimer);
    this.advanceTimer = null;
  }

  invalidate(): void {
    this.active = false;
    this.epoch += 1;
    this.clearAdvance();
  }
}

/**
 * Observe best-effort persistence/retirement without holding the exit UI forever.
 * Local abort/stop and ownership invalidation must happen BEFORE this function.
 * Timed-out work remains observed, so a late rejection is never unhandled.
 */
export async function settleClassroomExit(
  operations: readonly (() => Promise<unknown> | unknown)[],
  timeoutMs = 3000,
): Promise<{ timedOut: boolean; failed: number }> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const settled = Promise.all(
    operations.map((operation) =>
      Promise.resolve()
        .then(operation)
        .then(
          () => false,
          () => true,
        ),
    ),
  ).then((failures) => ({ timedOut: false, failed: failures.filter(Boolean).length }));
  const deadline = new Promise<{ timedOut: boolean; failed: number }>((resolve) => {
    timer = setTimeout(() => resolve({ timedOut: true, failed: 0 }), timeoutMs);
  });
  const result = await Promise.race([settled, deadline]);
  if (timer !== undefined) clearTimeout(timer);
  return result;
}

export interface EscapeIntent {
  readonly key: string;
  readonly defaultPrevented: boolean;
  readonly isComposing: boolean;
  readonly keyCode?: number;
  readonly ctrlKey: boolean;
  readonly metaKey: boolean;
  readonly altKey: boolean;
  readonly presenting: boolean;
  readonly interactionActive: boolean;
  readonly modalActive: boolean;
}

/** Esc exits a view, never completes/stops a lesson or cancels a Harness task. */
export function shouldExitClassroomFullscreen(intent: EscapeIntent): boolean {
  return (
    intent.key === 'Escape' &&
    intent.presenting &&
    !intent.defaultPrevented &&
    !intent.isComposing &&
    intent.keyCode !== 229 &&
    !intent.ctrlKey &&
    !intent.metaKey &&
    !intent.altKey &&
    !intent.interactionActive &&
    !intent.modalActive
  );
}
