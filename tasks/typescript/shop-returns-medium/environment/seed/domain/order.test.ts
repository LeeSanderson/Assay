import { describe, expect, it } from '@jest/globals'
import {
  copyOrder,
  counts,
  discountTotal,
  lineTotal,
  matches,
  moveTo,
  quantityOf,
  unitsOf,
} from './order.ts'
import type { Order } from './order.ts'

const ORDER: Order = {
  id: 'order-1',
  lines: [
    { sku: 'apple', name: 'Apple', unitPrice: 250, quantity: 2 },
    { sku: 'pear', name: 'Pear', unitPrice: 1000, quantity: 1 },
  ],
  subtotal: 1500,
  discounts: [
    { promotionId: 'ten', amount: 150 },
    { promotionId: 'off', amount: 50 },
  ],
  total: 1300,
  status: 'paid',
  paymentId: 'payment-1',
  placedOn: '2026-03-10',
  customerId: 'customer-1',
}

describe('the status of an order', () => {
  it('moves a paid order to shipped or cancelled', () => {
    expect(moveTo(ORDER, 'shipped').status).toBe('shipped')
    expect(moveTo(ORDER, 'cancelled').status).toBe('cancelled')
    expect(ORDER.status).toBe('paid')
  })

  it('moves a shipped or cancelled order nowhere', () => {
    const shipped = moveTo(ORDER, 'shipped')
    expect(() => moveTo(shipped, 'cancelled')).toThrow('order order-1 is shipped')
    const cancelled = moveTo(ORDER, 'cancelled')
    expect(() => moveTo(cancelled, 'shipped')).toThrow('order order-1 is cancelled')
  })

  it('counts an order in the sales unless it was cancelled', () => {
    expect(counts(ORDER)).toBe(true)
    expect(counts(moveTo(ORDER, 'shipped'))).toBe(true)
    expect(counts(moveTo(ORDER, 'cancelled'))).toBe(false)
  })
})

describe('the amounts of an order', () => {
  it('adds up its lines, its units and its discounts', () => {
    expect(ORDER.lines.map(lineTotal)).toEqual([500, 1000])
    expect(unitsOf(ORDER)).toBe(3)
    expect(discountTotal(ORDER)).toBe(200)
    expect(quantityOf(ORDER, 'apple')).toBe(2)
    expect(quantityOf(ORDER, 'kiwi')).toBe(0)
  })

  it('copies an order so that a change to the copy leaves it as it was', () => {
    const copy = copyOrder(ORDER)
    copy.lines[0].quantity = 9
    copy.discounts[0].amount = 1
    expect(ORDER.lines[0].quantity).toBe(2)
    expect(ORDER.discounts[0].amount).toBe(150)
  })
})

describe('order filters', () => {
  it('matches every order with an empty filter', () => {
    expect(matches(ORDER, {})).toBe(true)
  })

  it('matches each field that the filter gives', () => {
    expect(matches(ORDER, { status: 'paid', customerId: 'customer-1', sku: 'pear' })).toBe(true)
    expect(matches(ORDER, { sku: 'kiwi' })).toBe(false)
    expect(matches(ORDER, { customerId: 'customer-2' })).toBe(false)
    expect(matches(ORDER, { from: '2026-03-10', to: '2026-03-10' })).toBe(true)
    expect(matches(ORDER, { from: '2026-03-11' })).toBe(false)
    expect(matches(ORDER, { minTotal: 1300 })).toBe(true)
    expect(matches(ORDER, { minTotal: 1301 })).toBe(false)
  })
})
