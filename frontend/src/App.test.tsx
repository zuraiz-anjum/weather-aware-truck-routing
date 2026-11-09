import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError, planTrip } from './api'
import { plan } from './test/fixtures'

// MapLibre needs WebGL, which jsdom has not got; the map is checked in a browser.
vi.mock('./components/RouteMap', () => ({
  default: ({ selected, hour, focus }: { selected: string | null; hour: number; focus: { checkpoint: { mile: number } } | null }) => (
    <div data-testid="map">
      {selected}@{hour}
      {focus && `>${focus.checkpoint.mile}`}
    </div>
  ),
}))
vi.mock('./api', () => ({
  planTrip: vi.fn(),
  suggestPlaces: vi.fn().mockResolvedValue([]),
  ApiError: class ApiError extends Error {
    status: number
    retryAfter: number | null
    forecast: unknown
    constructor(status: number, detail: string, retryAfter: number | null = null, forecast: unknown = null) {
      super(detail)
      this.status = status
      this.retryAfter = retryAfter
      this.forecast = forecast
    }
  },
}))

// jsdom lays nothing out and has no scrollIntoView; the app calls it to bring an error on screen.
const scrollIntoView = vi.fn()
Element.prototype.scrollIntoView = scrollIntoView

// Resetting the mock between tests (mockReset) makes vitest 5 report the
// rejected promise as unhandled even though App catches it; clearing is enough.
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
})

// A link is taken only from the year or so around today, so the tests' links are dated from today.
const DAY_MS = 86_400_000
const tomorrow = new Date(Date.now() + DAY_MS).toISOString()
const yesterday = new Date(Date.now() - DAY_MS).toISOString()

function ask() {
  fireEvent.change(screen.getByLabelText('Origin'), { target: { value: 'Amarillo' } })
  fireEvent.change(screen.getByLabelText('Destination'), { target: { value: 'Oklahoma City' } })
  fireEvent.click(screen.getByText('Plan routes'))
}

// The countdown arms a fresh one-second timer after each tick renders, so the clock has to move a second at a time.
async function seconds(count: number) {
  for (let k = 0; k < count; k += 1) await act(() => vi.advanceTimersByTimeAsync(1000))
}

