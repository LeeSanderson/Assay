import { expect, it } from '@jest/globals'
import { Cart } from './cart.ts'
import { Catalogue, InMemoryProductRepository } from './catalogue.ts'
import { Checkout } from './checkout.ts'
import { FixedClock, SequentialIds } from './clock.ts'
import { InMemoryStockRepository, Inventory } from './inventory.ts'
import { InMemoryOrderRepository } from './orders.ts'
import { InMemoryPaymentGateway } from './payments.ts'

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
  const checkout = new Checkout({ catalogue, inventory, orders, payments, clock, ids })
  return { catalogue, inventory, orders, payments, checkout }
}

function cart(...items: [string, number][]): Cart {
  const cart = new Cart()
  for (const [sku, quantity] of items) cart.add(sku, quantity)
  return cart
}

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

it('gives each order its own id', () => {
  const { checkout } = shop()
  const first = checkout.placeOrder({ cart: cart(['apple', 1]), paymentToken: 'card' })
  const second = checkout.placeOrder({ cart: cart(['apple', 1]), paymentToken: 'card' })
  expect([first.id, second.id]).toEqual(['order-1', 'order-2'])
})
