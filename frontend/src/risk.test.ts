import { describe, expect, it } from 'vitest'
import { LEVELS, describeAverage, levelColor, levelName } from './risk'

describe('risk levels', () => {
  it('have a name and a colour each', () => {
    expect(LEVELS.map(levelName)).toEqual(['Low', 'Moderate', 'High', 'Severe', 'No Travel'])
    expect(new Set(LEVELS.map(levelColor)).size).toBe(5)
  })

  it('average risk is explained against the nearest level', () => {
    expect(describeAverage(0)).toBe('0.00 (about Low)')
    expect(describeAverage(1.4)).toBe('1.40 (about Moderate)')
    expect(describeAverage(3.6)).toBe('3.60 (about No Travel)')
  })
})
