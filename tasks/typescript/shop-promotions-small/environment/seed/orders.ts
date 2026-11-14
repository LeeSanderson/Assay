// Orders: what the checkout placed, and what happens to an order after it.
// A placed order is paid; it can then ship or be cancelled, once.

import type { Inventory } from './inventory.ts'
import type { PaymentGateway } from './payments.ts'
import type { Discount } from './promotions.ts'

export type OrderStatus = 'paid' | 'shipped' | 'cancelled'

export interface OrderLine {
  sku: string
  name: string
  unitPrice: number
  quantity: number
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

  // Cancels a paid order: its stock is released and its payment refunded.
  public cancel(id: string): void {
    const order = this.paidOrder(id)
    this.payments.refund(order.paymentId)
    this.inventory.release(id)
    this.repository.save({ ...order, status: 'cancelled' })
  }

  // The sum of the totals of the orders that are not cancelled.
  public revenue(): number {
    return this.repository
      .list()
      .filter((order) => order.status !== 'cancelled')
      .reduce((sum, order) => sum + order.total, 0)
  }

  // The units sold of each SKU over the orders that are not cancelled, most
  // first, and in SKU order on a tie; at most `limit` of them.
  public bestSellers(limit: number): SkuSales[] {
    const units = new Map<string, number>()
    for (const order of this.repository.list()) {
      if (order.status === 'cancelled') {
        continue
      }
      for (const line of order.lines) {
        units.set(line.sku, (units.get(line.sku) ?? 0) + line.quantity)
      }
    }
    return [...units.entries()]
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

function copy(order: Order): Order {
  return {
    ...order,
    lines: order.lines.map((line) => ({ ...line })),
    discounts: order.discounts.map((discount) => ({ ...discount })),
  }
}
