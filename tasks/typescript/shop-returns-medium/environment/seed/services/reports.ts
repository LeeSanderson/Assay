// Reports: figures for the people who run the shop, read from the stores.
// Each report counts the orders that are not cancelled, at their totals as
// placed (domain/report.ts).

import { checkPeriod, monthOf } from '../domain/dates.ts'
import type { IsoDate } from '../domain/dates.ts'
import { check } from '../domain/errors.ts'
import { compareText } from '../domain/ids.ts'
import { sum } from '../domain/money.ts'
import type { Cents } from '../domain/money.ts'
import { counts } from '../domain/order.ts'
import type { OrderRepository } from '../domain/order.ts'
import type { ProductRepository } from '../domain/product.ts'
import type { CustomerRepository } from '../domain/customer.ts'
import {
  cohorts,
  customerSales,
  dailySales,
  productSales,
  promotionUsage,
  salesSummary,
  shippingCosts,
  stockValues,
  weekdaySales,
} from '../domain/report.ts'
import type {
  Cohort,
  CustomerSales,
  DailySales,
  ProductSales,
  PromotionUsage,
  SalesSummary,
  ShippingCosts,
  StockValue,
  WeekdaySales,
} from '../domain/report.ts'
import type { ShipmentRepository } from '../domain/shipment.ts'
import { availableOf } from '../domain/stock.ts'
import type { StockRepository } from '../domain/stock.ts'

export interface ReportsDeps {
  orders: OrderRepository
  products: ProductRepository
  stock: StockRepository
  shipments: ShipmentRepository
  customers: CustomerRepository
}

export interface MonthlyMargin {
  month: string // YYYY-MM
  revenue: Cents
  shipping: Cents
  margin: Cents
}

export interface StockValuation {
  rows: StockValue[]
  total: Cents
}

export interface MonthlySales {
  month: string // YYYY-MM
  orders: number
  revenue: Cents
}

// A product to order more of: its available stock is below the threshold.
export interface ReorderLine {
  sku: string
  name: string
  available: number
  suggested: number // enough to bring the available stock up to the target
}

export class Reports {
  constructor(private readonly deps: ReportsDeps) {}

  public salesSummary(from: IsoDate, to: IsoDate): SalesSummary {
    checkPeriod(from, to)
    return salesSummary(this.deps.orders.list(), from, to)
  }

  public dailySales(from: IsoDate, to: IsoDate): DailySales[] {
    checkPeriod(from, to)
    return dailySales(this.deps.orders.list(), from, to)
  }

  // One row for each month with an order that counts, by month.
  public monthlySales(): MonthlySales[] {
    const months = new Map<string, MonthlySales>()
    for (const order of this.deps.orders.list().filter(counts)) {
      const month = monthOf(order.placedOn)
      const row = months.get(month) ?? { month, orders: 0, revenue: 0 }
      row.orders += 1
      row.revenue += order.total
      months.set(month, row)
    }
    return [...months.values()].sort((a, b) => compareText(a.month, b.month))
  }

  public promotionUsage(): PromotionUsage[] {
    return promotionUsage(this.deps.orders.list())
  }

  public stockValuation(): StockValuation {
    const rows = stockValues(this.deps.products.list(), this.deps.stock.list())
    return { rows, total: sum(rows.map((row) => row.value)) }
  }

  public topCustomers(limit: number): CustomerSales[] {
    check(Number.isInteger(limit) && limit >= 1, 'limit must be at least 1')
    return customerSales(this.deps.orders.list(), limit)
  }

  public shippingCosts(from: IsoDate, to: IsoDate): ShippingCosts {
    checkPeriod(from, to)
    return shippingCosts(this.deps.shipments.list(), from, to)
  }

  public productSales(from: IsoDate, to: IsoDate): ProductSales[] {
    checkPeriod(from, to)
    return productSales(this.deps.orders.list(), from, to)
  }

  public weekdaySales(from: IsoDate, to: IsoDate): WeekdaySales[] {
    checkPeriod(from, to)
    return weekdaySales(this.deps.orders.list(), from, to)
  }

  public cohorts(): Cohort[] {
    return cohorts(this.deps.customers.list(), this.deps.orders.list())
  }

  // The revenue of each month with an order that counts, less what the
  // carrier charged for the shipments created that month, by month.
  public monthlyMargin(): MonthlyMargin[] {
    const costs = new Map<string, Cents>()
    for (const shipment of this.deps.shipments.list()) {
      const month = monthOf(shipment.createdOn)
      costs.set(month, (costs.get(month) ?? 0) + shipment.cost)
    }
    return this.monthlySales().map((row) => {
      const shipping = costs.get(row.month) ?? 0
      return { month: row.month, revenue: row.revenue, shipping, margin: row.revenue - shipping }
    })
  }

  // The products on sale whose available stock is below `threshold`, with
  // the units to order to bring it up to `target`, in SKU order.
  public reorder(threshold: number, target: number): ReorderLine[] {
    check(target >= threshold, 'the target must not be below the threshold')
    const lines: ReorderLine[] = []
    const products = this.deps.products
      .list()
      .filter((product) => !product.discontinued)
      .sort((a, b) => compareText(a.sku, b.sku))
    for (const product of products) {
      const level = this.deps.stock.get(product.sku)
      const available = level === undefined ? 0 : availableOf(level)
      if (available < threshold) {
        lines.push({
          sku: product.sku,
          name: product.name,
          available,
          suggested: target - available,
        })
      }
    }
    return lines
  }
}
