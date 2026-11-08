import { Suspense, lazy, useCallback, useRef, useState } from 'react'
import { planTrip } from './api'
import CheckpointTable from './components/CheckpointTable'
import HourSlider from './components/HourSlider'
import Legend from './components/Legend'
import RouteCards from './components/RouteCards'
import TripForm from './components/TripForm'
import type { Plan, PlanRequest } from './types'

// MapLibre is most of the bundle; the form is usable while it is still arriving.
const RouteMap = lazy(() => import('./components/RouteMap'))

export default function App() {
  const [plan, setPlan] = useState<Plan | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [hour, setHour] = useState(0)
  const pending = useRef<AbortController | null>(null)

  const submit = useCallback(async (request: PlanRequest) => {
    pending.current?.abort()
    const controller = new AbortController()
    pending.current = controller
    setBusy(true)
    setError(null)
    try {
      const result = await planTrip(request, controller.signal)
      setPlan(result)
      setSelected(result.routes[0]?.id ?? null)
      setHour(0)
    } catch (failure: unknown) {
      if (failure instanceof DOMException && failure.name === 'AbortError') return
      setError(failure instanceof Error ? failure.message : 'Something went wrong.')
    } finally {
      if (pending.current === controller) setBusy(false)
    }
  }, [])

  const route = plan?.routes.find((r) => r.id === selected) ?? plan?.routes[0] ?? null
  // A plan left on screen after a failed attempt is the previous one.
  const stale = error !== null && plan !== null

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
            {stale && ' The plan below is the previous one.'}
          </p>
        )}
        {plan && (
          <div className={stale ? 'results stale' : 'results'}>
            <h2>
              {plan.origin.label} <span className="muted">to</span> {plan.destination.label}
            </h2>
            {plan.warning && <p className="warning">{plan.warning}</p>}
            {plan.notes.map((note) => (
              <p key={note} className="note">
                {note}
              </p>
            ))}
            <RouteCards plan={plan} selected={route?.id ?? null} onSelect={setSelected} />
            {route && <CheckpointTable route={route} />}
            <p className="small muted">
              Times are local to this browser. Driving times come from the routing engine and assume no stops.
              Wind is sustained wind at 10 m; rain and snow are hourly totals for the hour ahead.
            </p>
          </div>
        )}
      </aside>
      <main className={stale ? 'map-area stale' : 'map-area'}>
        <Suspense fallback={<div className="map map-loading muted">Loading the map&hellip;</div>}>
          <RouteMap plan={plan} selected={route?.id ?? null} hour={hour} onSelect={setSelected} />
        </Suspense>
        {plan && (
          <div className="map-controls">
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
