import { describe, expect, it } from '@jest/globals'
import { FixedClock, SequentialIds } from '../adapters/clock.ts'
import { InMemoryAccountRepository, InMemoryCustomerRepository } from '../adapters/memory.ts'
import type { ShopEvent } from '../domain/event.ts'
import { Accounts } from './accounts.ts'
import { Customers } from './customers.ts'

// Two customers, Ada (customer-1) and Bob (customer-2), with empty accounts.
function accounts() {
  const clock = new FixedClock('2026-03-10')
  const ids = new SequentialIds()
  const customers = new Customers({ repository: new InMemoryCustomerRepository(), clock, ids })
  const ada = customers.register('Ada', 'ada@example.com').id
  const bob = customers.register('Bob', 'bob@example.com').id
  const service = new Accounts({
    repository: new InMemoryAccountRepository(),
    customers,
    clock,
    ids,
  })
  return { service, customers, clock, ada, bob }
}

function event(type: string, subject: string, data: ShopEvent['data']): ShopEvent {
  return { id: 'event-1', type, subject, on: '2026-03-10', data }
}

describe('store credit', () => {
  it('adds and uses store credit', () => {
    const { service, ada } = accounts()
    service.addCredit(ada, 1000, 'gift card')
    service.useCredit(ada, 400, 'order order-1')
    expect(service.credit(ada)).toBe(600)
  })

  it('cannot take store credit below zero', () => {
    const { service, ada } = accounts()
    service.addCredit(ada, 300, 'goodwill')
    expect(() => service.useCredit(ada, 301, 'order order-1')).toThrow(
      'customer customer-1 has 300 store credit'
    )
  })

  it('rejects a broken amount or reason, or an unknown customer', () => {
    const { service, ada } = accounts()
    expect(() => service.addCredit(ada, 0, 'gift')).toThrow('amount must be at least 1')
    expect(() => service.addCredit(ada, 100, ' ')).toThrow('reason must not be empty')
    expect(() => service.addCredit('customer-9', 100, 'gift')).toThrow(
      'unknown customer customer-9'
    )
  })

  it('transfers store credit between customers, all or none', () => {
    const { service, customers, ada, bob } = accounts()
    service.addCredit(ada, 500, 'gift')
    service.transferCredit(ada, bob, 200)
    expect([service.credit(ada), service.credit(bob)]).toEqual([300, 200])
    customers.close(bob)
    expect(() => service.transferCredit(ada, bob, 100)).toThrow('customer customer-2 is closed')
    expect(() => service.transferCredit(ada, ada, 100)).toThrow(
      'a customer cannot transfer credit to itself'
    )
    expect(service.credit(ada)).toBe(300)
  })

  it('lists the customers who hold credit, the most first', () => {
    const { service, ada, bob } = accounts()
    service.addCredit(ada, 100, 'gift')
    service.addCredit(bob, 400, 'gift')
    expect(service.creditHolders()).toEqual([
      { customerId: bob, credit: 400 },
      { customerId: ada, credit: 100 },
    ])
  })
})

describe('loyalty points', () => {
  it('awards a point for each whole 100 cents of a placed order', () => {
    const { service, ada } = accounts()
    service.onOrderPlaced(event('order-placed', 'order-1', { total: 1299, customerId: ada }))
    service.onOrderPlaced(event('order-placed', 'order-2', { total: 99, customerId: ada }))
    service.onOrderPlaced(event('order-placed', 'order-3', { total: 5000 }))
    expect(service.points(ada)).toBe(12)
  })

  it('takes back the points of a cancelled order', () => {
    const { service, ada } = accounts()
    service.onOrderPlaced(event('order-placed', 'order-1', { total: 1299, customerId: ada }))
    service.onOrderPlaced(event('order-placed', 'order-2', { total: 500, customerId: ada }))
    service.onOrderCancelled(event('order-cancelled', 'order-1', { total: 1299, customerId: ada }))
    expect(service.points(ada)).toBe(5)
  })

  it('trades points for store credit in blocks of 500', () => {
    const { service, ada } = accounts()
    service.onOrderPlaced(event('order-placed', 'order-1', { total: 120000, customerId: ada }))
    service.redeemPoints(ada, 1000)
    expect([service.points(ada), service.credit(ada)]).toEqual([200, 1000])
    expect(() => service.redeemPoints(ada, 250)).toThrow('points must be a multiple of 500')
    expect(() => service.redeemPoints(ada, 500)).toThrow('customer customer-1 has 200 points')
  })

  it('gives a statement of every entry and both balances', () => {
    const { service, ada, clock } = accounts()
    service.addCredit(ada, 250, 'goodwill')
    clock.set('2026-03-11')
    service.onOrderPlaced(event('order-placed', 'order-4', { total: 700, customerId: ada }))
    const statement = service.statement(ada)
    expect([statement.credit, statement.points]).toEqual([250, 7])
    expect(statement.entries.map((e) => [e.kind, e.amount, e.reason, e.on])).toEqual([
      ['credit', 250, 'goodwill', '2026-03-10'],
      ['points', 7, 'order order-4', '2026-03-11'],
    ])
  })
})
