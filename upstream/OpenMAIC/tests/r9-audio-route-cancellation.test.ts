import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { POST as transcribe } from '@/app/api/transcription/route';
import { POST as synthesize } from '@/app/api/generate/tts/route';

const mocks = vi.hoisted(() => ({ asr: vi.fn(), tts: vi.fn(), usage: vi.fn() }));
vi.mock('@/lib/audio/asr-providers', () => ({ transcribeAudio: mocks.asr }));
vi.mock('@/lib/audio/tts-providers', async (original) => ({
  ...(await original<typeof import('@/lib/audio/tts-providers')>()),
  generateTTS: mocks.tts,
}));
vi.mock('@/lib/server/usage-storage', () => ({ recordGenerationUsage: mocks.usage }));
vi.mock('@/lib/server/provider-config', () => ({
  isServerConfiguredProvider: () => false,
  isServerProviderDisabled: () => false,
  isServerTTSProviderDisabled: () => false,
  resolveServerASRProviderId: () => 'openai-whisper',
  resolveASRApiKey: () => 'fixture-key',
  resolveASRBaseUrl: () => 'https://audio.example.invalid',
  resolveASRModel: () => 'fixture-asr',
  resolveTTSApiKey: () => 'fixture-key',
  resolveTTSBaseUrl: () => 'https://audio.example.invalid',
  resolveTTSModel: () => 'fixture-tts',
  TTSModelNotAllowedError: class extends Error {},
}));
vi.mock('@/lib/server/ssrf-guard', () => ({
  findUnsafeNetworkTargetError: () => undefined,
  validatePublicUrlForSSRF: async () => undefined,
}));

function asrRequest(owner: AbortController) {
  const body = new FormData();
  body.set('audio', new File(['fixture'], 'audio.wav', { type: 'audio/wav' }));
  body.set('providerId', 'openai-whisper');
  return new NextRequest('http://localhost/api/transcription', {
    method: 'POST',
    body,
    signal: owner.signal,
  });
}
function ttsRequest(owner: AbortController) {
  return new NextRequest('http://localhost/api/generate/tts', {
    method: 'POST',
    signal: owner.signal,
    body: JSON.stringify({
      text: 'hello',
      audioId: 'fixture-audio',
      ttsProviderId: 'openai-tts',
      ttsVoice: 'alloy',
    }),
    headers: { 'content-type': 'application/json' },
  });
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.asr.mockResolvedValue({ text: 'spoken text' });
  mocks.tts.mockImplementation(async (config) => {
    config.onCompleted?.();
    return { audio: new Uint8Array([1, 2]), format: 'mp3' };
  });
});

describe('audio API request lifetime', () => {
  it.each(['asr', 'tts'])(
    'rejects an already cancelled %s request without calling its provider',
    async (kind) => {
      const owner = new AbortController();
      const request = kind === 'asr' ? asrRequest(owner) : ttsRequest(owner);
      owner.abort();
      await expect((kind === 'asr' ? transcribe : synthesize)(request)).rejects.toMatchObject({
        name: 'AbortError',
      });
      expect(mocks.asr).not.toHaveBeenCalled();
      expect(mocks.tts).not.toHaveBeenCalled();
      expect(mocks.usage).not.toHaveBeenCalled();
    },
  );

  it.each(['asr', 'tts'])(
    'passes the exact %s request signal into the provider config',
    async (kind) => {
      const request =
        kind === 'asr' ? asrRequest(new AbortController()) : ttsRequest(new AbortController());
      const response = await (kind === 'asr' ? transcribe : synthesize)(request);
      expect(response.status).toBe(200);
      expect((kind === 'asr' ? mocks.asr : mocks.tts).mock.calls[0][0].signal).toBe(request.signal);
    },
  );

  it.each(['asr', 'tts'])('does not publish late %s output after cancellation', async (kind) => {
    const owner = new AbortController();
    const provider = kind === 'asr' ? mocks.asr : mocks.tts;
    provider.mockImplementation(async (config) => {
      owner.abort();
      if (kind === 'tts') config.onCompleted?.();
      return kind === 'asr' ? { text: 'stale' } : { audio: new Uint8Array([1]), format: 'mp3' };
    });
    await expect(
      (kind === 'asr' ? transcribe : synthesize)(
        kind === 'asr' ? asrRequest(owner) : ttsRequest(owner),
      ),
    ).rejects.toMatchObject({ name: 'AbortError' });
    if (kind === 'tts') {
      expect(mocks.usage).toHaveBeenCalledExactlyOnceWith({
        kind: 'tts',
        unit: 'character',
        providerId: 'openai-tts',
        modelId: 'fixture-tts',
        quantity: 5,
      });
    } else {
      expect(mocks.usage).not.toHaveBeenCalled();
    }
  });

  it.each(['asr', 'tts'])(
    'preserves %s AbortError instead of mapping it to HTTP 500',
    async (kind) => {
      const abort = new DOMException('cancelled upstream', 'AbortError');
      (kind === 'asr' ? mocks.asr : mocks.tts).mockRejectedValue(abort);
      const request =
        kind === 'asr' ? asrRequest(new AbortController()) : ttsRequest(new AbortController());
      await expect((kind === 'asr' ? transcribe : synthesize)(request)).rejects.toBe(abort);
    },
  );

  it.each(['asr', 'tts'])(
    'keeps an ordinary %s provider failure as its existing HTTP 500',
    async (kind) => {
      (kind === 'asr' ? mocks.asr : mocks.tts).mockRejectedValue(
        new Error('ordinary fixture provider error'),
      );
      const request =
        kind === 'asr' ? asrRequest(new AbortController()) : ttsRequest(new AbortController());
      expect((await (kind === 'asr' ? transcribe : synthesize)(request)).status).toBe(500);
      expect(mocks.usage).not.toHaveBeenCalled();
    },
  );
});
