import { describe, expect, it } from '@jest/globals'
import {
  allocate,
  checkCents,
  formatCents,
  formatMoney,
  includedTax,
  parseCents,
  percentOf,
  shareOf,
  splitEvenly,
  sum,
  takeInOrder,
  times,
} from './money.ts'

describe('arithmetic', () => {
  it('adds amounts and prices units', () => {
    expect(sum([250, 1000, 5])).toBe(1255)
    expect(sum([])).toBe(0)
    expect(times(250, 4)).toBe(1000)
  })

  it('takes a percentage and rounds it down', () => {
    expect(percentOf(1000, 10)).toBe(100)
    expect(percentOf(750, 15)).toBe(112)
    expect(percentOf(99, 50)).toBe(49)
  })

  it('takes a share of an amount and rounds it down', () => {
    expect(shareOf(112, 1, 3)).toBe(37)
    expect(shareOf(112, 2, 3)).toBe(74)
    expect(shareOf(112, 3, 3)).toBe(112)
    expect(() => shareOf(100, 1, 0)).toThrow('a share needs a whole above 0')
  })

  it('rejects an amount that is not a whole number of cents', () => {
    expect(() => checkCents(12.5, 'price')).toThrow('price must be a whole number of cents')
    expect(() => checkCents(0, 'amount', 1)).toThrow('amount must be at least 1')
    expect(() => checkCents(0, 'amount')).not.toThrow()
  })
})

describe('allocation', () => {
  it('splits an amount in proportion and gives the rounding to the first parts', () => {
    expect(allocate(100, [1, 1, 1])).toEqual([34, 33, 33])
    expect(allocate(1000, [250, 750])).toEqual([250, 750])
    expect(allocate(10, [1, 2])).toEqual([4, 6])
  })

  it('gives nothing to a weight of zero', () => {
    expect(allocate(5, [0, 1, 1])).toEqual([0, 3, 2])
    expect(allocate(5, [0, 0])).toEqual([0, 0])
  })

  it('splits an amount evenly', () => {
    expect(splitEvenly(100, 3)).toEqual([34, 33, 33])
    expect(splitEvenly(7, 1)).toEqual([7])
    expect(() => splitEvenly(7, 0)).toThrow('parts must be at least 1')
  })

  it('takes an amount from the lines in order, up to what each has left', () => {
    const remaining = [250, 1000, 400]
    expect(takeInOrder(remaining, [0, 1], 300)).toBe(300)
    expect(remaining).toEqual([0, 950, 400])
    expect(takeInOrder(remaining, [0], 50)).toBe(0)
  })
})

describe('tax', () => {
  it('works out the tax that a price includes', () => {
    expect(includedTax(1200, 2000)).toBe(200)
    expect(includedTax(1000, 2000)).toBe(167)
    expect(includedTax(1000, 0)).toBe(0)
  })

  it('rejects a tax rate that is not whole basis points', () => {
    expect(() => includedTax(1000, 12.5)).toThrow(
      'tax rate must be a whole number of basis points'
    )
  })
})

describe('formats', () => {
  it('formats cents as units and hundredths', () => {
    expect([formatCents(1234), formatCents(5), formatCents(0), formatCents(-150)]).toEqual([
      '12.34',
      '0.05',
      '0.00',
      '-1.50',
    ])
  })

  it('formats money with a sign and groups of thousands', () => {
    expect(formatMoney(123456)).toBe('£1,234.56')
    expect(formatMoney(100000000, '$')).toBe('$1,000,000.00')
    expect(formatMoney(-99)).toBe('-£0.99')
  })

  it('parses an amount back into cents', () => {
    expect(parseCents('12.34')).toBe(1234)
    expect(parseCents(' 7 ')).toBe(700)
    expect(parseCents('-0.50')).toBe(-50)
    expect(() => parseCents('12.3')).toThrow('12.3 is not an amount')
  })
})
