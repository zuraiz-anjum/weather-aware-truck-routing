import { useState, type FormEvent } from 'react'
import { fromInputValue, nextWholeHour, timeZoneName, toInputValue } from '../time'
import type { Place, PlaceInput as PlaceRequest, PlanRequest } from '../types'
import PlaceInput, { type PlaceValue } from './PlaceInput'

// The form's fields as typed, which a shared link fills in.
export interface Draft {
  origin: PlaceValue
  destination: PlaceValue
  departure: string
  load: string
  interval: string
}

interface Props {
  onSubmit: (request: PlanRequest) => void
  busy: boolean
  initial?: Draft
}

export const MAX_LOAD_LB = 200_000
// What the server accepts: up to an hour back, up to thirteen days less an hour ahead.
const LATEST_AHEAD_MS = 13 * 86_400_000 - 3_600_000

// Three trips a first look can start from: a click fills the boxes and plans.
const EXAMPLES: { origin: Place; destination: Place }[] = [
  { origin: { label: 'Denver, Colorado', lat: 39.7392, lon: -104.9903 }, destination: { label: 'Salt Lake City, Utah', lat: 40.7608, lon: -111.891 } },
  { origin: { label: 'Amarillo, Texas', lat: 35.222, lon: -101.8313 }, destination: { label: 'Oklahoma City, Oklahoma', lat: 35.4676, lon: -97.5164 } },
  { origin: { label: 'Chicago, Illinois', lat: 41.8781, lon: -87.6298 }, destination: { label: 'Atlanta, Georgia', lat: 33.749, lon: -84.388 } },
]

function asRequest(value: PlaceValue): PlaceRequest {
  return value.place
    ? { text: value.place.label, lat: value.place.lat, lon: value.place.lon }
    : { text: value.text.trim() }
}

export default function TripForm({ onSubmit, busy, initial }: Props) {
  const [origin, setOrigin] = useState<PlaceValue>(initial?.origin ?? { text: '' })
  const [destination, setDestination] = useState<PlaceValue>(initial?.destination ?? { text: '' })
  const [departure, setDeparture] = useState(() => initial?.departure ?? toInputValue(nextWholeHour()))
  const [bounds] = useState(() => {
    const now = new Date()
    return { min: toInputValue(now), max: toInputValue(new Date(now.getTime() + LATEST_AHEAD_MS)) }
  })
  const [load, setLoad] = useState(initial?.load ?? '20000')
  const [interval, setInterval] = useState(initial?.interval ?? 'auto')
  const [problem, setProblem] = useState<string | null>(null)

  function submit(event: FormEvent) {
    event.preventDefault()
    plan(origin, destination)
  }

  function example(trip: (typeof EXAMPLES)[number]) {
    const from = { text: trip.origin.label, place: trip.origin }
    const to = { text: trip.destination.label, place: trip.destination }
    setOrigin(from)
    setDestination(to)
    plan(from, to)
  }

  function plan(from: PlaceValue, to: PlaceValue) {
    const when = fromInputValue(departure)
    const pounds = Number(load)
    if (!from.text.trim() || !to.text.trim()) {
      setProblem('Give both an origin and a destination.')
    } else if (!when) {
      setProblem('Give a departure date and time.')
    } else if (load.trim() === '' || !Number.isFinite(pounds) || pounds < 0 || pounds > MAX_LOAD_LB) {
      setProblem(`Load weight must be between 0 and ${MAX_LOAD_LB.toLocaleString()} lb.`)
    } else {
      setProblem(null)
      onSubmit({
        origin: asRequest(from),
        destination: asRequest(to),
        departure: when.toISOString(),
        load_lb: Math.round(pounds),
        ...(interval === 'auto' ? {} : { interval_miles: Number(interval) }),
      })
    }
  }

  function swap() {
    setOrigin(destination)
    setDestination(origin)
  }

  return (
    <form className="trip-form" onSubmit={submit} noValidate>
      <PlaceInput label="Origin" value={origin} onChange={setOrigin} placeholder="City or address" />
      <PlaceInput label="Destination" value={destination} onChange={setDestination} placeholder="City or address" />
      <button type="button" className="link swap" onClick={swap}>
        Swap
      </button>
      <p className="small muted examples">
        Try{' '}
        {EXAMPLES.map((trip, k) => (
          <span key={trip.origin.label}>
            {k > 0 && (k === EXAMPLES.length - 1 ? ' or ' : ', ')}
            <button type="button" className="link" onClick={() => example(trip)} disabled={busy}>
              {trip.origin.label.split(',')[0]} to {trip.destination.label.split(',')[0]}
            </button>
          </span>
        ))}
        .
      </p>
      <div className="row">
        <div className="field">
          <label htmlFor="departure">Departure ({timeZoneName()})</label>
          <input
            id="departure"
            type="datetime-local"
            step={60}
            min={bounds.min}
            max={bounds.max}
            value={departure}
            onChange={(event) => setDeparture(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="load">Load weight (lb)</label>
          <input
            id="load"
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_LOAD_LB}
            step={500}
            value={load}
            onChange={(event) => setLoad(event.target.value)}
          />
        </div>
      </div>
      <div className="field">
        <label htmlFor="interval">Weather checkpoints</label>
        <select id="interval" value={interval} onChange={(event) => setInterval(event.target.value)}>
          <option value="auto">Every 10, 25 or 50 miles, by trip length</option>
          <option value="10">Every 10 miles</option>
          <option value="25">Every 25 miles</option>
          <option value="50">Every 50 miles</option>
        </select>
      </div>
      {problem && (
        <p className="problem" role="alert">
          {problem}
        </p>
      )}
      <button type="submit" className="primary" disabled={busy}>
        {busy ? 'Planning…' : 'Plan routes'}
      </button>
    </form>
  )
}
