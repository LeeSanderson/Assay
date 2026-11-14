import { describe, expect, it } from '@jest/globals'
import { FixedClock, SequentialIds } from '../adapters/clock.ts'
import {
  InMemoryCustomerRepository,
  InMemoryOrderRepository,
  InMemoryPaymentGateway,
  InMemoryProductRepository,
  InMemoryStockRepository,
} from '../adapters/memory.ts'
import { Cart } from '../domain/cart.ts'
import { Catalogue } from './catalogue.ts'
import { Checkout } from './checkout.ts'
import { Customers } from './customers.ts'
import { Inventory } from './inventory.ts'
import { Orders } from './orders.ts'

// A shop with apples at 250 (10 in stock) and pears at 1000 (5 in stock).
function shop() {
  const ids = new SequentialIds()
  const clock = new FixedClock('2026-03-10')
  const catalogue = new Catalogue(new InMemoryProductRepository())
  catalogue.addProduct('apple', 'Apple', 250)
  catalogue.addProduct('pear', 'Pear', 1000)
  const inventory = new Inventory(new InMemoryStockRepository())
  inventory.receive('apple', 10)
  inventory.receive('pear', 5)
  const repository = new InMemoryOrderRepository()
  const payments = new InMemoryPaymentGateway(ids)
  const customers = new Customers({ repository: new InMemoryCustomerRepository(), clock, ids })
  const checkout = new Checkout({
    catalogue,
    inventory,
    orders: repository,
    payments,
    clock,
    ids,
    customers,
  })
  const orders = new Orders(repository, inventory, payments)
  // place(['apple', 2], ...) places an order of those lines and gives its id.
  const place = (...items: [string, number][]): string => {
    const cart = new Cart()
    for (const [sku, quantity] of items) cart.add(sku, quantity)
    return checkout.placeOrder({ cart, paymentToken: 'card' }).id
  }
  return { inventory, payments, orders, place, checkout, customers, clock }
}

describe('finding orders', () => {
  it('finds an order by its id', () => {
    const { orders, place } = shop()
    const id = place(['apple', 2])
    expect(orders.order(id).total).toBe(500)
    expect(orders.order(id).status).toBe('paid')
  })

  it('rejects an unknown order', () => {
    expect(() => shop().orders.order('order-9')).toThrow('unknown order order-9')
  })

  it('lists the orders with a status in the order that they were placed', () => {
    const { orders, place } = shop()
    const first = place(['apple', 1])
    const second = place(['pear', 1])
    const third = place(['apple', 2])
    orders.ship(second)
    expect(orders.withStatus('paid').map((order) => order.id)).toEqual([first, third])
    expect(orders.withStatus('shipped').map((order) => order.id)).toEqual([second])
    expect(orders.all().map((order) => order.id)).toEqual([first, second, third])
  })

  it('finds the orders of a customer and the orders of a period', () => {
    const { orders, place, checkout, customers, clock } = shop()
    const ada = customers.register('Ada', 'ada@example.com')
    place(['apple', 1])
    clock.set('2026-03-12')
    const cart = new Cart()
    cart.add('pear', 1)
    const hers = checkout.placeOrder({ cart, paymentToken: 'card', customerId: ada.id }).id
    expect(orders.forCustomer(ada.id).map((order) => order.id)).toEqual([hers])
    expect(orders.placedBetween('2026-03-11', '2026-03-31').map((order) => order.id)).toEqual([
      hers,
    ])
  })

  it('searches the orders with a filter', () => {
    const { orders, place } = shop()
    place(['apple', 1])
    const second = place(['pear', 1], ['apple', 1])
    orders.ship(place(['pear', 2]))
    expect(orders.search({ sku: 'pear', status: 'paid' }).map((o) => o.id)).toEqual([second])
    expect(orders.search({ minTotal: 1250 }).map((o) => o.id)).toEqual(['order-2', 'order-3'])
  })

  it('finds the paid orders that have waited too long to ship', () => {
    const { orders, place, clock } = shop()
    const old = place(['apple', 1])
    clock.set('2026-03-14')
    place(['apple', 1])
    expect(orders.waitingSince('2026-03-15', 3).map((order) => order.id)).toEqual([old])
  })
})

describe('shipping and cancelling', () => {
  it('ships a paid order and takes its stock out of the inventory', () => {
    const { orders, inventory, place } = shop()
    const id = place(['apple', 2])
    orders.ship(id)
    expect(orders.order(id).status).toBe('shipped')
    expect(inventory.level('apple')).toEqual({ sku: 'apple', onHand: 8, reserved: 0 })
  })

  it('cancels a paid order, refunds its payment and releases its stock', () => {
    const { orders, inventory, payments, place } = shop()
    const id = place(['apple', 2], ['pear', 1])
    orders.cancel(id)
    expect(orders.order(id).status).toBe('cancelled')
    expect(payments.refunds()).toEqual([{ paymentId: 'payment-1', amount: 1500 }])
    expect(inventory.level('pear')).toEqual({ sku: 'pear', onHand: 5, reserved: 0 })
  })

  it('rejects a change to an order that is not paid', () => {
    const { orders, place } = shop()
    const shipped = place(['apple', 1])
    orders.ship(shipped)
    const cancelled = place(['apple', 1])
    orders.cancel(cancelled)
    expect(() => orders.cancel(shipped)).toThrow('order order-1 is shipped')
    expect(() => orders.ship(cancelled)).toThrow('order order-2 is cancelled')
    expect(() => orders.checkPaid(shipped)).toThrow('order order-1 is shipped')
  })
})

describe('sales', () => {
  it('adds up the revenue of the orders that are not cancelled', () => {
    const { orders, place } = shop()
    place(['apple', 2])
    orders.cancel(place(['pear', 1]))
    orders.ship(place(['pear', 2]))
    expect(orders.revenue()).toBe(2500)
  })

  it('works out the average order value', () => {
    const { orders, place } = shop()
    expect(orders.averageOrderValue()).toBe(0)
    place(['apple', 1])
    place(['pear', 1])
    place(['pear', 1])
    expect(orders.averageOrderValue()).toBe(750)
  })

  it('ranks the best sellers', () => {
    const { orders, place } = shop()
    place(['apple', 2], ['pear', 1])
    place(['pear', 1])
    orders.cancel(place(['apple', 5]))
    expect(orders.bestSellers(5)).toEqual([
      { sku: 'apple', quantity: 2 },
      { sku: 'pear', quantity: 2 },
    ])
    expect(orders.bestSellers(1)).toEqual([{ sku: 'apple', quantity: 2 }])
  })
})
