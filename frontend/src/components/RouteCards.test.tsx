import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { plan } from '../test/fixtures'
import RouteCards from './RouteCards'

afterEach(cleanup)

describe('RouteCards', () => {
  it('lists the routes with the recommended one marked and explained', () => {
    render(<RouteCards plan={plan()} selected="A" onSelect={vi.fn()} />)
    expect(screen.getByText('Recommended')).toBeTruthy()
    expect(screen.getByText('#2')).toBeTruthy()
    expect(screen.getByText(/The quickest route, and no other scores better on weather\./)).toBeTruthy()
    expect(screen.getByText('High')).toBeTruthy()
    expect(screen.getByRole('img', { name: '75 mi Low, 25 mi High' })).toBeTruthy()
    expect(screen.getByText(/2 h 30 min/)).toBeTruthy()
  })

  it('selects a route once from its card or its name', () => {
    const onSelect = vi.fn()
    render(<RouteCards plan={plan()} selected="A" onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: 'Route B' }))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith('B')
    fireEvent.click(screen.getByText('via US-60'))
    expect(onSelect).toHaveBeenCalledTimes(2)
    expect((screen.getByRole('button', { name: 'Route A' }) as HTMLButtonElement).getAttribute('aria-pressed')).toBe('true')
  })

  it('does not call a blocked best route recommended', () => {
    const blocked = plan()
    blocked.routes[0].summary = {
      ...blocked.routes[0].summary,
      recommended: false,
      miles_by_level: [0, 0, 0, 25, 75],
      worst_level: 4,
    }
    render(<RouteCards plan={blocked} selected="A" onSelect={vi.fn()} />)
    expect(screen.queryByText('Recommended')).toBeNull()
    expect(screen.getByText('Not clear to drive')).toBeTruthy()
    expect(screen.getByText(/100 mi Severe or worse, 75 of them No Travel/)).toBeTruthy()
  })

  it('says when a route came from a side point', () => {
    const withDetour = plan()
    withDetour.routes[1].detour = true
    render(<RouteCards plan={withDetour} selected="A" onSelect={vi.fn()} />)
    expect(screen.getByText(/routing through a point to one side/)).toBeTruthy()
  })
})
