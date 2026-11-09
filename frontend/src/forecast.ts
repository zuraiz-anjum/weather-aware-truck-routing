// When the server's own address has no weather allowance left, it says which
// forecast it needs and this browser fetches it with its own: the points in
// batches of a hundred, with exactly the query the server would have sent.

import type { ForecastOffer, OpenMeteoHourly, SuppliedForecast } from './types'

const POINTS_PER_REQUEST = 100

export async function fetchForecast(offer: ForecastOffer, signal?: AbortSignal): Promise<SuppliedForecast> {
  const batches: [number, number][][] = []
  for (let i = 0; i < offer.points.length; i += POINTS_PER_REQUEST) batches.push(offer.points.slice(i, i + POINTS_PER_REQUEST))
  const answers = await Promise.all(batches.map((batch) => fetchBatch(offer, batch, signal)))
  const hourly = answers.flat()
  if (hourly.length !== offer.points.length) {
    throw new Error(`the weather service answered for ${hourly.length} of ${offer.points.length} points`)
  }
  return { points: offer.points, hourly }
}

async function fetchBatch(offer: ForecastOffer, batch: [number, number][], signal?: AbortSignal): Promise<OpenMeteoHourly[]> {
  const url = new URL(offer.url)
  for (const [name, value] of Object.entries(offer.params)) url.searchParams.set(name, value)
  url.searchParams.set('latitude', batch.map(([lat]) => lat.toFixed(4)).join(','))
  url.searchParams.set('longitude', batch.map(([, lon]) => lon.toFixed(4)).join(','))
  let response: Response
  try {
    response = await fetch(url, { signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error('the weather service could not be reached from this browser')
  }
  const body: unknown = await response.json().catch(() => null)
  if (body && typeof body === 'object' && 'error' in body && (body as { error: unknown }).error) {
    throw new Error(String((body as { reason?: unknown }).reason || 'the weather service refused the request'))
  }
  if (!response.ok || body === null) throw new Error(`the weather service answered ${response.status}`)
  const items = (Array.isArray(body) ? body : [body]) as { hourly: OpenMeteoHourly }[]
  return items.map((item) => item.hourly)
}
