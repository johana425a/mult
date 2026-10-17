import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const harness = vi.hoisted(() => ({
  cleanups: [] as (() => void)[],
  config: {
    asrProviderId: 'fixture-asr',
    asrLanguage: 'en-US',
    asrProvidersConfig: {} as Record<string, unknown>,
  },
}));
vi.mock('react', () => ({
  useRef: (initial: unknown) => ({ current: initial }),
  useState: (initial: unknown) => [initial, vi.fn()],
  useCallback: (callback: unknown) => callback,
  useEffect: (effect: () => void | (() => void)) => {
    const cleanup = effect();
    if (cleanup) harness.cleanups.push(cleanup);
  },
}));
vi.mock('../lib/store/settings', () => ({ useSettingsStore: { getState: () => harness.config } }));
vi.mock('../lib/audio/wav-utils', () => ({
  normalizeASRUploadAudio: async (_provider: string, blob: Blob) => ({
    blob,
    fileName: 'fixture.webm',
  }),
}));
import { useAudioRecorder } from '../lib/hooks/use-audio-recorder';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

let recorders: FakeRecorder[];
class FakeRecorder {
  state = 'inactive';
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => unknown) | null = null;
  constructor(public stream: MediaStream) {
    recorders.push(this);
  }
  start() {
    this.state = 'recording';
  }
  stop = vi.fn(() => {
    this.state = 'inactive';
    this.onstop?.();
  });
}
function fakeStream() {
  const stop = vi.fn();
  return { stream: { getTracks: () => [{ stop }] } as unknown as MediaStream, stop };
}

beforeEach(() => {
  harness.cleanups = [];
  harness.config.asrProviderId = 'fixture-asr';
  recorders = [];
  vi.stubGlobal('window', {});
  vi.stubGlobal('MediaRecorder', FakeRecorder);
});
afterEach(() => {
  harness.cleanups.forEach((cleanup) => cleanup());
  vi.unstubAllGlobals();
});

describe('real recorder hook retirement with synthetic microphone and ASR', () => {
  it('stops a microphone permission grant that arrives after End', async () => {
    const grant = deferred<MediaStream>();
    const input = fakeStream();
    const getUserMedia = vi.fn(() => grant.promise);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
    const hook = useAudioRecorder();
    const starting = hook.startRecording();
    await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalledOnce());
    hook.cancelRecording();
    grant.resolve(input.stream);
    await starting;
    expect(input.stop).toHaveBeenCalledOnce();
    expect(recorders).toHaveLength(0);
  });

  it('End stops live microphone tracks without submitting transcription', async () => {
    const input = fakeStream();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => input.stream } });
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const hook = useAudioRecorder();
    await hook.startRecording();
    hook.cancelRecording();
    expect(recorders[0].stop).toHaveBeenCalledOnce();
    expect(input.stop).toHaveBeenCalled();
    expect(recorders[0].onstop).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('aborts pending ASR and ignores a server response that still arrives after End', async () => {
    const input = fakeStream();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => input.stream } });
    const response = deferred<Response>();
    const fetch = vi.fn((_url: unknown, _init: { signal: AbortSignal }) => response.promise);
    vi.stubGlobal('fetch', fetch);
    const transcript = vi.fn();
    const hook = useAudioRecorder({ onTranscription: transcript });
    await hook.startRecording();
    hook.stopRecording();
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    const signal = fetch.mock.calls[0][1].signal as AbortSignal;
    hook.cancelRecording();
    expect(signal.aborted).toBe(true);
    response.resolve({
      ok: true,
      json: async () => ({ text: 'late synthetic transcript' }),
    } as Response);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(transcript).not.toHaveBeenCalled();
  });

  it('unmount aborts ASR and does not publish into a later classroom', async () => {
    const input = fakeStream();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => input.stream } });
    const response = deferred<Response>();
    const fetch = vi.fn((_url: unknown, _init: { signal: AbortSignal }) => response.promise);
    vi.stubGlobal('fetch', fetch);
    const transcript = vi.fn();
    const hook = useAudioRecorder({ onTranscription: transcript });
    await hook.startRecording();
    hook.stopRecording();
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    const signal = fetch.mock.calls[0][1].signal as AbortSignal;
    harness.cleanups.forEach((cleanup) => cleanup());
    expect(signal.aborted).toBe(true);
    response.resolve({ ok: true, json: async () => ({ text: 'late after unmount' }) } as Response);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(transcript).not.toHaveBeenCalled();
  });

  it('normal Stop still delivers its transcript without cancelling the run', async () => {
    const input = fakeStream();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => input.stream } });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, json: async () => ({ text: 'valid synthetic transcript' }) })),
    );
    const transcript = vi.fn();
    const hook = useAudioRecorder({ onTranscription: transcript });
    await hook.startRecording();
    hook.stopRecording();
    await vi.waitFor(() => expect(transcript).toHaveBeenCalledWith('valid synthetic transcript'));
    expect(input.stop).toHaveBeenCalled();
  });

  it('invalidates captured browser-recognition callbacks on End', async () => {
    harness.config.asrProviderId = 'browser-native';
    let recognition: {
      onresult: null | ((event: unknown) => void);
      abort: ReturnType<typeof vi.fn>;
    };
    class Recognition {
      onresult = null;
      abort = vi.fn();
      start = vi.fn();
      constructor() {
        recognition = this;
      }
    }
    vi.stubGlobal('window', { SpeechRecognition: Recognition });
    const transcript = vi.fn();
    const hook = useAudioRecorder({ onTranscription: transcript });
    await hook.startRecording();
    const late = recognition!.onresult!;
    hook.cancelRecording();
    late({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: 'late recognition' } }] });
    expect(recognition!.abort).toHaveBeenCalledOnce();
    expect(transcript).not.toHaveBeenCalled();
  });
});
