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
import { PromotionEngine } from './promotion-engine.ts'

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
  const orders = new InMemoryOrderRepository()
  const payments = new InMemoryPaymentGateway(ids)
  const customers = new Customers({ repository: new InMemoryCustomerRepository(), clock, ids })
  const checkout = new Checkout({ catalogue, inventory, orders, payments, clock, ids, customers })
  return { catalogue, inventory, orders, payments, customers, checkout, clock, ids }
}

function cart(...items: [string, number][]): Cart {
  const cart = new Cart()
  for (const [sku, quantity] of items) cart.add(sku, quantity)
  return cart
}

describe('placing orders', () => {
  it('places an order at the catalogue prices', () => {
    const { checkout } = shop()
    const order = checkout.placeOrder({
      cart: cart(['apple', 2], ['pear', 1]),
      paymentToken: 'card',
    })
    expect(order).toEqual({
      id: 'order-1',
      lines: [
        { sku: 'apple', name: 'Apple', unitPrice: 250, quantity: 2 },
        { sku: 'pear', name: 'Pear', unitPrice: 1000, quantity: 1 },
      ],
      subtotal: 1500,
      discounts: [],
      total: 1500,
      status: 'paid',
      paymentId: 'payment-1',
      placedOn: '2026-03-10',
    })
  })

  it('quotes a cart without placing an order', () => {
    const { checkout, orders, inventory } = shop()
    expect(checkout.quote(cart(['apple', 2], ['pear', 1]))).toEqual({
      subtotal: 1500,
      discounts: [],
      total: 1500,
    })
    expect(orders.list()).toEqual([])
    expect(inventory.available('apple')).toBe(10)
  })

  it('charges the payment the total of the order', () => {
    const { checkout, payments } = shop()
    checkout.placeOrder({ cart: cart(['pear', 2]), paymentToken: 'card' })
    expect(payments.charges()).toEqual([{ id: 'payment-1', token: 'card', amount: 2000 }])
  })

  it('reserves the stock of the order', () => {
    const { checkout, inventory } = shop()
    checkout.placeOrder({ cart: cart(['apple', 3]), paymentToken: 'card' })
    expect(inventory.level('apple')).toEqual({ sku: 'apple', onHand: 10, reserved: 3 })
  })

  it('saves the order', () => {
    const { checkout, orders } = shop()
    const order = checkout.placeOrder({ cart: cart(['apple', 1]), paymentToken: 'card' })
    expect(orders.get('order-1')).toEqual(order)
  })

  it('gives each order its own id', () => {
    const { checkout } = shop()
    const first = checkout.placeOrder({ cart: cart(['apple', 1]), paymentToken: 'card' })
    const second = checkout.placeOrder({ cart: cart(['apple', 1]), paymentToken: 'card' })
    expect([first.id, second.id]).toEqual(['order-1', 'order-2'])
  })

  it('prices an order with the promotions of an engine', () => {
    const { catalogue, inventory, orders, payments, clock, ids } = shop()
    const promotions = new PromotionEngine()
    promotions.addPromotion({ id: 'ten', kind: 'percentage', percent: 10 })
    const checkout = new Checkout({ catalogue, inventory, orders, payments, clock, ids, promotions })
    const order = checkout.placeOrder({ cart: cart(['pear', 1]), paymentToken: 'card' })
    expect([order.discounts, order.total]).toEqual([[{ promotionId: 'ten', amount: 100 }], 900])
  })
})

