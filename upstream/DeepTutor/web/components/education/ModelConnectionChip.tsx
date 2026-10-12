'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { deepsteamRequest } from '@/lib/deepsteam-api'
import type { ModelConnection } from '@/lib/model-connection'
import ProviderIcon from '@/components/common/ProviderIcon'
import { LLM_OPTIONS_UPDATED_EVENT } from '@/lib/llm-options'

/** Read-only status; never probes or calls a model while rendering navigation. */
export function ModelConnectionChip() {
  const [connection, setConnection] = useState<ModelConnection | null>(null)
  useEffect(() => {
    let alive = true
    const refresh = () => { void deepsteamRequest<ModelConnection>('/models/connection').then(value => { if (alive) setConnection(value) }).catch(() => { if (alive) setConnection(null) }) }
    refresh()
    const timer = setInterval(refresh, 15000)
    window.addEventListener('focus', refresh)
    window.addEventListener(LLM_OPTIONS_UPDATED_EVENT, refresh)
    return () => { alive = false; clearInterval(timer); window.removeEventListener('focus', refresh); window.removeEventListener(LLM_OPTIONS_UPDATED_EVENT, refresh) }
  }, [])
  if (!connection?.model) return null
  return <Link href="/connect" prefetch={false} className="mb-2 flex min-w-0 items-center gap-2 rounded-lg border border-[var(--border)] px-2.5 py-2 text-xs" title={`${connection.provider_label} · ${connection.model}; Learning: ${connection.targets.learning === 'selected' ? 'Connected' : 'Not connected'}; Classroom: ${connection.targets.classroom === 'selected' ? 'Connected' : 'Not connected'}`}>
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--primary)]/10 text-[10px] font-semibold text-[var(--primary)]"><ProviderIcon provider={connection.provider} size={16} /></span>
    <span className="min-w-0"><strong className="block truncate text-[11px]">{connection.provider_label}</strong><span className="block truncate text-[10px] text-[var(--muted-foreground)]">{connection.model}</span></span>
  </Link>
}
