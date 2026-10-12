'use client'

import { FolderOpen, AlertCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatWorkspaces } from '@/hooks/useChatWorkspaces'
import { activeWorkspaceId } from '@/lib/workspace-scope'

/** Display the existing task binding. This never moves an existing conversation. */
export function WorkspaceSourceStatus({ workspaceId, compact = false }: {
  workspaceId?: string
  compact?: boolean
}) {
  const id = workspaceId ?? activeWorkspaceId()
  return id ? <BoundWorkspaceSourceStatus id={id} compact={compact} /> : null
}

function BoundWorkspaceSourceStatus({ id, compact }: { id: string; compact: boolean }) {
  const { workspaces, error } = useChatWorkspaces()
  const { i18n } = useTranslation()
  const zh = (i18n?.language ?? 'en').startsWith('zh')
  const workspace = workspaces.find(row => row.workspace_id === id)
  const unavailable = Boolean(error || workspace?.status === 'invalid')
  const label = workspace?.display_name || (zh ? 'Current workspace' : 'Current workspace')
  const detail = unavailable
    ? workspace?.error || error || (zh ? 'Workspace is unavailable' : 'Workspace is unavailable')
    : zh ? 'Find and read files here on demand, without uploading them again.' : 'Find and read files here on demand, without uploading them again.'
  return (
    <details className={`min-w-0 rounded-lg border border-border/60 bg-background/50 text-muted-foreground ${compact ? 'px-2.5 py-1.5 text-xs' : 'px-3 py-2 text-sm'}`}>
      <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden" title={workspace?.path || label}>
        {unavailable ? <AlertCircle size={14} className="shrink-0 text-amber-500" /> : <FolderOpen size={14} className="shrink-0 text-primary" />}
        <span className="shrink-0">{zh ? 'Source workspace' : 'Source workspace'}</span>
        <span className="min-w-0 truncate font-medium text-foreground">{label}</span>
        <span className="ml-auto shrink-0 text-[10px] opacity-70">{zh ? 'Details' : 'Details'}</span>
      </summary>
      <div className="mt-2 space-y-1 border-t border-border/50 pt-2 leading-5">
        {workspace?.path && <p className="break-all text-foreground">{workspace.path}</p>}
        <p role={unavailable ? 'alert' : undefined}>{workspace || unavailable ? detail : (zh ? 'Loading workspace information…' : 'Loading workspace information…')}</p>
        <p className="text-[11px]">{zh ? 'PDF, Word, PowerPoint and Markdown are read as needed, rather than loading the whole folder into model context.' : 'PDF, Word, PowerPoint and Markdown are read as needed, rather than loading the whole folder into model context.'}</p>
      </div>
    </details>
  )
}
