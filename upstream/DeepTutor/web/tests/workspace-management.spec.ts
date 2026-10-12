import { beforeEach, expect, it, vi } from 'vitest'
import { manageWorkspace } from '@/lib/workspace-management'
const fixture = vi.hoisted(() => ({ request: vi.fn(), invalidate: vi.fn(), notify: vi.fn() }))
vi.mock('@/lib/deepsteam-api', () => ({ deepsteamRequest: fixture.request, deepsteamJSON: (value: unknown, method: string) => ({ method, body: JSON.stringify(value) }) }))
vi.mock('@/lib/client-cache', () => ({ invalidateClientCache: fixture.invalidate }))
vi.mock('@/lib/session-events', () => ({ notifySessionsChanged: fixture.notify }))
beforeEach(() => { vi.clearAllMocks() })
it('uses the shared management route and refreshes native lists only after success', async () => {
  const response = { workspace: { id: 'harness-fixture', title: 'Fixture', archived: true }, operation: 'archive' }
  fixture.request.mockResolvedValue(response)
  expect(await manageWorkspace('native-fixture', { archived: true })).toBe(response)
  expect(fixture.request).toHaveBeenCalledWith('/harness/workspaces/native-fixture/manage', { method: 'PATCH', body: '{"archived":true}' })
  expect(fixture.invalidate).toHaveBeenCalledWith('workspaces:')
  expect(fixture.invalidate).toHaveBeenCalledWith('knowledge:')
  expect(fixture.notify).toHaveBeenCalledOnce()
})
it('keeps all local state unchanged when management is rejected', async () => {
  fixture.request.mockRejectedValue(new Error('workspace_busy'))
  await expect(manageWorkspace('harness-fixture', { archived: true })).rejects.toThrow('workspace_busy')
  expect(fixture.invalidate).not.toHaveBeenCalled()
  expect(fixture.notify).not.toHaveBeenCalled()
})
