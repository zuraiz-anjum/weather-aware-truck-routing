import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TripForm from './TripForm'

vi.mock('../api', () => ({ suggestPlaces: vi.fn().mockResolvedValue([]) }))

// jsdom lays nothing out and has no scrollIntoView; the form calls it to bring its problem on screen.
const scrollIntoView = vi.fn()
Element.prototype.scrollIntoView = scrollIntoView

afterEach(() => {
  cleanup()
  scrollIntoView.mockClear()
})

function fill(origin: string, destination: string) {
  fireEvent.change(screen.getByLabelText('Origin'), { target: { value: origin } })
  fireEvent.change(screen.getByLabelText('Destination'), { target: { value: destination } })
}

describe('TripForm', () => {
  it('asks for both places before planning, and brings the line on screen', () => {
    const onSubmit = vi.fn()
    render(<TripForm onSubmit={onSubmit} busy={false} />)
    fireEvent.click(screen.getByText('Plan routes'))
    expect(screen.getByRole('alert').textContent).toMatch(/origin and a destination/)
    expect(onSubmit).not.toHaveBeenCalled()
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', behavior: 'smooth' })
  })

  it('says when it has refused, so that an older error elsewhere can come down', () => {
    const onSubmit = vi.fn()
    const onInvalid = vi.fn()
    render(<TripForm onSubmit={onSubmit} onInvalid={onInvalid} busy={false} />)
    fill('A', 'B')
    fireEvent.change(screen.getByLabelText('Load weight (lb)'), { target: { value: '-1' } })
    fireEvent.click(screen.getByText('Plan routes'))
    expect(onInvalid).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Load weight (lb)'), { target: { value: '1000' } })
    fireEvent.click(screen.getByText('Plan routes'))
    expect(onInvalid).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('sends typed names, the departure as an instant, and the load as a whole number', () => {
    const onSubmit = vi.fn()
    render(<TripForm onSubmit={onSubmit} busy={false} />)
    fill('  Amarillo ', 'Oklahoma City')
    fireEvent.change(screen.getByLabelText(/Departure/), { target: { value: '2026-11-10T09:30' } })
    fireEvent.change(screen.getByLabelText('Load weight (lb)'), { target: { value: '36000.4' } })
    fireEvent.click(screen.getByText('Plan routes'))
    expect(onSubmit).toHaveBeenCalledTimes(1)
    const request = onSubmit.mock.calls[0][0]
    expect(request.origin).toEqual({ text: 'Amarillo' })
    expect(request.destination).toEqual({ text: 'Oklahoma City' })
    expect(request.departure).toBe(new Date(2026, 10, 10, 9, 30).toISOString())
    expect(request.load_lb).toBe(36000)
    expect(request).not.toHaveProperty('interval_miles')
  })

  it('passes a chosen checkpoint spacing and refuses an impossible load', () => {
    const onSubmit = vi.fn()
    render(<TripForm onSubmit={onSubmit} busy={false} />)
    fill('A', 'B')
    fireEvent.change(screen.getByLabelText('Weather checkpoints'), { target: { value: '50' } })
    fireEvent.change(screen.getByLabelText('Load weight (lb)'), { target: { value: '250000' } })
    fireEvent.click(screen.getByText('Plan routes'))
    expect(screen.getByRole('alert').textContent).toMatch(/between 0 and 200,000/)
    fireEvent.change(screen.getByLabelText('Load weight (lb)'), { target: { value: '80000' } })
    fireEvent.click(screen.getByText('Plan routes'))
    expect(onSubmit.mock.calls[0][0].interval_miles).toBe(50)
  })

  it('swaps the two places', () => {
    render(<TripForm onSubmit={vi.fn()} busy={false} />)
    fill('Here', 'There')
    fireEvent.click(screen.getByText('Swap'))
    expect((screen.getByLabelText('Origin') as HTMLInputElement).value).toBe('There')
    expect((screen.getByLabelText('Destination') as HTMLInputElement).value).toBe('Here')
  })

  it('plans an example trip in one click, with its coordinates', () => {
    const onSubmit = vi.fn()
    render(<TripForm onSubmit={onSubmit} busy={false} />)
    fireEvent.click(screen.getByRole('button', { name: 'Denver to Salt Lake City' }))
    expect(onSubmit).toHaveBeenCalledTimes(1)
    const request = onSubmit.mock.calls[0][0]
    expect(request.origin).toEqual({ text: 'Denver, Colorado', lat: 39.7392, lon: -104.9903 })
    expect(request.destination.text).toBe('Salt Lake City, Utah')
    expect((screen.getByLabelText('Origin') as HTMLInputElement).value).toBe('Denver, Colorado')
  })

  it('starts from a draft when given one', () => {
    const draft = {
      origin: { text: 'Amarillo', place: { label: 'Amarillo', lat: 35.2, lon: -101.8 } },
      destination: { text: 'Oklahoma City' },
      departure: '2026-11-12T09:00',
      load: '36000',
      interval: '50',
    }
    render(<TripForm onSubmit={vi.fn()} busy={false} initial={draft} />)
    expect((screen.getByLabelText('Origin') as HTMLInputElement).value).toBe('Amarillo')
    expect(screen.getByText('35.200, -101.800')).toBeTruthy()
    expect((screen.getByLabelText(/Departure/) as HTMLInputElement).value).toBe('2026-11-12T09:00')
    expect((screen.getByLabelText('Load weight (lb)') as HTMLInputElement).value).toBe('36000')
    expect((screen.getByLabelText('Weather checkpoints') as HTMLSelectElement).value).toBe('50')
  })

  it('is quiet while a plan is on its way', () => {
    render(<TripForm onSubmit={vi.fn()} busy={true} />)
    const button = screen.getByRole('button', { name: /Planning/ }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })
})
