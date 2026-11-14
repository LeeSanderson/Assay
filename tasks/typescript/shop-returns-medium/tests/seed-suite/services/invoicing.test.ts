import { describe, expect, it } from '@jest/globals'
import { FixedClock, SequentialIds } from '../adapters/clock.ts'
import {
  InMemoryInvoiceRepository,
  InMemoryOrderRepository,
  InMemoryPaymentGateway,
  InMemoryProductRepository,
  InMemoryStockRepository,
} from '../adapters/memory.ts'
import { Cart } from '../domain/cart.ts'
import { Catalogue } from './catalogue.ts'
import { Checkout } from './checkout.ts'
import { Inventory } from './inventory.ts'
import { Invoicing } from './invoicing.ts'
import { Orders } from './orders.ts'
import { PromotionEngine } from './promotion-engine.ts'

// A shop with apples at 250 and pears at 1200, and 300 off every order of
// at least one pear.
function shop(taxRate?: number) {
  const ids = new SequentialIds()
  const clock = new FixedClock('2026-03-10')
  const catalogue = new Catalogue(new InMemoryProductRepository())
  catalogue.addProduct('apple', 'Apple', 250)
  catalogue.addProduct('pear', 'Pear', 1200)
  const inventory = new Inventory(new InMemoryStockRepository())
  inventory.receive('apple', 20)
  inventory.receive('pear', 20)
  const promotions = new PromotionEngine()
  promotions.addPromotion({ id: 'off', kind: 'fixed', amount: 300, skus: ['pear'] })
  const repository = new InMemoryOrderRepository()
  const payments = new InMemoryPaymentGateway(ids)
  const checkout = new Checkout({
    catalogue,
    inventory,
    orders: repository,
    payments,
    clock,
    ids,
    promotions,
  })
  const orders = new Orders(repository, inventory, payments)
  const invoicing = new Invoicing({
    invoices: new InMemoryInvoiceRepository(),
    orders,
    clock,
    ids,
    taxRate,
  })
  const place = (...items: [string, number][]): string => {
    const cart = new Cart()
    for (const [sku, quantity] of items) cart.add(sku, quantity)
    return checkout.placeOrder({ cart, paymentToken: 'card' }).id
  }
  return { clock, orders, invoicing, place }
}

describe('issuing invoices', () => {
  it('issues the invoice of an order at the standard tax rate', () => {
    const { invoicing, place } = shop()
    const id = place(['apple', 2], ['pear', 1])
    expect(invoicing.issue(id)).toEqual({
      id: 'invoice-1',
      number: 'INV-000001',
      orderId: id,
      lines: [
        { sku: 'apple', description: 'Apple', quantity: 2, unitPrice: 250, amount: 500 },
        { sku: 'pear', description: 'Pear', quantity: 1, unitPrice: 1200, amount: 1200 },
      ],
      subtotal: 1700,
      discounts: [{ promotionId: 'off', amount: 300 }],
      total: 1400,
      taxRate: 2000,
      tax: 234,
      issuedOn: '2026-03-10',
    })
  })

  it('uses the tax rate that it was given', () => {
    const { invoicing, place } = shop(500)
    expect(invoicing.issue(place(['pear', 1])).tax).toBe(43)
  })

  it('rejects a broken tax rate', () => {
    expect(() => shop(-1)).toThrow('tax rate must be a whole number of basis points')
  })

  it('numbers the invoices in the order of issue', () => {
    const { invoicing, place } = shop()
    const first = place(['apple', 1])
    const second = place(['apple', 2])
    expect(invoicing.issue(second).number).toBe('INV-000001')
    expect(invoicing.issue(first).number).toBe('INV-000002')
    expect(invoicing.byNumber('INV-000002').orderId).toBe(first)
  })

  it('issues one invoice for an order that is not cancelled', () => {
    const { invoicing, orders, place } = shop()
    const id = place(['apple', 1])
    invoicing.issue(id)
    expect(() => invoicing.issue(id)).toThrow(`order ${id} already has an invoice`)
    const cancelled = place(['apple', 1])
    orders.cancel(cancelled)
    expect(() => invoicing.issue(cancelled)).toThrow(`order ${cancelled} is cancelled`)
    expect(() => invoicing.issue('order-9')).toThrow('unknown order order-9')
  })

  it('issues the invoices of every order that has none', () => {
    const { invoicing, orders, place } = shop()
    const first = place(['apple', 1])
    orders.cancel(place(['apple', 1]))
    const third = place(['apple', 1])
    invoicing.issue(third)
    const fourth = place(['pear', 1])
    expect(invoicing.uninvoiced()).toEqual([first, fourth])
    expect(invoicing.issueOutstanding().map((invoice) => invoice.orderId)).toEqual([first, fourth])
    expect(invoicing.uninvoiced()).toEqual([])
  })
})

describe('finding invoices', () => {
  it('finds an invoice by its id, its order or its number', () => {
    const { invoicing, place } = shop()
    const id = place(['apple', 1])
    const invoice = invoicing.issue(id)
    expect(invoicing.invoice(invoice.id)).toEqual(invoice)
    expect(invoicing.invoiceFor(id)).toEqual(invoice)
    expect(() => invoicing.invoice('invoice-9')).toThrow('unknown invoice invoice-9')
    expect(() => invoicing.byNumber('INV-000009')).toThrow('unknown invoice INV-000009')
    expect(() => invoicing.invoiceFor(place(['apple', 1]))).toThrow(
      'order order-2 has no invoice'
    )
  })

  it('sums up the tax of the invoices issued in a period', () => {
    const { clock, invoicing, place } = shop()
    invoicing.issue(place(['pear', 1])) // 900, tax 150
    clock.set('2026-03-20')
    invoicing.issue(place(['apple', 6])) // 1500, tax 250
    clock.set('2026-04-02')
    invoicing.issue(place(['apple', 1]))
    expect(invoicing.taxSummary('2026-03-01', '2026-03-31')).toEqual({
      from: '2026-03-01',
      to: '2026-03-31',
      invoices: 2,
      total: 2400,
      tax: 400,
    })
    expect(invoicing.issuedBetween('2026-04-01', '2026-04-30')).toHaveLength(1)
  })

  it('lists the invoices whose orders were cancelled after issue', () => {
    const { invoicing, orders, place } = shop()
    const id = place(['apple', 1])
    invoicing.issue(id)
    invoicing.issue(place(['apple', 1]))
    orders.cancel(id)
    expect(invoicing.cancelledAfterIssue().map((invoice) => invoice.orderId)).toEqual([id])
  })
})
