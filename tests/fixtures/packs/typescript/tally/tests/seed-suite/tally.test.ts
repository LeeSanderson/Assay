import { describe, expect, it } from '@jest/globals'
import { Tally } from './tally.ts'

describe('Tally', () => {
  it('counts nothing at first', () => {
    expect(new Tally().count('apple')).toBe(0)
  })

  it('adds to a count', () => {
    const tally = new Tally()
    tally.add('apple')
    tally.add('apple', 2)
    expect(tally.count('apple')).toBe(3)
  })

  it('lists the names in order', () => {
    const tally = new Tally()
    tally.add('pear')
    tally.add('apple')
    expect(tally.names()).toEqual(['apple', 'pear'])
  })
})
