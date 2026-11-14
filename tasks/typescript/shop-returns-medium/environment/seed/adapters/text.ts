// The documents of the shop as plain text: the receipt of an order, an
// invoice, a shipping label, a packing slip, the statement of an account,
// and the event log as JSON lines. Each row puts its label on the left and its
// amount on the right of a fixed width; amounts show as units and hundredths.

import { formatAddress } from '../domain/customer.ts'
import type { Statement } from '../domain/customer.ts'
import { check } from '../domain/errors.ts'
import type { ShopEvent } from '../domain/event.ts'
import type { Invoice } from '../domain/invoice.ts'
import { formatCents } from '../domain/money.ts'
import type { Cents } from '../domain/money.ts'
import { lineTotal } from '../domain/order.ts'
import type { Order } from '../domain/order.ts'
import type { Shipment } from '../domain/shipment.ts'

const WIDTH = 40

// One line per order line, then the subtotal, one line per discount, and the
// total. A discount shows as a negative amount.
export function receipt(order: Order): string {
  const rows = [`Order ${order.id} (${order.placedOn})`]
  for (const line of order.lines) {
    rows.push(row(`${line.quantity} x ${line.name}`, lineTotal(line)))
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

// The heading, one line per invoice line, the subtotal, the discounts, the
// total, and the tax that the total includes, with its rate.
export function invoiceText(invoice: Invoice): string {
  const rows = [
    `Invoice ${invoice.number} (${invoice.issuedOn})`,
    `Order ${invoice.orderId}` +
      (invoice.customerId === undefined ? '' : ` for ${invoice.customerId}`),
  ]
  for (const line of invoice.lines) {
    rows.push(
      row(`${line.quantity} x ${line.description} @ ${formatCents(line.unitPrice)}`, line.amount)
    )
  }
  rows.push(row('Subtotal', invoice.subtotal))
  for (const discount of invoice.discounts) {
    rows.push(row(`Discount ${discount.promotionId}`, -discount.amount))
  }
  rows.push(row('Total', invoice.total))
  rows.push(row(`Tax included at ${formatRate(invoice.taxRate)}`, invoice.tax))
  return rows.join('\n') + '\n'
}

// The label of a shipment: its id, its order, the address and the units.
export function shippingLabel(shipment: Shipment): string {
  return [
    `Shipment ${shipment.id} for order ${shipment.orderId}`,
    `To: ${formatAddress(shipment.address)}`,
    `Units: ${shipment.units} in ${shipment.parcels} parcel${shipment.parcels === 1 ? '' : 's'}`,
    `Zone: ${shipment.zone}`,
  ].join('\n') + '\n'
}

// The packing slip of an order: what goes in the box, with no prices.
export function packingSlip(order: Order, shipment: Shipment): string {
  const rows = [`Packing slip for order ${order.id}`, `Ship to: ${formatAddress(shipment.address)}`]
  for (const line of order.lines) {
    rows.push(`[ ] ${String(line.quantity).padStart(3)} x ${line.sku} ${line.name}`)
  }
  rows.push(`Units: ${shipment.units}`)
  return rows.join('\n') + '\n'
}

// The statement of an account: one row for each entry, with its date, and
// the balances. Store credit shows as an amount; points as a count.
export function statementText(statement: Statement): string {
  const rows = [`Statement of ${statement.customerId}`]
  for (const entry of statement.entries) {
    const amount =
      entry.kind === 'credit' ? formatCents(entry.amount) : `${entry.amount} points`
    const label = `${entry.on} ${entry.reason}`
    rows.push(label + ' '.repeat(Math.max(1, WIDTH - label.length - amount.length)) + amount)
  }
  rows.push(row('Store credit', statement.credit))
  rows.push(`Points: ${statement.points}`)
  return rows.join('\n') + '\n'
}

// The events, one JSON object a line, for another system to read.
export function eventsAsJsonLines(events: readonly ShopEvent[]): string {
  return events.map((event) => JSON.stringify(event)).join('\n') + (events.length ? '\n' : '')
}

// Reads events back from JSON lines; a blank line is skipped.
export function eventsFromJsonLines(text: string): ShopEvent[] {
  return text
    .split('\n')
    .filter((line) => line.trim() !== '')
    .map((line, index) => {
      const event = JSON.parse(line) as ShopEvent
      check(
        typeof event.id === 'string' && typeof event.type === 'string',
        `line ${index + 1} is not an event`
      )
      return event
    })
}

// A rate in basis points as a percentage: 2000 is `20%`, 550 is `5.5%`.
export function formatRate(rate: number): string {
  const whole = Math.floor(rate / 100)
  const rest = rate % 100
  if (rest === 0) return `${whole}%`
  return `${whole}.${String(rest).padStart(2, '0').replace(/0$/, '')}%`
}

function row(label: string, cents: Cents): string {
  const amount = formatCents(cents)
  const gap = Math.max(1, WIDTH - label.length - amount.length)
  return label + ' '.repeat(gap) + amount
}
