import { useEffect, useRef, useState } from 'react'
import { LngLatBounds, Map as MapLibre, Marker, NavigationControl, Popup } from 'maplibre-gl'
import type { ExpressionSpecification, GeoJSONSource, MapGeoJSONFeature, MapMouseEvent } from 'maplibre-gl'
import type { Feature, FeatureCollection, LineString, Point } from 'geojson'
import { LEVEL_COLORS, levelName } from '../risk'
import { formatDuration, formatShortTime } from '../time'
import { mileAt, Track } from '../progress'
import type { Checkpoint, Plan, Route } from '../types'

const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
const UNITED_STATES: [number, number, number, number] = [-125, 24, -66, 50]

const SELECTED = '#1f3a5f'
const UNSELECTED = '#9aa4b2'

interface Props {
  plan: Plan | null
  selected: string | null
  hour: number
  onSelect: (id: string) => void
}

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] }

function byLevel(level: ExpressionSpecification, values: readonly (string | number)[], fallback: string | number): ExpressionSpecification {
  return ['match', level, 0, values[0], 1, values[1], 2, values[2], 3, values[3], 4, values[4], fallback]
}

function levelAt(hour: number): ExpressionSpecification {
  return ['at', hour, ['get', 'levels']]
}

// Calm cells are a faint wash so the eye goes to the trouble.
const CELL_OPACITY = [0.12, 0.4, 0.45, 0.5, 0.55] as const

const isSelected: ExpressionSpecification = ['boolean', ['feature-state', 'selected'], false]

function install(map: MapLibre) {
  map.addSource('cells', { type: 'geojson', data: EMPTY })
  map.addSource('routes', { type: 'geojson', data: EMPTY, promoteId: 'id' })
  map.addSource('checkpoints', { type: 'geojson', data: EMPTY })

  map.addLayer({
    id: 'cells',
    type: 'fill',
    source: 'cells',
    paint: {
      'fill-color': byLevel(levelAt(0), LEVEL_COLORS, '#888'),
      'fill-opacity': byLevel(levelAt(0), CELL_OPACITY, 0),
      'fill-antialias': false,
    },
  })
  map.addLayer({
    id: 'routes-casing',
    type: 'line',
    source: 'routes',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': '#ffffff', 'line-width': ['case', isSelected, 9, 6] },
  })
  map.addLayer({
    id: 'routes',
    type: 'line',
    source: 'routes',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': ['case', isSelected, SELECTED, UNSELECTED], 'line-width': ['case', isSelected, 5, 3] },
  })
  // Every route's checkpoints are on the map; the chosen route's are the big ones.
  map.addLayer({
    id: 'checkpoints-other',
    type: 'circle',
    source: 'checkpoints',
    paint: {
      'circle-radius': 3,
      'circle-color': byLevel(['get', 'level'], LEVEL_COLORS, '#888'),
      'circle-opacity': 0.75,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 1,
    },
  })
  map.addLayer({
    id: 'checkpoints',
    type: 'circle',
    source: 'checkpoints',
    paint: {
      'circle-radius': 5,
      'circle-color': byLevel(['get', 'level'], LEVEL_COLORS, '#888'),
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 1.5,
    },
  })
}

function summarise(route: Route): string {
  return (
    `<b>Route ${escape(route.id)}</b> ${escape(route.name)}<br>` +
    `${Math.round(route.distance_miles).toLocaleString()} mi, ${escape(formatDuration(route.duration_seconds))}<br>` +
    `Worst <b style="color:${LEVEL_COLORS[route.summary.worst_level]}">${levelName(route.summary.worst_level)}</b>, ` +
    `average ${route.summary.average_risk.toFixed(2)}` +
    (route.summary.recommended ? '<br><i>Recommended</i>' : '')
  )
}

function routeFeatures(plan: Plan): FeatureCollection<LineString> {
  // Drawn in reverse rank order so the recommended route ends up on top.
  return {
    type: 'FeatureCollection',
    features: [...plan.routes].reverse().map((route) => ({
      type: 'Feature',
      id: route.id,
      geometry: route.geometry,
      properties: { id: route.id, summary: summarise(route) },
    })),
  }
}

function checkpointFeatures(plan: Plan): FeatureCollection<Point> {
  const features: Feature<Point>[] = []
  for (const route of plan.routes) {
    for (const c of route.checkpoints) {
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [c.lon, c.lat] },
        properties: { route: route.id, ...c },
      })
    }
  }
  return { type: 'FeatureCollection', features }
}

function escape(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
}

function describe(route: string, c: Checkpoint): string {
  const rows = [
    ['Wind', `${c.wind_mph.toFixed(0)} mph`, c.wind_level],
    ['Rain', `${c.rain_in.toFixed(2)} in/h`, c.rain_level],
    ['Snow', `${c.snow_in.toFixed(2)} in/h`, c.snow_level],
  ] as const
  return (
    `<b>Route ${escape(route)}, mile ${Math.round(c.mile)}</b><br>` +
    `${escape(formatShortTime(c.eta))}<br>` +
    rows.map(([name, value, level]) => `${name} ${value}${level > 0 ? ` <i>${levelName(level)}</i>` : ''}`).join('<br>') +
    `<br><b style="color:${LEVEL_COLORS[c.level]}">${levelName(c.level)}</b>` +
    (c.load_rule ? `<br><small>${escape(c.load_rule)}</small>` : '')
  )
}

function bounds(plan: Plan): LngLatBounds {
  const box = new LngLatBounds()
  for (const route of plan.routes) for (const [lon, lat] of route.geometry.coordinates) box.extend([lon, lat])
  return box
}

function truckElement(id: string): HTMLElement {
  const element = document.createElement('div')
  element.className = 'truck'
  element.textContent = id
  return element
}

