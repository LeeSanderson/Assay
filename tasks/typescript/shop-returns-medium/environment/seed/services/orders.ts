// Orders: what happens to an order after the checkout placed it. A paid
// order can ship or be cancelled, once.

import { checkPeriod, daysBetween } from '../domain/dates.ts'
import type { IsoDate } from '../domain/dates.ts'
import { notFound } from '../domain/errors.ts'
import { compareText } from '../domain/ids.ts'
import { sum } from '../domain/money.ts'
import type { Cents } from '../domain/money.ts'
import { checkStatus, counts, matches, moveTo } from '../domain/order.ts'
import type {
  Order,
  OrderFilter,
  OrderRepository,
  OrderStatus,
  SkuSales,
} from '../domain/order.ts'
import type { PaymentGateway } from '../domain/payment.ts'
import type { Inventory } from './inventory.ts'

export class Orders {
  constructor(
    private readonly repository: OrderRepository,
    private readonly inventory: Inventory,
    private readonly payments: PaymentGateway
  ) {}

  public order(id: string): Order {
    const order = this.repository.get(id)
    if (order === undefined) {
      throw notFound('order', id)
    }
    return order
  }

  // Every order, in the order that they were placed.
  public all(): Order[] {
    return this.repository.list()
  }

  public withStatus(status: OrderStatus): Order[] {
    return this.repository.list().filter((order) => order.status === status)
  }

  // The orders of a customer, in the order that they were placed.
  public forCustomer(customerId: string): Order[] {
    return this.repository.list().filter((order) => order.customerId === customerId)
  }

  // The orders placed in the period, both dates included.
  public placedBetween(from: IsoDate, to: IsoDate): Order[] {
    checkPeriod(from, to)
    return this.repository
      .list()
      .filter((order) => order.placedOn >= from && order.placedOn <= to)
  }

  // The orders that match the filter, in the order that they were placed.
  public search(filter: OrderFilter): Order[] {
    return this.repository.list().filter((order) => matches(order, filter))
  }

  // The paid orders placed more than `days` days before the date, which
  // have waited too long to ship.
  public waitingSince(date: IsoDate, days: number): Order[] {
    return this.withStatus('paid').filter((order) => daysBetween(order.placedOn, date) > days)
  }

  // Ships a paid order: its reserved stock leaves the inventory.
  public ship(id: string): void {
    const order = this.order(id)
    const shipped = moveTo(order, 'shipped')
    this.inventory.commit(id)
    this.repository.save(shipped)
  }

  // Cancels a paid order: its stock is released and its payment, if it has
  // one, refunded.
  public cancel(id: string): void {
    const order = this.order(id)
    const cancelled = moveTo(order, 'cancelled')
    if (order.paymentId !== '') {
      this.payments.refund(order.paymentId)
    }
    this.inventory.release(id)
    this.repository.save(cancelled)
  }

  // Checks that an order is paid, and so can still change.
  public checkPaid(id: string): Order {
    const order = this.order(id)
    checkStatus(order, 'paid')
    return order
  }

  // The sum of the totals of the orders that are not cancelled.
  public revenue(): Cents {
    return sum(
      this.repository
        .list()
        .filter(counts)
        .map((order) => order.total)
    )
  }

  // The revenue per order that is not cancelled, rounded down; 0 with none.
  public averageOrderValue(): Cents {
    const counted = this.repository.list().filter(counts)
    return counted.length === 0 ? 0 : Math.floor(this.revenue() / counted.length)
  }

  // The units sold of each SKU over the orders that are not cancelled, most
  // first, and in SKU order on a tie; at most `limit` of them.
  public bestSellers(limit: number): SkuSales[] {
    const units = new Map<string, number>()
    for (const order of this.repository.list().filter(counts)) {
      for (const line of order.lines) {
        units.set(line.sku, (units.get(line.sku) ?? 0) + line.quantity)
      }
    }
    return [...units.entries()]
      .map(([sku, quantity]) => ({ sku, quantity }))
      .sort((a, b) => b.quantity - a.quantity || compareText(a.sku, b.sku))
      .slice(0, limit)
  }
}
