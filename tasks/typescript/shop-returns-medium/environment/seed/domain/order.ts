// Orders: what the checkout placed. A placed order is paid; it can then ship
// or be cancelled, once. The lines and the amounts of an order stay as they
// were placed.

import { wrongState } from './errors.ts'
import type { IsoDate } from './dates.ts'
import { sum, times } from './money.ts'
import type { Cents } from './money.ts'
import type { Discount } from './promotion.ts'

export type OrderStatus = 'paid' | 'shipped' | 'cancelled'

export interface OrderLine {
  sku: string
  name: string
  unitPrice: Cents
  quantity: number
}

export interface Order {
  id: string
  lines: OrderLine[]
  subtotal: Cents
  discounts: Discount[]
  total: Cents
  status: OrderStatus
  paymentId: string // '' when the order cost nothing, and so had no payment
  placedOn: IsoDate
  customerId?: string // absent when a guest placed the order
}

export interface SkuSales {
  sku: string
  quantity: number
}

export interface OrderRepository {
  get(id: string): Order | undefined
  save(order: Order): void
  list(): Order[] // in the order that they were first saved
}

// The statuses that an order can move to from each status. A status that is
// not here moves nowhere.
const NEXT: Partial<Record<OrderStatus, readonly OrderStatus[]>> = {
  paid: ['shipped', 'cancelled'],
}

// The order with its new status, or the error `order <id> is <status>` when
// its status does not allow the move.
export function moveTo(order: Order, status: OrderStatus): Order {
  if (!(NEXT[order.status] ?? []).includes(status)) {
    throw wrongState('order', order.id, order.status)
  }
  return { ...order, status }
}

// Checks that the order has the status: `order <id> is <status>` when not.
export function checkStatus(order: Order, status: OrderStatus): void {
  if (order.status !== status) {
    throw wrongState('order', order.id, order.status)
  }
}

// An order counts in the sales unless it was cancelled.
export function counts(order: Order): boolean {
  return order.status !== 'cancelled'
}

export function lineTotal(line: OrderLine): Cents {
  return times(line.unitPrice, line.quantity)
}

export function unitsOf(order: Order): number {
  return order.lines.reduce((total, line) => total + line.quantity, 0)
}

export function discountTotal(order: Order): Cents {
  return sum(order.discounts.map((discount) => discount.amount))
}

// What to look for in the orders. Each field that is given must match; an
// empty filter matches every order.
export interface OrderFilter {
  status?: OrderStatus
  customerId?: string
  sku?: string // the order has a line of the SKU
  from?: IsoDate // placed on or after
  to?: IsoDate // placed on or before
  minTotal?: Cents
}

export function matches(order: Order, filter: OrderFilter): boolean {
  if (filter.status !== undefined && order.status !== filter.status) return false
  if (filter.customerId !== undefined && order.customerId !== filter.customerId) return false
  if (filter.sku !== undefined && !order.lines.some((line) => line.sku === filter.sku)) {
    return false
  }
  if (filter.from !== undefined && order.placedOn < filter.from) return false
  if (filter.to !== undefined && order.placedOn > filter.to) return false
  if (filter.minTotal !== undefined && order.total < filter.minTotal) return false
  return true
}

// The quantity of a SKU over the lines of the order.
export function quantityOf(order: Order, sku: string): number {
  return order.lines
    .filter((line) => line.sku === sku)
    .reduce((total, line) => total + line.quantity, 0)
}

export function copyOrder(order: Order): Order {
  return {
    ...order,
    lines: order.lines.map((line) => ({ ...line })),
    discounts: order.discounts.map((discount) => ({ ...discount })),
  }
}