describe('failed checkouts', () => {
  it('rejects an empty cart', () => {
    const { checkout } = shop()
    expect(() => checkout.placeOrder({ cart: new Cart(), paymentToken: 'card' })).toThrow(
      'the cart is empty'
    )
  })

  it('rejects an unknown product', () => {
    const { checkout } = shop()
    expect(() => checkout.placeOrder({ cart: cart(['kiwi', 1]), paymentToken: 'card' })).toThrow(
      'unknown product kiwi'
    )
  })

  it('rejects a discontinued product', () => {
    const { checkout, catalogue } = shop()
    catalogue.discontinue('pear')
    expect(() => checkout.quote(cart(['pear', 1]))).toThrow('product pear is discontinued')
  })

  it('rejects coupons when it has no promotions engine', () => {
    const { checkout } = shop()
    expect(() => checkout.quote(cart(['pear', 1]), ['SAVE10'])).toThrow(
      'this checkout takes no coupons'
    )
  })

  it('changes nothing when the stock is short', () => {
    const { checkout, inventory, payments, orders } = shop()
    expect(() =>
      checkout.placeOrder({ cart: cart(['apple', 1], ['pear', 6]), paymentToken: 'card' })
    ).toThrow('not enough stock of pear: 5 available')
    expect(inventory.available('apple')).toBe(10)
    expect(payments.charges()).toEqual([])
    expect(orders.list()).toEqual([])
  })

  it('releases the stock when the payment is declined', () => {
    const { checkout, inventory, payments, orders } = shop()
    payments.decline('stolen')
    expect(() => checkout.placeOrder({ cart: cart(['apple', 2]), paymentToken: 'stolen' })).toThrow(
      'payment declined'
    )
    expect(inventory.level('apple')).toEqual({ sku: 'apple', onHand: 10, reserved: 0 })
    expect(orders.list()).toEqual([])
  })
})

describe('customers', () => {
  it('places an order for a customer', () => {
    const { checkout, customers } = shop()
    const ada = customers.register('Ada', 'ada@example.com')
    const order = checkout.placeOrder({
      cart: cart(['apple', 1]),
      paymentToken: 'card',
      customerId: ada.id,
    })
    expect(order.customerId).toBe('customer-1')
  })

  it('rejects an unknown or closed customer and changes nothing', () => {
    const { checkout, customers, payments } = shop()
    const request = { cart: cart(['apple', 1]), paymentToken: 'card' }
    expect(() => checkout.placeOrder({ ...request, customerId: 'customer-9' })).toThrow(
      'unknown customer customer-9'
    )
    const ada = customers.register('Ada', 'ada@example.com')
    customers.close(ada.id)
    expect(() => checkout.placeOrder({ ...request, customerId: ada.id })).toThrow(
      'customer customer-1 is closed'
    )
    expect(payments.charges()).toEqual([])
  })
})

describe('cart problems', () => {
  it('lists the problems of a cart without throwing', () => {
    const { checkout, catalogue } = shop()
    catalogue.addProduct('fig', 'Fig', 400)
    catalogue.discontinue('fig')
    expect(
      checkout.problems(cart(['kiwi', 1], ['fig', 1], ['pear', 7], ['apple', 2]))
    ).toEqual([
      { sku: 'kiwi', problem: 'unknown product' },
      { sku: 'fig', problem: 'discontinued' },
      { sku: 'pear', problem: 'not enough stock', available: 5 },
    ])
  })

  it('fits a cart to what the checkout can place', () => {
    const { checkout, inventory } = shop()
    inventory.reserve('order-9', [{ sku: 'apple', quantity: 10 }])
    const items = cart(['kiwi', 1], ['pear', 7], ['apple', 2])
    expect(checkout.fit(items)).toHaveLength(3)
    expect(items.lines()).toEqual([{ sku: 'pear', quantity: 5 }])
    expect(checkout.problems(items)).toEqual([])
  })

  it('fills a new cart with the lines of an earlier order', () => {
    const { checkout, catalogue } = shop()
    const order = checkout.placeOrder({
      cart: cart(['apple', 2], ['pear', 1]),
      paymentToken: 'card',
    })
    catalogue.discontinue('pear')
    expect(checkout.reorder(order.id).lines()).toEqual([{ sku: 'apple', quantity: 2 }])
    expect(() => checkout.reorder('order-9')).toThrow('unknown order order-9')
  })
})
