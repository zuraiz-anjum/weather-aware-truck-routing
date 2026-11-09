// The shapes the API sends and takes. They mirror backend/trips/planner.py.

import type { FeatureCollection, LineString, Polygon } from 'geojson'

export type Level = 0 | 1 | 2 | 3 | 4

export interface Place {
  label: string
  lat: number
  lon: number
}

export interface PlaceInput {
  text?: string
  lat?: number
  lon?: number
}

// What the server asks the browser to fetch when its own address has no
// weather allowance left: Open-Meteo's address, the query apart from the
// coordinates, and the points, in the order the readings must come back.
export interface ForecastOffer {
  url: string
  params: Record<string, string>
  points: [number, number][]
}

// One point's hourly series as Open-Meteo sends it; the tail may be null.
export interface OpenMeteoHourly {
  time: number[]
  wind_speed_10m: (number | null)[]
  rain: (number | null)[]
  showers: (number | null)[]
  snowfall: (number | null)[]
}

export interface SuppliedForecast {
  points: [number, number][]
  hourly: OpenMeteoHourly[]
}

export interface PlanRequest {
  origin: PlaceInput
  destination: PlaceInput
  departure: string
  load_lb: number
  interval_miles?: number
  forecast?: SuppliedForecast // readings fetched by this browser, when the server asked for them
}

export interface Checkpoint {
  mile: number
  lat: number
  lon: number
  eta: string
  seconds: number
  covers_miles: number
  wind_mph: number
  rain_in: number
  snow_in: number
  level: Level
  wind_level: Level
  rain_level: Level
  snow_level: Level
  load_rule: string | null
}

export interface RouteSummary {
  miles_by_level: number[]
  average_risk: number
  worst_level: Level
  rank: number
  recommended: boolean
  reason: string | null
}

export interface Route {
  id: string
  name: string
  detour: boolean
  distance_miles: number
  minor_miles: number // on roads without a route number, or county or forest roads, which a truck may not be allowed on
  minor_roads: string[] // the furthest-driven of those, by name
  duration_seconds: number
  arrival: string
  geometry: LineString
  checkpoints: Checkpoint[]
  summary: RouteSummary
}

export interface CellProperties {
  levels: Level[]
}

export type Heatmap = FeatureCollection<Polygon, CellProperties> & { cell_miles: number }

export interface Plan {
  origin: Place
  destination: Place
  departure: string
  load_lb: number
  interval_miles: number
  slider_hours: number
  notes: string[]
  warning: string | null
  routes: Route[]
  heatmap: Heatmap
}
