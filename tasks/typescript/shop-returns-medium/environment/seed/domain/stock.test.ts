import { describe, expect, it } from '@jest/globals'
import { availableOf, mergeLines, runningBalance } from './stock.ts'

describe('stock', () => {
  it('makes available what is on hand and not reserved', () => {
    expect(availableOf({ sku: 'apple', onHand: 10, reserved: 3 })).toBe(7)
  })

  it('merges the lines of one SKU, in the order that each SKU first appears', () => {
    expect(
      mergeLines([
        { sku: 'pear', quantity: 1 },
        { sku: 'apple', quantity: 2 },
        { sku: 'pear', quantity: 3 },
      ])
    ).toEqual([
      { sku: 'pear', quantity: 4 },
      { sku: 'apple', quantity: 2 },
    ])
  })

  it('keeps a running balance of the movements', () => {
    expect(
      runningBalance([
        { sku: 'apple', quantity: 10, reason: 'received' },
        { sku: 'apple', quantity: -4, reason: 'shipped' },
        { sku: 'apple', quantity: -1, reason: 'counted' },
      ])
    ).toEqual([
      { quantity: 10, reason: 'received', balance: 10 },
      { quantity: -4, reason: 'shipped', balance: 6 },
      { quantity: -1, reason: 'counted', balance: 5 },
    ])
  })
})
