// Where a truck is on its route at a given moment, for the marker that
// moves with the forecast slider. The checkpoints give the clock (mile
// against seconds from departure); the route geometry gives the road.

import type { Checkpoint, Route } from './types'

const EARTH_RADIUS_MILES = 3958.7613

export function haversineMiles(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const rad = Math.PI / 180
  const dLat = (lat2 - lat1) * rad
  const dLon = (lon2 - lon1) * rad
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_MILES * Math.asin(Math.sqrt(Math.min(a, 1)))
}

export function cumulativeMiles(coordinates: number[][]): number[] {
  const miles = [0]
  for (let i = 1; i < coordinates.length; i++) {
    const [lon1, lat1] = coordinates[i - 1]
    const [lon2, lat2] = coordinates[i]
    miles.push(miles[i - 1] + haversineMiles(lon1, lat1, lon2, lat2))
  }
  return miles
}

function interpolate(xs: number[], ys: number[], x: number): number {
  if (x <= xs[0]) return ys[0]
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1]
  let lo = 0
  let hi = xs.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (xs[mid] <= x) lo = mid
    else hi = mid
  }
  const span = xs[hi] - xs[lo]
  return span === 0 ? ys[hi] : ys[lo] + ((ys[hi] - ys[lo]) * (x - xs[lo])) / span
}

export function mileAt(checkpoints: Checkpoint[], seconds: number): number {
  return interpolate(
    checkpoints.map((c) => c.seconds),
    checkpoints.map((c) => c.mile),
    seconds,
  )
}

// A route's geometry is a little shorter than its driven distance, so the
// mile markers are scaled to the geometry before looking up a position.
export class Track {
  private readonly coordinates: number[][]
  private readonly miles: number[]
  private readonly scale: number

  constructor(route: Route) {
    this.coordinates = route.geometry.coordinates
    this.miles = cumulativeMiles(this.coordinates)
    const drawn = this.miles[this.miles.length - 1]
    this.scale = drawn > 0 ? drawn / route.distance_miles : 1
  }

  positionAt(mile: number): [number, number] {
    const along = mile * this.scale
    const lon = interpolate(this.miles, this.coordinates.map((c) => c[0]), along)
    const lat = interpolate(this.miles, this.coordinates.map((c) => c[1]), along)
    return [lon, lat]
  }
}
