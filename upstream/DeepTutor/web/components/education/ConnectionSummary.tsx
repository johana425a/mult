'use client'

import { standaloneCopy, useStandaloneCopy } from '@/i18n/standalone'
import Link from 'next/link'
import { Check, Image as ImageIcon, Volume2 } from 'lucide-react'
import type { ModelConnection } from '@/lib/model-connection'
import ProviderIcon from '@/components/common/ProviderIcon'

export function ConnectionSummary({ connection }: { connection: ModelConnection | null }) {
  useStandaloneCopy()
  if (!connection) return <p role="status" className="text-xs text-[var(--muted-foreground)]">{standaloneCopy("Loading the current model connection...")}</p>
  const target = (value: string) => value === 'selected' ? standaloneCopy("Connected") : ['unavailable', 'blocked'].includes(value) ? standaloneCopy("Unavailable") : standaloneCopy("Not connected")
  return <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-xs" aria-label={standaloneCopy("Current model connection")}>
    <span className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--primary)]/10 text-[11px] font-semibold text-[var(--primary)]" aria-hidden="true"><ProviderIcon provider={connection.provider} size={19} /></span><span><strong className="block text-sm">{connection.provider_label || connection.provider} · {connection.model || standaloneCopy("No model selected")}</strong><span className="text-[var(--muted-foreground)]">{connection.route === 'account' ? standaloneCopy("Account sign-in") : connection.route === 'apikey' ? 'API Key' : connection.route === 'local' ? standaloneCopy("Local model") : connection.route === 'native' ? standaloneCopy("Learning model settings") : standaloneCopy("Custom endpoint")}</span></span></span>
    <span>{standaloneCopy("Learning:")} {target(connection.targets.learning)}</span><span>{standaloneCopy("Classroom:")} {target(connection.targets.classroom)}</span>
    <span className="inline-flex items-center gap-1"><Check size={12} />{standaloneCopy("Text")} {connection.text.verified ? standaloneCopy("Verified") : standaloneCopy("Not verified")}</span>
    <span className="inline-flex items-center gap-1"><ImageIcon size={12} />{standaloneCopy("Vision")} {connection.vision.verified ? standaloneCopy("Verified") : standaloneCopy("Not verified")}</span>
    <span className="inline-flex items-center gap-1"><Volume2 size={12} />{standaloneCopy("Narration")} {!connection.narration.enabled ? standaloneCopy("Disabled") : connection.narration.configured ? (connection.narration.mode === 'local' ? standaloneCopy("System voice") : standaloneCopy("Speech API")) : standaloneCopy("Not configured")}</span>
    <Link href="/connect" className="ml-auto underline underline-offset-4">{standaloneCopy("Connect a model")}</Link>
    {connection.message && <p role="status" className="w-full text-[var(--muted-foreground)]">{connection.message}</p>}
  </div>
}
