import { describe, expect, it } from '@jest/globals'
import type { Coupon, Line } from '../domain/promotion.ts'
import { PromotionEngine } from './promotion-engine.ts'

const TODAY = '2026-03-10'

// A subtotal of 1500.
const LINES: Line[] = [
  { sku: 'apple', unitPrice: 250, quantity: 2 },
  { sku: 'pear', unitPrice: 1000, quantity: 1 },
]

const SAVE10: Coupon = {
  code: 'SAVE10',
  promotion: { id: 'save-ten', kind: 'percentage', percent: 10 },
  expiresOn: '2026-03-31',
  usageLimit: 2,
}

describe('promotions', () => {
  it('prices lines with the promotions that always apply', () => {
    const engine = new PromotionEngine()
    engine.addPromotion({ id: 'off', kind: 'fixed', amount: 200 })
    expect(engine.quote(LINES, [], TODAY)).toEqual({
      subtotal: 1500,
      discounts: [{ promotionId: 'off', amount: 200 }],
      total: 1300,
    })
  })

  it('ends a promotion', () => {
    const engine = new PromotionEngine()
    engine.addPromotion({ id: 'off', kind: 'fixed', amount: 200 })
    engine.removePromotion('off')
    expect(engine.quote(LINES, [], TODAY).total).toBe(1500)
    expect(() => engine.removePromotion('off')).toThrow('unknown promotion off')
  })

  it('lists the promotions that can take money off a SKU', () => {
    const engine = new PromotionEngine()
    engine.addPromotion({ id: 'all', kind: 'percentage', percent: 5 })
    engine.addPromotion({ id: 'pears', kind: 'percentage', percent: 10, skus: ['pear'] })
    expect(engine.promotionsFor('pear').map((p) => p.id)).toEqual(['all', 'pears'])
    expect(engine.promotionsFor('apple').map((p) => p.id)).toEqual(['all'])
    expect(engine.activePromotions()).toHaveLength(2)
  })

  it('rejects a promotion id that is already in the engine', () => {
    const engine = new PromotionEngine()
    engine.addPromotion({ id: 'off', kind: 'fixed', amount: 200 })
    expect(() => engine.addPromotion({ id: 'off', kind: 'fixed', amount: 100 })).toThrow(
      'promotion off already exists'
    )
  })
})

describe('coupons', () => {
  it('counts the uses of each coupon on each redeem', () => {
    const engine = new PromotionEngine()
    engine.addCoupon(SAVE10)
    engine.quote(LINES, ['SAVE10'], TODAY)
    engine.redeem(LINES, ['SAVE10'], TODAY)
    expect(engine.couponUsage()).toEqual([
      { code: 'SAVE10', uses: 1, usageLimit: 2, expiresOn: '2026-03-31' },
    ])
  })

  it('withdraws a coupon that no one has used', () => {
    const engine = new PromotionEngine()
    engine.addCoupon(SAVE10)
    engine.addCoupon({ ...SAVE10, code: 'USED', promotion: { ...SAVE10.promotion, id: 'u' } })
    engine.redeem(LINES, ['USED'], TODAY)
    engine.removeCoupon('SAVE10')
    expect(() => engine.quote(LINES, ['SAVE10'], TODAY)).toThrow('unknown coupon SAVE10')
    expect(() => engine.removeCoupon('USED')).toThrow('coupon USED has been used')
    expect(() => engine.removeCoupon('NOPE')).toThrow('unknown coupon NOPE')
  })

  it('checks the lines before the coupons', () => {
    const engine = new PromotionEngine()
    const lines = [{ sku: 'apple', unitPrice: 250, quantity: 0 }]
    expect(() => engine.quote(lines, ['NOPE'], TODAY)).toThrow('quantity must be at least 1')
  })
})

describe('explanations', () => {
  it('explains a quote without using a coupon', () => {
    const engine = new PromotionEngine()
    engine.addCoupon({ ...SAVE10, usageLimit: 1 })
    engine.addPromotion({ id: 'kiwi', kind: 'fixed', amount: 100, skus: ['kiwi'] })
    expect(engine.explain(LINES, ['SAVE10'], TODAY)).toEqual([
      { promotionId: 'kiwi', outcome: 'nothing to take', amount: 0 },
      { promotionId: 'save-ten', outcome: 'applied', amount: 150 },
    ])
    expect(engine.redeem(LINES, ['SAVE10'], TODAY).total).toBe(1350)
  })

  it('describes its promotions and coupons in words', () => {
    const engine = new PromotionEngine()
    engine.addPromotion({ id: 'pears', kind: 'percentage', percent: 10, skus: ['pear'] })
    engine.addCoupon(SAVE10)
    expect(engine.describe()).toEqual([
      '10% off pear',
      'SAVE10: 10% off everything, until 2026-03-31',
    ])
  })
})
