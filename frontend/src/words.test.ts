import { describe, expect, it } from 'vitest'
import { sentence } from './words'

describe('sentence', () => {
  it('capitalises and closes a message, and leaves a sentence alone', () => {
    expect(sentence('the departure is in the past')).toBe('The departure is in the past.')
    expect(sentence('Something went wrong.')).toBe('Something went wrong.')
    expect(sentence(' try again? ')).toBe('Try again?')
    expect(sentence('')).toBe('')
  })
})
