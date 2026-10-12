/** Read-time compatibility for this desktop app's own historical media URLs.
 * Stored documents are untouched; remote/custom API URLs keep their normal
 * proxy/SSRF policy. Node URL reports opaque custom origins as "null", so
 * identity must compare the actual protocol and host, never that string.
 */
function classroomPage(href: string | undefined): URL | undefined {
  if (!href) return undefined;
  try {
    const page = new URL(href);
    return page.protocol === 'deepsteam:' && page.hostname === 'classroom'
      && !page.port && !page.username && !page.password ? page : undefined;
  } catch { return undefined; }
}

export function normalizeDesktopClassroomMediaUrl(
  value: string,
  pageHref = typeof location !== 'undefined' ? location.href : undefined,
): string {
  const page = classroomPage(pageHref);
  if (!page) return value;
  try {
    const url = new URL(value, page.href);
    const ownLegacy = url.protocol === 'http:' && url.port === '3793'
      && ['localhost', '[::1]'].includes(url.hostname);
    const ownDesktop = url.protocol === 'deepsteam:' && url.hostname === 'classroom' && !url.port;
    if ((!ownLegacy && !ownDesktop) || url.username || url.password
      || !url.pathname.startsWith('/api/classroom-media/')) return value;
    return url.pathname + url.search + url.hash;
  } catch { return value; }
}

export function isSameOriginMediaUrl(
  value: string,
  pageHref = typeof location !== 'undefined' ? location.href : undefined,
): boolean {
  if (!pageHref) return false;
  try {
    const page = new URL(pageHref), url = new URL(value, page.href);
    if (url.username || url.password) return false;
    if (classroomPage(pageHref)) {
      return url.protocol === page.protocol && url.hostname === page.hostname && !url.port;
    }
    return page.origin !== 'null' && url.origin === page.origin;
  } catch { return false; }
}

export function isDesktopClassroomMediaUrl(
  value: string,
  pageHref = typeof location !== 'undefined' ? location.href : undefined,
): boolean {
  if (!classroomPage(pageHref)) return false;
  try {
    const normalized = normalizeDesktopClassroomMediaUrl(value, pageHref);
    return isSameOriginMediaUrl(normalized, pageHref)
      && new URL(normalized, pageHref).pathname.startsWith('/api/classroom-media/');
  } catch { return false; }
}

/** Opaque origins must not accidentally equate other desktop service hosts. */
export function assertDesktopMediaOrigin(
  value: string,
  pageHref = typeof location !== 'undefined' ? location.href : undefined,
): void {
  let url: URL;
  try { url = new URL(value, pageHref); } catch { return; }
  if (url.protocol === 'deepsteam:' && !isSameOriginMediaUrl(value, pageHref)) {
    throw new TypeError('Unsupported desktop media origin.');
  }
}
