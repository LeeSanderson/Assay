// Reports: figures over the orders, the stock and the shipments, worked out
// from the records as they are. Each figure counts the orders that are not
// cancelled, at their totals as placed. These are pure functions;
// services/reports.ts loads the records and calls them.

import type { Customer } from './customer.ts'
import { weekday, within } from './dates.ts'
import type { IsoDate } from './dates.ts'
import { compareText } from './ids.ts'
import { sum, times } from './money.ts'
import type { Cents } from './money.ts'
import { counts, discountTotal, unitsOf } from './order.ts'
import type { Order } from './order.ts'
import type { Product } from './product.ts'
import type { Shipment } from './shipment.ts'
import type { StockLevel } from './stock.ts'

export interface SalesSummary {
  from: IsoDate
  to: IsoDate
  orders: number
  units: number
  subtotal: Cents
  discounts: Cents
  revenue: Cents
  averageOrder: Cents // revenue / orders, rounded down; 0 with no orders
}

export interface DailySales {
  date: IsoDate
  orders: number
  revenue: Cents
}

export interface PromotionUsage {
  promotionId: string
  orders: number
  amount: Cents
}

export interface StockValue {
  sku: string
  onHand: number
  unitPrice: Cents
  value: Cents
}

export interface CustomerSales {
  customerId: string
  orders: number
  revenue: Cents
}

export interface ShippingCosts {
  shipments: number
  cost: Cents
  byZone: Record<string, Cents>
}

// The orders that count, placed in the period.
export function countedIn(orders: readonly Order[], from: IsoDate, to: IsoDate): Order[] {
  return orders.filter((order) => counts(order) && within(order.placedOn, from, to))
}

export function salesSummary(orders: readonly Order[], from: IsoDate, to: IsoDate): SalesSummary {
  const counted = countedIn(orders, from, to)
  const revenue = sum(counted.map((order) => order.total))
  return {
    from,
    to,
    orders: counted.length,
    units: counted.reduce((total, order) => total + unitsOf(order), 0),
    subtotal: sum(counted.map((order) => order.subtotal)),
    discounts: sum(counted.map(discountTotal)),
    revenue,
    averageOrder: counted.length === 0 ? 0 : Math.floor(revenue / counted.length),
  }
}

// One row for each day of the period with an order that counts, by date.
export function dailySales(orders: readonly Order[], from: IsoDate, to: IsoDate): DailySales[] {
  const days = new Map<IsoDate, DailySales>()
  for (const order of countedIn(orders, from, to)) {
    const day = days.get(order.placedOn) ?? { date: order.placedOn, orders: 0, revenue: 0 }
    day.orders += 1
    day.revenue += order.total
    days.set(order.placedOn, day)
  }
  return [...days.values()].sort((a, b) => compareText(a.date, b.date))
}

export interface WeekdaySales {
  weekday: string
  orders: number
  revenue: Cents
}

// The orders that count, placed in the period, by the day of the week, from
// Monday to Sunday. A day with no order is left out.
export function weekdaySales(orders: readonly Order[], from: IsoDate, to: IsoDate) {
  const rows = new Map<string, WeekdaySales>()
  for (const order of countedIn(orders, from, to)) {
    const day = weekday(order.placedOn)
    const row = rows.get(day) ?? { weekday: day, orders: 0, revenue: 0 }
    row.orders += 1
    row.revenue += order.total
    rows.set(day, row)
  }
  return WEEK.filter((day) => rows.has(day)).map((day) => rows.get(day) as WeekdaySales)
}

const WEEK = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

// What each promotion took off over the orders that count: the most first,
// and by promotion id on a tie.
export function promotionUsage(orders: readonly Order[]): PromotionUsage[] {
  const usage = new Map<string, PromotionUsage>()
  for (const order of orders.filter(counts)) {
    for (const discount of order.discounts) {
      const row = usage.get(discount.promotionId) ?? {
        promotionId: discount.promotionId,
        orders: 0,
        amount: 0,
      }
      row.orders += 1
      row.amount += discount.amount
      usage.set(discount.promotionId, row)
    }
  }
  return [...usage.values()].sort(
    (a, b) => b.amount - a.amount || compareText(a.promotionId, b.promotionId)
  )
}

