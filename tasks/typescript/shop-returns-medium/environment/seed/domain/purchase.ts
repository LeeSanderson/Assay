// Purchasing: the shop buys stock from its suppliers with purchase orders. A
// purchase order is drafted, then sent to the supplier, and its lines are
// received into the inventory, in one delivery or in several. A purchase
// order is received when every unit of every line has come in. What the
// shop pays a supplier (the unit cost) is not what it charges customers.

import { check, checkNotEmpty, checkQuantity, wrongState } from './errors.ts'
import type { IsoDate } from './dates.ts'
import { checkCents, sum, times } from './money.ts'
import type { Cents } from './money.ts'

export interface Supplier {
  id: string
  name: string
  email: string
  leadTimeDays: number // the days from sending an order to its delivery
}

export interface SupplierRepository {
  get(id: string): Supplier | undefined
  save(supplier: Supplier): void
  list(): Supplier[]
}

export type PurchaseStatus = 'draft' | 'sent' | 'received' | 'cancelled'

export interface PurchaseLine {
  sku: string
  quantity: number
  unitCost: Cents
  received: number
}

export interface PurchaseOrder {
  id: string
  supplierId: string
  lines: PurchaseLine[]
  status: PurchaseStatus
  createdOn: IsoDate
  sentOn?: IsoDate
  expectedOn?: IsoDate // the sent date plus the lead time of the supplier
}

export interface PurchaseRepository {
  get(id: string): PurchaseOrder | undefined
  save(order: PurchaseOrder): void
  list(): PurchaseOrder[] // in the order that they were drafted
}

export function checkSupplier(name: string, email: string, leadTimeDays: number): void {
  checkNotEmpty(name, 'name')
  checkNotEmpty(email, 'email')
  check(
    Number.isInteger(leadTimeDays) && leadTimeDays >= 0,
    'lead time must be a whole number of days'
  )
}

export function checkPurchaseLine(sku: string, quantity: number, unitCost: Cents): void {
  checkNotEmpty(sku, 'SKU')
  checkQuantity(quantity)
  checkCents(unitCost, 'unit cost', 1)
}

// Checks that the purchase order has the status: `purchase <id> is <status>`
// when not.
export function checkPurchaseStatus(order: PurchaseOrder, status: PurchaseStatus): void {
  if (order.status !== status) {
    throw wrongState('purchase', order.id, order.status)
  }
}

// The units of a line that have not come in yet.
export function outstanding(line: PurchaseLine): number {
  return line.quantity - line.received
}

export function isReceived(order: PurchaseOrder): boolean {
  return order.lines.every((line) => outstanding(line) === 0)
}

// What the purchase order costs the shop, for every unit ordered.
export function costOfPurchase(order: PurchaseOrder): Cents {
  return sum(order.lines.map((line) => times(line.unitCost, line.quantity)))
}

export function copyPurchase(order: PurchaseOrder): PurchaseOrder {
  return { ...order, lines: order.lines.map((line) => ({ ...line })) }
}

export function copySupplier(supplier: Supplier): Supplier {
  return { ...supplier }
}
