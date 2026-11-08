import { describe, expect, it } from 'vitest'
import { LEVELS, chipText, levelColor, levelInk, levelName } from './risk'

describe('risk levels', () => {
  it('have a name, a fill and an ink each', () => {
    expect(LEVELS.map(levelName)).toEqual(['Low', 'Moderate', 'High', 'Severe', 'No Travel'])
    expect(new Set(LEVELS.map(levelColor)).size).toBe(5)
    expect(new Set(LEVELS.map(levelInk)).size).toBe(5)
  })

  it('chips on the light fills get dark lettering', () => {
    expect(LEVELS.map(chipText)).toEqual(['#ffffff', '#1d2430', '#1d2430', '#ffffff', '#ffffff'])
  })
})
