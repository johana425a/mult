import { apiFetch, apiUrl } from '@/lib/api'
import type { LLMSelection } from '@/features/chat/model/protocol'
import { invalidateLLMOptionsCache } from '@/lib/llm-options'
import { scopedUrl } from '@/lib/workspace-scope'

export interface ResolvedModel {
  provider: string
  provider_label: string
  model: string
  model_name: string
  selection_source: 'default' | 'override'
  reasoning_effort?: string | null
  context_window?: number | null
  context_window_source?: string
  capabilities?: { tools?: boolean; vision?: boolean; json_output?: boolean }
}

// Only public identity fields may enter a badge. Never stringify arbitrary
// metadata, replay state or runtime configuration into the interface.
export function publicResolvedModel(value: unknown): ResolvedModel | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  const model = typeof item.model === 'string' ? item.model : ''
  const name = typeof item.model_name === 'string' ? item.model_name : model
  if (!name || /^(?:dsroute|dsexec)_/i.test(name) || /^(?:dsroute|dsexec)_/i.test(model)) return null
  return {
    provider: typeof item.provider === 'string' ? item.provider : '',
    provider_label: typeof item.provider_label === 'string' ? item.provider_label : '',
    model, model_name: name,
    selection_source: item.selection_source === 'override' ? 'override' : 'default',
    reasoning_effort: typeof item.reasoning_effort === 'string' ? item.reasoning_effort : null,
    context_window: typeof item.context_window === 'number' && item.context_window > 0 ? item.context_window : null,
  }
}

export function messageResolvedModel(message: { resolvedModel?: unknown; events?: { metadata?: Record<string, unknown> }[] }): ResolvedModel | null {
  const saved = publicResolvedModel(message.resolvedModel)
  if (saved) return saved
  for (const event of message.events || []) {
    const snapshot = publicResolvedModel(event.metadata?.resolved_model)
    if (snapshot) return snapshot
  }
  return null
}

async function modelRequest(path: string, method: string, data: unknown) {
  const response = await apiFetch(apiUrl(path), { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  if (!response.ok) throw new Error('Model configuration could not be saved. Refresh and try again.')
  return response.json() as Promise<{ selection: LLMSelection; resolved_model: ResolvedModel; available: boolean }>
}
export function resolveModel(selection: LLMSelection | null, surface: string) {
  return modelRequest('/api/contest/models/resolve', 'POST', { llm_selection: selection, surface })
}
export async function setGlobalDefaultModel(selection: LLMSelection) {
  const result = await modelRequest('/api/contest/models/default', 'PUT', { llm_selection: selection })
  invalidateLLMOptionsCache()
  return result
}

export async function saveSessionModel(sessionId: string, selection: LLMSelection | null, workspaceId?: string) {
  return modelRequest(scopedUrl(`/api/contest/models/sessions/${encodeURIComponent(sessionId)}`, workspaceId), 'PUT', { llm_selection: selection })
}