// The value of the stock on hand of each product at its price, in SKU order.
// A product with no stock on hand is left out.
export function stockValues(products: readonly Product[], levels: readonly StockLevel[]) {
  const rows: StockValue[] = []
  for (const product of [...products].sort((a, b) => compareText(a.sku, b.sku))) {
    const onHand = levels.find((level) => level.sku === product.sku)?.onHand ?? 0
    if (onHand > 0) {
      rows.push({
        sku: product.sku,
        onHand,
        unitPrice: product.unitPrice,
        value: times(product.unitPrice, onHand),
      })
    }
  }
  return rows
}

// The customers who spent the most over the orders that count, at most
// `limit` of them, and by customer id on a tie. Guest orders are left out.
export function customerSales(orders: readonly Order[], limit: number): CustomerSales[] {
  const rows = new Map<string, CustomerSales>()
  for (const order of orders.filter(counts)) {
    if (order.customerId === undefined) continue
    const row = rows.get(order.customerId) ?? {
      customerId: order.customerId,
      orders: 0,
      revenue: 0,
    }
    row.orders += 1
    row.revenue += order.total
    rows.set(order.customerId, row)
  }
  return [...rows.values()]
    .sort((a, b) => b.revenue - a.revenue || compareText(a.customerId, b.customerId))
    .slice(0, limit)
}

export interface ProductSales {
  sku: string
  units: number
  gross: Cents // the units at their unit prices, before any discount
  orders: number
}

// The units and the gross sales of each SKU over the orders that count,
// placed in the period: the most gross first, and by SKU on a tie.
export function productSales(
  orders: readonly Order[],
  from: IsoDate,
  to: IsoDate
): ProductSales[] {
  const rows = new Map<string, ProductSales>()
  for (const order of countedIn(orders, from, to)) {
    for (const line of order.lines) {
      const row = rows.get(line.sku) ?? { sku: line.sku, units: 0, gross: 0, orders: 0 }
      row.units += line.quantity
      row.gross += times(line.unitPrice, line.quantity)
      row.orders += 1
      rows.set(line.sku, row)
    }
  }
  return [...rows.values()].sort((a, b) => b.gross - a.gross || compareText(a.sku, b.sku))
}

export interface Cohort {
  month: string // the month in which the customers registered, YYYY-MM
  customers: number
  buyers: number // the customers of the cohort with an order that counts
  revenue: Cents
}

// The customers grouped by the month that they registered, by month, with
// how many of them bought and what they spent over the orders that count.
export function cohorts(customers: readonly Customer[], orders: readonly Order[]): Cohort[] {
  const rows = new Map<string, Cohort>()
  const counted = orders.filter(counts)
  for (const customer of customers) {
    const month = customer.registeredOn.slice(0, 7)
    const row = rows.get(month) ?? { month, customers: 0, buyers: 0, revenue: 0 }
    const theirs = counted.filter((order) => order.customerId === customer.id)
    row.customers += 1
    row.buyers += theirs.length > 0 ? 1 : 0
    row.revenue += sum(theirs.map((order) => order.total))
    rows.set(month, row)
  }
  return [...rows.values()].sort((a, b) => compareText(a.month, b.month))
}

// What the carrier charged for the shipments created in the period.
export function shippingCosts(
  shipments: readonly Shipment[],
  from: IsoDate,
  to: IsoDate
): ShippingCosts {
  const inPeriod = shipments.filter((shipment) => within(shipment.createdOn, from, to))
  const byZone: Record<string, Cents> = {}
  for (const shipment of inPeriod) {
    byZone[shipment.zone] = (byZone[shipment.zone] ?? 0) + shipment.cost
  }
  return {
    shipments: inPeriod.length,
    cost: sum(inPeriod.map((shipment) => shipment.cost)),
    byZone,
  }
}
