import { expect, test, type Page, type Route } from '@playwright/test'
import { plan } from '../src/test/fixtures'
import type { Level } from '../src/types'

// Whatever the page or MapLibre complains of fails the test: a worker that
// would not load, a style that was refused, an expression the GPU rejected.
function complaints(page: Page): string[] {
  const found: string[] = []
  page.on('pageerror', (error) => found.push(error.message))
  page.on('console', (message) => {
    // The tile server's own failures, such as a glyph range it has not got, are not the app's.
    if (message.type() === 'error' && !message.location().url.includes('tiles.openfreemap.org')) found.push(message.text())
  })
  return found
}

test('the map draws its base layer', async ({ page }) => {
  const errors = complaints(page)
  // Vector tiles are fetched and parsed by MapLibre's worker, so one arriving means the worker is alive.
  const tile = page.waitForResponse((response) => response.url().endsWith('.pbf') && response.ok())
  await page.goto('/')
  await expect(page.locator('canvas.maplibregl-canvas')).toBeVisible()
  await tile
  expect(errors).toEqual([])
})

test('a plan is drawn and the slider moves through it', async ({ page }) => {
  const errors = complaints(page)
  const levels = Array.from({ length: 49 }, (_, hour) => (hour % 5) as Level)
  const cell = {
    type: 'Feature' as const,
    geometry: { type: 'Polygon' as const, coordinates: [[[-100.5, 34.5], [-98, 34.5], [-98, 35.5], [-100.5, 35.5], [-100.5, 34.5]]] },
    properties: { levels },
  }
  await page.route('**/api/places/**', (route) => route.fulfill({ json: { places: [] } }))
  await page.route('**/api/plan/', (route) => route.fulfill({ json: plan({ heatmap: { type: 'FeatureCollection', cell_miles: 5, features: [cell] } }) }))
  await page.goto('/')
  await page.getByLabel('Origin').fill('Amarillo')
  await page.getByLabel('Destination').fill('Oklahoma City')
  await page.getByRole('button', { name: 'Plan routes' }).click()
  await expect(page.getByText('Recommended')).toBeVisible()
  await expect(page).toHaveURL(/from=Amarillo&to=Oklahoma\+City&leave=/)
  // Two trucks and two ends, placed once the map has its style and has taken the plan.
  await expect(page.locator('.maplibregl-marker')).toHaveCount(4)
  await page.getByLabel(/Forecast at/).press('End')
  await expect(page.getByText('(departure + 48 h)')).toBeVisible()
  await page.getByRole('button', { name: 'Route B' }).click()
  await expect(page.getByRole('region', { name: 'Checkpoints on route B' })).toBeVisible()
  await page.getByRole('button', { name: '50' }).click()
  await expect(page.locator('.maplibregl-popup')).toContainText('Route B, mile 50')
  expect(errors).toEqual([])
})

test('fetches the forecast itself when the server has no allowance left', async ({ page }) => {
  const errors = complaints(page)
  const points: [number, number][] = [[35.2, -101.8], [35.3, -101.0]]
  const hourly = { time: [1762732800, 1762736400], wind_speed_10m: [5, 6], rain: [0, 0], showers: [0, 0], snowfall: [0, 0] }
  const offer = {
    url: 'https://weather.example/v1/forecast',
    params: { hourly: 'wind_speed_10m,rain,showers,snowfall', wind_speed_unit: 'mph', start_hour: '2026-11-10T00:00', end_hour: '2026-11-13T00:00' },
    points,
  }
  const asked: string[] = []
  await page.route('**/api/places/**', (route) => route.fulfill({ json: { places: [] } }))
  await page.route('https://weather.example/**', (route) => {
    asked.push(route.request().url())
    return route.fulfill({ json: points.map(() => ({ hourly })) })
  })
  const posted: unknown[] = []
  await page.route('**/api/plan/', (route: Route) => {
    const body = route.request().postDataJSON()
    posted.push(body)
    if (!body.forecast) {
      return route.fulfill({
        status: 503,
        headers: { 'Retry-After': '86400' },
        json: { detail: "the weather service's free allowance for the day is spent; try again tomorrow", forecast: offer },
      })
    }
    return route.fulfill({ json: plan() })
  })
  await page.goto('/')
  await page.getByLabel('Origin').fill('Amarillo')
  await page.getByLabel('Destination').fill('Oklahoma City')
  await page.getByRole('button', { name: 'Plan routes' }).click()
  await expect(page.getByText('Recommended')).toBeVisible()
  expect(asked).toHaveLength(1)
  expect(new URL(asked[0]).searchParams.get('latitude')).toBe('35.2000,35.3000')
  expect(posted).toHaveLength(2)
  expect((posted[1] as { forecast: unknown }).forecast).toEqual({ points, hourly: [hourly, hourly] })
  await expect(page.locator('.maplibregl-marker')).toHaveCount(4)
  // The browser notes the 503 this test served on purpose; nothing else may be in the console.
  expect(errors.filter((message) => !message.includes('status of 503'))).toEqual([])
})
