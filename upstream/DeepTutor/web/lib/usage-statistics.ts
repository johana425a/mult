import type { components } from '@/contracts/generated/api'
import { apiFetch, apiUrl } from '@/lib/api'

export type UsageStatistics = components['schemas']['UsageStatistics']
export type DailyUsage = components['schemas']['DailyUsage']

export type UsageFailureCode = 'timezone_data_unavailable' | 'invalid_timezone' | 'authentication_required' | 'unavailable'

export class UsageStatisticsError extends Error {
  constructor(public readonly code: UsageFailureCode) {
    super(code)
    this.name = 'UsageStatisticsError'
  }
}

export async function fetchUsageStatistics(
  year: number,
  signal?: AbortSignal
): Promise<UsageStatistics> {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const query = new URLSearchParams({ year: String(year), timezone })
  const response = await apiFetch(apiUrl(`/api/settings/usage?${query}`), { signal })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null
    if (detail && typeof detail === 'object' && 'code' in detail && detail.code === 'timezone_data_unavailable')
      throw new UsageStatisticsError('timezone_data_unavailable')
    if (response.status === 400 && detail === 'Invalid timezone')
      throw new UsageStatisticsError('invalid_timezone')
    if (response.status === 401 || response.status === 403)
      throw new UsageStatisticsError('authentication_required')
    // Do not show arbitrary backend text, which can contain sensitive diagnostics.
    throw new UsageStatisticsError('unavailable')
  }
  return response.json()
}

export function usageYear(value: string | null, current: number): number {
  const year = Number(value)
  return Number.isInteger(year) && year >= 1970 && year <= current ? year : current
}

/** UTC calendar arithmetic avoids DST gaps; the API already bins in local time. */
export function activityCalendar(days: readonly DailyUsage[], year: number) {
  const byDate = new Map(days.map(day => [day.date, day]))
  const start = new Date(Date.UTC(year, 0, 1))
  const offset = (start.getUTCDay() + 6) % 7
  const dates: DailyUsage[] = []
  for (
    let day = new Date(start);
    day.getUTCFullYear() === year;
    day.setUTCDate(day.getUTCDate() + 1)
  ) {
    const date = day.toISOString().slice(0, 10)
    dates.push(
      byDate.get(date) ?? { date, total_tokens: 0, total_calls: 0, turns: 0, tracked_turns: 0 }
    )
  }
  const weeks: (DailyUsage | null)[][] = []
  for (let week = 0; week < Math.ceil((offset + dates.length) / 7); week++) {
    weeks.push(
      Array.from({ length: 7 }, (_, weekday) => dates[week * 7 + weekday - offset] ?? null)
    )
  }
  return { weeks, dates, offset }
}
