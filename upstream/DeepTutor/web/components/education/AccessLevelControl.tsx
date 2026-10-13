'use client'

import { useEffect, useState } from 'react'
import { FolderLock, HardDrive } from 'lucide-react'
import { Dialog } from '@/shared/ui/Dialog'
import { pageActionClass } from '@/components/layout/FeaturePage'
import { harnessWorkspaceAPI as api, type HarnessAccessLevel } from '@/lib/harness-workspace'

const options: { id: HarnessAccessLevel; label: string; Icon: typeof FolderLock }[] = [
  { id: 'workspace', label: 'Workspace only', Icon: FolderLock },
  { id: 'full', label: 'Full computer', Icon: HardDrive },
]

/**
 * DeepSteam access level for agent tasks. Full computer (the default) lets
 * tasks use other folders and drives and search for material proactively;
 * Workspace only keeps file and document tools inside the opened folder.
 * Credential stores stay protected either way. Applies from the next task.
 */
export function AccessLevelControl({ disabled, onChange, compact }: { disabled?: boolean; onChange?: (level: HarnessAccessLevel) => void; compact?: boolean }) {
  const [level, setLevel] = useState<HarnessAccessLevel>('full')
  const [available, setAvailable] = useState(false)
  const [locked, setLocked] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    api.access().then(value => {
      if (!active) return
      setLevel(value.default_access); setLocked(Boolean(value.locked)); setAvailable(true); onChange?.(value.default_access)
    }).catch(() => { /* Host offline: keep the safe default display. */ })
    return () => { active = false }
  }, [onChange])

  const save = async (next: HarnessAccessLevel) => {
    setSaving(true); setError('')
    try {
      const value = await api.setAccess(next)
      setLevel(value.default_access); onChange?.(value.default_access); setConfirming(false)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The access level was not changed.')
    } finally { setSaving(false) }
  }
  const choose = (next: HarnessAccessLevel) => {
    if (next === level || disabled || locked || saving) return
    if (next === 'full') setConfirming(true)
    else void save(next)
  }

  const index = options.findIndex(option => option.id === level)
  const dialog = <Dialog open={confirming} title="Allow access to the whole computer?" onClose={() => setConfirming(false)} size="sm" busy={saving} closeLabel="Close"
    footer={<><button className={pageActionClass('secondary')} disabled={saving} onClick={() => setConfirming(false)}>Keep workspace only</button>
      <button data-autofocus className={pageActionClass('primary')} disabled={saving} onClick={() => void save('full')}>{saving ? 'Saving...' : 'Allow full access'}</button></>}>
    <div className="space-y-2 text-sm leading-relaxed">
      <p>Agents will be able to open, search and edit files in other folders and drives when a task needs them, and may look for relevant material on their own, as a coding agent with full access would.</p>
      <p className="text-[var(--muted-foreground)]">Password stores, browser profiles and DeepSteam&apos;s own settings stay protected. You can switch back at any time; it applies from the next task.</p>
    </div>
  </Dialog>
  if (compact) {
    // Toolbar chip for the chat composer: one tap toggles, full access asks first.
    if (!available) return null
    const current = options[index] ?? options[1]
    const Icon = current.Icon
    const next = level === 'full' ? 'workspace' : 'full'
    return <>
      <button type="button" disabled={disabled || locked || saving} onClick={() => choose(next)}
        aria-label={`Agent access: ${current.label}. ${locked ? 'Fixed by this installation.' : `Switch to ${next === 'full' ? 'Full computer' : 'Workspace only'}.`}`}
        title={error || (locked ? 'This installation keeps agents inside the opened folder.'
          : level === 'full' ? 'Agents may use other folders and drives. Click to keep them inside the workspace.' : 'Agents stay inside the opened folder. Click to allow other drives.')}
        className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2 text-[13px] font-medium text-[var(--muted-foreground)] transition-[background-color,color,transform] duration-150 hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)] active:scale-[0.97] disabled:opacity-50">
        <Icon key={level} size={15} strokeWidth={1.7} aria-hidden className="ds-pop-icon" />
        <span className="hidden sm:inline">{current.label}</span>
      </button>
      {dialog}
    </>
  }
  return <div className="flex flex-col gap-1.5">
    <div role="radiogroup" aria-label="Agent access level" className="ds-segmented" data-disabled={disabled || locked || undefined}>
      <span aria-hidden className="ds-segmented-thumb" style={{ transform: `translateX(${index * 100}%)` }} />
      {options.map(({ id, label, Icon }) => <button key={id} type="button" role="radio" aria-checked={level === id}
        disabled={disabled || locked || saving} onClick={() => choose(id)} className="ds-segmented-option">
        <Icon size={13} aria-hidden />{label}
      </button>)}
    </div>
    <p className="text-[11px] leading-snug text-[var(--muted-foreground)]">
      {locked ? 'This installation keeps agents inside the opened folder.'
        : level === 'full' ? 'Agents may use other folders and drives and look for material on their own. Applies from the next task.'
          : 'Agents read and edit only the opened folder. Switch to Full computer to let them use other drives.'}
    </p>
    {error && <p role="alert" className="text-[11px] text-[var(--destructive)]">{error}</p>}
    {dialog}
  </div>
}
