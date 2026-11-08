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

  it('selects a route from its card or its name', () => {
    const onSelect = vi.fn()
    render(<RouteCards plan={plan()} selected="A" onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button', { name: 'Route B' }))
    expect(onSelect).toHaveBeenCalledWith('B')
    expect((screen.getByRole('button', { name: 'Route A' }) as HTMLButtonElement).getAttribute('aria-pressed')).toBe('true')
  })

  it('says when a route came from a side point', () => {
    const withDetour = plan()
    withDetour.routes[1].detour = true
    render(<RouteCards plan={withDetour} selected="A" onSelect={vi.fn()} />)
    expect(screen.getByText(/routing through a point to one side/)).toBeTruthy()
  })
})
