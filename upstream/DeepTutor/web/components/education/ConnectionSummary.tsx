'use client'

import Link from 'next/link'
import { Check, Image as ImageIcon, Volume2 } from 'lucide-react'
import type { ModelConnection } from '@/lib/model-connection'
import ProviderIcon from '@/components/common/ProviderIcon'

export function ConnectionSummary({ connection }: { connection: ModelConnection | null }) {
  if (!connection) return <p role="status" className="text-xs text-[var(--muted-foreground)]">Loading the current model connection...</p>
  const target = (value: string) => value === 'selected' ? 'Connected' : ['unavailable', 'blocked'].includes(value) ? 'Unavailable' : 'Not connected'
  return <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-xs" aria-label="Current model connection">
    <span className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--primary)]/10 text-[11px] font-semibold text-[var(--primary)]" aria-hidden="true"><ProviderIcon provider={connection.provider} size={19} /></span><span><strong className="block text-sm">{connection.provider_label || connection.provider} · {connection.model || 'No model selected'}</strong><span className="text-[var(--muted-foreground)]">{connection.route === 'account' ? 'Account sign-in' : connection.route === 'apikey' ? 'API Key' : connection.route === 'local' ? 'Local model' : connection.route === 'native' ? 'Learning model settings' : 'Custom endpoint'}</span></span></span>
    <span>Learning: {target(connection.targets.learning)}</span><span>Classroom: {target(connection.targets.classroom)}</span>
    <span className="inline-flex items-center gap-1"><Check size={12} />Text {connection.text.verified ? 'Verified' : 'Not verified'}</span>
    <span className="inline-flex items-center gap-1"><ImageIcon size={12} />Vision {connection.vision.verified ? 'Verified' : 'Not verified'}</span>
    <span className="inline-flex items-center gap-1"><Volume2 size={12} />Narration {!connection.narration.enabled ? 'Disabled' : connection.narration.configured ? (connection.narration.mode === 'local' ? 'System voice' : 'Speech API') : 'Not configured'}</span>
    <Link href="/connect" className="ml-auto underline underline-offset-4">Connect a model</Link>
    {connection.message && <p role="status" className="w-full text-[var(--muted-foreground)]">{connection.message}</p>}
  </div>
}
