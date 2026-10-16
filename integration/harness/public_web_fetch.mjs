/** Keep the official direct DNS-pinned HTTP backend; refuse uncheckable proxy DNS. */
import { HttpFetchProvider } from '@deepseek-ai/dsh-web-fetch-http';
import { proxyRouteFor } from '@deepseek-ai/dsh-http-proxy';
import { WebError } from '@deepseek-ai/dsh-web';

export class PublicPinnedHttpFetch extends HttpFetchProvider {
  // The pinned official implementation calls this method for every redirect
  // hop. Its direct branch resolves and validates every IP and pins transport.
  // A remote-DNS proxy cannot offer that guarantee, so reject it before any
  // request is sent. Never change the global proxy used by model services.
  async requestOnce(url, signal) {
    if (proxyRouteFor(url).proxied) {
      throw new WebError('This webpage route uses a remote-DNS proxy whose public destination cannot be verified. '
        + 'The webpage request was blocked before network access. Use a direct webpage connection; the model proxy remains unchanged.',
      'WEB_PROXY_DESTINATION_UNVERIFIABLE');
    }
    return super.requestOnce(url, signal);
  }
}

export const name = 'deepsteam-public-pinned-web-fetch';
export const inject = ['web'];
export function apply(ctx) {
  ctx.web.registerFetchProvider(new PublicPinnedHttpFetch({ userAgent: 'DeepSteam/official-harness',
    maxResponseBytes: 5_000_000, maxBodyChars: 100_000, timeoutMs: 30_000, maxRedirects: 5 }));
}
