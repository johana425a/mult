import { beforeEach, describe, expect, it, vi } from 'vitest';
import { audioProviderFetch, createAudioProviderFetch } from '@/lib/server/audio-provider-fetch';

const mocks = vi.hoisted(() => ({
  transport: vi.fn(),
  redirected: vi.fn(),
  dispatcher: vi.fn(() => ({ destroy: async () => {} })),
}));
vi.mock('undici', async (original) => ({
  ...(await original<typeof import('undici')>()),
  fetch: mocks.transport,
}));
vi.mock('@/lib/server/pinned-dispatcher', () => ({ createValidatedDispatcher: mocks.dispatcher }));
vi.mock('@/lib/server/ssrf-guard', () => ({
  allowLocalNetworksEnabled: () => false,
  assertSafeConnectionAddress: vi.fn(),
  findUnsafeNetworkTargetError: () => undefined,
}));
vi.mock('@/lib/server/fetch-with-redirect-validation', () => ({
  fetchWithRedirectValidation: mocks.redirected,
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.transport.mockResolvedValue(new Response('audio'));
  mocks.redirected.mockResolvedValue(new Response('audio'));
});

describe('strict audio transport cancellation fences', () => {
  it('rejects pre-abort before constructing or calling a transport', async () => {
    const owner = new AbortController();
    owner.abort();
    await expect(
      audioProviderFetch('https://audio.example.invalid', { signal: owner.signal }),
    ).rejects.toBe(owner.signal.reason);
    expect(mocks.transport).not.toHaveBeenCalled();
    expect(mocks.redirected).not.toHaveBeenCalled();
    expect(mocks.dispatcher).not.toHaveBeenCalled();
  });

  it.each([false, true])(
    'rejects ignored late cancellation, rejectRedirects=%s',
    async (rejectRedirects) => {
      const owner = new AbortController();
      (rejectRedirects ? mocks.transport : mocks.redirected).mockImplementation(async () => {
        owner.abort();
        return new Response('late result');
      });
      await expect(
        audioProviderFetch(
          'https://audio.example.invalid',
          { signal: owner.signal },
          { rejectRedirects },
        ),
      ).rejects.toBe(owner.signal.reason);
    },
  );

  it('preserves a distinct native timeout reason', async () => {
    const timeout = new AbortController();
    const reason = new DOMException('deadline', 'TimeoutError');
    mocks.redirected.mockImplementation(async () => {
      timeout.abort(reason);
      throw new Error('late network error');
    });
    await expect(
      audioProviderFetch('https://audio.example.invalid', { signal: timeout.signal }),
    ).rejects.toBe(reason);
  });

  it('combines SDK and caller signals instead of replacing either lifecycle', async () => {
    const owner = new AbortController();
    const sdk = new AbortController();
    const bound = createAudioProviderFetch({}, owner.signal);
    await bound('https://audio.example.invalid', { signal: sdk.signal });
    const combined = mocks.redirected.mock.calls[0][1].signal as AbortSignal;
    sdk.abort();
    expect(combined.aborted).toBe(true);
    await expect(bound('https://audio.example.invalid')).resolves.toBeInstanceOf(Response);
    owner.abort();
    await expect(bound('https://audio.example.invalid')).rejects.toBe(owner.signal.reason);
  });
});
