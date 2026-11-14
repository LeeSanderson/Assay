// Returns: a customer sends back units of a shipped order. Each return issues
// a credit note, which refunds what the customer paid for those units: their
// price less their share of each discount of the order.

import type { Clock, IdSource } from './clock.ts'
import type { Inventory } from './inventory.ts'
import { returnedUnits } from './orders.ts'
import type { Order, OrderRepository } from './orders.ts'
import type { PaymentGateway } from './payments.ts'
import type { Discount } from './promotions.ts'

export type ItemCondition = 'resellable' | 'damaged'

export interface ReturnLine {
  sku: string
  quantity: number
  condition: ItemCondition
}

export interface CreditLine {
  sku: string
  quantity: number
  amount: number
}

export interface CreditNote {
  id: string
  orderId: string
  lines: CreditLine[]
  discounts: Discount[]
  amount: number
  issuedOn: string
}

export interface ReturnsDeps {
  orders: OrderRepository
  inventory: Inventory
  payments: PaymentGateway
  clock: Clock
  ids: IdSource
}

const RETURN_DAYS = 30
const CONDITIONS: readonly string[] = ['resellable', 'damaged']

export class Returns {
  constructor(private readonly deps: ReturnsDeps) {}

  // Returns the units of the lines, or none of them, and issues their credit note.
  public returnItems(orderId: string, lines: ReturnLine[]): CreditNote {
    const order = this.order(orderId)
    if (order.status !== 'shipped') {
      throw new Error(`order ${orderId} is ${order.status}`)
    }
    const today = this.deps.clock.today()
    if (today > addDays(order.placedOn, RETURN_DAYS)) {
      throw new Error(`the return window of order ${orderId} has closed`)
    }
    if (lines.length === 0) {
      throw new Error('nothing to return')
    }
    const seen = new Set<string>()
    for (const line of lines) {
      const ordered = order.lines.find((l) => l.sku === line.sku)
      if (ordered === undefined) {
        throw new Error(`SKU ${line.sku} is not in order ${orderId}`)
      }
      if (seen.has(line.sku)) {
        throw new Error(`SKU ${line.sku} is in more than one line`)
      }
      seen.add(line.sku)
      if (line.quantity < 1) {
        throw new Error('quantity must be at least 1')
      }
      if (!CONDITIONS.includes(line.condition)) {
        throw new Error(`unknown condition ${line.condition}`)
      }
      const left = ordered.quantity - returnedUnits(order, line.sku)
      if (line.quantity > left) {
        throw new Error(`${line.sku} has ${left} left to return`)
      }
    }

    const note = this.creditNote(order, lines)
    if (note.amount > 0 && order.paymentId !== '') {
      this.deps.payments.refundPart(order.paymentId, note.amount)
    }
    for (const line of lines) {
      if (line.condition === 'resellable') {
        this.deps.inventory.restock(line.sku, line.quantity)
      }
    }
    const creditNotes = [...(order.creditNotes ?? []), note]
    const updated: Order = { ...order, creditNotes }
    if (order.lines.every((l) => l.quantity === returnedUnits(updated, l.sku))) {
      updated.status = 'returned'
    }
    this.deps.orders.save(updated)
    return note
  }

  // The credit notes of the order, in the order that they were issued.
  public creditNotes(orderId: string): CreditNote[] {
    return this.order(orderId).creditNotes ?? []
  }

  private order(id: string): Order {
    const order = this.deps.orders.get(id)
    if (order === undefined) {
      throw new Error(`unknown order ${id}`)
    }
    return order
  }

  // Each discount on a line is reversed in proportion to the units returned:
  // after `r` of `q` units in all, floor(part * r / q) of it.
  private creditNote(order: Order, lines: ReturnLine[]): CreditNote {
    const reversed = new Map<string, number>()
    const credit = lines.map((line) => {
      const ordered = order.lines.find((l) => l.sku === line.sku)!
      const before = returnedUnits(order, line.sku)
      const after = before + line.quantity
      let amount = ordered.unitPrice * line.quantity
      for (const part of ordered.discounts ?? []) {
        const share =
          Math.floor((part.amount * after) / ordered.quantity) -
          Math.floor((part.amount * before) / ordered.quantity)
        amount -= share
        reversed.set(part.promotionId, (reversed.get(part.promotionId) ?? 0) + share)
      }
      return { sku: line.sku, quantity: line.quantity, amount }
    })
    const discounts = order.discounts
      .map((d) => ({ promotionId: d.promotionId, amount: reversed.get(d.promotionId) ?? 0 }))
      .filter((d) => d.amount > 0)
    return {
      id: this.deps.ids.next('credit'),
      orderId: order.id,
      lines: credit,
      discounts,
      amount: credit.reduce((sum, line) => sum + line.amount, 0),
      issuedOn: this.deps.clock.today(),
    }
  }
}

function addDays(date: string, days: number): string {
  const time = Date.parse(`${date}T00:00:00Z`) + days * 24 * 60 * 60 * 1000
  return new Date(time).toISOString().slice(0, 10)
}
