import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, planTrip } from './api'
import { fetchForecast } from './forecast'
import CheckpointTable from './components/CheckpointTable'
import HourSlider from './components/HourSlider'
import Legend from './components/Legend'
import RouteCards from './components/RouteCards'
import TripForm from './components/TripForm'
import { readLink, writeLink } from './link'
import { formatTime } from './time'
import { sentence } from './words'
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
  const [fetching, setFetching] = useState(false) // the forecast is being fetched through this browser
  const [focus, setFocus] = useState<{ route: string; checkpoint: Checkpoint } | null>(null) // picked in the table, for the map to go to
  const pending = useRef<AbortController | null>(null)
  const lastRequest = useRef<{ request: PlanRequest; attempt: number } | null>(null)
  const overlay = useRef<HTMLDivElement>(null)
  const alarm = useRef<HTMLParagraphElement>(null)
  const [opening] = useState(() => readLink(window.location.search)) // a plan sent on as a link
  // The link's departure has gone by, so nothing was planned from it; said until a plan is asked for.
  const [passed, setPassed] = useState(() => opening !== null && Date.parse(opening.request.departure) <= Date.now())

  const submit = useCallback(async function submit(request: PlanRequest, attempt = 1) {
    pending.current?.abort()
    const controller = new AbortController()
    pending.current = controller
    lastRequest.current = { request, attempt }
    setBusy(true)
    setError(null)
    setRetryIn(null)
    setFetching(false)
    setPassed(false)
    try {
      const result = await planTrip(request, controller.signal)
      setPlan(result)
      setSelected(result.routes[0]?.id ?? null)
      setHour(0)
      setFocus(null)
      window.history.replaceState(null, '', writeLink(request))
    } catch (failure: unknown) {
      if (failure instanceof DOMException && failure.name === 'AbortError') return
      // The server's address has no weather allowance left for the hour or the
      // day, and it has said which forecast it needs: this browser fetches it
      // with its own allowance and sends the readings back to be judged.
      if (failure instanceof ApiError && failure.forecast && !request.forecast) {
        setFetching(true)
        try {
          const forecast = await fetchForecast(failure.forecast, controller.signal)
          if (pending.current !== controller) return
          return await submit({ ...request, forecast }, attempt)
        } catch (fetching: unknown) {
          if (fetching instanceof DOMException && fetching.name === 'AbortError') return
          setError(`${sentence(failure.message)} Fetching it through this browser did not work either: ${fetching instanceof Error ? fetching.message : 'something went wrong'}`)
          return
        } finally {
          setFetching(false)
        }
      }
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

  // A link whose departure is still ahead is planned once the page is up;
  // one whose departure has passed only fills the form and waits to be changed.
  useEffect(() => {
    if (!opening || Date.parse(opening.request.departure) <= Date.now()) return
    const timer = setTimeout(() => void submit(opening.request), 0)
    return () => clearTimeout(timer)
  }, [opening, submit])

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

  // On a phone the form fills the panel and this line lands under its fold, where
  // a failed plan would show as nothing more than the busy notice going away.
  useEffect(() => {
    if (error) alarm.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [error])

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
        <TripForm onSubmit={submit} onInvalid={() => setError(null)} busy={busy} initial={opening?.draft} />
        {error && (
          <p className="problem" role="alert" ref={alarm}>
            {sentence(error)}
            {stale && ' The plan below is the previous one.'}
          </p>
        )}
        {fetching && (
          <p className="waiting" role="status">
            The weather service's allowance for the server is spent, so the forecast is being fetched through this browser instead.
          </p>
        )}
        {retryIn !== null && (
          // Only the sentence is a live region, so a screen reader hears it once and not every second of the count.
          <p className="waiting">
            <span role="status">The weather service is busy for the moment; the plan will be asked for again by itself.</span> Trying
            again in {retryIn} s.{stale && ' The plan below is the previous one.'}
          </p>
        )}
        {passed && <p className="note">The departure in this link has passed; choose a new time and plan again.</p>}
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
        <footer className="small muted credits">
          Weather by <a href="https://open-meteo.com/">Open-Meteo</a>, roads by <a href="https://project-osrm.org/">OSRM</a>, places by{' '}
          <a href="https://photon.komoot.io/">Photon</a>. <a href="https://github.com/zuraiz-anjum/weather-aware-truck-routing">Source</a>.
        </footer>
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
            Fetching the roads, then the forecast for every checkpoint and cell. A new pair of places takes a few seconds.
          </div>
        )}
      </main>
    </div>
  )
}
