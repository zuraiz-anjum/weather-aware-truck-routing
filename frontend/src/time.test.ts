import { describe, expect, it } from 'vitest'
import { formatDuration, fromInputValue, hoursAfter, nextWholeHour, toInputValue } from './time'

describe('formatDuration', () => {
  it('reads as hours and minutes', () => {
    expect(formatDuration(0)).toBe('0 min')
    expect(formatDuration(45 * 60)).toBe('45 min')
    expect(formatDuration(3600)).toBe('1 h')
    expect(formatDuration(3600 * 14 + 60 * 20)).toBe('14 h 20 min')
    expect(formatDuration(3600 * 14 + 29)).toBe('14 h')
  })
})

describe('datetime-local values', () => {
  it('round-trip through local wall-clock time', () => {
    const date = new Date(2026, 10, 10, 9, 5)
    expect(toInputValue(date)).toBe('2026-11-10T09:05')
    expect(fromInputValue('2026-11-10T09:05')?.getTime()).toBe(date.getTime())
    expect(fromInputValue('')).toBeNull()
    expect(fromInputValue('not a date')).toBeNull()
  })

  it('the default departure is the next whole hour', () => {
    const now = new Date(2026, 10, 10, 9, 5, 30)
    expect(nextWholeHour(now).getTime()).toBe(new Date(2026, 10, 10, 10, 0, 0).getTime())
    expect(nextWholeHour(new Date(2026, 10, 10, 23, 30)).getTime()).toBe(new Date(2026, 10, 11, 0, 0).getTime())
  })
})

describe('hoursAfter', () => {
  it('adds whole hours to an ISO instant', () => {
    expect(hoursAfter('2026-11-10T14:00:00+00:00', 12).toISOString()).toBe('2026-11-11T02:00:00.000Z')
  })
})
