// Invoicing: the shop issues one invoice for each order that is not
// cancelled, on request, numbered in the order of issue.

import { checkPeriod, within } from '../domain/dates.ts'
import type { Clock, IsoDate } from '../domain/dates.ts'
import { check, conflict, invalid, notFound, wrongState } from '../domain/errors.ts'
import { PREFIX } from '../domain/ids.ts'
import type { IdSource } from '../domain/ids.ts'
import { invoiceNumber, invoiceOf, STANDARD_TAX_RATE } from '../domain/invoice.ts'
import type { Invoice, InvoiceRepository } from '../domain/invoice.ts'
import { sum } from '../domain/money.ts'
import type { Cents } from '../domain/money.ts'
import { counts } from '../domain/order.ts'
import type { Orders } from './orders.ts'

export interface InvoicingDeps {
  invoices: InvoiceRepository
  orders: Orders
  clock: Clock
  ids: IdSource
  taxRate?: number // in basis points; STANDARD_TAX_RATE when absent
}

// The tax of a period: the invoices issued in it and the tax that they hold.
export interface TaxSummary {
  from: IsoDate
  to: IsoDate
  invoices: number
  total: Cents
  tax: Cents
}

export class Invoicing {
  private readonly taxRate: number

  constructor(private readonly deps: InvoicingDeps) {
    this.taxRate = deps.taxRate ?? STANDARD_TAX_RATE
    check(
      Number.isInteger(this.taxRate) && this.taxRate >= 0,
      'tax rate must be a whole number of basis points'
    )
  }

  public issue(orderId: string): Invoice {
    const order = this.deps.orders.order(orderId)
    if (!counts(order)) {
      throw wrongState('order', order.id, order.status)
    }
    if (this.find(orderId) !== undefined) {
      throw conflict(`order ${orderId} already has an invoice`)
    }
    const invoice = invoiceOf(
      order,
      this.deps.ids.next(PREFIX.invoice),
      invoiceNumber(this.deps.invoices.list().length + 1),
      this.taxRate,
      this.deps.clock.today()
    )
    this.deps.invoices.save(invoice)
    return invoice
  }

  // Issues the invoice of each order that counts and has none, in the order
  // that the orders were placed, and gives the new invoices.
  public issueOutstanding(): Invoice[] {
    return this.uninvoiced().map((orderId) => this.issue(orderId))
  }

  public invoice(id: string): Invoice {
    const invoice = this.deps.invoices.get(id)
    if (invoice === undefined) {
      throw notFound('invoice', id)
    }
    return invoice
  }

  // The invoice of an order: an error when it has none.
  public invoiceFor(orderId: string): Invoice {
    this.deps.orders.order(orderId)
    const invoice = this.find(orderId)
    if (invoice === undefined) {
      throw invalid(`order ${orderId} has no invoice`)
    }
    return invoice
  }

  public byNumber(number: string): Invoice {
    const invoice = this.deps.invoices.list().find((i) => i.number === number)
    if (invoice === undefined) {
      throw notFound('invoice', number)
    }
    return invoice
  }

  public issuedBetween(from: IsoDate, to: IsoDate): Invoice[] {
    checkPeriod(from, to)
    return this.deps.invoices.list().filter((invoice) => within(invoice.issuedOn, from, to))
  }

  public taxSummary(from: IsoDate, to: IsoDate): TaxSummary {
    const invoices = this.issuedBetween(from, to)
    return {
      from,
      to,
      invoices: invoices.length,
      total: sum(invoices.map((invoice) => invoice.total)),
      tax: sum(invoices.map((invoice) => invoice.tax)),
    }
  }

  // The invoices whose orders were cancelled after the invoice was issued,
  // which the accountant must cancel by hand, in the order of issue.
  public cancelledAfterIssue(): Invoice[] {
    return this.deps.invoices
      .list()
      .filter((invoice) => !counts(this.deps.orders.order(invoice.orderId)))
  }

  // The orders that count and have no invoice yet, by id, in the order that
  // they were placed.
  public uninvoiced(): string[] {
    return this.deps.orders
      .all()
      .filter((order) => counts(order) && this.find(order.id) === undefined)
      .map((order) => order.id)
  }

  private find(orderId: string): Invoice | undefined {
    return this.deps.invoices.list().find((invoice) => invoice.orderId === orderId)
  }
}
