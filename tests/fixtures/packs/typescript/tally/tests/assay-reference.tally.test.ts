import { describe, expect, it } from '@jest/globals'
import { Tally } from './tally.ts'

describe('top', () => {
  it('gives the names with the highest counts first', () => {
    const tally = new Tally()
    tally.add('apple', 2)
    tally.add('pear', 5)
    tally.add('plum', 1)
    expect(tally.top(2)).toEqual(['pear', 'apple'])
  })

  it('breaks a tie by name', () => {
    const tally = new Tally()
    tally.add('pear', 3)
    tally.add('apple', 3)
    expect(tally.top(2)).toEqual(['apple', 'pear'])
  })

  it('gives every name when k is larger than the tally', () => {
    const tally = new Tally()
    tally.add('apple')
    expect(tally.top(5)).toEqual(['apple'])
  })
})
