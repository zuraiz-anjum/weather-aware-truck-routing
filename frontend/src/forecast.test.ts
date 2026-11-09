import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchForecast } from './forecast'

const HOURLY = { time: [1, 2], wind_speed_10m: [5, 6], rain: [0, 0], showers: [0, 0], snowfall: [0, null] }

afterEach(() => vi.unstubAllGlobals())

function answering(body: unknown, status = 200) {
  const fetched = vi.fn().mockImplementation(async (url: URL) => {
    const count = url.searchParams.get('latitude')!.split(',').length
    return { ok: status < 400, status, json: async () => (typeof body === 'function' ? body(count) : body) }
  })
  vi.stubGlobal('fetch', fetched)
  return fetched
}

describe('fetchForecast', () => {
  it('asks a hundred points at a time with the offered query and the coordinates to four decimals', async () => {
    const fetched = answering((count: number) => Array.from({ length: count }, () => ({ hourly: HOURLY })))
    const points = Array.from({ length: 250 }, (_, k) => [35 + k / 1000, -101 - k / 1000] as [number, number])
    const offer = { url: 'https://weather.example/v1/forecast', params: { hourly: 'wind_speed_10m,rain,showers,snowfall', start_hour: '2026-11-10T00:00' }, points }
    const forecast = await fetchForecast(offer)
    expect(fetched).toHaveBeenCalledTimes(3)
    const first = fetched.mock.calls[0][0] as URL
    expect(first.origin + first.pathname).toBe('https://weather.example/v1/forecast')
    expect(first.searchParams.get('start_hour')).toBe('2026-11-10T00:00')
    expect(first.searchParams.get('latitude')!.split(',')).toHaveLength(100)
    expect(first.searchParams.get('latitude')!.startsWith('35.0000,35.0010,')).toBe(true)
    expect((fetched.mock.calls[2][0] as URL).searchParams.get('longitude')!.split(',')).toHaveLength(50)
    expect(forecast.points).toBe(points)
    expect(forecast.hourly).toHaveLength(250)
    expect(forecast.hourly[0]).toBe(HOURLY)
  })

  it('takes a single point answered bare, and says what the service refused', async () => {
    answering({ hourly: HOURLY })
    const one = await fetchForecast({ url: 'https://weather.example/v1/forecast', params: {}, points: [[35, -101]] })
    expect(one.hourly).toEqual([HOURLY])
    answering({ error: true, reason: 'Daily API request limit exceeded' })
    await expect(fetchForecast({ url: 'https://weather.example/v1/forecast', params: {}, points: [[35, -101]] })).rejects.toThrow(
      'Daily API request limit exceeded',
    )
    answering(null, 500)
    await expect(fetchForecast({ url: 'https://weather.example/v1/forecast', params: {}, points: [[35, -101]] })).rejects.toThrow(
      'answered 500',
    )
  })
})
