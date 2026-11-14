// Orders: what the checkout placed, and what happens to an order after it.
// A placed order is paid; it can then ship or be cancelled, once. The units of
// a shipped order can be returned; when all of them are, the order is returned.

import type { Inventory } from './inventory.ts'
import type { PaymentGateway } from './payments.ts'
import type { Discount } from './promotions.ts'
import type { CreditNote } from './returns.ts'

export type OrderStatus = 'paid' | 'shipped' | 'cancelled' | 'returned'

export interface OrderLine {
  sku: string
  name: string
  unitPrice: number
  quantity: number
  discounts?: Discount[] // the part of each discount on this line; absent when none
}

export interface Order {
  id: string
  lines: OrderLine[]
  subtotal: number
  discounts: Discount[]
  total: number
  status: OrderStatus
  paymentId: string
  placedOn: string
  creditNotes?: CreditNote[] // the credit notes of its returns; absent when none
}

export interface SkuSales {
  sku: string
  quantity: number
}

export interface OrderRepository {
  get(id: string): Order | undefined
  save(order: Order): void
  list(): Order[]
}

export class InMemoryOrderRepository implements OrderRepository {
  private readonly orders = new Map<string, Order>()

  get(id: string): Order | undefined {
    const order = this.orders.get(id)
    return order === undefined ? undefined : copy(order)
  }

  save(order: Order): void {
    this.orders.set(order.id, copy(order))
  }

  // The orders in the order that they were first saved.
  list(): Order[] {
    return [...this.orders.values()].map(copy)
  }
}

export class Orders {
  constructor(
    private readonly repository: OrderRepository,
    private readonly inventory: Inventory,
    private readonly payments: PaymentGateway
  ) {}

  public order(id: string): Order {
    const order = this.repository.get(id)
    if (order === undefined) {
      throw new Error(`unknown order ${id}`)
    }
    return order
  }

  public withStatus(status: OrderStatus): Order[] {
    return this.repository.list().filter((order) => order.status === status)
  }

  // Ships a paid order: its reserved stock leaves the inventory.
  public ship(id: string): void {
    const order = this.paidOrder(id)
    this.inventory.commit(id)
    this.repository.save({ ...order, status: 'shipped' })
  }

  // Cancels a paid order: its stock is released and its payment, if it has
  // one, refunded.
  public cancel(id: string): void {
    const order = this.paidOrder(id)
    if (order.paymentId !== '') {
      this.payments.refund(order.paymentId)
    }
    this.inventory.release(id)
    this.repository.save({ ...order, status: 'cancelled' })
  }

  // The sum of the totals of the orders that are not cancelled, less what
  // their credit notes refunded.
  public revenue(): number {
    return this.repository
      .list()
      .filter((order) => order.status !== 'cancelled')
      .reduce((sum, order) => sum + order.total - refunded(order), 0)
  }

  // The units sold and not returned of each SKU over the orders that are not
  // cancelled, most first, and in SKU order on a tie; at most `limit` of them.
  public bestSellers(limit: number): SkuSales[] {
    const units = new Map<string, number>()
    for (const order of this.repository.list()) {
      if (order.status === 'cancelled') {
        continue
      }
      for (const line of order.lines) {
        const kept = line.quantity - returnedUnits(order, line.sku)
        units.set(line.sku, (units.get(line.sku) ?? 0) + kept)
      }
    }
    return [...units.entries()]
      .filter(([, quantity]) => quantity > 0)
      .map(([sku, quantity]) => ({ sku, quantity }))
      .sort((a, b) => b.quantity - a.quantity || (a.sku < b.sku ? -1 : a.sku > b.sku ? 1 : 0))
      .slice(0, limit)
  }

  private paidOrder(id: string): Order {
    const order = this.order(id)
    if (order.status !== 'paid') {
      throw new Error(`order ${id} is ${order.status}`)
    }
    return order
  }
}

// The units of the SKU that the credit notes of the order have returned.
export function returnedUnits(order: Order, sku: string): number {
  return (order.creditNotes ?? [])
    .flatMap((note) => note.lines)
    .filter((line) => line.sku === sku)
    .reduce((sum, line) => sum + line.quantity, 0)
}

function refunded(order: Order): number {
  return (order.creditNotes ?? []).reduce((sum, note) => sum + note.amount, 0)
}

function copy(order: Order): Order {
  const copied: Order = {
    ...order,
    lines: order.lines.map((line) =>
      line.discounts === undefined
        ? { ...line }
        : { ...line, discounts: line.discounts.map((d) => ({ ...d })) }
    ),
    discounts: order.discounts.map((discount) => ({ ...discount })),
  }
  if (order.creditNotes !== undefined) {
    copied.creditNotes = order.creditNotes.map((note) => ({
      ...note,
      lines: note.lines.map((line) => ({ ...line })),
      discounts: note.discounts.map((d) => ({ ...d })),
    }))
  }
  return copied
}
