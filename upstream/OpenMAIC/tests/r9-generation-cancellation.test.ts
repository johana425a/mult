import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  assertGenerationRunCurrent,
  finishGenerationWhenSaved,
  scheduleAgentReveal,
  waitForGenerationChoice,
} from '@/lib/hooks/generation-lifecycle';

afterEach(() => vi.useRealTimers());

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

describe('generation lifecycle ownership', () => {
  it('rejects a superseded run even when its transport ignored abort', () => {
    const first = new AbortController();
    const second = new AbortController();
    expect(() => assertGenerationRunCurrent(first, second)).toThrow('superseded');
    expect(() => assertGenerationRunCurrent(second, second)).not.toThrow();
    second.abort();
    expect(() => assertGenerationRunCurrent(second, second)).toThrow('cancelled');
  });

  it('settles a parked reveal on cancellation and makes its late resolver inert', async () => {
    const controller = new AbortController();
    let resolver!: (value: void) => void;
    const cleanup = vi.fn();
    const waiting = waitForGenerationChoice<void>(controller.signal, (resolve) => {
      resolver = resolve;
      return cleanup;
    });
    controller.abort();
    await expect(waiting).rejects.toMatchObject({ name: 'AbortError' });
    resolver();
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  it('detaches an accepted review and does not run abort cleanup twice', async () => {
    const controller = new AbortController();
    let resolver!: (value: string[]) => void;
    const cleanup = vi.fn();
    const waiting = waitForGenerationChoice(controller.signal, (resolve) => {
      resolver = resolve;
      return cleanup;
    });
    resolver(['edited-outline']);
    await expect(waiting).resolves.toEqual(['edited-outline']);
    controller.abort();
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  it('does not install a new UI wait for an already cancelled run', async () => {
    const controller = new AbortController();
    controller.abort();
    const installer = vi.fn();
    await expect(waitForGenerationChoice(controller.signal, installer)).rejects.toMatchObject({
      name: 'AbortError',
    });
    expect(installer).not.toHaveBeenCalled();
  });

  it('does not discard recovery state or navigate on save failure', async () => {
    const complete = vi.fn();
    await expect(
      finishGenerationWhenSaved(
        async () => false,
        () => {},
        complete,
        'Save failed',
      ),
    ).rejects.toThrow('Save failed');
    expect(complete).not.toHaveBeenCalled();
  });

  it('does not navigate when cancellation arrives during a successful save', async () => {
    const controller = new AbortController();
    const saving = deferred<boolean>();
    const complete = vi.fn();
    const finishing = finishGenerationWhenSaved(
      () => saving.promise,
      () => assertGenerationRunCurrent(controller, controller),
      complete,
      'Save failed',
    );
    controller.abort();
    saving.resolve(true);
    await expect(finishing).rejects.toMatchObject({ name: 'AbortError' });
    expect(complete).not.toHaveBeenCalled();
  });

  it('completes once after a durable current-run save', async () => {
    const complete = vi.fn();
    await finishGenerationWhenSaved(
      async () => true,
      () => {},
      complete,
      'Save failed',
    );
    expect(complete).toHaveBeenCalledTimes(1);
  });

  it('clears every multi-agent reveal timer when the modal closes', () => {
    vi.useFakeTimers();
    const reveal = vi.fn();
    const complete = vi.fn();
    const stop = scheduleAgentReveal(3, reveal, complete);
    vi.advanceTimersByTime(900);
    expect(reveal.mock.calls).toEqual([[1], [2]]);
    stop();
    vi.advanceTimersByTime(5000);
    expect(reveal).toHaveBeenCalledTimes(2);
    expect(complete).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('clears the one-agent completion callback before reopening another roster', () => {
    vi.useFakeTimers();
    const stale = vi.fn();
    const stop = scheduleAgentReveal(1, vi.fn(), stale);
    vi.advanceTimersByTime(400);
    stop();
    const current = vi.fn();
    scheduleAgentReveal(1, vi.fn(), current);
    vi.advanceTimersByTime(1000);
    expect(stale).not.toHaveBeenCalled();
    expect(current).toHaveBeenCalledTimes(1);
  });
});

/** Execute the actual preview flow with deterministic local dependencies. */
function previewFixture(
  options: { agentMode?: string; previewPhase?: string; save?: () => Promise<boolean> } = {},
) {
  const outline = { id: 'outline-1', title: 'Fixture', description: '', order: 1 };
  const session = {
    requirements: { requirement: 'Fixture' },
    sceneOutlines: [outline],
    previewPhase: options.previewPhase ?? 'generating-content',
  };
  const storage = new Map([['generationSession', JSON.stringify(session)]]);
  const fetchResult = deferred<Response>();
  const contentResult = deferred<{ success: boolean; content: object }>();
  const save = options.save ?? vi.fn(async () => true);
  const stageStore = {
    stage: null as any,
    setStage: vi.fn((stage) => {
      stageStore.stage = stage;
    }),
    setOutlines: vi.fn(),
    setGeneratingOutlines: vi.fn(),
    addScene: vi.fn(),
    setCurrentSceneId: vi.fn(),
    saveToStorage: save,
  };
  const settings = {
    agentMode: options.agentMode ?? 'auto',
    selectedAgentIds: [],
    ttsEnabled: false,
    ttsProvidersConfig: {},
    setSelectedAgentIds: vi.fn(),
    setAgentSelectionIsUserSet: vi.fn(),
  };
  const settingsHook = Object.assign(() => false, { getState: () => settings });
  const router = { push: vi.fn() };
  let stateIndex = 0;
  let capture: any;
  const effects: Array<() => unknown> = [];
  const lifecycle = {
    assertGenerationRunCurrent,
    finishGenerationWhenSaved,
    waitForGenerationChoice,
  };
  const modules: Record<string, any> = {
    react: {
      useState: (initial: any) => [
        stateIndex++ === 0 ? session : stateIndex === 2 ? true : initial,
        vi.fn(),
      ],
      useRef: (current: any) => ({ current }),
      useEffect: (effect: () => unknown) => effects.push(effect),
    },
    'next/navigation': { useRouter: () => router },
    '@/lib/hooks/use-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    '@/lib/hooks/generation-lifecycle': lifecycle,
    '@/lib/store/stage': { useStageStore: { getState: () => stageStore } },
    '@/lib/store/settings': { useSettingsStore: settingsHook },
    '@/lib/orchestration/registry/store': {
      useAgentRegistry: { getState: () => ({ getAgent: () => undefined }) },
      applyGeneratedAgentsToRegistry: vi.fn(() => []),
    },
    '@/lib/audio/voxcpm-voices': { useAllVoiceProfiles: () => ({ profiles: [] }) },
    '@/lib/audio/voice-resolver': {
      getEnabledProvidersWithVoices: () => [],
      resolveNarratorVoiceForGeneration: () => undefined,
    },
    '@/lib/document/session-sources': { resolveSessionDocumentSources: () => [] },
    '@/lib/utils/model-config': {
      getCurrentModelConfig: () => ({}),
      getStageRoutesHeaderValue: () => '',
    },
    '@/lib/hooks/use-scene-generator': {
      fetchSceneContent: vi.fn(() => contentResult.promise),
      fetchSceneActions: vi.fn(async () => ({ success: true, scene: { id: 'scene-1', order: 1 } })),
    },
    '@openmaic/generation/browser': { isAbortError: (error: any) => error?.name === 'AbortError' },
    '@/lib/media/video-manifest': { buildVideoManifestFromOutlines: () => [] },
    '@/lib/logger': {
      createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
    },
    './types': {
      getActiveSteps: () => [
        { id: 'outline' },
        { id: 'agent-generation' },
        { id: 'slide-content' },
        { id: 'actions' },
      ],
    },
    nanoid: { nanoid: () => 'fixture-stage' },
  };
  const source = readFileSync(resolve('app/generation-preview/page.tsx'), 'utf8').replace(
    '  // Still loading session from sessionStorage',
    '  globalThis.__capture({ startGeneration, goBackToHome, agentRevealResolveRef });\n  return null;\n  // Still loading session from sessionStorage',
  );
  const compiled = ts.transpileModule(source + '\nGenerationPreviewContent();', {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const context = {
    exports: {},
    require: (name: string) => modules[name] ?? {},
    __capture: (value: any) => {
      capture = value;
    },
    AbortController,
    DOMException,
    Blob,
    fetch: vi.fn(() => fetchResult.promise),
    sessionStorage: {
      getItem: (key: string) => storage.get(key),
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    },
    localStorage: { removeItem: vi.fn() },
    setTimeout,
    clearTimeout,
  };
  runInNewContext(compiled, context);
  return {
    capture,
    storage,
    fetchResult,
    contentResult,
    stageStore,
    router,
    settings,
    modules,
    effects,
  };
}

async function flush() {
  for (let i = 0; i < 12; i++) await Promise.resolve();
}

describe('actual preview async boundaries', () => {
  it('does not fall back or set a stage after a late aborted profiles response', async () => {
    const fixture = previewFixture();
    const running = fixture.capture.startGeneration();
    await flush();
    fixture.capture.goBackToHome();
    fixture.fetchResult.reject(new DOMException('Cancelled', 'AbortError'));
    await running;
    expect(fixture.stageStore.setStage).not.toHaveBeenCalled();
    expect(fixture.settings.setSelectedAgentIds).not.toHaveBeenCalled();
    expect(fixture.router.push.mock.calls).toEqual([['/']]);
  });

  it('rejects late successful profiles before installing the reveal or roster', async () => {
    const fixture = previewFixture();
    const running = fixture.capture.startGeneration();
    await flush();
    fixture.capture.goBackToHome();
    fixture.fetchResult.resolve(new Response(JSON.stringify({ success: true, agents: [] })));
    await running;
    expect(fixture.stageStore.setStage).not.toHaveBeenCalled();
    expect(fixture.capture.agentRevealResolveRef.current).toBeNull();
    expect(fixture.settings.setSelectedAgentIds).not.toHaveBeenCalled();
  });

  it('settles an open reveal on exit without publishing a stage', async () => {
    const fixture = previewFixture();
    const running = fixture.capture.startGeneration();
    fixture.fetchResult.resolve(new Response(JSON.stringify({ success: true, agents: [] })));
    await flush();
    expect(fixture.capture.agentRevealResolveRef.current).toBeTypeOf('function');
    fixture.capture.goBackToHome();
    await running;
    expect(fixture.capture.agentRevealResolveRef.current).toBeNull();
    expect(fixture.stageStore.setStage).not.toHaveBeenCalled();
  });

  it('never adds a scene or navigates for late content after exit', async () => {
    const fixture = previewFixture({ agentMode: 'preset' });
    const running = fixture.capture.startGeneration();
    await flush();
    fixture.capture.goBackToHome();
    fixture.contentResult.resolve({ success: true, content: {} });
    await running;
    expect(fixture.stageStore.addScene).not.toHaveBeenCalled();
    expect(fixture.router.push.mock.calls).toEqual([['/']]);
  });

  it('does not publish a late scene into a different current classroom', async () => {
    const fixture = previewFixture({ agentMode: 'preset' });
    const running = fixture.capture.startGeneration();
    await flush();
    fixture.stageStore.stage = { id: 'new-classroom' };
    fixture.contentResult.resolve({ success: true, content: {} });
    await running;
    expect(fixture.stageStore.addScene).not.toHaveBeenCalled();
    expect(fixture.stageStore.stage.id).toBe('new-classroom');
    expect(fixture.router.push).not.toHaveBeenCalled();
  });

  it('retains recovery state when the actual flow cannot save', async () => {
    const fixture = previewFixture({ agentMode: 'preset', save: async () => false });
    const running = fixture.capture.startGeneration();
    fixture.contentResult.resolve({ success: true, content: {} });
    await running;
    expect(fixture.storage.has('generationSession')).toBe(true);
    expect(fixture.storage.has('generationParams')).toBe(false);
    expect(fixture.router.push).not.toHaveBeenCalled();
  });

  it('does not clear a new session or navigate after exiting during save', async () => {
    const saving = deferred<boolean>();
    const fixture = previewFixture({ agentMode: 'preset', save: () => saving.promise });
    const running = fixture.capture.startGeneration();
    fixture.contentResult.resolve({ success: true, content: {} });
    await flush();
    fixture.capture.goBackToHome();
    fixture.storage.set('generationSession', 'new-session');
    saving.resolve(true);
    await running;
    expect(fixture.storage.get('generationSession')).toBe('new-session');
    expect(fixture.storage.has('generationParams')).toBe(false);
    expect(fixture.router.push.mock.calls).toEqual([['/']]);
  });

  it('starts a restored outline-ready wait once and cancels it on leaving', async () => {
    vi.useFakeTimers();
    const fixture = previewFixture({ agentMode: 'preset', previewPhase: 'outline-ready' });
    // The actual mount auto-start effect is the third registered effect.
    fixture.effects[2]();
    fixture.effects[2]();
    expect(vi.getTimerCount()).toBe(1);
    fixture.capture.goBackToHome();
    await flush();
    vi.advanceTimersByTime(5000);
    expect(fixture.stageStore.setStage).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('resumes a restored outline-ready session after its review timer', async () => {
    vi.useFakeTimers();
    const fixture = previewFixture({ agentMode: 'preset', previewPhase: 'outline-ready' });
    const running = fixture.capture.startGeneration();
    expect(fixture.stageStore.setStage).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2500);
    await flush();
    expect(fixture.stageStore.setStage).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fixture.storage.get('generationSession')!).previewPhase).toBe(
      'generating-content',
    );
    fixture.capture.goBackToHome();
    fixture.contentResult.resolve({ success: true, content: {} });
    await running;
    expect(fixture.router.push.mock.calls).toEqual([['/']]);
  });
});
