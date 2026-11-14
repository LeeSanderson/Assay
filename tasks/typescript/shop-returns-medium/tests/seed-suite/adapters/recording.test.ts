import { describe, expect, it } from '@jest/globals'
import type { Change } from '../domain/event.ts'
import type { Order } from '../domain/order.ts'
import { InMemoryCustomerRepository, InMemoryOrderRepository } from './memory.ts'
import { RecordingCustomerRepository, RecordingOrderRepository } from './recording.ts'

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

// A sink that keeps each change.
function sink() {
  const changes: Change[] = []
  return { changes, record: (change: Change) => changes.push(change) }
}

describe('recording stores', () => {
  it('saves through the store that they wrap', () => {
    const inner = new InMemoryOrderRepository()
    const orders = new RecordingOrderRepository(inner, sink())
    orders.save(ORDER)
    expect(inner.get('order-1')).toEqual(ORDER)
    expect(orders.get('order-1')).toEqual(ORDER)
    expect(orders.list()).toHaveLength(1)
  })

  it('records each change that a rule turns into an event', () => {
    const changes = sink()
    const orders = new RecordingOrderRepository(new InMemoryOrderRepository(), changes)
    orders.save(ORDER)
    orders.save({ ...ORDER })
    orders.save({ ...ORDER, status: 'cancelled' })
    expect(changes.changes.map((change) => change.type)).toEqual([
      'order-placed',
      'order-cancelled',
    ])
  })

  it('records the changes of customers by their own rule', () => {
    const changes = sink()
    const customers = new RecordingCustomerRepository(new InMemoryCustomerRepository(), changes)
    const ada = { id: 'customer-1', name: 'Ada', email: 'ada@example.com', registeredOn: 'd' }
    customers.save(ada)
    customers.save({ ...ada, name: 'Ada L' })
    expect(changes.changes).toEqual([
      { type: 'customer-registered', subject: 'customer-1', data: { email: 'ada@example.com' } },
      { type: 'customer-updated', subject: 'customer-1', data: { fields: 'name' } },
    ])
  })
})
