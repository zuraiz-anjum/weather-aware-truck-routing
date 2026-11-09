import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, planTrip } from './api'
import CheckpointTable from './components/CheckpointTable'
import HourSlider from './components/HourSlider'
import Legend from './components/Legend'
import RouteCards from './components/RouteCards'
import TripForm from './components/TripForm'
import { formatTime } from './time'
import type { Checkpoint, Plan, PlanRequest } from './types'

// MapLibre is most of the bundle; the form is usable while it is still arriving.
const RouteMap = lazy(() => import('./components/RouteMap'))

export default function App() {
  const [plan, setPlan] = useState<Plan | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [hour, setHour] = useState(0)
  const [retryIn, setRetryIn] = useState<number | null>(null) // seconds until a busy weather service is asked again
  const [focus, setFocus] = useState<{ route: string; checkpoint: Checkpoint } | null>(null) // picked in the table, for the map to go to
  const pending = useRef<AbortController | null>(null)
  const lastRequest = useRef<{ request: PlanRequest; attempt: number } | null>(null)
  const overlay = useRef<HTMLDivElement>(null)

  const submit = useCallback(async (request: PlanRequest, attempt = 1) => {
    pending.current?.abort()
    const controller = new AbortController()
    pending.current = controller
    lastRequest.current = { request, attempt }
    setBusy(true)
    setError(null)
    setRetryIn(null)
    try {
      const result = await planTrip(request, controller.signal)
      setPlan(result)
      setSelected(result.routes[0]?.id ?? null)
      setHour(0)
      setFocus(null)
    } catch (failure: unknown) {
      if (failure instanceof DOMException && failure.name === 'AbortError') return
      // The weather service's allowance for the minute is spent: wait it out
      // and ask again by itself, twice at most, then say what the server said.
      const busyForAMoment =
        failure instanceof ApiError && failure.status === 503 && failure.retryAfter !== null && failure.retryAfter <= 90
      if (busyForAMoment && attempt < 3) {
        setRetryIn(failure.retryAfter)
        return
      }
      setError(failure instanceof Error ? failure.message : 'Something went wrong.')
    } finally {
      if (pending.current === controller) setBusy(false)
    }
  }, [])

  const choose = useCallback((id: string) => {
    setSelected(id)
    setFocus(null)
  }, [])

  useEffect(() => {
    if (retryIn === null || retryIn <= 0) return
    const timer = setTimeout(() => {
      if (retryIn > 1) setRetryIn(retryIn - 1)
      else if (lastRequest.current) void submit(lastRequest.current.request, lastRequest.current.attempt + 1)
    }, 1000)
    return () => clearTimeout(timer)
  }, [retryIn, submit])

  const route = plan?.routes.find((r) => r.id === selected) ?? plan?.routes[0] ?? null
  // A plan left on screen after a failed attempt, or while one is waiting to be retried, is the previous one.
  const stale = plan !== null && (error !== null || retryIn !== null)

  return (
    <div className="app">
      <aside className="panel">
        <header>
          <h1>Weather-Aware Truck Routing</h1>
          <p className="muted">
            Three routes, the weather each one meets at the hour the truck gets there, and which to take.
          </p>
        </header>
        <TripForm onSubmit={submit} busy={busy} />
        {error && (
          <p className="problem" role="alert">
            {error}
            {stale && `${error.endsWith('.') ? '' : '.'} The plan below is the previous one.`}
          </p>
        )}
        {retryIn !== null && (
          // Only the sentence is a live region, so a screen reader hears it once and not every second of the count.
          <p className="waiting">
            <span role="status">The weather service is busy for the moment; the plan will be asked for again by itself.</span> Trying
            again in {retryIn} s.{stale && ' The plan below is the previous one.'}
          </p>
        )}
        {plan && (
          <div className={stale ? 'results stale' : 'results'}>
            <h2>
              {plan.origin.label} <span className="muted">to</span> {plan.destination.label}
            </h2>
            <p className="small muted">
              {plan.load_lb.toLocaleString()} lb, leaving {formatTime(plan.departure)}
            </p>
            {plan.warning && <p className="warning">{plan.warning}</p>}
            {plan.notes.map((note) => (
              <p key={note} className="note">
                {note}
              </p>
            ))}
            <RouteCards plan={plan} selected={route?.id ?? null} onSelect={choose} />
            {route && (
              <CheckpointTable
                route={route}
                picked={focus?.route === route.id ? focus.checkpoint.mile : null}
                onPick={(checkpoint) => setFocus({ route: route.id, checkpoint })}
              />
            )}
            <p className="small muted">
              Times are local to this browser. Driving times come from the routing engine and assume no stops.
              Wind is sustained wind at 10 m; rain and snow are hourly totals for the hour ahead. Heatmap cells
              are rated at the slider hour; checkpoint dots when the truck gets there.
            </p>
          </div>
        )}
      </aside>
      <main className={stale ? 'map-area stale' : 'map-area'}>
        <Suspense fallback={<div className="map map-loading muted">Loading the map&hellip;</div>}>
          <RouteMap plan={plan} selected={route?.id ?? null} hour={hour} onSelect={choose} focus={focus} overlay={overlay} />
        </Suspense>
        {plan && (
          <div className="map-controls" ref={overlay}>
            <HourSlider plan={plan} hour={hour} onChange={setHour} />
            <Legend cellMiles={plan.heatmap.cell_miles} />
          </div>
        )}
        {busy && (
          <div className="map-busy" aria-live="polite">
            Fetching routes and forecasts&hellip;
          </div>
        )}
      </main>
    </div>
  )
}
