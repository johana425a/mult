import { beforeEach, expect, it, vi } from 'vitest'
import { fetchUsageStatistics } from '@/lib/usage-statistics'

const mocks = vi.hoisted(() => ({fetch: vi.fn()}))
vi.mock('@/lib/api', () => ({apiFetch: mocks.fetch, apiUrl: (url: string) => url}))
beforeEach(() => mocks.fetch.mockReset())

it('classifies a missing database from its stable error code', async () => {
  mocks.fetch.mockResolvedValue({ok: false, status: 503, json: async () => ({detail: {code: 'timezone_data_unavailable', message: 'private diagnostic'}})})
  await expect(fetchUsageStatistics(2025)).rejects.toMatchObject({code: 'timezone_data_unavailable', message: 'timezone_data_unavailable'})
})

it('keeps input and authentication failures distinct from server diagnostics', async () => {
  mocks.fetch.mockResolvedValueOnce({ok: false, status: 400, json: async () => ({detail: 'Invalid timezone'})})
    .mockResolvedValueOnce({ok: false, status: 401, json: async () => ({detail: 'private diagnostic'})})
    .mockResolvedValueOnce({ok: false, status: 500, json: async () => ({detail: 'secret key'})})
  await expect(fetchUsageStatistics(2025)).rejects.toMatchObject({code: 'invalid_timezone'})
  await expect(fetchUsageStatistics(2025)).rejects.toMatchObject({code: 'authentication_required'})
  await expect(fetchUsageStatistics(2025)).rejects.toMatchObject({code: 'unavailable', message: 'unavailable'})
})
