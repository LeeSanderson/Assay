// Returns: a customer sends back units of a shipped order, up to 30 days
// after it was placed. Each return issues a credit note, which refunds what
// the customer paid for those units: their price, less their share of each
// discount of the order. A return reverses each part of a discount on a line
// in proportion to the units of that line that come back.

import { daysBetween } from './dates.ts'
import type { IsoDate } from './dates.ts'
import { checkQuantity, invalid, wrongState } from './errors.ts'
import { shareOf, sum, times } from './money.ts'
import type { Cents } from './money.ts'
import { returnedUnits } from './order.ts'
import type { Order } from './order.ts'
import type { Discount } from './promotion.ts'

export type ItemCondition = 'resellable' | 'damaged'

export interface ReturnLine {
  sku: string
  quantity: number
  condition: ItemCondition
}

export interface CreditLine {
  sku: string
  quantity: number
  amount: Cents // what the credit note refunds for these units
}

export interface CreditNote {
  id: string
  orderId: string
  lines: CreditLine[]
  discounts: Discount[] // the part of each discount of the order that the return reverses
  amount: Cents // the sum of the amounts of the lines
  issuedOn: IsoDate
}

export const RETURN_DAYS = 30
const CONDITIONS: readonly string[] = ['resellable', 'damaged']

// Checks that the lines can come back from the order on the date: the order
// is shipped, the return window is open, and each line names a SKU of the
// order once, with a quantity that is still left to return.
export function checkReturn(order: Order, lines: readonly ReturnLine[], today: IsoDate): void {
  if (order.status !== 'shipped') {
    throw wrongState('order', order.id, order.status)
  }
  if (daysBetween(order.placedOn, today) > RETURN_DAYS) {
    throw invalid(`the return window of order ${order.id} has closed`)
  }
  if (lines.length === 0) {
    throw invalid('nothing to return')
  }
  const seen = new Set<string>()
  for (const line of lines) {
    const ordered = order.lines.find((l) => l.sku === line.sku)
    if (ordered === undefined) {
      throw invalid(`SKU ${line.sku} is not in order ${order.id}`)
    }
    if (seen.has(line.sku)) {
      throw invalid(`SKU ${line.sku} is in more than one line`)
    }
    seen.add(line.sku)
    checkQuantity(line.quantity)
    if (!CONDITIONS.includes(line.condition)) {
      throw invalid(`unknown condition ${line.condition}`)
    }
    const left = ordered.quantity - returnedUnits(order, line.sku)
    if (line.quantity > left) {
      throw invalid(`${line.sku} has ${left} left to return`)
    }
  }
}

// What a return of the lines refunds, without its id and date: each part of
// a discount on a line, after `r` of its `q` units in all have come back, is
// reversed to floor(part * r / q), so this return reverses the difference.
export function creditFor(
  order: Order,
  lines: readonly ReturnLine[]
): Pick<CreditNote, 'lines' | 'discounts' | 'amount'> {
  const reversed = new Map<string, Cents>()
  const credit = lines.map((line) => {
    const ordered = order.lines.find((l) => l.sku === line.sku)
    if (ordered === undefined) {
      throw invalid(`SKU ${line.sku} is not in order ${order.id}`)
    }
    const before = returnedUnits(order, line.sku)
    const after = before + line.quantity
    let amount = times(ordered.unitPrice, line.quantity)
    for (const part of ordered.discounts ?? []) {
      const share =
        shareOf(part.amount, after, ordered.quantity) - shareOf(part.amount, before, ordered.quantity)
      amount -= share
      reversed.set(part.promotionId, (reversed.get(part.promotionId) ?? 0) + share)
    }
    return { sku: line.sku, quantity: line.quantity, amount }
  })
  const discounts = order.discounts
    .map((d) => ({ promotionId: d.promotionId, amount: reversed.get(d.promotionId) ?? 0 }))
    .filter((d) => d.amount > 0)
  return { lines: credit, discounts, amount: sum(credit.map((line) => line.amount)) }
}

// The order with the credit note added; returned once every unit of every
// line has come back.
export function withCreditNote(order: Order, note: CreditNote): Order {
  const updated: Order = { ...order, creditNotes: [...(order.creditNotes ?? []), note] }
  if (order.lines.every((line) => line.quantity === returnedUnits(updated, line.sku))) {
    updated.status = 'returned'
  }
  return updated
}
