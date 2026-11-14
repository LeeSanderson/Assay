// The receipt of an order, as plain text. Amounts are whole cents, shown as
// units and hundredths: 1234 cents is `12.34`.

import type { Order } from './orders.ts'

const WIDTH = 40

export function formatCents(cents: number): string {
  const sign = cents < 0 ? '-' : ''
  const whole = Math.floor(Math.abs(cents) / 100)
  const hundredths = Math.abs(cents) % 100
  return `${sign}${whole}.${String(hundredths).padStart(2, '0')}`
}

// One line per order line, then the subtotal, one line per discount, and the
// total. A discount shows as a negative amount.
export function receipt(order: Order): string {
  const rows = [`Order ${order.id} (${order.placedOn})`]
  for (const line of order.lines) {
    rows.push(row(`${line.quantity} x ${line.name}`, line.unitPrice * line.quantity))
  }
  rows.push(row('Subtotal', order.subtotal))
  for (const discount of order.discounts) {
    rows.push(row(`Discount ${discount.promotionId}`, -discount.amount))
  }
  rows.push(row('Total', order.total))
  if (order.status !== 'paid') {
    rows.push(`Status: ${order.status}`)
  }
  return rows.join('\n') + '\n'
}

function row(label: string, cents: number): string {
  const amount = formatCents(cents)
  const gap = Math.max(1, WIDTH - label.length - amount.length)
  return label + ' '.repeat(gap) + amount
}
