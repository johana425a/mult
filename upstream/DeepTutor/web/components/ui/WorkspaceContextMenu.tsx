'use client'

import { MoreHorizontal } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export interface WorkspaceContextMenuItem {
  id: string
  label: string
  onSelect: () => void
  disabled?: boolean
  danger?: boolean
}

/** Shared workspace row controls; callers own all registration mutations. */
export function WorkspaceContextMenu({ children, items, disabled = false, label = 'Workspace actions', className = '' }: {
  children: ReactNode
  items: readonly WorkspaceContextMenuItem[]
  disabled?: boolean
  label?: string
  className?: string
}) {
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)
  const [position, setPosition] = useState({ left: 0, top: 0 })
  const row = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const previousFocus = useRef<HTMLElement | null>(null)
  const close = useCallback((restore = false) => {
    setAnchor(null)
    if (restore && previousFocus.current?.isConnected) previousFocus.current.focus()
  }, [])

  const open = (x: number, y: number, source: HTMLElement | null) => {
    if (disabled || !items.length) return
    previousFocus.current = source
    setPosition({ left: Math.max(8, Math.min(x, window.innerWidth - 216)), top: Math.max(8, y) })
    setAnchor({ x, y })
  }
  const openFromRow = (source: HTMLElement | null) => {
    const bounds = row.current?.getBoundingClientRect()
    if (bounds) open(bounds.left, bounds.bottom + 4, source)
  }

  useLayoutEffect(() => {
    if (!anchor || !menu.current) return
    const bounds = menu.current.getBoundingClientRect()
    setPosition({ left: Math.max(8, Math.min(anchor.x, window.innerWidth - bounds.width - 8)), top: Math.max(8, Math.min(anchor.y, window.innerHeight - bounds.height - 8)) })
    menu.current.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus()
  }, [anchor])
  useEffect(() => {
    if (!anchor) return
    const outside = (event: MouseEvent) => {
      if (!menu.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) close()
    }
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close(true) }
    }
    const reposition = () => close()
    document.addEventListener('mousedown', outside)
    document.addEventListener('keydown', escape)
    window.addEventListener('resize', reposition)
    window.addEventListener('scroll', reposition, true)
    return () => {
      document.removeEventListener('mousedown', outside)
      document.removeEventListener('keydown', escape)
      window.removeEventListener('resize', reposition)
      window.removeEventListener('scroll', reposition, true)
    }
  }, [anchor, close])
  useEffect(() => { if (disabled) close() }, [disabled, close])

  const menuKeys = (event: KeyboardEvent<HTMLDivElement>) => {
    const buttons = [...(menu.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || [])]
    if (event.key === 'Tab') { close(); return }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || !buttons.length) return
    event.preventDefault()
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : event.key === 'ArrowDown' ? (current + 1) % buttons.length : (current - 1 + buttons.length) % buttons.length
    buttons[next]?.focus()
  }

  return <div ref={row} className={`group/workspace-context relative min-w-0 ${className}`} onContextMenu={event => {
    if (disabled) return
    event.preventDefault(); event.stopPropagation()
    const target = event.target as HTMLElement
    open(event.clientX, event.clientY, target.closest<HTMLElement>('button, a, [tabindex]') || trigger.current)
  }} onKeyDown={event => {
    if ((event.shiftKey && event.key === 'F10') || event.key === 'ContextMenu') {
      event.preventDefault(); event.stopPropagation(); openFromRow(event.target as HTMLElement)
    }
  }}>
    {children}
    <button ref={trigger} type="button" aria-label={label} aria-haspopup="menu" aria-expanded={Boolean(anchor)} disabled={disabled}
      className="absolute right-1 top-2 z-10 flex size-6 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
      onClick={event => { event.stopPropagation(); if (anchor) close(true); else openFromRow(trigger.current) }}>
      <MoreHorizontal size={14} />
    </button>
    {anchor && createPortal(<div ref={menu} role="menu" aria-label={label} onKeyDown={menuKeys} onContextMenu={event => event.preventDefault()}
      style={{ position: 'fixed', ...position }} className="animate-pop-in z-[80] max-h-[calc(100vh-16px)] w-52 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--popover)] p-1 shadow-lg">
      {items.map(item => <button key={item.id} type="button" role="menuitem" disabled={item.disabled} onClick={() => { close(true); item.onSelect() }}
        className={`block w-full rounded-lg px-3 py-2 text-left text-xs transition-colors hover:bg-[var(--muted)] focus:bg-[var(--muted)] focus:outline-none disabled:opacity-40 ${item.danger ? 'text-[var(--destructive)]' : 'text-[var(--foreground)]'}`}>{item.label}</button>)}
    </div>, document.body)}
  </div>
}
