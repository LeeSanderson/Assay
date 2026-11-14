// The promotions engine: the promotions that the shop runs, and the coupons
// that customers can give at checkout. It prices lines with the promotions
// that always apply and those of the coupons given. A quote uses no coupon;
// a redeem uses each coupon given once. The engine holds its promotions and
// coupons in memory: they are the shop's configuration, not its records.

import { conflict, invalid, notFound } from '../domain/errors.ts'
import { compareText } from '../domain/ids.ts'
import {
  checkLines,
  describePromotion,
  explainPricing,
  priceLines,
  validatePromotion,
} from '../domain/promotion.ts'
import type { Coupon, Line, PricingStep, Promotion, Quote } from '../domain/promotion.ts'

// A coupon and how many times it has been used.
export interface CouponUsage {
  code: string
  uses: number
  usageLimit: number
  expiresOn: string
}

export class PromotionEngine {
  private readonly promotions: Promotion[] = []
  private readonly coupons = new Map<string, Coupon>()
  private readonly uses = new Map<string, number>()

  public addPromotion(promotion: Promotion): void {
    this.checkNewPromotion(promotion)
    this.promotions.push(promotion)
  }

  // Ends a promotion that always applies.
  public removePromotion(id: string): void {
    const index = this.promotions.findIndex((promotion) => promotion.id === id)
    if (index === -1) {
      throw notFound('promotion', id)
    }
    this.promotions.splice(index, 1)
  }

  public addCoupon(coupon: Coupon): void {
    if (this.coupons.has(coupon.code)) {
      throw conflict(`coupon ${coupon.code} already exists`)
    }
    if (coupon.usageLimit < 1) throw invalid('usage limit must be at least 1')
    this.checkNewPromotion(coupon.promotion)
    this.coupons.set(coupon.code, coupon)
    this.uses.set(coupon.code, 0)
  }

  // Withdraws a coupon that no one has used yet.
  public removeCoupon(code: string): void {
    if (!this.coupons.has(code)) {
      throw notFound('coupon', code)
    }
    if ((this.uses.get(code) ?? 0) > 0) {
      throw invalid(`coupon ${code} has been used`)
    }
    this.coupons.delete(code)
    this.uses.delete(code)
  }

  // The promotions that always apply and can take money off the SKU: those
  // that name it, and those that name no SKU, in the order that they were
  // added.
  public promotionsFor(sku: string): Promotion[] {
    return this.activePromotions().filter(
      (promotion) => (promotion.skus ?? []).length === 0 || promotion.skus?.includes(sku)
    )
  }

  // The promotions that always apply, in the order that they were added.
  public activePromotions(): Promotion[] {
    return this.promotions.map((promotion) => ({ ...promotion }))
  }

  // The coupons and their uses, by code.
  public couponUsage(): CouponUsage[] {
    return [...this.coupons.values()]
      .map((coupon) => ({
        code: coupon.code,
        uses: this.uses.get(coupon.code) ?? 0,
        usageLimit: coupon.usageLimit,
        expiresOn: coupon.expiresOn,
      }))
      .sort((a, b) => compareText(a.code, b.code))
  }

  public quote(lines: Line[], coupons: string[], today: string): Quote {
    return this.price(lines, coupons, today)
  }

  public redeem(lines: Line[], coupons: string[], today: string): Quote {
    const quote = this.price(lines, coupons, today)
    for (const code of coupons) {
      this.uses.set(code, (this.uses.get(code) ?? 0) + 1)
    }
    return quote
  }

  private checkNewPromotion(promotion: Promotion): void {
    const ids = [...this.promotions, ...[...this.coupons.values()].map((c) => c.promotion)]
    if (ids.some((p) => p.id === promotion.id)) {
      throw conflict(`promotion ${promotion.id} already exists`)
    }
    validatePromotion(promotion)
  }

  // What each promotion would do to the lines, and why, as `quote` prices
  // them. It uses no coupon.
  public explain(lines: Line[], coupons: string[], today: string): PricingStep[] {
    return explainPricing(lines, this.considered(lines, coupons, today))
  }

  // The promotions and coupons in words, the promotions first, then the
  // coupons by code.
  public describe(): string[] {
    const coupons = [...this.coupons.values()].sort((a, b) => compareText(a.code, b.code))
    return [
      ...this.promotions.map(describePromotion),
      ...coupons.map(
        (coupon) =>
          `${coupon.code}: ${describePromotion(coupon.promotion)}, until ${coupon.expiresOn}`
      ),
    ]
  }

  private price(lines: Line[], codes: string[], today: string): Quote {
    return priceLines(lines, this.considered(lines, codes, today))
  }

  // The promotions that apply: those that always do, and those of the
  // coupons. It checks the lines first, then each coupon in the order given.
  private considered(lines: Line[], codes: string[], today: string): Promotion[] {
    checkLines(lines)
    const considered = [...this.promotions]
    const given = new Set<string>()
    for (const code of codes) {
      if (given.has(code)) throw invalid(`coupon ${code} given more than once`)
      given.add(code)
      const coupon = this.coupons.get(code)
      if (coupon === undefined) throw notFound('coupon', code)
      if (today > coupon.expiresOn) throw invalid(`coupon ${code} has expired`)
      if ((this.uses.get(code) ?? 0) >= coupon.usageLimit) {
        throw invalid(`coupon ${code} has reached its usage limit`)
      }
      considered.push(coupon.promotion)
    }
    return considered
  }
}
