import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useChatWorkspaces } from '@/hooks/useChatWorkspaces'

const fixture = vi.hoisted(() => ({ list: vi.fn(), refresh: undefined as (() => void) | undefined }))
vi.mock('@/lib/workspaces-api', () => ({ listWorkspaces: fixture.list }))
vi.mock('@/lib/session-events', () => ({ subscribeSessionChanges: (callback: () => void) => {
  fixture.refresh = callback
  return () => { fixture.refresh = undefined }
} }))
beforeEach(() => { fixture.list.mockReset(); fixture.refresh = undefined })
afterEach(cleanup)

it('does not restore a deleted group from a late response to an older registry refresh', async () => {
  let old!: (rows: unknown[]) => void
  let fresh!: (rows: unknown[]) => void
  fixture.list.mockImplementationOnce(() => new Promise(resolve => { old = resolve }))
    .mockImplementationOnce(() => new Promise(resolve => { fresh = resolve }))
  const view = renderHook(() => useChatWorkspaces())
  act(() => { fixture.refresh!() })
  await act(async () => { fresh([{ workspace_id: 'one', kind: 'workspace', archived: true }]) })
  expect(view.result.current.workspaces[0].archived).toBe(true)
  await act(async () => { old([{ workspace_id: 'one', kind: 'workspace', archived: false }]) })
  expect(view.result.current.workspaces[0].archived).toBe(true)
})

it('keeps archived user workspaces for recovery while excluding built-in configuration snapshots', async () => {
  fixture.list.mockResolvedValue([
    { workspace_id: 'one', kind: 'workspace', archived: true },
    { workspace_id: 'system', kind: 'system' },
    { workspace_id: 'general', kind: 'general' },
  ])
  const view = renderHook(() => useChatWorkspaces())
  await waitFor(() => expect(view.result.current.workspaces).toHaveLength(1))
  expect(view.result.current.workspaces[0]).toMatchObject({ workspace_id: 'one', archived: true })
})