describe('App', () => {
  it('plans a trip, shows the routes and lets one be chosen', async () => {
    vi.mocked(planTrip).mockResolvedValue(plan({ notes: ['Only two distinct road routes were found between these places.'] }))
    render(<App />)
    ask()
    expect(screen.getByText(/Fetching the roads/)).toBeTruthy()
    await waitFor(() => expect(screen.getByText('Recommended')).toBeTruthy())
    expect(screen.getByText(/Only two distinct road routes/)).toBeTruthy()
    await waitFor(() => expect(screen.getByTestId('map').textContent).toBe('A@0'))
    expect(screen.getByRole('region', { name: 'Checkpoints on route A' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Route B' }))
    expect(screen.getByTestId('map').textContent).toBe('B@0')
    expect(screen.getByRole('region', { name: 'Checkpoints on route B' })).toBeTruthy()

    fireEvent.change(screen.getByLabelText(/Forecast at/), { target: { value: '12' } })
    expect(screen.getByTestId('map').textContent).toBe('B@12')
    expect(window.location.search).toContain('from=Amarillo&to=Oklahoma+City&leave=')
  })

  it('opens a shared link and plans it when the departure is still ahead', async () => {
    vi.mocked(planTrip).mockResolvedValue(plan())
    window.history.replaceState(null, '', `?from=Amarillo&from_at=35.2,-101.8&to=Oklahoma+City&leave=${tomorrow}&load=36000&every=50`)
    render(<App />)
    await waitFor(() => expect(screen.getByText('Recommended')).toBeTruthy())
    expect(planTrip).toHaveBeenCalledWith(
      { origin: { text: 'Amarillo', lat: 35.2, lon: -101.8 }, destination: { text: 'Oklahoma City' }, departure: tomorrow, load_lb: 36000, interval_miles: 50 },
      expect.any(AbortSignal),
    )
    expect((screen.getByLabelText('Load weight (lb)') as HTMLInputElement).value).toBe('36000')
    expect(screen.queryByText(/departure in this link has passed/)).toBeNull()
  })

  it('only fills the form from a link whose departure has passed, and says so until a plan is asked for', async () => {
    vi.mocked(planTrip).mockResolvedValue(plan())
    window.history.replaceState(null, '', `?from=Amarillo&to=Oklahoma+City&leave=${yesterday}&load=20000`)
    render(<App />)
    expect(planTrip).not.toHaveBeenCalled()
    expect((screen.getByLabelText('Origin') as HTMLInputElement).value).toBe('Amarillo')
    const note = screen.getByText('The departure in this link has passed; choose a new time and plan again.')
    expect(note.className).toBe('note')
    expect(screen.queryByRole('alert')).toBeNull()
    fireEvent.click(screen.getByText('Plan routes'))
    expect(screen.queryByText(/departure in this link has passed/)).toBeNull()
    await waitFor(() => expect(screen.getByText('Recommended')).toBeTruthy())
    expect(planTrip).toHaveBeenCalledTimes(1)
  })

  it('takes the map to a checkpoint picked from the table, until another route is chosen', async () => {
    vi.mocked(planTrip).mockResolvedValue(plan())
    render(<App />)
    ask()
    await waitFor(() => expect(screen.getByText('Recommended')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '50' }))
    expect(screen.getByTestId('map').textContent).toBe('A@0>50')
    expect(screen.getByRole('button', { name: '50' }).closest('tr')?.className).toBe('picked')
    fireEvent.click(screen.getByRole('button', { name: 'Route B' }))
    expect(screen.getByTestId('map').textContent).toBe('B@0')
    expect(document.querySelector('tr.picked')).toBeNull()
  })

  it('fetches the forecast through the browser when the server has no allowance left, and says so', async () => {
    const offer = {
      url: 'https://weather.example/v1/forecast',
      params: { hourly: 'wind_speed_10m,rain,showers,snowfall', start_hour: '2026-11-10T00:00', end_hour: '2026-11-13T00:00' },
      points: [[35.2, -101.8], [35.3, -101.0]] as [number, number][],
    }
    const hourly = { time: [1, 2], wind_speed_10m: [5, 6], rain: [0, 0], showers: [0, 0], snowfall: [0, 0] }
    const fetched = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [{ hourly }, { hourly }] })
    vi.stubGlobal('fetch', fetched)
    try {
      vi.mocked(planTrip)
        .mockImplementationOnce(() => Promise.reject(new ApiError(503, "the weather service's free allowance for the day is spent", 86400, offer)))
        .mockResolvedValueOnce(plan())
      render(<App />)
      ask()
      await waitFor(() => expect(screen.getByText('Recommended')).toBeTruthy())
      expect(fetched).toHaveBeenCalledTimes(1)
      const url = new URL(fetched.mock.calls[0][0])
      expect(url.origin + url.pathname).toBe('https://weather.example/v1/forecast')
      expect(url.searchParams.get('latitude')).toBe('35.2000,35.3000')
      expect(url.searchParams.get('end_hour')).toBe('2026-11-13T00:00')
      expect(planTrip).toHaveBeenCalledTimes(2)
      expect(vi.mocked(planTrip).mock.calls[1][0].forecast).toEqual({ points: offer.points, hourly: [hourly, hourly] })
      expect(screen.queryByRole('status')).toBeNull()
      expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', behavior: 'smooth' }) // the status line was brought on screen
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('says when the browser could not fetch the forecast either', async () => {
    const offer = { url: 'https://weather.example/v1/forecast', params: {}, points: [[35.2, -101.8]] as [number, number][] }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ error: true, reason: 'Daily API request limit exceeded' }) }))
    try {
      vi.mocked(planTrip).mockImplementation(() => Promise.reject(new ApiError(503, "the weather service's free allowance for the day is spent", 86400, offer)))
      render(<App />)
      ask()
      await waitFor(() => expect(screen.getByRole('alert').textContent).toBe(
        "The weather service's free allowance for the day is spent. Fetching it through this browser did not work either: Daily API request limit exceeded.",
      ))
      expect(planTrip).toHaveBeenCalledTimes(1)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('shows what the server said when a trip cannot be planned', async () => {
    vi.mocked(planTrip).mockImplementation(() => Promise.reject(new ApiError(422, 'no road route between those places')))
    render(<App />)
    ask()
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('No road route between those places.'))
    expect(screen.queryByText('Recommended')).toBeNull()
    // On a phone the line lands under the fold of the form, so it is brought on screen.
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', behavior: 'smooth' })
  })

  it('takes down its own error when the form refuses the next attempt, so one problem shows at a time', async () => {
    vi.mocked(planTrip).mockResolvedValueOnce(plan())
    render(<App />)
    ask()
    await waitFor(() => expect(screen.getByText('Recommended')).toBeTruthy())
    vi.mocked(planTrip).mockImplementation(() => Promise.reject(new ApiError(503, 'try again in a minute')))
    ask()
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Try again in a minute. The plan below is the previous one.'))
    fireEvent.change(screen.getByLabelText('Load weight (lb)'), { target: { value: '250000' } })
    fireEvent.click(screen.getByText('Plan routes'))
    const alerts = screen.getAllByRole('alert')
    expect(alerts).toHaveLength(1)
    expect(alerts[0].textContent).toMatch(/between 0 and 200,000/)
    expect(planTrip).toHaveBeenCalledTimes(2)
  })

  it('names the places as resolved and shows the warning when nothing is clear to drive', async () => {
    vi.mocked(planTrip).mockResolvedValue(plan({ warning: 'No route is clear to drive at this departure.' }))
    render(<App />)
    ask()
    await waitFor(() => expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('Amarillo, Texas to Oklahoma City, Oklahoma'))
    expect(screen.getByText('No route is clear to drive at this departure.')).toBeTruthy()
  })

  it('marks the previous plan as stale when a new attempt fails', async () => {
    vi.mocked(planTrip).mockResolvedValueOnce(plan())
    render(<App />)
    ask()
    await waitFor(() => expect(screen.getByText('Recommended')).toBeTruthy())
    vi.mocked(planTrip).mockImplementation(() => Promise.reject(new ApiError(503, 'try again in a minute')))
    ask()
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Try again in a minute. The plan below is the previous one.'))
    expect(document.querySelector('.results.stale')).toBeTruthy()
  })

  it('waits out a busy weather service and asks again by itself', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(planTrip)
        .mockImplementationOnce(() => Promise.reject(new ApiError(503, 'try again in a minute', 2)))
        .mockResolvedValueOnce(plan())
      render(<App />)
      ask()
      await vi.waitFor(() => expect(screen.getByText(/Trying again in 2 s\./)).toBeTruthy())
      expect(screen.getByRole('status').textContent).toBe('The weather service is busy for the moment; the plan will be asked for again by itself.')
      await seconds(1)
      expect(screen.getByText(/Trying again in 1 s\./)).toBeTruthy()
      await seconds(1)
      await vi.waitFor(() => expect(screen.getByText('Recommended')).toBeTruthy())
      expect(planTrip).toHaveBeenCalledTimes(2)
      expect(screen.queryByRole('status')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('gives up after a third busy answer and shows what the server said', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(planTrip).mockImplementation(() => Promise.reject(new ApiError(503, 'try again in a minute', 2)))
      render(<App />)
      ask()
      await vi.waitFor(() => expect(screen.getByText(/Trying again in 2 s\./)).toBeTruthy())
      await seconds(2)
      await vi.waitFor(() => expect(planTrip).toHaveBeenCalledTimes(2))
      await vi.waitFor(() => expect(screen.getByText(/Trying again in 2 s\./)).toBeTruthy())
      await seconds(2)
      await vi.waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Try again in a minute.'))
      expect(planTrip).toHaveBeenCalledTimes(3)
      expect(screen.queryByRole('status')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})
