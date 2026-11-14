// Accounts: the store credit (in cents) and the loyalty points of each
// customer, as a log of entries. A customer earns one point for each whole
// 100 cents of an order that it places, and loses them again when the order
// is cancelled. The account learns of orders from the event log: the
// composition root (shop.ts) hands it the `order-placed` and
// `order-cancelled` events.

import { balanceOf } from '../domain/customer.ts'
import type { AccountEntry, AccountRepository, EntryKind, Statement } from '../domain/customer.ts'
import type { Clock } from '../domain/dates.ts'
import { check, checkNotEmpty, invalid } from '../domain/errors.ts'
import type { ShopEvent } from '../domain/event.ts'
import { compareText, PREFIX } from '../domain/ids.ts'
import type { IdSource } from '../domain/ids.ts'
import { checkCents } from '../domain/money.ts'
import type { Cents } from '../domain/money.ts'
import type { Customers } from './customers.ts'

export interface AccountsDeps {
  repository: AccountRepository
  customers: Customers
  clock: Clock
  ids: IdSource
}

// The cents of an order that earn one point.
export const CENTS_PER_POINT = 100
// The points that a customer trades for store credit, at one cent a point,
// in blocks of this many.
export const POINTS_PER_REDEMPTION = 500

export class Accounts {
  constructor(private readonly deps: AccountsDeps) {}

  public credit(customerId: string): Cents {
    return balanceOf(this.entries(customerId), 'credit')
  }

  public points(customerId: string): number {
    return balanceOf(this.entries(customerId), 'points')
  }

  public statement(customerId: string): Statement {
    const entries = this.entries(customerId)
    return {
      customerId,
      credit: balanceOf(entries, 'credit'),
      points: balanceOf(entries, 'points'),
      entries,
    }
  }

  // The customers who hold store credit, with how much, the most first, and
  // by customer id on a tie: what the shop owes in credit.
  public creditHolders(): { customerId: string; credit: Cents }[] {
    return this.deps.customers
      .search('')
      .map((customer) => ({ customerId: customer.id, credit: this.credit(customer.id) }))
      .filter((row) => row.credit > 0)
      .sort((a, b) => b.credit - a.credit || compareText(a.customerId, b.customerId))
  }

  // Gives store credit, as a goodwill gesture or a gift card.
  public addCredit(customerId: string, amount: Cents, reason: string): AccountEntry {
    checkCents(amount, 'amount', 1)
    checkNotEmpty(reason, 'reason')
    return this.add(customerId, 'credit', amount, reason)
  }

  // Spends store credit; it cannot take the balance below zero.
  public useCredit(customerId: string, amount: Cents, reason: string): AccountEntry {
    checkCents(amount, 'amount', 1)
    checkNotEmpty(reason, 'reason')
    const balance = this.credit(customerId)
    if (amount > balance) {
      throw invalid(`customer ${customerId} has ${balance} store credit`)
    }
    return this.add(customerId, 'credit', -amount, reason)
  }

  // Moves store credit from one customer to another, all or none.
  public transferCredit(from: string, to: string, amount: Cents): void {
    check(from !== to, 'a customer cannot transfer credit to itself')
    this.deps.customers.open(to)
    this.useCredit(from, amount, `transfer to ${to}`)
    this.add(to, 'credit', amount, `transfer from ${from}`)
  }

  // Trades points for store credit, in blocks of POINTS_PER_REDEMPTION.
  public redeemPoints(customerId: string, points: number): AccountEntry {
    check(
      Number.isInteger(points) && points > 0 && points % POINTS_PER_REDEMPTION === 0,
      `points must be a multiple of ${POINTS_PER_REDEMPTION}`
    )
    const balance = this.points(customerId)
    if (points > balance) {
      throw invalid(`customer ${customerId} has ${balance} points`)
    }
    this.add(customerId, 'points', -points, 'redeemed')
    return this.add(customerId, 'credit', points, 'points redeemed')
  }

  // Awards the points of a placed order to its customer; a guest order earns
  // none.
  public onOrderPlaced(event: ShopEvent): void {
    const customerId = event.data.customerId
    const points = Math.floor(Number(event.data.total) / CENTS_PER_POINT)
    if (typeof customerId === 'string' && points > 0) {
      this.add(customerId, 'points', points, `order ${event.subject}`)
    }
  }

  // Takes back the points that a cancelled order earned.
  public onOrderCancelled(event: ShopEvent): void {
    const customerId = event.data.customerId
    if (typeof customerId !== 'string') {
      return
    }
    const reason = `order ${event.subject}`
    const earned = this.entries(customerId).filter(
      (entry) => entry.kind === 'points' && entry.reason === reason
    )
    for (const entry of earned) {
      this.add(customerId, 'points', -entry.amount, `cancelled ${reason}`)
    }
  }

  private add(customerId: string, kind: EntryKind, amount: number, reason: string): AccountEntry {
    this.deps.customers.customer(customerId)
    const entry: AccountEntry = {
      id: this.deps.ids.next(PREFIX.entry),
      customerId,
      kind,
      amount,
      reason,
      on: this.deps.clock.today(),
    }
    this.deps.repository.add(entry)
    return entry
  }

  private entries(customerId: string): AccountEntry[] {
    this.deps.customers.customer(customerId)
    return this.deps.repository.entries(customerId)
  }
}
