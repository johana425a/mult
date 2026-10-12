'use client'

import { useCallback, useMemo, useSyncExternalStore } from 'react'
import type { LLMSelection } from '@/features/chat/model/protocol'

const CHANGED = 'deepsteam:model-preference-changed'
const unavailableStorageDrafts = new Map<string, string>()
const serverSnapshot = () => null

/** Non-secret UI preference; the server validates and freezes it per task. */
export function useSurfaceModelSelection(scope: string, saved?: LLMSelection | null) {
  const key = `deepsteam:model-choice:${scope}`
  const read = useCallback(() => {
    try { return localStorage.getItem(key) } catch { return unavailableStorageDrafts.get(key) ?? null }
  }, [key])
  const subscribe = useCallback((notify: () => void) => {
    const changed = () => notify()
    window.addEventListener(CHANGED, changed)
    window.addEventListener('storage', changed)
    return () => { window.removeEventListener(CHANGED, changed); window.removeEventListener('storage', changed) }
  }, [])
  const raw = useSyncExternalStore(subscribe, read, serverSnapshot)
  const selection = useMemo(() => {
    if (raw === null) return saved ?? null
    try {
      const value = JSON.parse(raw)
      return value && typeof value.profile_id === 'string' && typeof value.model_id === 'string' ? { profile_id: value.profile_id, model_id: value.model_id } : null
    } catch { return saved ?? null }
  }, [raw, saved])
  const select = useCallback((value: LLMSelection | null) => {
    const encoded = JSON.stringify(value)
    try { localStorage.setItem(key, encoded) } catch { unavailableStorageDrafts.set(key, encoded) }
    window.dispatchEvent(new Event(CHANGED))
  }, [key])
  return [selection, select] as const
}
