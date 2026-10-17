import { beforeEach, expect, it, vi } from 'vitest';
import { transcribeAudio } from '@/lib/audio/asr-providers';

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock('@/lib/server/audio-provider-fetch', () => ({
  audioProviderFetch: mocks.fetch,
  audioEndpointPolicy: () => ({}),
  createAudioProviderFetch: () => mocks.fetch,
}));
beforeEach(() => vi.clearAllMocks());

it('real OpenAI transcription SDK does not retry a retryable HTTP failure after caller cancellation', async () => {
  const owner = new AbortController();
  mocks.fetch.mockImplementation(async () => {
    owner.abort();
    return Response.json({ error: { message: 'retryable fixture error' } }, { status: 503 });
  });
  await expect(
    transcribeAudio(
      { providerId: 'openai-whisper', apiKey: 'fixture-key', signal: owner.signal },
      Buffer.from('fixture audio'),
    ),
  ).rejects.toMatchObject({ name: 'AbortError' });
  expect(mocks.fetch).toHaveBeenCalledTimes(1);
  expect(mocks.fetch.mock.calls[0][1].signal.aborted).toBe(true);
});
