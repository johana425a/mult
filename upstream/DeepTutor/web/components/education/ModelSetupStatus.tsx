'use client'

import { useEffect, useState } from 'react'
import { deepsteamRequest } from '@/lib/deepsteam-api'
import type { ModelConnection } from '@/lib/model-connection'
import { ConnectionSummary } from './ConnectionSummary'

export function ModelSetupStatus({ service }: { service: 'llm' | 'embedding' }) {
  const [connection, setConnection] = useState<ModelConnection | null>(null)
  useEffect(() => {
    let alive = true
    void deepsteamRequest<ModelConnection>('/models/connection').then(value => { if (alive) setConnection(value) }).catch(() => {})
    return () => { alive = false }
  }, [])
  if (service === 'llm') return <ConnectionSummary connection={connection} />
  if (!connection?.embedding) return null
  const embedding = connection.embedding
  return <div className="rounded-xl border border-[var(--border)] p-4 text-xs leading-relaxed" role="status"><strong className="block text-sm">Embedding search: {embedding.verified ? 'Verified' : embedding.configured ? 'Configured; verification pending' : 'Not configured'}</strong>{embedding.model && <p className="mt-1">{embedding.provider} · {embedding.model}</p>}<p className="mt-2 text-[var(--muted-foreground)]">{embedding.message}</p></div>
}
