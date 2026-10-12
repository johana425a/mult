import { isDeepSteamDesktopLocation, safeServiceError } from './deepsteam-transport'

/** The desktop resolves service origins internally; browser development stays local. */
export function deepsteamService(port: 3791 | 3793): string {
  if (isDeepSteamDesktopLocation()) return `deepsteam://${port === 3791 ? 'portal' : 'classroom'}`
  const hostname = typeof window !== 'undefined' && ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
    ? window.location.hostname : '127.0.0.1'
  return `http://${hostname}:${port}`
}

export async function deepsteamRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${deepsteamService(3791)}/api${path}`, {
    cache: 'no-store', signal: AbortSignal.timeout(120000), ...options,
  })
  const value = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof value.detail === 'string' ? value.detail : value.detail?.message
    throw new Error(safeServiceError(detail || `The operation did not complete (${response.status}). Try again.`))
  }
  return value as T
}

export function deepsteamJSON(value: unknown, method = 'POST'): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) }
}
