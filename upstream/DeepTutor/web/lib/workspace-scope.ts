import { browserBaseUrl, isSameApplicationOrigin } from './deepsteam-transport'

/** Content scope belongs to the current task URL, never to a global tab preference. */
export function activeWorkspaceId(): string {
  if (typeof window === 'undefined') return ''
  const query = new URLSearchParams(window.location.search)
  return query.get('dt_workspace') ?? query.get('workspace') ?? ''
}

export function scopedUrl(path: string, workspaceId = activeWorkspaceId()): string {
  // Never attach local identity to third-party URLs (including signed media).
  const base = new URL(browserBaseUrl())
  if (path.startsWith('//')) return path
  const absolute = /^(?:https?|deepsteam):\/\//.test(path)
  if (!path.startsWith('/') && !absolute) return path
  const url = new URL(path, base)
  if (!isSameApplicationOrigin(url, base)) return path
  if (url.pathname === '/kanban' || url.pathname === '/api/task-board' || url.pathname.startsWith('/api/task-board/')) {
    url.searchParams.delete('dt_workspace')
    url.searchParams.delete('workspace')
    return absolute ? url.toString() : `${url.pathname}${url.search}${url.hash}`
  }
  if (!url.searchParams.has('dt_workspace'))
    url.searchParams.set('dt_workspace', url.searchParams.get('workspace') ?? workspaceId)
  return absolute ? url.toString() : `${url.pathname}${url.search}${url.hash}`
}

let navigate: ((path: string) => void) | undefined
let navigationVersion = 0

/** Installed by the root navigation bridge; callers need no router singleton. */
export function registerWorkspaceNavigator(push: (path: string) => void): () => void {
  navigate = push
  return () => { if (navigate === push) navigate = undefined }
}

export async function selectWorkspace(
  workspaceId: string,
  destination = '/learning',
  options?: { beforeNavigate?: () => Promise<void> }
): Promise<void> {
  const version = ++navigationVersion
  const pending: Promise<void>[] = []
  window.dispatchEvent(new CustomEvent('deeptutor:before-workspace-switch', { detail: pending }))
  try {
    await Promise.all(pending)
    if (version !== navigationVersion) return
    await options?.beforeNavigate?.()
  } catch {
    const { notify } = await import('./notifications')
    const { default: i18n } = await import('i18next')
    notify(i18n.t('Could not save the draft. Free browser storage before switching workspaces.'), { tone: 'error' })
    window.dispatchEvent(new CustomEvent('deeptutor:workspace-switch-error'))
    return
  }
  if (version !== navigationVersion) return
  // Next owns navigation. The workspace layout resets only scoped runtimes;
  // the document, account settings and loaded assets stay in place.
  const url = new URL(scopedUrl(destination, workspaceId), browserBaseUrl())
  navigate?.(`${url.pathname}${url.search}${url.hash}`)
}

/** Keep live runtimes when staying in one store; reset them before crossing stores. */
export function navigateTask(path: string, push: (path: string) => void): void {
  const destination = scopedUrl(path)
  const url = new URL(destination, browserBaseUrl())
  const target = url.searchParams.get('dt_workspace') ?? url.searchParams.get('workspace') ?? ''
  if (target === activeWorkspaceId()) push(destination)
  else void selectWorkspace(target, destination)
}

