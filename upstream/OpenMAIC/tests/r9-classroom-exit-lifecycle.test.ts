import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ClassroomPlaybackLifetime,
  settleClassroomExit,
  shouldExitClassroomFullscreen,
  type PlaybackOwner,
} from '../lib/playback/classroom-exit-lifecycle';

afterEach(() => vi.useRealTimers());

function fixture() {
  vi.useFakeTimers();
  const lifetime = new ClassroomPlaybackLifetime();
  const engine = {};
  let current: PlaybackOwner = { stageId: 'A', sceneId: 'A1', engine };
  const lease = lifetime.lease(lifetime.beginScene(), current);
  const advance = vi.fn();
  return {
    lifetime,
    lease,
    advance,
    get: () => current,
    set: (next: PlaybackOwner) => {
      current = next;
    },
  };
}

describe('classroom callback ownership', () => {
  it('advances only the same live classroom, scene and engine', () => {
    const f = fixture();
    f.lifetime.scheduleAdvance(f.lease, f.get, f.advance);
    vi.advanceTimersByTime(1500);
    expect(f.advance).toHaveBeenCalledOnce();
  });

  it.each(['stage', 'scene', 'engine'] as const)(
    'rejects a late callback after %s changes',
    (changed) => {
      const f = fixture();
      f.lifetime.scheduleAdvance(f.lease, f.get, f.advance);
      const next = { ...f.get() };
      if (changed === 'stage') next.stageId = 'B';
      if (changed === 'scene') next.sceneId = 'A2';
      if (changed === 'engine') next.engine = {};
      f.set(next);
      vi.advanceTimersByTime(1500);
      expect(f.advance).not.toHaveBeenCalled();
      expect(f.lifetime.isCurrent(f.lease, f.get())).toBe(false);
    },
  );

  it('exit clears the timer and rejects late completion even if the old state stays visible', () => {
    const f = fixture();
    f.lifetime.scheduleAdvance(f.lease, f.get, f.advance);
    f.lifetime.invalidate();
    expect(vi.getTimerCount()).toBe(0);
    expect(f.lifetime.isCurrent(f.lease, f.get())).toBe(false);
    f.lifetime.scheduleAdvance(f.lease, f.get, f.advance);
    vi.advanceTimersByTime(1500);
    expect(f.advance).not.toHaveBeenCalled();
  });

  it('an old lease remains invalid after a new scene starts with identical IDs', () => {
    const f = fixture();
    f.lifetime.beginScene();
    expect(f.lifetime.isCurrent(f.lease, f.get())).toBe(false);
  });
});

describe('bounded classroom retirement', () => {
  it('runs independent cleanup even if one operation fails', async () => {
    const saved = vi.fn();
    const result = await settleClassroomExit([
      () => {
        throw new Error('retire failure');
      },
      saved,
    ]);
    expect(saved).toHaveBeenCalledOnce();
    expect(result).toEqual({ timedOut: false, failed: 1 });
  });

  it('releases the UI after a deadline and observes a late rejection', async () => {
    vi.useFakeTimers();
    let reject!: (reason: Error) => void;
    const pending = new Promise<void>((_resolve, rejection) => {
      reject = rejection;
    });
    const result = settleClassroomExit([() => pending]);
    await vi.advanceTimersByTimeAsync(3000);
    await expect(result).resolves.toEqual({ timedOut: true, failed: 0 });
    reject(new Error('late failure'));
    await Promise.resolve();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('fullscreen Escape intent', () => {
  const base = {
    key: 'Escape',
    defaultPrevented: false,
    isComposing: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    presenting: true,
    interactionActive: false,
    modalActive: false,
  };
  it('works while typing focus is elsewhere because focus is not a fullscreen-exit veto', () => {
    expect(shouldExitClassroomFullscreen(base)).toBe(true);
  });
  it.each([
    'defaultPrevented',
    'isComposing',
    'ctrlKey',
    'metaKey',
    'altKey',
    'interactionActive',
    'modalActive',
  ] as const)('respects %s ownership', (property) => {
    expect(shouldExitClassroomFullscreen({ ...base, [property]: true })).toBe(false);
  });
  it('ignores IME 229 and does not end a non-fullscreen classroom', () => {
    expect(shouldExitClassroomFullscreen({ ...base, keyCode: 229 })).toBe(false);
    expect(shouldExitClassroomFullscreen({ ...base, presenting: false })).toBe(false);
  });
});
