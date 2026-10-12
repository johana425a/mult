export type UninstallerStatus = 'opened' | 'already-open' | 'unavailable' | 'failed' | 'denied'

interface DeepSteamDesktop {
  webSocketUrl?(path: string): string | null
  openOfficial(url: string): Promise<boolean>
  pickWorkspaceDirectory(): Promise<string | null>
  openWorkspaceDirectory(path: string): Promise<boolean>
  openRegisteredWorkspaceDirectory(workspaceId: string): Promise<boolean>
  openUninstaller?(): Promise<{ status: UninstallerStatus }>
  version: string
}

export function canOpenUninstaller(): boolean {
  return typeof window !== 'undefined' && typeof window.deepsteamDesktop?.openUninstaller === 'function'
}

export async function openUninstaller(): Promise<{ status: UninstallerStatus }> {
  if (!canOpenUninstaller()) return { status: 'unavailable' }
  return window.deepsteamDesktop!.openUninstaller!()
}

declare global {
  interface Window { deepsteamDesktop?: DeepSteamDesktop }
}

export function canPickWorkspaceDirectory(): boolean {
  return typeof window !== 'undefined' && typeof window.deepsteamDesktop?.pickWorkspaceDirectory === 'function'
}

export async function pickWorkspaceDirectory(): Promise<string | null> {
  if (!canPickWorkspaceDirectory()) throw new Error('Choose a local folder in the DeepSteam desktop app. In a browser, enter an existing local directory manually.')
  return window.deepsteamDesktop!.pickWorkspaceDirectory()
}

export function folderName(path: string): string {
  return path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || 'New workspace'
}

export async function openWorkspaceDirectory(path: string, workspaceId?: string): Promise<boolean> {
  if (!window.deepsteamDesktop?.openWorkspaceDirectory) throw new Error('Open the local workspace folder from the desktop app.')
  if (workspaceId && window.deepsteamDesktop.openRegisteredWorkspaceDirectory && await window.deepsteamDesktop.openRegisteredWorkspaceDirectory(workspaceId)) return true
  if (await window.deepsteamDesktop.openWorkspaceDirectory(path)) return true
  const selected = await pickWorkspaceDirectory()
  const normalize = (value: string) => value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
  if (!selected) return false
  if (normalize(selected) !== normalize(path)) throw new Error(`Choose the same folder as the current workspace: ${path}`)
  return window.deepsteamDesktop.openWorkspaceDirectory(selected)
}
