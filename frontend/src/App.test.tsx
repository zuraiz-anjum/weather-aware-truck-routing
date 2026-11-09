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
    constructor(status: number, detail: string, retryAfter: number | null = null) {
      super(detail)
      this.status = status
      this.retryAfter = retryAfter
    }
  },
}))

// Resetting the mock between tests (mockReset) makes vitest 5 report the
// rejected promise as unhandled even though App catches it; clearing is enough.
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

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
    expect(screen.getByText(/Fetching routes/)).toBeTruthy()
    await waitFor(() => expect(screen.getByText('Recommended')).toBeTruthy())
    expect(screen.getByText(/Only two distinct road routes/)).toBeTruthy()
    await waitFor(() => expect(screen.getByTestId('map').textContent).toBe('A@0'))
    expect(screen.getByRole('region', { name: 'Checkpoints on route A' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Route B' }))
    expect(screen.getByTestId('map').textContent).toBe('B@0')
    expect(screen.getByRole('region', { name: 'Checkpoints on route B' })).toBeTruthy()

    fireEvent.change(screen.getByLabelText(/Forecast at/), { target: { value: '12' } })
    expect(screen.getByTestId('map').textContent).toBe('B@12')
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

  it('shows what the server said when a trip cannot be planned', async () => {
    vi.mocked(planTrip).mockImplementation(() => Promise.reject(new ApiError(422, 'no road route between those places')))
    render(<App />)
    ask()
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('No road route between those places.'))
    expect(screen.queryByText('Recommended')).toBeNull()
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
