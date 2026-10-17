import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { transcribeAudio } from '@/lib/audio/asr-providers';
import { generateTTS, TTSRequestTimeoutError } from '@/lib/audio/tts-providers';
import type { ASRProviderId } from '@/lib/audio/types';

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  sdkTranscribe: vi.fn(),
  sdkFactory: vi.fn(() => ({ transcription: () => ({}) })),
  sdkFetchFactory: vi.fn(() => vi.fn()),
}));
vi.mock('@/lib/server/audio-provider-fetch', () => ({
  audioProviderFetch: mocks.fetch,
  audioEndpointPolicy: () => ({ allowLocalNetworks: false }),
  createAudioProviderFetch: mocks.sdkFetchFactory,
}));
vi.mock('@ai-sdk/openai', () => ({ createOpenAI: mocks.sdkFactory }));
vi.mock('ai', () => ({ experimental_transcribe: mocks.sdkTranscribe }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const recording = () => new File(['RIFF0000WAVE'], 'recording.wav', { type: 'audio/wav' });
const asrResponse = () =>
  Response.json({
    text: 'spoken text',
    combinedPhrases: [{ text: 'spoken text' }],
    output: { choices: [{ message: { content: [{ text: 'spoken text' }] } }] },
  });
const audioResponse = () =>
  new Response(new Uint8Array([1, 2, 3]), { headers: { 'content-type': 'audio/mpeg' } });
const asrConfig = (providerId: ASRProviderId, signal?: AbortSignal) => ({
  providerId,
  apiKey: 'fixture-key',
  modelId: 'fixture-model',
  baseUrl: 'https://audio.example.invalid',
  signal,
});
const ttsConfig = (signal?: AbortSignal) => ({
  providerId: 'openai-tts' as const,
  apiKey: 'fixture-key',
  voice: 'alloy',
  signal,
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.fetch.mockResolvedValue(asrResponse());
  mocks.sdkTranscribe.mockResolvedValue({ text: 'spoken text' });
});
afterEach(() => vi.unstubAllEnvs());

describe('ASR caller-owned cancellation', () => {
  it('does not start a provider for an already cancelled recording', async () => {
    const owner = new AbortController();
    owner.abort();
    await expect(
      transcribeAudio(asrConfig('openai-whisper', owner.signal), recording()),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(mocks.sdkFactory).not.toHaveBeenCalled();
    expect(mocks.fetch).not.toHaveBeenCalled();
  });

  it.each<ASRProviderId>([
    'custom-asr-fixture',
    'qwen-asr',
    'azure-asr',
    'funasr-asr',
    'lemonade-asr',
  ])('passes owner signal to %s HTTP requests', async (providerId) => {
    const owner = new AbortController();
    await expect(
      transcribeAudio(asrConfig(providerId, owner.signal), recording()),
    ).resolves.toEqual({ text: 'spoken text' });
    expect(mocks.fetch.mock.calls[0][1].signal).toBe(owner.signal);
  });

  it('passes cancellation into both the SDK and its bound transport', async () => {
    const owner = new AbortController();
    await expect(
      transcribeAudio(asrConfig('openai-whisper', owner.signal), recording()),
    ).resolves.toEqual({ text: 'spoken text' });
    expect(mocks.sdkTranscribe.mock.calls[0][0].abortSignal).toBe(owner.signal);
    expect(mocks.sdkFetchFactory.mock.calls[0][1]).toBe(owner.signal);
  });

  it('rejects late success when the provider ignored cancellation', async () => {
    const owner = new AbortController();
    const pending = deferred<Response>();
    mocks.fetch.mockReturnValue(pending.promise);
    const running = transcribeAudio(asrConfig('custom-asr-fixture', owner.signal), recording());
    owner.abort();
    pending.resolve(asrResponse());
    await expect(running).rejects.toMatchObject({ name: 'AbortError' });
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
  });

  it('normalizes a late ordinary SDK failure to the cancelled owner reason', async () => {
    const owner = new AbortController();
    const pending = deferred<{ text: string }>();
    mocks.sdkTranscribe.mockReturnValue(pending.promise);
    const running = transcribeAudio(
      asrConfig('openai-whisper', owner.signal),
      Buffer.from('audio'),
    );
    owner.abort();
    pending.reject(new Error('ordinary late SDK failure'));
    await expect(running).rejects.toMatchObject({ name: 'AbortError' });
    expect(mocks.sdkTranscribe).toHaveBeenCalledTimes(1);
  });

  it('does not disguise AbortError as an empty or short transcription', async () => {
    const abort = new DOMException('audio is empty', 'AbortError');
    mocks.sdkTranscribe.mockRejectedValue(abort);
    await expect(transcribeAudio(asrConfig('openai-whisper'), recording())).rejects.toBe(abort);
  });

  it('keeps existing non-cancelled silence behavior', async () => {
    mocks.sdkTranscribe.mockRejectedValue(new Error('audio is empty'));
    await expect(transcribeAudio(asrConfig('openai-whisper'), recording())).resolves.toEqual({
      text: '',
    });
  });
});

describe('TTS caller cancellation and retained timeout', () => {
  it('does not start synthesis for an already cancelled owner', async () => {
    const owner = new AbortController();
    owner.abort();
    await expect(generateTTS(ttsConfig(owner.signal), 'hello')).rejects.toMatchObject({
      name: 'AbortError',
    });
    expect(mocks.fetch).not.toHaveBeenCalled();
  });

  it('keeps its timeout signal combined with the owner and preserves successful audio', async () => {
    const owner = new AbortController();
    mocks.fetch.mockResolvedValue(audioResponse());
    await expect(generateTTS(ttsConfig(owner.signal), 'hello')).resolves.toMatchObject({
      format: 'mp3',
    });
    const combined = mocks.fetch.mock.calls[0][1].signal as AbortSignal;
    expect(combined).not.toBe(owner.signal);
    owner.abort();
    expect(combined.aborted).toBe(true);
  });

  it('drops late audio after caller cancellation', async () => {
    const owner = new AbortController();
    const pending = deferred<Response>();
    mocks.fetch.mockReturnValue(pending.promise);
    const completed = vi.fn();
    const running = generateTTS({ ...ttsConfig(owner.signal), onCompleted: completed }, 'hello');
    owner.abort();
    pending.resolve(audioResponse());
    await expect(running).rejects.toMatchObject({ name: 'AbortError' });
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it('does not classify a cancelled caller as a generic provider failure', async () => {
    const owner = new AbortController();
    const pending = deferred<Response>();
    mocks.fetch.mockReturnValue(pending.promise);
    const running = generateTTS(ttsConfig(owner.signal), 'hello');
    owner.abort();
    pending.reject(new Error('provider failed after cancellation'));
    await expect(running).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('keeps an expired deadline as a typed provider timeout rather than caller cancellation', async () => {
    vi.stubEnv('TTS_REQUEST_TIMEOUT_MS', '5');
    mocks.fetch.mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 15));
      return audioResponse();
    });
    await expect(generateTTS(ttsConfig(), 'hello')).rejects.toBeInstanceOf(TTSRequestTimeoutError);
  });

  it('keeps a timeout typed when a transport reports its abort as AbortError', async () => {
    vi.stubEnv('TTS_REQUEST_TIMEOUT_MS', '5');
    mocks.fetch.mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init.signal.addEventListener(
            'abort',
            () => reject(new DOMException('transport aborted', 'AbortError')),
            { once: true },
          );
        }),
    );
    // Keep one ordinary timer alive while the native AbortSignal deadline fires.
    const keepAlive = setTimeout(() => {}, 30);
    try {
      await expect(generateTTS(ttsConfig(), 'hello')).rejects.toBeInstanceOf(
        TTSRequestTimeoutError,
      );
    } finally {
      clearTimeout(keepAlive);
    }
  });
});
