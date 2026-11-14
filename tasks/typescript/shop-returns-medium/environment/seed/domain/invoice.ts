// Invoices. The shop issues one invoice for an order that is not cancelled.
// An invoice copies the lines, the discounts and the total of the order as
// placed, and shows the tax that the total includes, at the tax rate of the
// shop. Invoices have their own number, with no gaps: INV-000001, INV-000002.

import type { IsoDate } from './dates.ts'
import { includedTax, times } from './money.ts'
import type { Cents } from './money.ts'
import type { Order } from './order.ts'
import type { Discount } from './promotion.ts'

export interface InvoiceLine {
  sku: string
  description: string
  quantity: number
  unitPrice: Cents
  amount: Cents
}

export interface Invoice {
  id: string
  number: string
  orderId: string
  customerId?: string
  lines: InvoiceLine[]
  subtotal: Cents
  discounts: Discount[]
  total: Cents // what the customer paid, tax included
  taxRate: number // in basis points: 2000 is 20%
  tax: Cents // the tax that the total includes
  issuedOn: IsoDate
}

export interface InvoiceRepository {
  get(id: string): Invoice | undefined
  save(invoice: Invoice): void
  list(): Invoice[] // in the order that they were issued
}

// The tax rate of the shop, in basis points.
export const STANDARD_TAX_RATE = 2000

export function invoiceNumber(sequence: number): string {
  return `INV-${String(sequence).padStart(6, '0')}`
}

// The invoice of an order. It names each field of the order that it copies.
export function invoiceOf(
  order: Order,
  id: string,
  number: string,
  taxRate: number,
  issuedOn: IsoDate
): Invoice {
  const invoice: Invoice = {
    id,
    number,
    orderId: order.id,
    lines: order.lines.map((line) => ({
      sku: line.sku,
      description: line.name,
      quantity: line.quantity,
      unitPrice: line.unitPrice,
      amount: times(line.unitPrice, line.quantity),
    })),
    subtotal: order.subtotal,
    discounts: order.discounts.map((discount) => ({
      promotionId: discount.promotionId,
      amount: discount.amount,
    })),
    total: order.total,
    taxRate,
    tax: includedTax(order.total, taxRate),
    issuedOn,
  }
  if (order.customerId !== undefined) {
    invoice.customerId = order.customerId
  }
  return invoice
}

export function copyInvoice(invoice: Invoice): Invoice {
  return {
    ...invoice,
    lines: invoice.lines.map((line) => ({ ...line })),
    discounts: invoice.discounts.map((discount) => ({ ...discount })),
  }
}
