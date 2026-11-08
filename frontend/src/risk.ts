import type { Level } from './types'

export const LEVELS: Level[] = [0, 1, 2, 3, 4]

export const LEVEL_NAMES = ['Low', 'Moderate', 'High', 'Severe', 'No Travel'] as const

// Fills for the map, the chips and the bars: green through red to purple,
// the order a weather warning map uses, each distinct from its neighbours
// for colour-blind readers.
export const LEVEL_COLORS = ['#2e9e5e', '#e2b007', '#ef7f1a', '#d73a2d', '#6f2dbd'] as const

// The same scale darkened for text on white, where amber and orange would
// be too faint to read.
export const LEVEL_INKS = ['#1e7a46', '#8a6a00', '#b35600', '#b42318', '#5b21b6'] as const

export function levelName(level: Level): string {
  return LEVEL_NAMES[level]
}

export function levelColor(level: Level): string {
  return LEVEL_COLORS[level]
}

export function levelInk(level: Level): string {
  return LEVEL_INKS[level]
}

// Dark lettering on the two light fills, white on the rest.
export function chipText(level: Level): string {
  return level === 1 || level === 2 ? '#1d2430' : '#ffffff'
}
