import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TripForm from './TripForm'

vi.mock('../api', () => ({ suggestPlaces: vi.fn().mockResolvedValue([]) }))

afterEach(cleanup)

function fill(origin: string, destination: string) {
  fireEvent.change(screen.getByLabelText('Origin'), { target: { value: origin } })
  fireEvent.change(screen.getByLabelText('Destination'), { target: { value: destination } })
}

describe('TripForm', () => {
  it('asks for both places before planning', () => {
    const onSubmit = vi.fn()
    render(<TripForm onSubmit={onSubmit} busy={false} />)
    fireEvent.click(screen.getByText('Plan routes'))
    expect(screen.getByRole('alert').textContent).toMatch(/origin and a destination/)
    expect(onSubmit).not.toHaveBeenCalled()
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

  it('is quiet while a plan is on its way', () => {
    render(<TripForm onSubmit={vi.fn()} busy={true} />)
    const button = screen.getByRole('button', { name: /Planning/ }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })
})
