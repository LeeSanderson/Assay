import { describe, expect, it } from '@jest/globals'
import type { Customer } from './customer.ts'
import { customerChange, invoiceChange, orderChange, shipmentChange } from './event.ts'
import type { Invoice } from './invoice.ts'
import type { Order } from './order.ts'
import type { Shipment } from './shipment.ts'

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

describe('order changes', () => {
  it('places a new order', () => {
    expect(orderChange(undefined, ORDER)).toEqual({
      type: 'order-placed',
      subject: 'order-1',
      data: { total: 500, lines: 1 },
    })
  })

  it('names the customer of the order', () => {
    const change = orderChange(undefined, { ...ORDER, customerId: 'customer-1' })
    expect(change?.data).toEqual({ total: 500, lines: 1, customerId: 'customer-1' })
  })

  it('turns a change of status into an event of the new status', () => {
    expect(orderChange(ORDER, { ...ORDER, status: 'shipped' })).toEqual({
      type: 'order-shipped',
      subject: 'order-1',
      data: { total: 500 },
    })
  })

  it('gives no event when the status stays the same', () => {
    expect(orderChange(ORDER, { ...ORDER })).toBeUndefined()
  })
})

describe('other changes', () => {
  const shipment: Shipment = {
    id: 'shipment-1',
    orderId: 'order-1',
    address: { line1: '1 High St', city: 'Leeds', postcode: 'LS1 1AA', country: 'GB' },
    zone: 'domestic',
    units: 2,
    parcels: 1,
    cost: 500,
    status: 'pending',
    createdOn: '2026-03-10',
  }

  it('creates and dispatches a shipment', () => {
    expect(shipmentChange(undefined, shipment)?.type).toBe('shipment-created')
    const dispatched = { ...shipment, status: 'dispatched' as const, trackingCode: 'TRK1' }
    expect(shipmentChange(shipment, dispatched)).toEqual({
      type: 'shipment-dispatched',
      subject: 'shipment-1',
      data: { orderId: 'order-1', trackingCode: 'TRK1' },
    })
  })

  it('issues an invoice once', () => {
    const invoice = { id: 'invoice-1', orderId: 'order-1', number: 'INV-000001', total: 500 }
    expect(invoiceChange(undefined, invoice as Invoice)).toEqual({
      type: 'invoice-issued',
      subject: 'invoice-1',
      data: { orderId: 'order-1', number: 'INV-000001', total: 500 },
    })
    expect(invoiceChange(invoice as Invoice, invoice as Invoice)).toBeUndefined()
  })

  it('registers, updates and closes a customer', () => {
    const ada: Customer = {
      id: 'customer-1',
      name: 'Ada',
      email: 'ada@example.com',
      registeredOn: '2026-03-10',
    }
    expect(customerChange(undefined, ada)?.type).toBe('customer-registered')
    expect(customerChange(ada, { ...ada, name: 'Ada L', email: 'al@example.com' })?.data).toEqual({
      fields: 'name,email',
    })
    expect(customerChange(ada, { ...ada })).toBeUndefined()
    expect(customerChange(ada, { ...ada, closedOn: '2026-04-01' })?.type).toBe('customer-closed')
  })
})
