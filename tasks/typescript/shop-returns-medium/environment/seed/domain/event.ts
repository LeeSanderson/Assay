// Events: the log of what happened in the shop, oldest first. The services do
// not write events. The event log learns of each change from the stores: a
// recording store (adapters/recording.ts) compares each record that it saves
// with the record that it held, and these rules turn the change into an
// event, or into none.

import type { IsoDate } from './dates.ts'
import type { Customer } from './customer.ts'
import type { Invoice } from './invoice.ts'
import type { Order } from './order.ts'
import type { Shipment } from './shipment.ts'

// The data of an event: a few plain values, never a whole record.
export type EventData = Record<string, string | number>

export interface ShopEvent {
  id: string
  type: string // `<record>-<what happened>`, as `order-placed`
  subject: string // the id of the record
  on: IsoDate
  data: EventData
}

export interface EventStore {
  append(event: ShopEvent): void
  list(): ShopEvent[] // oldest first
}

// What a rule gives for a change: the type, the subject and the data.
export interface Change {
  type: string
  subject: string
  data: EventData
}

// Where a recording store sends the changes that it sees: the event log.
export interface ChangeSink {
  record(change: Change): void
}

// A new order is placed; a change of status gives `order-<status>`.
export function orderChange(before: Order | undefined, after: Order): Change | undefined {
  const data: EventData = { total: after.total }
  if (after.customerId !== undefined) data.customerId = after.customerId
  if (before === undefined) {
    return { type: 'order-placed', subject: after.id, data: { ...data, lines: after.lines.length } }
  }
  if (before.status !== after.status) {
    return { type: `order-${after.status}`, subject: after.id, data }
  }
  return undefined
}

// A new shipment is created; a change of status gives `shipment-<status>`.
export function shipmentChange(
  before: Shipment | undefined,
  after: Shipment
): Change | undefined {
  const data: EventData = { orderId: after.orderId }
  if (before === undefined) {
    return { type: 'shipment-created', subject: after.id, data: { ...data, cost: after.cost } }
  }
  if (before.status !== after.status) {
    if (after.trackingCode !== undefined) data.trackingCode = after.trackingCode
    return { type: `shipment-${after.status}`, subject: after.id, data }
  }
  return undefined
}

// An invoice is issued once, and never changes.
export function invoiceChange(before: Invoice | undefined, after: Invoice): Change | undefined {
  if (before !== undefined) return undefined
  return {
    type: 'invoice-issued',
    subject: after.id,
    data: { orderId: after.orderId, number: after.number, total: after.total },
  }
}

// A new customer registers; a change of name, email or address updates it;
// and a customer can close its account.
export function customerChange(
  before: Customer | undefined,
  after: Customer
): Change | undefined {
  if (before === undefined) {
    return { type: 'customer-registered', subject: after.id, data: { email: after.email } }
  }
  if (before.closedOn === undefined && after.closedOn !== undefined) {
    return { type: 'customer-closed', subject: after.id, data: { email: after.email } }
  }
  const changed: string[] = []
  if (before.name !== after.name) changed.push('name')
  if (before.email !== after.email) changed.push('email')
  if (JSON.stringify(before.address) !== JSON.stringify(after.address)) changed.push('address')
  if (changed.length === 0) return undefined
  return { type: 'customer-updated', subject: after.id, data: { fields: changed.join(',') } }
}

export function copyEvent(event: ShopEvent): ShopEvent {
  return { ...event, data: { ...event.data } }
}
