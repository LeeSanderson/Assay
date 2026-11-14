import { expect, it } from '@jest/globals'
import type { Order } from './orders.ts'
import { formatCents, receipt } from './receipt.ts'

const ORDER: Order = {
  id: 'order-7',
  lines: [
    { sku: 'apple', name: 'Apple', unitPrice: 250, quantity: 2 },
    { sku: 'pear', name: 'Pear', unitPrice: 1000, quantity: 1 },
  ],
  subtotal: 1500,
  discounts: [],
  total: 1500,
  status: 'paid',
  paymentId: 'payment-7',
  placedOn: '2026-03-10',
}

it('formats cents as units and hundredths', () => {
  expect([formatCents(1234), formatCents(5), formatCents(0), formatCents(-150)]).toEqual([
    '12.34',
    '0.05',
    '0.00',
    '-1.50',
  ])
})

it('prints the lines, the subtotal and the total of an order', () => {
  expect(receipt(ORDER)).toBe(
    [
      'Order order-7 (2026-03-10)',
      '2 x Apple                           5.00',
      '1 x Pear                           10.00',
      'Subtotal                           15.00',
      'Total                              15.00',
      '',
    ].join('\n')
  )
})

it('prints each discount as a negative amount and the status of an order that is not paid', () => {
  const order: Order = {
    ...ORDER,
    discounts: [{ promotionId: 'ten', amount: 150 }],
    total: 1350,
    status: 'cancelled',
  }
  expect(receipt(order)).toBe(
    [
      'Order order-7 (2026-03-10)',
      '2 x Apple                           5.00',
      '1 x Pear                           10.00',
      'Subtotal                           15.00',
      'Discount ten                       -1.50',
      'Total                              13.50',
      'Status: cancelled',
      '',
    ].join('\n')
  )
})
