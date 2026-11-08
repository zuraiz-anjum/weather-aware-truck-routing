import type { Level } from './types'

export const LEVELS: Level[] = [0, 1, 2, 3, 4]

export const LEVEL_NAMES = ['Low', 'Moderate', 'High', 'Severe', 'No Travel'] as const

// Green through red to purple, the order a weather warning map uses, and
// each distinct from its neighbours for colour-blind readers.
export const LEVEL_COLORS = ['#2e9e5e', '#e2b007', '#ef7f1a', '#d73a2d', '#6f2dbd'] as const

export function levelName(level: Level): string {
  return LEVEL_NAMES[level]
}

export function levelColor(level: Level): string {
  return LEVEL_COLORS[level]
}

// Average risk is a mile-weighted mean of the levels, so 1.4 reads as
// "between Moderate and High, nearer Moderate".
export function describeAverage(average: number): string {
  const nearest = Math.min(4, Math.max(0, Math.round(average))) as Level
  return `${average.toFixed(2)} (about ${LEVEL_NAMES[nearest]})`
}
