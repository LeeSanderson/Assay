import { describe, expect, it } from '@jest/globals'
import { invoiceNumber, invoiceOf } from './invoice.ts'
import type { Order } from './order.ts'

const ORDER: Order = {
  id: 'order-3',
  lines: [
    { sku: 'apple', name: 'Apple', unitPrice: 250, quantity: 2 },
    { sku: 'pear', name: 'Pear', unitPrice: 1000, quantity: 1 },
  ],
  subtotal: 1500,
  discounts: [{ promotionId: 'off', amount: 300 }],
  total: 1200,
  status: 'shipped',
  paymentId: 'payment-3',
  placedOn: '2026-03-10',
}

describe('invoices', () => {
  it('numbers invoices with six digits', () => {
    expect([invoiceNumber(1), invoiceNumber(123456)]).toEqual(['INV-000001', 'INV-123456'])
  })

  it('copies the lines, the discounts and the total of the order', () => {
    expect(invoiceOf(ORDER, 'invoice-1', 'INV-000001', 2000, '2026-03-12')).toEqual({
      id: 'invoice-1',
      number: 'INV-000001',
      orderId: 'order-3',
      lines: [
        { sku: 'apple', description: 'Apple', quantity: 2, unitPrice: 250, amount: 500 },
        { sku: 'pear', description: 'Pear', quantity: 1, unitPrice: 1000, amount: 1000 },
      ],
      subtotal: 1500,
      discounts: [{ promotionId: 'off', amount: 300 }],
      total: 1200,
      taxRate: 2000,
      tax: 200,
      issuedOn: '2026-03-12',
    })
  })

  it('names the customer of the order, when it has one', () => {
    const invoice = invoiceOf({ ...ORDER, customerId: 'customer-1' }, 'i', 'n', 0, '2026-03-12')
    expect([invoice.customerId, invoice.tax]).toEqual(['customer-1', 0])
  })
})
