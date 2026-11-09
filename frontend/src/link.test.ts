import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readLink, writeLink } from './link'

// How far off a link's departure may be is measured from today, so today is pinned.
beforeEach(() => vi.setSystemTime('2026-11-09T12:00:00Z'))
afterEach(() => vi.useRealTimers())

describe('a plan in the address bar', () => {
  it('writes the inputs readably and reads them back', () => {
    const request = {
      origin: { text: 'Denver, Colorado', lat: 39.7392, lon: -104.9903 },
      destination: { text: 'Salt Lake City' },
      departure: '2026-11-12T14:00:00.000Z',
      load_lb: 36000,
      interval_miles: 25,
    }
    const link = writeLink(request)
    expect(link).toBe('?from=Denver,+Colorado&from_at=39.7392,-104.9903&to=Salt+Lake+City&leave=2026-11-12T14:00:00.000Z&load=36000&every=25')
    const opening = readLink(link)
    expect(opening?.request).toEqual(request)
    expect(opening?.draft.origin).toEqual({ text: 'Denver, Colorado', place: { label: 'Denver, Colorado', lat: 39.7392, lon: -104.9903 } })
    expect(opening?.draft.destination).toEqual({ text: 'Salt Lake City' })
    expect(opening?.draft.load).toBe('36000')
    expect(opening?.draft.interval).toBe('25')
  })

  it('leaves out what is not a plan', () => {
    expect(readLink('')).toBeNull()
    expect(readLink('?from=A&to=B')).toBeNull()
    expect(readLink('?from=A&to=B&leave=tomorrow&load=1')).toBeNull()
    expect(readLink('?from=A&to=B&leave=2026-11-12T14:00:00Z&load=250000')).toBeNull()
    expect(readLink('?from=A&to=B&leave=2026-11-12T14:00:00Z&load=1&every=15')).toBeNull()
    // No load is no plan, rather than an empty truck; a load of nothing is still a load.
    expect(readLink('?from=A&to=B&leave=2026-11-12T14:00:00Z')).toBeNull()
    expect(readLink('?from=A&to=B&leave=2026-11-12T14:00:00Z&load=')).toBeNull()
    expect(readLink('?from=A&to=B&leave=2026-11-12T14:00:00Z&load=0')?.request.load_lb).toBe(0)
    // Coordinates that make no sense are dropped, the name kept.
    const opening = readLink('?from=A&from_at=95,0&to=B&leave=2026-11-12T14:00:00Z&load=1')
    expect(opening?.request.origin).toEqual({ text: 'A' })
    expect(opening?.draft.interval).toBe('auto')
  })

  it('takes a departure from the year or so around today, not one years off either way', () => {
    expect(readLink('?from=A&to=B&leave=2026-06-01T14:00:00Z&load=1')).not.toBeNull()
    expect(readLink('?from=A&to=B&leave=2027-06-01T14:00:00Z&load=1')).not.toBeNull()
    expect(readLink('?from=A&to=B&leave=2025-09-01T14:00:00Z&load=1')).toBeNull()
    expect(readLink('?from=A&to=B&leave=2028-01-01T14:00:00Z&load=1')).toBeNull()
    expect(readLink('?from=A&to=B&leave=2099-01-01T14:00:00Z&load=1')).toBeNull()
  })
})
