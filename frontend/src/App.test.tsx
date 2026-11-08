import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError, planTrip } from './api'
import { plan } from './test/fixtures'

// MapLibre needs WebGL, which jsdom has not got; the map is checked in a browser.
vi.mock('./components/RouteMap', () => ({
  default: ({ selected, hour }: { selected: string | null; hour: number }) => (
    <div data-testid="map">
      {selected}@{hour}
    </div>
  ),
}))
vi.mock('./api', () => ({
  planTrip: vi.fn(),
  suggestPlaces: vi.fn().mockResolvedValue([]),
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number, detail: string) {
      super(detail)
      this.status = status
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

  it('shows what the server said when a trip cannot be planned', async () => {
    vi.mocked(planTrip).mockImplementation(() => Promise.reject(new ApiError(422, 'no road route between those places')))
    render(<App />)
    ask()
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('no road route between those places'))
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
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('try again in a minute'))
    expect(screen.getByRole('alert').textContent).toContain('The plan below is the previous one.')
    expect(document.querySelector('.results.stale')).toBeTruthy()
  })
})
