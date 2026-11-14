import { describe, expect, it } from '@jest/globals'
import { SequentialIds } from './clock.ts'
import {
  InMemoryAccountRepository,
  InMemoryEventStore,
  InMemoryOrderRepository,
  InMemoryOutbox,
  InMemoryPaymentGateway,
  InMemoryProductRepository,
  InMemoryStockRepository,
} from './memory.ts'
import type { Order } from '../domain/order.ts'

const ORDER: Order = {
  id: 'order-1',
  lines: [{ sku: 'apple', name: 'Apple', unitPrice: 250, quantity: 2 }],
  subtotal: 500,
  discounts: [],
  total: 500,
  status: 'paid',
  paymentId: 'payment-1',
  placedOn: '2026-03-10',
}

describe('stores', () => {
  it('gives back a copy of what it saved', () => {
    const orders = new InMemoryOrderRepository()
    orders.save(ORDER)
    const copy = orders.get('order-1')!
    copy.lines[0].quantity = 9
    expect(orders.get('order-1')).toEqual(ORDER)
  })

  it('keeps a copy of what it was given', () => {
    const products = new InMemoryProductRepository()
    const apple = { sku: 'apple', name: 'Apple', unitPrice: 250, discontinued: false }
    products.save(apple)
    apple.unitPrice = 1
    expect(products.get('apple')?.unitPrice).toBe(250)
  })

  it('lists records in the order that each was first saved', () => {
    const orders = new InMemoryOrderRepository()
    orders.save({ ...ORDER, id: 'order-2' })
    orders.save(ORDER)
    orders.save({ ...ORDER, id: 'order-2', status: 'shipped' })
    expect(orders.list().map((order) => [order.id, order.status])).toEqual([
      ['order-2', 'shipped'],
      ['order-1', 'paid'],
    ])
  })

  it('keeps the reservations and the movements of the stock', () => {
    const stock = new InMemoryStockRepository()
    stock.saveReservation({ orderId: 'order-1', lines: [{ sku: 'apple', quantity: 2 }] })
    stock.addMovement({ sku: 'apple', quantity: 5, reason: 'received' })
    expect(stock.reservation('order-1')?.lines).toEqual([{ sku: 'apple', quantity: 2 }])
    expect(stock.reservations()).toHaveLength(1)
    stock.removeReservation('order-1')
    expect(stock.reservation('order-1')).toBeUndefined()
    expect(stock.movements()).toEqual([{ sku: 'apple', quantity: 5, reason: 'received' }])
  })

  it('keeps the entries of each account and the events, oldest first', () => {
    const accounts = new InMemoryAccountRepository()
    const entry = { customerId: 'customer-1', kind: 'credit' as const, reason: 'gift' }
    accounts.add({ ...entry, id: 'entry-1', amount: 500, on: '2026-03-10' })
    accounts.add({ ...entry, id: 'entry-2', customerId: 'customer-2', amount: 1, on: '2026-03-10' })
    expect(accounts.entries('customer-1').map((e) => e.id)).toEqual(['entry-1'])
    const events = new InMemoryEventStore()
    events.append({ id: 'event-1', type: 'order-placed', subject: 'o', on: 'd', data: {} })
    expect(events.list().map((event) => event.id)).toEqual(['event-1'])
  })
})

describe('the payment gateway', () => {
  function gateway(): InMemoryPaymentGateway {
    return new InMemoryPaymentGateway(new SequentialIds())
  }

  it('charges a token', () => {
    const payments = gateway()
    expect(payments.charge('card', 1500)).toEqual({ id: 'payment-1', token: 'card', amount: 1500 })
    expect(payments.charges()).toEqual([{ id: 'payment-1', token: 'card', amount: 1500 }])
  })

  it('rejects an amount below 1', () => {
    const payments = gateway()
    expect(() => payments.charge('card', 0)).toThrow('amount must be at least 1')
    expect(payments.charges()).toEqual([])
  })

  it('declines a declined token', () => {
    const payments = gateway()
    payments.decline('stolen')
    expect(() => payments.charge('stolen', 100)).toThrow('payment declined')
    expect(payments.charges()).toEqual([])
  })

  it('refunds a whole payment once', () => {
    const payments = gateway()
    const payment = payments.charge('card', 1500)
    expect(payments.refund(payment.id)).toEqual({ paymentId: 'payment-1', amount: 1500 })
    expect(() => payments.refund(payment.id)).toThrow('payment payment-1 is already refunded')
    expect(payments.refunds()).toEqual([{ paymentId: 'payment-1', amount: 1500 }])
  })

  it('rejects a refund of an unknown payment', () => {
    expect(() => gateway().refund('payment-9')).toThrow('unknown payment payment-9')
  })

  it('holds the charges less the refunds', () => {
    const payments = gateway()
    payments.charge('card', 1500)
    payments.refund(payments.charge('card', 400).id)
    expect(payments.balance()).toBe(1500)
  })
})

describe('the outbox', () => {
  it('keeps each message, in the order sent', () => {
    const outbox = new InMemoryOutbox()
    outbox.send({ to: 'ada@example.com', subject: 'One', body: '1' })
    outbox.send({ to: 'bob@example.com', subject: 'Two', body: '2' })
    expect(outbox.sent().map((m) => m.subject)).toEqual(['One', 'Two'])
    expect(outbox.sentTo('bob@example.com')).toEqual([
      { to: 'bob@example.com', subject: 'Two', body: '2' },
    ])
  })
})
