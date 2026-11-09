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

export interface PlanRequest {
  origin: PlaceInput
  destination: PlaceInput
  departure: string
  load_lb: number
  interval_miles?: number
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
  unnumbered_miles: number // on roads without a route number, which a truck may not be allowed on
  unnumbered_roads: string[] // the furthest-driven of those, by name
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
