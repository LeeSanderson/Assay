import { describe, expect, it } from '@jest/globals'
import type { Order } from './order.ts'
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
} from './report.ts'
import type { Shipment } from './shipment.ts'

// order(id, placedOn, total, ...) with one line of apples at 250, and the
// discount that takes the subtotal down to the total.
function order(
  id: string,
  placedOn: string,
  apples: number,
  discount: number,
  more: Partial<Order> = {}
): Order {
  const subtotal = apples * 250
  return {
    id,
    lines: [{ sku: 'apple', name: 'Apple', unitPrice: 250, quantity: apples }],
    subtotal,
    discounts: discount > 0 ? [{ promotionId: 'ten', amount: discount }] : [],
    total: subtotal - discount,
    status: 'paid',
    paymentId: `payment-${id}`,
    placedOn,
    ...more,
  }
}

const ORDERS: Order[] = [
  order('order-1', '2026-03-09', 4, 100, { customerId: 'customer-2' }), // Monday, 900
  order('order-2', '2026-03-10', 2, 0, { customerId: 'customer-1' }), // Tuesday, 500
  order('order-3', '2026-03-10', 8, 0, { status: 'cancelled', customerId: 'customer-1' }),
  order('order-4', '2026-03-16', 1, 25, { status: 'shipped' }), // Monday, 225
]

describe('sales', () => {
  it('sums up the orders that count in a period', () => {
    expect(salesSummary(ORDERS, '2026-03-01', '2026-03-31')).toEqual({
      from: '2026-03-01',
      to: '2026-03-31',
      orders: 3,
      units: 7,
      subtotal: 1750,
      discounts: 125,
      revenue: 1625,
      averageOrder: 541,
    })
  })

  it('gives an average of 0 for a period with no orders', () => {
    expect(salesSummary(ORDERS, '2026-04-01', '2026-04-30').averageOrder).toBe(0)
  })

  it('gives one row for each day with sales, by date', () => {
    expect(dailySales(ORDERS, '2026-03-01', '2026-03-31')).toEqual([
      { date: '2026-03-09', orders: 1, revenue: 900 },
      { date: '2026-03-10', orders: 1, revenue: 500 },
      { date: '2026-03-16', orders: 1, revenue: 225 },
    ])
  })

  it('gives one row for each weekday with sales, from Monday', () => {
    expect(weekdaySales(ORDERS, '2026-03-01', '2026-03-31')).toEqual([
      { weekday: 'Monday', orders: 2, revenue: 1125 },
      { weekday: 'Tuesday', orders: 1, revenue: 500 },
    ])
  })

  it('ranks the products by their gross sales', () => {
    const pears = order('order-5', '2026-03-11', 1, 0)
    pears.lines = [{ sku: 'pear', name: 'Pear', unitPrice: 1000, quantity: 2 }]
    expect(productSales([...ORDERS, pears], '2026-03-01', '2026-03-31')).toEqual([
      { sku: 'pear', units: 2, gross: 2000, orders: 1 },
      { sku: 'apple', units: 7, gross: 1750, orders: 3 },
    ])
  })
})

describe('promotions and customers', () => {
  it('adds up what each promotion took off, the most first', () => {
    const other = order('order-5', '2026-03-11', 4, 0)
    other.discounts = [{ promotionId: 'big', amount: 400 }]
    expect(promotionUsage([...ORDERS, other])).toEqual([
      { promotionId: 'big', orders: 1, amount: 400 },
      { promotionId: 'ten', orders: 2, amount: 125 },
    ])
  })

  it('ranks the customers by what they spent, without guests', () => {
    expect(customerSales(ORDERS, 5)).toEqual([
      { customerId: 'customer-2', orders: 1, revenue: 900 },
      { customerId: 'customer-1', orders: 1, revenue: 500 },
    ])
    expect(customerSales(ORDERS, 1)).toHaveLength(1)
  })

  it('groups the customers by the month that they registered', () => {
    const customer = (id: string, registeredOn: string) => ({
      id,
      name: id,
      email: `${id}@example.com`,
      registeredOn,
    })
    expect(
      cohorts(
        [
          customer('customer-1', '2026-02-20'),
          customer('customer-2', '2026-03-01'),
          customer('customer-3', '2026-03-05'),
        ],
        ORDERS
      )
    ).toEqual([
      { month: '2026-02', customers: 1, buyers: 1, revenue: 500 },
      { month: '2026-03', customers: 2, buyers: 1, revenue: 900 },
    ])
  })
})

describe('stock and shipping', () => {
  it('values the stock on hand of each product, in SKU order', () => {
    const products = [
      { sku: 'pear', name: 'Pear', unitPrice: 1000, discontinued: false },
      { sku: 'apple', name: 'Apple', unitPrice: 250, discontinued: false },
      { sku: 'fig', name: 'Fig', unitPrice: 400, discontinued: false },
    ]
    const levels = [
      { sku: 'pear', onHand: 2, reserved: 1 },
      { sku: 'apple', onHand: 10, reserved: 0 },
    ]
    expect(stockValues(products, levels)).toEqual([
      { sku: 'apple', onHand: 10, unitPrice: 250, value: 2500 },
      { sku: 'pear', onHand: 2, unitPrice: 1000, value: 2000 },
    ])
  })

  it('adds up the shipping costs of a period by zone', () => {
    const shipment = (id: string, zone: Shipment['zone'], cost: number, createdOn: string) =>
      ({ id, zone, cost, createdOn }) as Shipment
    expect(
      shippingCosts(
        [
          shipment('shipment-1', 'domestic', 400, '2026-03-10'),
          shipment('shipment-2', 'europe', 900, '2026-03-11'),
          shipment('shipment-3', 'domestic', 500, '2026-03-12'),
          shipment('shipment-4', 'domestic', 700, '2026-04-01'),
        ],
        '2026-03-01',
        '2026-03-31'
      )
    ).toEqual({ shipments: 3, cost: 1800, byZone: { domestic: 900, europe: 900 } })
  })
})
