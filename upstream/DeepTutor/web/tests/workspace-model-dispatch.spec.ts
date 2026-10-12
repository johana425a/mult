import { beforeEach, expect, it, vi } from 'vitest'
import { harnessWorkspaceAPI } from '../lib/harness-workspace'
import { deepsteamRequest } from '../lib/deepsteam-api'

vi.mock('../lib/deepsteam-api', () => ({
  deepsteamRequest: vi.fn().mockResolvedValue({ status: 'running' }),
  deepsteamJSON: (body: unknown) => ({ method: 'POST', body: JSON.stringify(body) }),
}))
beforeEach(() => vi.clearAllMocks())
it('sends an explicit workspace choice to execution, not just to the visible label', async () => {
  const selection = { profile_id: 'api-fixture', model_id: 'vision-fixture' }
  await harnessWorkspaceAPI.turn('session-fixture', 'fixture prompt', selection)
  expect(deepsteamRequest).toHaveBeenCalledWith('/harness/sessions/session-fixture/turn', { method: 'POST', body: JSON.stringify({ text: 'fixture prompt', llm_selection: selection }) })
})
it('sends explicit null when following default so an old persisted override cannot remain active', async () => {
  await harnessWorkspaceAPI.turn('session-fixture', 'next prompt', null)
  expect(deepsteamRequest).toHaveBeenCalledWith('/harness/sessions/session-fixture/turn', { method: 'POST', body: JSON.stringify({ text: 'next prompt', llm_selection: null }) })
})
