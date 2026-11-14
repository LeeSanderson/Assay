import { describe, expect, it } from '@jest/globals'
import { FixedClock, SequentialIds } from '../adapters/clock.ts'
import {
  InMemoryCustomerRepository,
  InMemoryOrderRepository,
  InMemoryPaymentGateway,
  InMemoryProductRepository,
  InMemoryShipmentRepository,
  InMemoryStockRepository,
} from '../adapters/memory.ts'
import { Cart } from '../domain/cart.ts'
import { Catalogue } from './catalogue.ts'
import { Checkout } from './checkout.ts'
import { Customers } from './customers.ts'
import { Inventory } from './inventory.ts'
import { Orders } from './orders.ts'
import { PromotionEngine } from './promotion-engine.ts'
import { Reports } from './reports.ts'

// A shop with apples at 250 and pears at 1000, 20 of each, and 10% off pears.
function shop() {
  const ids = new SequentialIds()
  const clock = new FixedClock('2026-03-10')
  const products = new InMemoryProductRepository()
  const catalogue = new Catalogue(products)
  catalogue.addProduct('apple', 'Apple', 250)
  catalogue.addProduct('pear', 'Pear', 1000)
  const stock = new InMemoryStockRepository()
  const inventory = new Inventory(stock)
  inventory.receive('apple', 20)
  inventory.receive('pear', 20)
  const promotions = new PromotionEngine()
  promotions.addPromotion({ id: 'pears', kind: 'percentage', percent: 10, skus: ['pear'] })
  const repository = new InMemoryOrderRepository()
  const payments = new InMemoryPaymentGateway(ids)
  const customerStore = new InMemoryCustomerRepository()
  const customers = new Customers({ repository: customerStore, clock, ids })
  const checkout = new Checkout({
    catalogue,
    inventory,
    orders: repository,
    payments,
    clock,
    ids,
    promotions,
    customers,
  })
  const orders = new Orders(repository, inventory, payments)
  const shipments = new InMemoryShipmentRepository()
  const reports = new Reports({
    orders: repository,
    products,
    stock,
    shipments,
    customers: customerStore,
  })
  const place = (customerId: string | undefined, ...items: [string, number][]): string => {
    const cart = new Cart()
    for (const [sku, quantity] of items) cart.add(sku, quantity)
    return checkout.placeOrder({ cart, paymentToken: 'card', customerId }).id
  }
  return { clock, catalogue, inventory, customers, orders, shipments, reports, place }
}

describe('sales reports', () => {
  it('sums up the sales of a period', () => {
    const { clock, orders, reports, place } = shop()
    place(undefined, ['apple', 2], ['pear', 1]) // 500 + 900
    orders.cancel(place(undefined, ['pear', 5]))
    clock.set('2026-04-01')
    place(undefined, ['apple', 1])
    expect(reports.salesSummary('2026-03-01', '2026-03-31')).toEqual({
      from: '2026-03-01',
      to: '2026-03-31',
      orders: 1,
      units: 3,
      subtotal: 1500,
      discounts: 100,
      revenue: 1400,
      averageOrder: 1400,
    })
  })

  it('rejects a period that ends before it starts', () => {
    expect(() => shop().reports.salesSummary('2026-03-31', '2026-03-01')).toThrow(
      'the period from 2026-03-31 to 2026-03-01 ends before it starts'
    )
  })

  it('gives the sales of each day, each weekday and each month', () => {
    const { clock, reports, place } = shop()
    place(undefined, ['apple', 1])
    place(undefined, ['apple', 2])
    clock.set('2026-04-02')
    place(undefined, ['pear', 1])
    expect(reports.dailySales('2026-03-01', '2026-04-30')).toEqual([
      { date: '2026-03-10', orders: 2, revenue: 750 },
      { date: '2026-04-02', orders: 1, revenue: 900 },
    ])
    expect(reports.weekdaySales('2026-03-01', '2026-04-30')).toEqual([
      { weekday: 'Tuesday', orders: 2, revenue: 750 },
      { weekday: 'Thursday', orders: 1, revenue: 900 },
    ])
    expect(reports.monthlySales()).toEqual([
      { month: '2026-03', orders: 2, revenue: 750 },
      { month: '2026-04', orders: 1, revenue: 900 },
    ])
  })

  it('ranks the products by their gross sales', () => {
    const { reports, place } = shop()
    place(undefined, ['apple', 6], ['pear', 1])
    expect(reports.productSales('2026-03-01', '2026-03-31')).toEqual([
      { sku: 'apple', units: 6, gross: 1500, orders: 1 },
      { sku: 'pear', units: 1, gross: 1000, orders: 1 },
    ])
  })

  it('adds up what each promotion took off', () => {
    const { reports, place } = shop()
    place(undefined, ['pear', 2])
    place(undefined, ['pear', 1], ['apple', 1])
    expect(reports.promotionUsage()).toEqual([{ promotionId: 'pears', orders: 2, amount: 300 }])
  })
})

