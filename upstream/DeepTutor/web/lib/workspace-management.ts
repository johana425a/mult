import { deepsteamJSON, deepsteamRequest } from './deepsteam-api'
import { invalidateClientCache } from './client-cache'
import { notifySessionsChanged } from './session-events'

export interface ManagedWorkspace {
  id: string | null
  harness_workspace_id: string | null
  native_workspace_id: string | null
  title: string
  name: string
  path: string
  archived: boolean
  session_ids: string[]
}
export interface WorkspaceManagementResult {
  workspace: ManagedWorkspace
  operation: 'rename' | 'archive' | 'restore'
}

/** Shared management mutation; deletion is reversible registry archival. */
export async function manageWorkspace(id: string, patch: { name?: string; archived?: boolean }): Promise<WorkspaceManagementResult> {
  const result = await deepsteamRequest<WorkspaceManagementResult>(`/harness/workspaces/${encodeURIComponent(id)}/manage`, deepsteamJSON(patch, 'PATCH'))
  invalidateClientCache('workspaces:')
  invalidateClientCache('knowledge:')
  notifySessionsChanged()
  return result
}
