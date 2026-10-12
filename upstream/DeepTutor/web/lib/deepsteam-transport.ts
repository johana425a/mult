/** Desktop origins are logical services; only the main process resolves ports. */
export function isDeepSteamDesktopLocation(): boolean {
  return typeof window !== 'undefined' && window.location.protocol === 'deepsteam:'
    && ['app', 'portal', 'classroom'].includes(window.location.hostname)
}

export function browserBaseUrl(): string {
  return typeof window === 'undefined' ? 'http://workspace.local/' : window.location.href
}

/** URL.origin can be "null" for a custom scheme; compare its real authority. */
export function isSameApplicationOrigin(value: URL, base = new URL(browserBaseUrl())): boolean {
  return value.protocol === base.protocol && value.host === base.host
    && !value.username && !value.password
}

export function desktopWebSocketUrl(path: string): string {
  if (!isDeepSteamDesktopLocation()) return path
  const url = window.deepsteamDesktop?.webSocketUrl?.(path)
  if (!url) throw new Error('The desktop connection is unavailable. Reopen DeepSteam.')
  return url
}

/** Display only. Never rewrite actual API configuration, remote URLs or content. */
export function safeServiceError(message: string): string {
  return message.replace(/\b(?:https?|wss?):\/\/(?:127\.0\.0\.1|localhost|\[::1\]):(379[1-6]|8011)(?=[\/?#\s"'<>)}\],;]|$)/gi,
    (_url, port: string) => port === '3793' ? 'DeepSteam classroom service' : port === '3796' ? 'DeepSteam model connection' : 'DeepSteam internal service')
}

export function serviceEndpointLabel(endpoint: string): string {
  const safe = safeServiceError(endpoint)
  return safe === endpoint ? endpoint : 'Managed automatically by DeepSteam'
}
