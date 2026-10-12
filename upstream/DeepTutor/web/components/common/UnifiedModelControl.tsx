'use client'

import { useEffect, useMemo, useState } from 'react'
import ModelSelector from '@/components/chat/home/ModelSelector'
import { useLLMOptions } from '@/hooks/useLLMOptions'
import type { LLMSelection } from '@/features/chat/model/protocol'
import { resolveModel, type ResolvedModel } from '@/lib/resolved-model'

export function UnifiedModelControl({ value, onChange, surface, disabled = false, label, placement = 'top' }: {
  value: LLMSelection | null
  onChange: (selection: LLMSelection | null) => void
  surface: string
  disabled?: boolean
  label?: string
  placement?: 'top' | 'bottom'
}) {
  const models = useLLMOptions()
  const profileId = value?.profile_id
  const modelId = value?.model_id
  const selection = useMemo(() => profileId && modelId ? { profile_id: profileId, model_id: modelId } : null, [profileId, modelId])
  const requestKey = JSON.stringify([selection, surface, models.activeDefault])
  const [result, setResult] = useState<{ key: string; resolved: ResolvedModel | null; error: string } | null>(null)
  const resolved = result?.key === requestKey ? result.resolved : null
  const error = result?.key === requestKey ? result.error : ''
  useEffect(() => {
    let alive = true
    void resolveModel(selection, surface).then(response => { if (alive) setResult({ key: requestKey, resolved: response.resolved_model, error: '' }) }).catch(() => { if (alive) setResult({ key: requestKey, resolved: null, error: 'The model is unavailable. Check the connection or select another model.' }) })
    return () => { alive = false }
  }, [selection, surface, models.options, requestKey])
  return <div className="min-w-0 space-y-1.5" data-model-surface={surface}>
    {label && <p className="text-xs font-medium text-[var(--muted-foreground)]">{label}</p>}
    <ModelSelector options={models.options} activeDefault={models.activeDefault} value={value} loading={models.loading} error={models.error} disabled={disabled} allowSystemDefault pinned placement={placement} onChange={onChange} onRefresh={() => void models.refresh({ force: true })} />
    {error && <p role="status" className="text-xs text-[var(--destructive)]">{error}</p>}
    {resolved && <p className="text-[11px] text-[var(--muted-foreground)]">{resolved.context_window ? `Context ${(resolved.context_window / 1000).toLocaleString('en-US', { maximumFractionDigits: 1 })}k` : 'Context capacity not provided'}{resolved.reasoning_effort ? ` · Reasoning ${resolved.reasoning_effort}` : ''}</p>}
  </div>
}
