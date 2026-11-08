import type { Checkpoint, Level, Plan, Route } from '../types'

export const DEPARTURE = '2026-11-10T14:00:00+00:00'

function checkpoint(mile: number, seconds: number, level: Level = 0, overrides: Partial<Checkpoint> = {}): Checkpoint {
  return {
    mile,
    lat: 35,
    lon: -100 + mile / 60,
    eta: new Date(Date.parse(DEPARTURE) + seconds * 1000).toISOString(),
    seconds,
    covers_miles: 25,
    wind_mph: level >= 2 ? 40 : 10,
    rain_in: 0,
    snow_in: 0,
    level,
    wind_level: level,
    rain_level: 0,
    snow_level: 0,
    load_rule: null,
    ...overrides,
  }
}

export function route(id: string, overrides: Partial<Route> = {}): Route {
  return {
    id,
    name: 'via I-40 and US-287',
    detour: false,
    distance_miles: 100,
    duration_seconds: 7200,
    arrival: new Date(Date.parse(DEPARTURE) + 7200 * 1000).toISOString(),
    geometry: {
      type: 'LineString',
      coordinates: [
        [-100, 35],
        [-99.5, 35],
        [-99, 35],
        [-98.5, 35],
      ],
    },
    checkpoints: [checkpoint(0, 0), checkpoint(25, 1800), checkpoint(50, 3600, 2), checkpoint(75, 5400), checkpoint(100, 7200)],
    summary: {
      miles_by_level: [75, 0, 25, 0, 0],
      average_risk: 0.5,
      worst_level: 2,
      rank: 1,
      recommended: true,
      reason: 'the quickest route, and no other scores better on weather',
    },
    ...overrides,
  }
}

export function plan(overrides: Partial<Plan> = {}): Plan {
  return {
    origin: { label: 'Amarillo, Texas', lat: 35.2, lon: -101.8 },
    destination: { label: 'Oklahoma City, Oklahoma', lat: 35.5, lon: -97.5 },
    departure: DEPARTURE,
    load_lb: 20000,
    interval_miles: 25,
    slider_hours: 48,
    notes: [],
    routes: [
      route('A'),
      route('B', {
        name: 'via US-60',
        duration_seconds: 9000,
        summary: { miles_by_level: [100, 0, 0, 0, 0], average_risk: 0, worst_level: 0, rank: 2, recommended: false, reason: null },
      }),
    ],
    heatmap: { type: 'FeatureCollection', cell_miles: 5, features: [] },
    ...overrides,
  }
}
