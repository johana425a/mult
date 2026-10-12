'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { activeWorkspaceId, registerWorkspaceNavigator, scopedUrl, selectWorkspace } from '@/lib/workspace-scope'
import { isSameApplicationOrigin } from '@/lib/deepsteam-transport'

/** Feature links inherit the task scope; explicitly bound content links keep theirs. */
export function WorkspaceNavigation() {
  const router = useRouter()
  useEffect(() => registerWorkspaceNavigator(router.push), [router])
  useEffect(() => {
    const follow = (event: MouseEvent) => {
      const anchor = (event.target as Element).closest?.('a[href]') as HTMLAnchorElement | null
      if (!anchor || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
          event.button !== 0 || anchor.target === '_blank' || anchor.hasAttribute('download')) return
      const url = new URL(anchor.href)
      if (!isSameApplicationOrigin(url)) return
      const scoped = new URL(scopedUrl(url.toString()))
      const target = scoped.searchParams.get('dt_workspace') ?? scoped.searchParams.get('workspace') ?? ''
      if (target !== activeWorkspaceId() || scoped.toString() !== url.toString()) {
        event.preventDefault()
        event.stopImmediatePropagation()
        if (target !== activeWorkspaceId()) void selectWorkspace(target, scoped.toString())
        else router.push(`${scoped.pathname}${scoped.search}${scoped.hash}`)
      }
    }
    document.addEventListener('click', follow, true)
    return () => document.removeEventListener('click', follow, true)
  }, [router])
  return null
}