// "Amarillo" on the map, the whole label on hover.
function endElement(label: string): HTMLElement {
  const element = document.createElement('div')
  element.className = 'end'
  element.textContent = label.split(',')[0]
  element.title = label
  return element
}

export default function RouteMap({ plan, selected, hour, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibre | null>(null)
  const trucks = useRef<globalThis.Map<string, Marker>>(new globalThis.Map())
  const ends = useRef<Marker[]>([])
  const tracks = useRef<globalThis.Map<string, Track>>(new globalThis.Map())
  const select = useRef(onSelect)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    select.current = onSelect
  }, [onSelect])

  useEffect(() => {
    const instance = new MapLibre({
      container: container.current!,
      style: STYLE_URL,
      bounds: UNITED_STATES,
      fitBoundsOptions: { padding: 20 },
      attributionControl: { compact: true },
    })
    instance.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    const popup = new Popup({ closeButton: false, closeOnClick: false, maxWidth: '260px' })

    instance.on('load', () => {
      install(instance)
      instance.on('click', 'routes', (event: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
        const id = event.features?.[0]?.properties?.id
        if (typeof id === 'string') select.current(id)
      })
      instance.on('mouseenter', 'routes', () => (instance.getCanvas().style.cursor = 'pointer'))
      instance.on('mousemove', 'routes', (event: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
        const summary = event.features?.[0]?.properties?.summary
        if (typeof summary === 'string') popup.setLngLat(event.lngLat).setHTML(summary).addTo(instance)
      })
      instance.on('mouseleave', 'routes', () => {
        instance.getCanvas().style.cursor = ''
        popup.remove()
      })
      for (const layer of ['checkpoints', 'checkpoints-other']) {
        instance.on('mouseenter', layer, (event: MapMouseEvent & { features?: MapGeoJSONFeature[] }) => {
          const feature = event.features?.[0]
          if (!feature || feature.geometry.type !== 'Point') return
          instance.getCanvas().style.cursor = 'default'
          const [lon, lat] = feature.geometry.coordinates
          const { route, ...checkpoint } = feature.properties as Checkpoint & { route: string }
          popup.setLngLat([lon, lat]).setHTML(describe(route, checkpoint)).addTo(instance)
        })
        instance.on('mouseleave', layer, () => {
          instance.getCanvas().style.cursor = ''
          popup.remove()
        })
      }
      setReady(true)
    })
    map.current = instance
    return () => {
      instance.remove()
      map.current = null
      setReady(false)
    }
  }, [])

  // A new plan: fresh data for every layer, new markers, and the view fitted to the routes.
  useEffect(() => {
    const instance = map.current
    if (!instance || !ready) return
    for (const marker of trucks.current.values()) marker.remove()
    for (const marker of ends.current) marker.remove()
    trucks.current.clear()
    ends.current = []
    tracks.current.clear()
    if (!plan) {
      for (const source of ['cells', 'routes', 'checkpoints']) (instance.getSource(source) as GeoJSONSource).setData(EMPTY)
      return
    }
    ;(instance.getSource('cells') as GeoJSONSource).setData(plan.heatmap)
    ;(instance.getSource('routes') as GeoJSONSource).setData(routeFeatures(plan))
    ;(instance.getSource('checkpoints') as GeoJSONSource).setData(checkpointFeatures(plan))
    for (const route of plan.routes) {
      tracks.current.set(route.id, new Track(route))
      const marker = new Marker({ element: truckElement(route.id) }).setLngLat(route.geometry.coordinates[0] as [number, number])
      marker.getElement().addEventListener('click', () => select.current(route.id))
      trucks.current.set(route.id, marker.addTo(instance))
    }
    ends.current = [
      new Marker({ element: endElement(plan.origin.label), anchor: 'bottom', offset: [0, -4] }).setLngLat([plan.origin.lon, plan.origin.lat]).addTo(instance),
      new Marker({ element: endElement(plan.destination.label), anchor: 'bottom', offset: [0, -4] }).setLngLat([plan.destination.lon, plan.destination.lat]).addTo(instance),
    ]
    instance.fitBounds(bounds(plan), { padding: { top: 48, right: 48, bottom: 120, left: 48 }, duration: 700, maxZoom: 11 })
  }, [plan, ready])

  // The chosen route is drawn bold with its checkpoints; the others stay in the background.
  useEffect(() => {
    const instance = map.current
    if (!instance || !ready || !plan) return
    for (const route of plan.routes) {
      instance.setFeatureState({ source: 'routes', id: route.id }, { selected: route.id === selected })
      trucks.current.get(route.id)?.getElement().classList.toggle('selected', route.id === selected)
    }
    instance.setFilter('checkpoints', ['==', ['get', 'route'], selected ?? ''])
    instance.setFilter('checkpoints-other', ['!=', ['get', 'route'], selected ?? ''])
  }, [plan, selected, ready])

  // The slider hour recolours the cells and moves each truck to where it is by then.
  useEffect(() => {
    const instance = map.current
    if (!instance || !ready) return
    instance.setPaintProperty('cells', 'fill-color', byLevel(levelAt(hour), LEVEL_COLORS, '#888'))
    instance.setPaintProperty('cells', 'fill-opacity', byLevel(levelAt(hour), CELL_OPACITY, 0))
    if (!plan) return
    const seconds = hour * 3600
    for (const route of plan.routes) {
      const marker = trucks.current.get(route.id)
      const track = tracks.current.get(route.id)
      if (!marker || !track) continue
      marker.setLngLat(track.positionAt(mileAt(route.checkpoints, seconds)))
      marker.getElement().classList.toggle('arrived', seconds >= route.duration_seconds)
    }
  }, [plan, hour, ready])

  return <div ref={container} className="map" role="region" aria-label="Map of the routes" />
}
