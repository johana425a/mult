'use client'

import { useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { WorkspaceContextMenu } from './WorkspaceContextMenu'
import { ConfirmDialog } from './ConfirmDialog'

/** One confirmation and one in-flight request; failures keep the object and retry visible. */
export function PermanentDeleteMenu({ children, title, description, onDelete, onOpen, disabled = false, className = '' }: {
  children: ReactNode
  title: string
  description: string
  onDelete?: () => Promise<unknown>
  onOpen?: () => void
  disabled?: boolean
  className?: string
}) {
  const { t } = useTranslation()
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inFlight = useRef(false)
  const remove = async () => {
    if (!onDelete || inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError('')
    try { await onDelete(); setConfirm(false) }
    catch (reason) { setError(reason instanceof Error ? reason.message : t('Delete failed')) }
    finally { inFlight.current = false; setBusy(false) }
  }
  return <>
    <WorkspaceContextMenu className={className} disabled={disabled || busy} label={t('Manage {{name}}', { name: title })} items={[
      ...(onOpen ? [{ id: 'open', label: t('Open'), onSelect: onOpen }] : []),
      ...(onDelete ? [{ id: 'delete', label: t('Delete permanently'), danger: true, onSelect: () => { setError(''); setConfirm(true) } }] : []),
    ]}>{children}</WorkspaceContextMenu>
    <ConfirmDialog open={confirm} title={t('Delete {{name}}?', { name: title })} confirmLabel={error ? t('Retry deletion') : t('Delete permanently')} tone="danger" busy={busy} busyLabel={t('Stopping tasks and deleting…')} onCancel={() => setConfirm(false)} onConfirm={() => void remove()}>
      <p>{description}</p>
      {error && <p role="alert" className="mt-3 text-[var(--destructive)]">{error}</p>}
    </ConfirmDialog>
  </>
}
