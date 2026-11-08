import { useState, type FormEvent } from 'react'
import { fromInputValue, nextWholeHour, timeZoneName, toInputValue } from '../time'
import type { PlaceInput as PlaceRequest, PlanRequest } from '../types'
import PlaceInput, { type PlaceValue } from './PlaceInput'

interface Props {
  onSubmit: (request: PlanRequest) => void
  busy: boolean
}

export const MAX_LOAD_LB = 200_000

function asRequest(value: PlaceValue): PlaceRequest {
  return value.place
    ? { text: value.place.label, lat: value.place.lat, lon: value.place.lon }
    : { text: value.text.trim() }
}

export default function TripForm({ onSubmit, busy }: Props) {
  const [origin, setOrigin] = useState<PlaceValue>({ text: '' })
  const [destination, setDestination] = useState<PlaceValue>({ text: '' })
  const [departure, setDeparture] = useState(() => toInputValue(nextWholeHour()))
  const [load, setLoad] = useState('20000')
  const [interval, setInterval] = useState('auto')
  const [problem, setProblem] = useState<string | null>(null)

  function submit(event: FormEvent) {
    event.preventDefault()
    const when = fromInputValue(departure)
    const pounds = Number(load)
    if (!origin.text.trim() || !destination.text.trim()) {
      setProblem('Give both an origin and a destination.')
    } else if (!when) {
      setProblem('Give a departure date and time.')
    } else if (load.trim() === '' || !Number.isFinite(pounds) || pounds < 0 || pounds > MAX_LOAD_LB) {
      setProblem(`Load weight must be between 0 and ${MAX_LOAD_LB.toLocaleString()} lb.`)
    } else {
      setProblem(null)
      onSubmit({
        origin: asRequest(origin),
        destination: asRequest(destination),
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
      <div className="row">
        <div className="field">
          <label htmlFor="departure">Departure ({timeZoneName()})</label>
          <input
            id="departure"
            type="datetime-local"
            step={60}
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
