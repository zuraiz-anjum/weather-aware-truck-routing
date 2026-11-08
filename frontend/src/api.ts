import type { Place, Plan, PlanRequest } from './types'

export class ApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
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
    throw new ApiError(response.status, detail)
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
