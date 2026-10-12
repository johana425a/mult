/**
 * A fetch implementation that routes asset requests through the same-origin
 * /api/proxy-media endpoint. Callers that also handle browser-owned URLs can opt
 * into cross-origin-only mode so local, blob, and data URLs stay direct, and can
 * try a CORS-enabled CDN directly before falling back to the bounded proxy. The
 * proxy validates the URL server-side (SSRF guard) and returns the bytes.
 */
import { fetchProxiedMediaUrl } from '@/lib/media/proxy-media-cache';
import { normalizeDesktopClassroomMediaUrl, isSameOriginMediaUrl,
  isDesktopClassroomMediaUrl, assertDesktopMediaOrigin } from '@/lib/media/desktop-media-url';

export function createProxiedFetch(
  options: { crossOriginOnly?: boolean; directFirst?: boolean } = {},
): typeof fetch {
  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    const originalUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const pageHref = typeof location !== 'undefined' ? location.href : undefined;
    const url = normalizeDesktopClassroomMediaUrl(originalUrl, pageHref);
    assertDesktopMediaOrigin(url, pageHref);
    const normalized = url !== originalUrl;
    if (normalized) {
      // Preserve Request headers, method and cancellation when retargeting its
      // own legacy local media address. Plain string callers stay relative.
      input = input instanceof Request ? new Request(new URL(url, pageHref).href, input)
        : input instanceof URL ? new URL(url, pageHref) : url;
    }
    // Own classroom bytes never belong in the remote proxy, even in the
    // exporters' default mode which otherwise proxies all requested assets.
    if (normalized || isDesktopClassroomMediaUrl(url, pageHref)) return fetch(input, init);
    let shouldProxy = false;
    try {
      const resolved = pageHref ? new URL(url, pageHref) : new URL(url);
      shouldProxy =
        (resolved.protocol === 'http:' || resolved.protocol === 'https:') &&
        !isSameOriginMediaUrl(url, pageHref);
    } catch {
      // Relative and browser-owned URLs are fetched directly.
    }
    const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined);
    if (options.crossOriginOnly && !shouldProxy) return fetch(input, init);
    if (options.directFirst) {
      try {
        return await fetch(input, init);
      } catch (error) {
        if (signal?.aborted) throw error;
      }
    }
    return fetchProxiedMediaUrl(url, { signal });
  }) as unknown as typeof fetch;
}
