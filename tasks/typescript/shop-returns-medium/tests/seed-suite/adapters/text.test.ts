import { describe, expect, it } from '@jest/globals'
import type { ShopEvent } from '../domain/event.ts'
import type { Invoice } from '../domain/invoice.ts'
import type { Order } from '../domain/order.ts'
import type { Shipment } from '../domain/shipment.ts'
import {
  eventsAsJsonLines,
  eventsFromJsonLines,
  formatRate,
  invoiceText,
  packingSlip,
  receipt,
  shippingLabel,
  statementText,
} from './text.ts'

const ORDER: Order = {
  id: 'order-7',
  lines: [
    { sku: 'apple', name: 'Apple', unitPrice: 250, quantity: 2 },
    { sku: 'pear', name: 'Pear', unitPrice: 1000, quantity: 1 },
  ],
  subtotal: 1500,
  discounts: [],
  total: 1500,
  status: 'paid',
  paymentId: 'payment-7',
  placedOn: '2026-03-10',
}

const SHIPMENT: Shipment = {
  id: 'shipment-2',
  orderId: 'order-7',
  address: { line1: '1 High St', city: 'Leeds', postcode: 'LS1 1AA', country: 'GB' },
  zone: 'domestic',
  units: 3,
  parcels: 1,
  cost: 600,
  status: 'pending',
  createdOn: '2026-03-10',
}

describe('receipts', () => {
  it('prints the lines, the subtotal and the total of an order', () => {
    expect(receipt(ORDER)).toBe(
      [
        'Order order-7 (2026-03-10)',
        '2 x Apple                           5.00',
        '1 x Pear                           10.00',
        'Subtotal                           15.00',
        'Total                              15.00',
        '',
      ].join('\n')
    )
  })

  it('prints each discount as a negative amount and the status of an order that is not paid', () => {
    const order: Order = {
      ...ORDER,
      discounts: [{ promotionId: 'ten', amount: 150 }],
      total: 1350,
      status: 'cancelled',
    }
    expect(receipt(order)).toBe(
      [
        'Order order-7 (2026-03-10)',
        '2 x Apple                           5.00',
        '1 x Pear                           10.00',
        'Subtotal                           15.00',
        'Discount ten                       -1.50',
        'Total                              13.50',
        'Status: cancelled',
        '',
      ].join('\n')
    )
  })
})

describe('documents', () => {
  it('prints an invoice with the tax that it includes', () => {
    const invoice: Invoice = {
      id: 'invoice-1',
      number: 'INV-000001',
      orderId: 'order-7',
      customerId: 'customer-1',
      lines: [{ sku: 'pear', description: 'Pear', quantity: 1, unitPrice: 1200, amount: 1200 }],
      subtotal: 1200,
      discounts: [],
      total: 1200,
      taxRate: 2000,
      tax: 200,
      issuedOn: '2026-03-12',
    }
    expect(invoiceText(invoice)).toBe(
      [
        'Invoice INV-000001 (2026-03-12)',
        'Order order-7 for customer-1',
        '1 x Pear @ 12.00                   12.00',
        'Subtotal                           12.00',
        'Total                              12.00',
        'Tax included at 20%                 2.00',
        '',
      ].join('\n')
    )
  })

  it('prints a shipping label and a packing slip', () => {
    expect(shippingLabel({ ...SHIPMENT, parcels: 2 })).toBe(
      [
        'Shipment shipment-2 for order order-7',
        'To: 1 High St, Leeds LS1 1AA, GB',
        'Units: 3 in 2 parcels',
        'Zone: domestic',
        '',
      ].join('\n')
    )
    expect(packingSlip(ORDER, SHIPMENT)).toBe(
      [
        'Packing slip for order order-7',
        'Ship to: 1 High St, Leeds LS1 1AA, GB',
        '[ ]   2 x apple Apple',
        '[ ]   1 x pear Pear',
        'Units: 3',
        '',
      ].join('\n')
    )
  })

  it('prints the statement of an account', () => {
    const text = statementText({
      customerId: 'customer-1',
      credit: 300,
      points: 12,
      entries: [
        {
          id: 'entry-1',
          customerId: 'customer-1',
          kind: 'credit',
          amount: 300,
          reason: 'gift',
          on: '2026-03-10',
        },
        {
          id: 'entry-2',
          customerId: 'customer-1',
          kind: 'points',
          amount: 12,
          reason: 'order order-1',
          on: '2026-03-11',
        },
      ],
    })
    expect(text).toBe(
      [
        'Statement of customer-1',
        '2026-03-10 gift                     3.00',
        '2026-03-11 order order-1       12 points',
        'Store credit                        3.00',
        'Points: 12',
        '',
      ].join('\n')
    )
  })

  it('writes a rate as a percentage', () => {
    expect([formatRate(2000), formatRate(550), formatRate(525), formatRate(0)]).toEqual([
      '20%',
      '5.5%',
      '5.25%',
      '0%',
    ])
  })
})

describe('json lines', () => {
  it('writes events one a line and reads them back', () => {
    const events: ShopEvent[] = [
      { id: 'event-1', type: 'order-placed', subject: 'order-1', on: '2026-03-10', data: {} },
      {
        id: 'event-2',
        type: 'order-shipped',
        subject: 'order-1',
        on: '2026-03-11',
        data: { total: 5 },
      },
    ]
    const text = eventsAsJsonLines(events)
    expect(text.split('\n')).toHaveLength(3)
    expect(eventsFromJsonLines(text)).toEqual(events)
    expect(eventsAsJsonLines([])).toBe('')
  })

  it('rejects a line that is not an event', () => {
    expect(() => eventsFromJsonLines('{"id":"event-1","type":"x"}\n{"hello":1}\n')).toThrow(
      'line 2 is not an event'
    )
  })
})
