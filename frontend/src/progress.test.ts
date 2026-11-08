import { describe, expect, it } from 'vitest'
import { cumulativeMiles, haversineMiles, mileAt, Track } from './progress'
import { route } from './test/fixtures'

describe('distances', () => {
  it('New York to Los Angeles is about 2,445 miles', () => {
    expect(haversineMiles(-74.006, 40.7128, -118.2437, 34.0522)).toBeCloseTo(2445, -1)
  })

  it('accumulate along the coordinates', () => {
    const miles = cumulativeMiles([
      [-100, 35],
      [-99, 35],
      [-98, 35],
    ])
    expect(miles[0]).toBe(0)
    expect(miles[2]).toBeCloseTo(2 * miles[1], 6)
  })
})

describe('mileAt', () => {
  it('interpolates the clock between checkpoints and holds at the ends', () => {
    const points = route('A').checkpoints
    expect(mileAt(points, 0)).toBe(0)
    expect(mileAt(points, 900)).toBe(12.5)
    expect(mileAt(points, 3600)).toBe(50)
    expect(mileAt(points, 99_999)).toBe(100)
  })
})

describe('Track', () => {
  it('puts the truck on the road at a mile marker, scaling markers to the drawn line', () => {
    const track = new Track(route('A'))
    expect(track.positionAt(0)).toEqual([-100, 35])
    expect(track.positionAt(100)).toEqual([-98.5, 35])
    const [lon, lat] = track.positionAt(50)
    expect(lon).toBeCloseTo(-99.25, 6)
    expect(lat).toBeCloseTo(35, 6)
  })
})
