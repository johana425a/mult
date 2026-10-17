import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Action } from '../lib/types/action';
import type { Scene } from '../lib/types/stage';
import type { AudioPlayer } from '../lib/utils/audio-player';
import type { StageStore } from '../lib/api/stage-api';

const fixture = vi.hoisted(() => ({
  owner: { stage: { id: 'A' }, currentSceneId: 'A1' },
  elements: [{ id: 'A-element' }] as { id: string }[],
  writes: [] as { course: string; kind: string }[],
  canvas: {
    whiteboardOpen: false,
    whiteboardClearing: false,
    setWhiteboardOpen: vi.fn(),
    setWhiteboardClearing: vi.fn(),
    clearAllEffects: vi.fn(),
    pauseVideo: vi.fn(),
  },
}));
vi.mock('../lib/api/stage-api', () => ({
  createStageAPI: () => ({
    whiteboard: {
      get: () => ({
        success: true,
        data: { id: `${fixture.owner.stage.id}-wb`, elements: fixture.elements },
      }),
      addElement: () => {
        fixture.writes.push({ course: fixture.owner.stage.id, kind: 'draw' });
      },
      update: () => {
        fixture.writes.push({ course: fixture.owner.stage.id, kind: 'clear' });
      },
    },
  }),
}));
vi.mock('../lib/store/canvas', () => ({ useCanvasStore: { getState: () => fixture.canvas } }));
vi.mock('../lib/store/whiteboard-history', () => ({
  useWhiteboardHistoryStore: { getState: () => ({ pushSnapshot: vi.fn() }) },
}));
vi.mock('../lib/store/media-generation', () => ({
  useMediaGenerationStore: { getState: () => ({ tasks: {} }) },
}));
vi.mock('../lib/store/settings', () => ({
  useSettingsStore: { getState: () => ({ ttsEnabled: false }) },
}));
import { ActionEngine } from '../lib/action/engine';
import { PlaybackEngine } from '../lib/playback/engine';

beforeEach(() => {
  vi.useFakeTimers();
  fixture.owner = { stage: { id: 'A' }, currentSceneId: 'A1' };
  fixture.writes = [];
  fixture.canvas.whiteboardOpen = false;
  fixture.canvas.whiteboardClearing = false;
  fixture.canvas.setWhiteboardOpen.mockImplementation((open: boolean) => {
    fixture.canvas.whiteboardOpen = open;
  });
  fixture.canvas.setWhiteboardClearing.mockImplementation((clearing: boolean) => {
    fixture.canvas.whiteboardClearing = clearing;
  });
  fixture.canvas.clearAllEffects.mockClear();
});
afterEach(() => vi.useRealTimers());

const draw = {
  id: 'draw-A',
  type: 'wb_draw_text',
  content: 'Synthetic text',
  x: 0,
  y: 0,
} as Action;
function engines(action: Action) {
  const store = { getState: () => fixture.owner } as unknown as StageStore;
  const audio = { stop: vi.fn(), pause: vi.fn(), isPlaying: () => false } as unknown as AudioPlayer;
  const actions = new ActionEngine(store, audio);
  const scene = { id: 'A1', stageId: 'A', type: 'slide', actions: [action] } as Scene;
  const complete = vi.fn();
  return {
    actions,
    player: new PlaybackEngine([scene], actions, audio, { onComplete: complete }),
    complete,
  };
}

describe('real playback and action engines retire deferred whiteboard work', () => {
  it('End during whiteboard opening aborts the deferred draw before writing', async () => {
    const f = engines(draw);
    f.player.start();
    expect(fixture.canvas.whiteboardOpen).toBe(true);
    f.player.stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fixture.writes).toEqual([]);
    expect(f.complete).not.toHaveBeenCalled();
  });

  it('End then switch to B cannot draw into B after the old open animation', async () => {
    const f = engines(draw);
    f.player.start();
    f.player.stop();
    fixture.owner = { stage: { id: 'B' }, currentSceneId: 'B1' };
    await vi.advanceTimersByTimeAsync(5000);
    expect(fixture.writes).toEqual([]);
    expect(f.complete).not.toHaveBeenCalled();
  });

  it('an owner change rejects an un-signalled old action after its await', async () => {
    const f = engines(draw);
    const executing = f.actions.execute(draw);
    const assertion = expect(executing).rejects.toMatchObject({ name: 'AbortError' });
    fixture.owner = { stage: { id: 'B' }, currentSceneId: 'B1' };
    await vi.advanceTimersByTimeAsync(5000);
    await assertion;
    expect(fixture.writes).toEqual([]);
  });

  it('Pause preserves the current atomic action but does not declare completion', async () => {
    const f = engines(draw);
    f.player.start();
    f.player.pause();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fixture.writes).toEqual([{ course: 'A', kind: 'draw' }]);
    expect(f.player.getMode()).toBe('paused');
    expect(f.complete).not.toHaveBeenCalled();
  });

  it('End during clear animation cannot remove the new B whiteboard', async () => {
    fixture.canvas.whiteboardOpen = true;
    const f = engines({ id: 'clear-A', type: 'wb_clear' } as Action);
    f.player.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(fixture.canvas.whiteboardClearing).toBe(true);
    f.player.stop();
    fixture.owner = { stage: { id: 'B' }, currentSceneId: 'B1' };
    fixture.canvas.whiteboardClearing = false;
    const clearingCalls = fixture.canvas.setWhiteboardClearing.mock.calls.length;
    await vi.advanceTimersByTimeAsync(5000);
    expect(fixture.writes).toEqual([]);
    expect(fixture.canvas.setWhiteboardClearing.mock.calls.length).toBe(clearingCalls);
    expect(f.complete).not.toHaveBeenCalled();
  });

  it('stopping an old engine does not clear B effects after a course switch', () => {
    const f = engines(draw);
    fixture.owner = { stage: { id: 'B' }, currentSceneId: 'B1' };
    f.player.stop();
    expect(fixture.canvas.clearAllEffects).not.toHaveBeenCalled();
  });

  it('an old A engine cannot start an action against B before React cleanup runs', async () => {
    const f = engines(draw);
    fixture.owner = { stage: { id: 'B' }, currentSceneId: 'B1' };
    f.player.start();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fixture.canvas.whiteboardOpen).toBe(false);
    expect(fixture.writes).toEqual([]);
    expect(f.complete).not.toHaveBeenCalled();
  });

  it('a stale A jump cannot reset the B whiteboard before reconstruction', async () => {
    const f = engines(draw);
    fixture.owner = { stage: { id: 'B' }, currentSceneId: 'B1' };
    const result = await f.player.jumpToAction(0, { autoplay: false });
    expect(result).toBe(false);
    expect(fixture.writes).toEqual([]);
    expect(fixture.canvas.clearAllEffects).not.toHaveBeenCalled();
  });
});
