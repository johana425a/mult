import { deepsteamJSON, deepsteamRequest } from './deepsteam-api'
import type { LLMSelection } from '@/features/chat/model/protocol'
import type { ResolvedModel } from './resolved-model'

export interface HarnessWorkspace { id: string; path: string; title: string; created_at: string; updated_at: string; session_ids: string[]; archived?: boolean }
export type HarnessAccessLevel = 'workspace' | 'full'
export interface HarnessAccess { default_access: HarnessAccessLevel; levels: HarnessAccessLevel[]; locked?: boolean }
export interface HarnessSession { id: string; workspace_id: string; status: string; cwd: string; title?: string; llm_selection?: LLMSelection | null; resolved_model?: ResolvedModel; access_level?: HarnessAccessLevel }
export interface HarnessApproval {
  id: string; session_id: string; tool_name: string
  exact_action: { name: string; arguments: unknown; cwd: string }
  status: string; warning?: string
}
export interface HarnessEvent {
  resolved_model?: ResolvedModel
  seq: number; type: string; timestamp: string; text?: string; tool_name?: string
  arguments?: unknown; content?: unknown; is_error?: boolean; approval?: HarnessApproval; approval_id?: string; outcome?: string
}
export interface WorkspaceEvents { session: HarnessSession; events: HarnessEvent[]; next_seq: number; pending_approvals: HarnessApproval[] }

export function mergeHarnessEvents(previous: HarnessEvent[], incoming: HarnessEvent[]): HarnessEvent[] {
  const events = new Map(previous.map(event => [event.seq, event]))
  for (const event of incoming) if (Number.isInteger(event.seq) && event.seq >= 0) events.set(event.seq, event)
  return [...events.values()].sort((a, b) => a.seq - b.seq)
}

export function harnessEventText(event: HarnessEvent): string {
  if (typeof event.text === 'string') return event.text
  if (typeof event.content === 'string') return event.content
  if (Array.isArray(event.content)) return event.content.filter(block => block?.type === 'text' && typeof block.text === 'string').map(block => block.text).join('\n')
  return event.content === undefined ? '' : JSON.stringify(event.content, null, 2)
}

export interface HarnessImage { attachmentId: string; mediaType: string }
export function harnessEventImages(event: HarnessEvent): HarnessImage[] {
  const blocks = Array.isArray(event.content) ? event.content : [event.content]
  return blocks.flatMap(block => {
    const image = block && typeof block === 'object' ? block as { type?: string; attachment?: HarnessImage } : null
    return image?.type === 'image' && typeof image.attachment?.attachmentId === 'string'
      && /^image\/(png|jpeg|webp|gif)$/.test(image.attachment.mediaType) ? [image.attachment] : []
  })
}

export const harnessWorkspaceAPI = {
  access: () => deepsteamRequest<HarnessAccess>('/harness/workspace-access'),
  setAccess: (level: HarnessAccessLevel) => deepsteamRequest<HarnessAccess>('/harness/workspace-access', deepsteamJSON({ default_access: level })),
  list: () => deepsteamRequest<{ workspaces: HarnessWorkspace[] }>('/harness/workspaces'),
  create: (path: string, name: string) => deepsteamRequest<{ workspace: HarnessWorkspace }>('/harness/workspaces', deepsteamJSON({ path, name })),
  sessions: (id: string) => deepsteamRequest<{ sessions: HarnessSession[] }>(`/harness/workspaces/${encodeURIComponent(id)}/sessions`),
  newSession: (id: string) => deepsteamRequest<{ session: HarnessSession }>(`/harness/workspaces/${encodeURIComponent(id)}/sessions`, deepsteamJSON({})),
  events: (id: string, after: number) => deepsteamRequest<WorkspaceEvents>(`/harness/sessions/${encodeURIComponent(id)}/events?after_seq=${after}`),
  turn: (id: string, text: string, llmSelection: LLMSelection | null = null) => deepsteamRequest<{ run_id: string; session_id: string; status: string; resolved_model?: ResolvedModel; access_level?: HarnessAccessLevel }>(`/harness/sessions/${encodeURIComponent(id)}/turn`, deepsteamJSON({ text, llm_selection: llmSelection })),
  cancel: (id: string) => deepsteamRequest<{ cancelled: boolean }>(`/harness/sessions/${encodeURIComponent(id)}/cancel`, deepsteamJSON({})),
  approve: (approval: HarnessApproval, decision: 'allow' | 'deny') => deepsteamRequest<{ accepted: boolean }>(`/harness/approvals/${encodeURIComponent(approval.id)}`, deepsteamJSON({ session_id: approval.session_id, decision })),
}
