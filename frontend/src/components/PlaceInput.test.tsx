import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { suggestPlaces } from '../api'
import PlaceInput from './PlaceInput'

vi.mock('../api', () => ({ suggestPlaces: vi.fn() }))

const DENVER = { label: 'Denver, Colorado', lat: 39.74, lon: -104.98 }
const DENVER_IA = { label: 'Denver, Iowa', lat: 42.67, lon: -92.34 }

beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(suggestPlaces).mockReset().mockResolvedValue([DENVER, DENVER_IA])
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

async function settle() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300)
  })
}

describe('PlaceInput', () => {
  it('asks for suggestions a moment after typing and picks one with the keyboard', async () => {
    const onChange = vi.fn()
    const { rerender } = render(<PlaceInput label="Origin" value={{ text: '' }} onChange={onChange} />)
    fireEvent.focus(screen.getByRole('combobox'))
    rerender(<PlaceInput label="Origin" value={{ text: 'den' }} onChange={onChange} />)
    expect(suggestPlaces).not.toHaveBeenCalled()
    await settle()
    expect(suggestPlaces).toHaveBeenCalledWith('den', expect.any(AbortSignal))
    const options = screen.getAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual(['Denver, Colorado', 'Denver, Iowa'])

    const input = screen.getByRole('combobox')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onChange).toHaveBeenLastCalledWith({ text: 'Denver, Iowa', place: DENVER_IA })
  })

  it('picks with the mouse and shows the coordinates of a picked place', async () => {
    const onChange = vi.fn()
    const { rerender } = render(<PlaceInput label="Origin" value={{ text: 'den' }} onChange={onChange} />)
    fireEvent.focus(screen.getByRole('combobox'))
    await settle()
    fireEvent.pointerDown(screen.getByText('Denver, Colorado'))
    expect(onChange).toHaveBeenLastCalledWith({ text: 'Denver, Colorado', place: DENVER })
    rerender(<PlaceInput label="Origin" value={{ text: 'Denver, Colorado', place: DENVER }} onChange={onChange} />)
    expect(screen.getByText('39.740, -104.980')).toBeTruthy()
    expect(screen.queryAllByRole('option')).toHaveLength(0)
  })

  it('keeps the list closed when focus has moved on before the answer came', async () => {
    const onChange = vi.fn()
    const { rerender } = render(<PlaceInput label="Origin" value={{ text: '' }} onChange={onChange} />)
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    rerender(<PlaceInput label="Origin" value={{ text: 'den' }} onChange={onChange} />)
    fireEvent.blur(input)
    await settle()
    expect(suggestPlaces).toHaveBeenCalledTimes(1)
    expect(screen.queryAllByRole('option')).toHaveLength(0)
    // Coming back to the field shows what was found.
    fireEvent.focus(input)
    expect(screen.getAllByRole('option')).toHaveLength(2)
  })

  it('does not ask for one letter, and says so when the lookup fails', async () => {
    const onChange = vi.fn()
    const { rerender } = render(<PlaceInput label="Origin" value={{ text: 'd' }} onChange={onChange} />)
    await settle()
    expect(suggestPlaces).not.toHaveBeenCalled()
    vi.mocked(suggestPlaces).mockRejectedValue(new Error('down'))
    rerender(<PlaceInput label="Origin" value={{ text: 'denver' }} onChange={onChange} />)
    await settle()
    expect(screen.getByText(/Suggestions are not available/)).toBeTruthy()
  })

  it('takes no more of a name than the server reads', () => {
    render(<PlaceInput label="Origin" value={{ text: '' }} onChange={vi.fn()} />)
    expect((screen.getByRole('combobox') as HTMLInputElement).maxLength).toBe(200)
  })
})
