// Money. Every amount in the shop is a whole number of cents, of one
// currency, held in a plain number: 1234 is 12.34. The shop never holds a
// fraction of a cent. Where a rule divides an amount (a percentage, a share,
// a tax), it rounds down, and says so; the helpers below are the only places
// that divide money.

import { check } from './errors.ts'

export type Cents = number

export const ZERO: Cents = 0

// Checks that an amount is a whole number of cents, of at least `least`.
export function checkCents(amount: Cents, what: string, least = 0): void {
  check(Number.isInteger(amount), `${what} must be a whole number of cents`)
  check(amount >= least, `${what} must be at least ${least}`)
}

export function sum(amounts: readonly Cents[]): Cents {
  return amounts.reduce((total, amount) => total + amount, 0)
}

// The price of `quantity` units at `unitPrice` each.
export function times(unitPrice: Cents, quantity: number): Cents {
  return unitPrice * quantity
}

// `percent` per cent of the amount, rounded down to a whole cent.
export function percentOf(amount: Cents, percent: number): Cents {
  return Math.floor((amount * percent) / 100)
}

// The share of `amount` that `part` is of `whole`, rounded down: the part of
// a discount that a share of the units carries.
export function shareOf(amount: Cents, part: number, whole: number): Cents {
  check(whole > 0, 'a share needs a whole above 0')
  return Math.floor((amount * part) / whole)
}

// Splits an amount over weights in proportion, each part rounded down, and
// the cents that the rounding leaves over given one each to the first parts.
// The parts always add up to the amount.
export function allocate(amount: Cents, weights: readonly number[]): Cents[] {
  const whole = sum(weights)
  if (whole === 0) {
    return weights.map(() => 0)
  }
  const parts = weights.map((weight) => Math.floor((amount * weight) / whole))
  let left = amount - sum(parts)
  for (let i = 0; left > 0 && i < parts.length; i++) {
    if (weights[i] > 0) {
      parts[i] += 1
      left -= 1
    }
  }
  return parts
}

// The tax that a price holds when the price includes tax at `rate` basis
// points (2000 is 20%): the price less the price without tax, which rounds
// down.
export function includedTax(price: Cents, rate: number): Cents {
  check(Number.isInteger(rate) && rate >= 0, 'tax rate must be a whole number of basis points')
  return price - Math.floor((price * 10000) / (10000 + rate))
}

// Takes up to `amount` from the remaining amounts at the given indexes, in
// order, and gives what it took. It changes `remaining`.
export function takeInOrder(remaining: Cents[], indexes: readonly number[], amount: Cents): Cents {
  let left = amount
  for (const i of indexes) {
    const take = Math.min(left, remaining[i])
    remaining[i] -= take
    left -= take
  }
  return amount - left
}

// An amount as units and hundredths: 1234 cents is `12.34`, -150 is `-1.50`.
export function formatCents(cents: Cents): string {
  const sign = cents < 0 ? '-' : ''
  const whole = Math.floor(Math.abs(cents) / 100)
  const hundredths = Math.abs(cents) % 100
  return `${sign}${whole}.${String(hundredths).padStart(2, '0')}`
}

// An amount for people to read, with the currency sign and a comma between
// each group of three digits: 123456 cents is `£1,234.56`.
export function formatMoney(cents: Cents, sign = '£'): string {
  const plain = formatCents(Math.abs(cents))
  const [whole, hundredths] = plain.split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${cents < 0 ? '-' : ''}${sign}${grouped}.${hundredths}`
}

// Splits an amount into `parts` amounts that differ by at most one cent, the
// larger ones first.
export function splitEvenly(amount: Cents, parts: number): Cents[] {
  check(Number.isInteger(parts) && parts >= 1, 'parts must be at least 1')
  return allocate(
    amount,
    Array.from({ length: parts }, () => 1)
  )
}

// The larger of two amounts, and the smaller.
export function max(a: Cents, b: Cents): Cents {
  return a > b ? a : b
}

export function min(a: Cents, b: Cents): Cents {
  return a < b ? a : b
}

// Parses `12.34` (or `12`, or `-0.50`) into cents.
export function parseCents(text: string): Cents {
  const match = /^(-?)(\d+)(?:\.(\d{2}))?$/.exec(text.trim())
  check(match !== null, `${text} is not an amount`)
  const [, sign, whole, hundredths] = match as RegExpExecArray
  const cents = Number(whole) * 100 + Number(hundredths ?? '0')
  return sign === '-' ? -cents : cents
}
