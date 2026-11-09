import { expect, test, type Page } from '@playwright/test'
import { plan } from '../src/test/fixtures'
import type { Level } from '../src/types'

// Whatever the page or MapLibre complains of fails the test: a worker that
// would not load, a style that was refused, an expression the GPU rejected.
function complaints(page: Page): string[] {
  const found: string[] = []
  page.on('pageerror', (error) => found.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') found.push(message.text())
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
  // Two trucks and two ends, placed once the map has its style and has taken the plan.
  await expect(page.locator('.maplibregl-marker')).toHaveCount(4)
  await page.getByLabel(/Forecast at/).press('End')
  await expect(page.getByText('(departure + 48 h)')).toBeVisible()
  await page.getByRole('button', { name: 'Route B' }).click()
  await expect(page.getByRole('region', { name: 'Checkpoints on route B' })).toBeVisible()
  expect(errors).toEqual([])
})