describe('customer reports', () => {
  it('ranks the customers by what they spent', () => {
    const { customers, reports, place } = shop()
    const ada = customers.register('Ada', 'ada@example.com').id
    const bob = customers.register('Bob', 'bob@example.com').id
    place(ada, ['apple', 1])
    place(bob, ['pear', 1])
    place(ada, ['apple', 2])
    expect(reports.topCustomers(5)).toEqual([
      { customerId: bob, orders: 1, revenue: 900 },
      { customerId: ada, orders: 2, revenue: 750 },
    ])
    expect(() => reports.topCustomers(0)).toThrow('limit must be at least 1')
  })

  it('groups the customers by the month that they registered', () => {
    const { clock, customers, reports, place } = shop()
    const ada = customers.register('Ada', 'ada@example.com').id
    clock.set('2026-04-01')
    customers.register('Bob', 'bob@example.com')
    place(ada, ['apple', 1])
    expect(reports.cohorts()).toEqual([
      { month: '2026-03', customers: 1, buyers: 1, revenue: 250 },
      { month: '2026-04', customers: 1, buyers: 0, revenue: 0 },
    ])
  })
})

describe('stock reports', () => {
  it('values the stock on hand', () => {
    const { inventory, reports } = shop()
    inventory.writeOff('pear', 18)
    expect(reports.stockValuation()).toEqual({
      rows: [
        { sku: 'apple', onHand: 20, unitPrice: 250, value: 5000 },
        { sku: 'pear', onHand: 2, unitPrice: 1000, value: 2000 },
      ],
      total: 7000,
    })
  })

  it('suggests what to reorder to bring the stock up to a target', () => {
    const { catalogue, inventory, reports, place } = shop()
    catalogue.addProduct('fig', 'Fig', 400)
    catalogue.addProduct('kiwi', 'Kiwi', 300)
    catalogue.discontinue('kiwi')
    inventory.writeOff('pear', 15)
    place(undefined, ['pear', 2])
    expect(reports.reorder(5, 12)).toEqual([
      { sku: 'fig', name: 'Fig', available: 0, suggested: 12 },
      { sku: 'pear', name: 'Pear', available: 3, suggested: 9 },
    ])
    expect(() => reports.reorder(5, 4)).toThrow('the target must not be below the threshold')
  })
})

describe('shipping reports', () => {
  it('adds up the shipping costs and the margin of each month', () => {
    const { shipments, reports, place } = shop()
    const id = place(undefined, ['pear', 1])
    shipments.save({
      id: 'shipment-1',
      orderId: id,
      address: { line1: '1 High St', city: 'Leeds', postcode: 'LS1 1AA', country: 'GB' },
      zone: 'domestic',
      units: 1,
      parcels: 1,
      cost: 400,
      status: 'pending',
      createdOn: '2026-03-11',
    })
    expect(reports.shippingCosts('2026-03-01', '2026-03-31')).toEqual({
      shipments: 1,
      cost: 400,
      byZone: { domestic: 400 },
    })
    expect(reports.monthlyMargin()).toEqual([
      { month: '2026-03', revenue: 900, shipping: 400, margin: 500 },
    ])
  })
})
