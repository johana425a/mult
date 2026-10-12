import { apiFetch, apiUrl } from '@/lib/api'
import { invalidateClientCache, withClientCache } from '@/lib/client-cache'
import { notifySessionsChanged } from '@/lib/session-events'
import { deepsteamJSON, deepsteamRequest } from '@/lib/deepsteam-api'
import { folderName } from '@/lib/deepsteam-desktop'
import { manageWorkspace } from '@/lib/workspace-management'

export interface WorkspaceResources {
  skills: string[] | null
  mcp: string[] | null
  knowledge_bases: string[] | null
}

export const inheritedWorkspaceResources = (): WorkspaceResources => ({
  skills: null,
  mcp: null,
  knowledge_bases: null,
})

export interface WorkspaceResourceOption {
  id: string
  name: string
  description?: string
  source?: string
  provenance_label?: string
  available?: boolean
}
export type WorkspaceResourceCatalog = Record<keyof WorkspaceResources, WorkspaceResourceOption[]>

export function getWorkspaceResources(workspaceId = ''): Promise<WorkspaceResourceCatalog> {
  return request(
    `/api/settings/workspace/resources?workspace_id=${encodeURIComponent(workspaceId)}`
  )
}

export interface ChatWorkspaceRegistration {
  harness_workspace_id?: string
  resources?: WorkspaceResources
  workspace_id: string
  kind: 'system' | 'general' | 'workspace'
  follows_root: boolean
  display_name: string
  path: string
  archived: boolean
  created_at: string
  status: 'ready' | 'invalid'
  error: string
}

