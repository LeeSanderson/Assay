import { describe, expect, it } from '@jest/globals'
import {
  describePromotion,
  explainPricing,
  precedence,
  priceLines,
  validatePromotion,
} from './promotion.ts'
import type { Line, Promotion } from './promotion.ts'

// A subtotal of 1500.
const LINES: Line[] = [
  { sku: 'apple', unitPrice: 250, quantity: 2 },
  { sku: 'pear', unitPrice: 1000, quantity: 1 },
]

const ten: Promotion = { id: 'ten', kind: 'percentage', percent: 10 }

describe('validation', () => {
  it('accepts each kind of promotion with its fields', () => {
    for (const promotion of [
      ten,
      { id: 'off', kind: 'fixed', amount: 100 },
      { id: 'x', kind: 'buy-x-get-y', buy: 2, get: 1 },
      { id: 'pair', kind: 'bundle', skus: ['apple', 'pear'], price: 900 },
    ] as Promotion[]) {
      expect(() => validatePromotion(promotion)).not.toThrow()
    }
  })

  it('rejects the fields that a kind does not allow', () => {
    expect(() => validatePromotion({ id: 'p', kind: 'percentage', percent: 101 })).toThrow(
      'percent must be between 1 and 100'
    )
    expect(() => validatePromotion({ id: 'f', kind: 'fixed', amount: 0 })).toThrow(
      'amount must be positive'
    )
    expect(() => validatePromotion({ id: 'b', kind: 'bundle', skus: ['apple'] })).toThrow(
      'a bundle needs at least two SKUs'
    )
  })
})

describe('pricing', () => {
  it('orders promotions by priority, then by id', () => {
    const promotions: Promotion[] = [
      { ...ten, id: 'b' },
      { ...ten, id: 'a' },
      { ...ten, id: 'c', priority: 2 },
    ]
    expect([...promotions].sort(precedence).map((p) => p.id)).toEqual(['c', 'a', 'b'])
  })

  it('prices lines with no promotion at their subtotal', () => {
    expect(priceLines(LINES, [])).toEqual({ subtotal: 1500, discounts: [], total: 1500 })
  })

  it('lets each promotion work on what the earlier ones left', () => {
    const quote = priceLines(LINES, [
      { ...ten, priority: 1 },
      { id: 'off', kind: 'fixed', amount: 100 },
    ])
    expect(quote).toEqual({
      subtotal: 1500,
      discounts: [
        { promotionId: 'ten', amount: 150 },
        { promotionId: 'off', amount: 100 },
      ],
      total: 1250,
    })
  })

  it('prices each complete set of a bundle at the bundle price', () => {
    const lines: Line[] = [
      { sku: 'apple', unitPrice: 250, quantity: 2 },
      { sku: 'pear', unitPrice: 1000, quantity: 2 },
    ]
    const pair: Promotion = { id: 'pair', kind: 'bundle', skus: ['apple', 'pear'], price: 900 }
    expect(priceLines(lines, [pair]).total).toBe(1800)
  })

  it('rejects a SKU on two lines', () => {
    expect(() => priceLines([...LINES, LINES[0]], [])).toThrow(
      'SKU apple is in more than one line'
    )
  })
})

describe('explanations', () => {
  it('says what each promotion did, in order of precedence', () => {
    const steps = explainPricing(LINES, [
      { id: 'kiwi', kind: 'percentage', percent: 50, skus: ['kiwi'] },
      { id: 'solo', kind: 'fixed', amount: 100, exclusive: true },
      { ...ten, priority: 1 },
    ])
    expect(steps).toEqual([
      { promotionId: 'ten', outcome: 'applied', amount: 150 },
      { promotionId: 'kiwi', outcome: 'nothing to take', amount: 0 },
      { promotionId: 'solo', outcome: 'not alone', amount: 0 },
    ])
  })

  it('marks the promotions after an exclusive one that applied', () => {
    const steps = explainPricing(LINES, [
      { id: 'solo', kind: 'fixed', amount: 100, exclusive: true, priority: 1 },
      ten,
    ])
    expect(steps.map((step) => step.outcome)).toEqual(['applied', 'after exclusive'])
  })

  it('describes each kind of promotion in words', () => {
    expect(describePromotion(ten)).toBe('10% off everything')
    expect(describePromotion({ id: 'f', kind: 'fixed', amount: 250, skus: ['apple'] })).toBe(
      '2.50 off apple'
    )
    expect(describePromotion({ id: 'x', kind: 'buy-x-get-y', buy: 2, get: 1 })).toBe(
      'buy 2 get 1 free on everything'
    )
    expect(
      describePromotion({
        id: 'pair',
        kind: 'bundle',
        skus: ['apple', 'pear'],
        price: 900,
        exclusive: true,
      })
    ).toBe('apple + pear for 9.00 (not with other offers)')
  })
})
