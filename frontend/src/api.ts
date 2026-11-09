import type { ForecastOffer, Place, Plan, PlanRequest } from './types'

export class ApiError extends Error {
  status: number
  retryAfter: number | null // seconds, when the server said how long to wait
  forecast: ForecastOffer | null // what to fetch for it, when the server's weather allowance is spent

  constructor(status: number, detail: string, retryAfter: number | null = null, forecast: ForecastOffer | null = null) {
    super(detail)
    this.status = status
    this.retryAfter = retryAfter
    this.forecast = forecast
  }
}

function offerIn(body: unknown): ForecastOffer | null {
  const offer = body && typeof body === 'object' ? (body as { forecast?: unknown }).forecast : null
  if (!offer || typeof offer !== 'object') return null
  const { url, params, points } = offer as Partial<ForecastOffer>
  return typeof url === 'string' && params && typeof params === 'object' && Array.isArray(points) ? { url, params, points } : null
}

async function call<T>(url: string, init: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, { ...init, headers: { Accept: 'application/json', ...init.headers } })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, 'The server could not be reached.')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body && typeof body.detail === 'string' ? body.detail : `The server answered ${response.status}.`
    const wait = Number(response.headers.get('Retry-After'))
    throw new ApiError(response.status, detail, Number.isFinite(wait) && wait > 0 ? wait : null, offerIn(body))
  }
  return body as T
}

export function planTrip(request: PlanRequest, signal?: AbortSignal): Promise<Plan> {
  return call<Plan>('/api/plan/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
}

export async function suggestPlaces(text: string, signal?: AbortSignal): Promise<Place[]> {
  const found = await call<{ places: Place[] }>(`/api/places/?q=${encodeURIComponent(text)}`, { signal })
  return found.places
}
