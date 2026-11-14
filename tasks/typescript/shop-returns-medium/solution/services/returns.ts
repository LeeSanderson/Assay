// Returns: a customer sends back units of a shipped order, in one return or
// in several. Each return puts the resellable units back into stock, issues
// a credit note and refunds its amount to the payment of the order. A return
// that fails changes nothing: it checks everything before its first write.

import type { Clock } from '../domain/dates.ts'
import { notFound } from '../domain/errors.ts'
import { PREFIX } from '../domain/ids.ts'
import type { IdSource } from '../domain/ids.ts'
import type { Order, OrderRepository } from '../domain/order.ts'
import type { PaymentGateway } from '../domain/payment.ts'
import { checkReturn, creditFor, withCreditNote } from '../domain/return.ts'
import type { CreditNote, ReturnLine } from '../domain/return.ts'
import type { Inventory } from './inventory.ts'

export interface ReturnsDeps {
  orders: OrderRepository
  inventory: Inventory
  payments: PaymentGateway
  clock: Clock
  ids: IdSource
}

export class Returns {
  constructor(private readonly deps: ReturnsDeps) {}

  // Returns the units of the lines from the order, or none of them, and gives
  // the credit note of the return.
  public returnItems(orderId: string, lines: ReturnLine[]): CreditNote {
    const order = this.order(orderId)
    const today = this.deps.clock.today()
    checkReturn(order, lines, today)
    const note: CreditNote = {
      id: this.deps.ids.next(PREFIX.credit),
      orderId: order.id,
      ...creditFor(order, lines),
      issuedOn: today,
    }
    if (note.amount > 0 && order.paymentId !== '') {
      this.deps.payments.refundPart(order.paymentId, note.amount)
    }
    for (const line of lines) {
      if (line.condition === 'resellable') {
        this.deps.inventory.restock(line.sku, line.quantity)
      }
    }
    this.deps.orders.save(withCreditNote(order, note))
    return note
  }

  // The credit notes of the order, in the order that they were issued.
  public creditNotes(orderId: string): CreditNote[] {
    return this.order(orderId).creditNotes ?? []
  }

  private order(id: string): Order {
    const order = this.deps.orders.get(id)
    if (order === undefined) {
      throw notFound('order', id)
    }
    return order
  }
}
