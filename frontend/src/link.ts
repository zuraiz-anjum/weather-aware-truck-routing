// A plan's inputs in the address bar, so that the link can be sent on and
// opened into the same form. Nothing is stored anywhere: the server keeps
// no state, and a link carrying the inputs is enough to make the plan again.

import { MAX_LOAD_LB, type Draft } from './components/TripForm'
import type { PlaceValue } from './components/PlaceInput'
import { toInputValue } from './time'
import type { PlaceInput, PlanRequest } from './types'

export interface Opening {
  draft: Draft // what the form starts with
  request: PlanRequest // what to plan, when the departure is still ahead
}

const INTERVALS = ['10', '25', '50']
// A link from any time back still fills the form, to be given a new time, and
// the page says so. One more than a year ahead is a typo or a prod, and sent on
// to the server it would come back as a raw framework message.
const FURTHEST_AHEAD_MS = 400 * 86_400_000

export function readLink(search: string): Opening | null {
  const params = new URLSearchParams(search)
  const origin = place(params, 'from')
  const destination = place(params, 'to')
  const leave = Date.parse(params.get('leave') || '')
  const load = params.get('load')
  const every = params.get('every')
  // A load that is not there is not an empty truck: Number(null) would be 0.
  if (!origin || !destination || Number.isNaN(leave) || !load) return null
  if (leave - Date.now() > FURTHEST_AHEAD_MS) return null
  const pounds = Number(load)
  if (!Number.isInteger(pounds) || pounds < 0 || pounds > MAX_LOAD_LB) return null
  if (every !== null && !INTERVALS.includes(every)) return null
  const departure = new Date(leave)
  return {
    draft: {
      origin: asValue(origin),
      destination: asValue(destination),
      departure: toInputValue(departure),
      load: String(pounds),
      interval: every ?? 'auto',
    },
    request: {
      origin,
      destination,
      departure: departure.toISOString(),
      load_lb: pounds,
      ...(every ? { interval_miles: Number(every) } : {}),
    },
  }
}

export function writeLink(request: PlanRequest): string {
  const params = new URLSearchParams()
  put(params, 'from', request.origin)
  put(params, 'to', request.destination)
  params.set('leave', request.departure)
  params.set('load', String(request.load_lb))
  if (request.interval_miles) params.set('every', String(request.interval_miles))
  // Commas and colons are safe in a query string and easier on the eye than their escapes.
  return '?' + params.toString().replace(/%2C/g, ',').replace(/%3A/g, ':')
}

function place(params: URLSearchParams, name: string): PlaceInput | null {
  const text = (params.get(name) || '').trim()
  if (!text) return null
  const at = (params.get(`${name}_at`) || '').split(',').map(Number)
  const [lat, lon] = at
  if (at.length === 2 && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) return { text, lat, lon }
  return { text }
}

function put(params: URLSearchParams, name: string, input: PlaceInput) {
  params.set(name, input.text || '')
  if (input.lat !== undefined && input.lon !== undefined) params.set(`${name}_at`, `${input.lat},${input.lon}`)
}

function asValue(input: PlaceInput): PlaceValue {
  const text = input.text || ''
  if (input.lat !== undefined && input.lon !== undefined) return { text, place: { label: text, lat: input.lat, lon: input.lon } }
  return { text }
}
