import { describe, expect, it } from '@jest/globals'
import { compareIds, compareText, idNumber, PREFIX } from './ids.ts'

describe('identifiers', () => {
  it('reads the number at the end of an id', () => {
    expect(idNumber('order-12')).toBe(12)
    expect(idNumber('apple')).toBe(0)
  })

  it('orders ids of one kind by their number', () => {
    expect(['order-10', 'order-9', 'order-1'].sort(compareIds)).toEqual([
      'order-1',
      'order-9',
      'order-10',
    ])
    expect(['payment-1', 'order-2'].sort(compareIds)).toEqual(['order-2', 'payment-1'])
  })

  it('orders texts by their code units', () => {
    expect(['pear', 'Apple', 'apple'].sort(compareText)).toEqual(['Apple', 'apple', 'pear'])
  })

  it('names a prefix for each kind of record', () => {
    expect([PREFIX.order, PREFIX.payment, PREFIX.shipment]).toEqual([
      'order',
      'payment',
      'shipment',
    ])
  })
})