const endpoint = '/api/settings/workspace/registrations'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(apiUrl(url), init)
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`)
  return payload as T
}

export function listWorkspaces(force = false): Promise<ChatWorkspaceRegistration[]> {
  return withClientCache(
    'workspaces:list',
    async () => {
      const result = await request<{ workspaces: ChatWorkspaceRegistration[] }>(endpoint)
      return result.workspaces
    },
    { force, ttlMs: 15_000 }
  )
}

export async function saveWorkspace(
  input: { name?: string; path?: string; archived?: boolean; resources?: WorkspaceResources },
  workspaceId?: string
): Promise<ChatWorkspaceRegistration> {
  const result = await request<{ workspace: ChatWorkspaceRegistration }>(
    workspaceId ? `${endpoint}/${encodeURIComponent(workspaceId)}` : endpoint,
    {
      method: workspaceId ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }
  )
  invalidateClientCache('workspaces:')
  invalidateClientCache('knowledge:')
  notifySessionsChanged()
  if (!workspaceId && input.path?.trim()) {
    return linkHarnessWorkspace(result.workspace)
  }
  return result.workspace
}

async function linkHarnessWorkspace(workspace: ChatWorkspaceRegistration): Promise<ChatWorkspaceRegistration> {
  try {
    const linked = await deepsteamRequest<{ workspace: { id: string; path: string } }>('/harness/workspaces', deepsteamJSON({ path: workspace.path, name: workspace.display_name }))
    // The earlier notification exposes a successful native registration even if
    // linkage fails. Refresh again only once both registries are ready.
    invalidateClientCache('workspaces:')
    notifySessionsChanged()
    return { ...workspace, harness_workspace_id: linked.workspace.id }
  } catch (failure) {
    throw new Error(`The learning workspace is registered at ${workspace.path}. Agent registration is incomplete. Retry with the same folder; its files remain in place. ${failure instanceof Error ? failure.message : ''}`)
  }
}

/** Open an existing folder without resetting its title or assigned resources. */
export async function openWorkspaceFolder(path: string): Promise<ChatWorkspaceRegistration> {
  const [validated, catalog] = await Promise.all([
    request<{ path: string; status: string; error?: string }>('/api/settings/workspace/validate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) }),
    getWorkspaceCatalog(),
  ])
  if (validated.status !== 'ready') throw new Error(validated.error || 'The folder is currently unavailable.')
  const normalize = (value: string) => value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
  const existing = catalog.workspaces.find(row => normalize(row.path) === normalize(validated.path))
  if (existing) {
    if (existing.status !== 'ready') throw new Error(existing.error || 'The workspace is currently unavailable.')
    let opened = existing
    if (existing.archived) {
      const restored = await manageWorkspace(existing.workspace_id, { archived: false })
      opened = { ...existing, archived: restored.workspace.archived, display_name: restored.workspace.title || restored.workspace.name, path: restored.workspace.path }
      if (opened.archived) throw new Error('The workspace has not been restored. Try again shortly.')
    }
    return linkHarnessWorkspace(opened)
  }
  // Omit resource updates: defaults apply to a new registration, while a
  // concurrent registration retains its resource selection.
  return saveWorkspace({ name: folderName(validated.path).slice(0, 100), path: validated.path })
}

export function workspaceChatHref(workspaceId: string): string {
  return `/chat?dt_workspace=${encodeURIComponent(workspaceId)}`
}

export interface WorkspaceCatalog {
  root: string
  workspaces: ChatWorkspaceRegistration[]
  migration?: { id: string } | null
}

export interface SystemWorkspaceSnapshot {
  generated_at: string
  models: Record<
    string,
    {
      active_profile_id?: string
      active_model_id?: string
      profiles: {
        id?: string
        name?: string
        binding?: string
        endpoint_origin?: string
        models: { id?: string; name?: string; model?: string }[]
      }[]
    }
  >
  mcp: { name: string; enabled: boolean; transport: string; endpoint_origin: string }[]
}

export function getWorkspaceCatalog(): Promise<WorkspaceCatalog> {
  return request<WorkspaceCatalog>(endpoint)
}

export async function migrateWorkspace(
  path: string,
  workspaceId?: string
): Promise<WorkspaceCatalog> {
  const result = await request<WorkspaceCatalog>(
    workspaceId
      ? `${endpoint}/${encodeURIComponent(workspaceId)}/migrate`
      : `${endpoint}/migrate-root`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }
  )
  invalidateClientCache('workspaces:')
  invalidateClientCache('knowledge:')
  notifySessionsChanged()
  return result
}

export function getSystemWorkspaceSnapshot(): Promise<SystemWorkspaceSnapshot> {
  return request<SystemWorkspaceSnapshot>(`${endpoint}/system-snapshot`, { method: 'POST' })
}

export function workspaceLabel(row: ChatWorkspaceRegistration, zh: boolean): string {
  if (row.kind === 'system') return zh ? 'System workspace' : 'System workspace'
  if (row.kind === 'general') return zh ? 'General workspace' : 'General workspace'
  return row.display_name
}

export async function resourceUsage(
  kind: keyof WorkspaceResources,
  resourceId: string,
  skillWorkspace = ''
): Promise<string[]> {
  const params = new URLSearchParams({
    kind,
    resource_id: resourceId,
    skill_workspace: skillWorkspace,
  })
  const result = await request<{ workspaces: { display_name: string }[] }>(
    `/api/settings/workspace/resource-usage?${params}`
  )
  return result.workspaces.map(row => row.display_name)
}

export interface KnowledgeMovePreview {
  source_id: string
  target_id: string
  source_workspace_id: string
  target_workspace_id: string
  name: string
  files: number
  bytes: number
  assignments: { workspace_id: string; display_name: string }[]
  blockers: string[]
  status?: string
  cleanup_path?: string
}

export function previewKnowledgeMove(sourceId: string, targetWorkspaceId: string): Promise<KnowledgeMovePreview> {
  return request('/api/settings/workspace/knowledge-bases/preview-move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_id: sourceId, target_workspace_id: targetWorkspaceId }),
  })
}

export async function moveKnowledgeBase(sourceId: string, targetWorkspaceId: string): Promise<KnowledgeMovePreview> {
  const result = await request<KnowledgeMovePreview>('/api/settings/workspace/knowledge-bases/move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_id: sourceId, target_workspace_id: targetWorkspaceId }),
  })
  invalidateClientCache('workspaces:')
  invalidateClientCache('knowledge:')
  notifySessionsChanged()
  return result
}
