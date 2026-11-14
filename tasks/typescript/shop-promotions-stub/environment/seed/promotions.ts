export type PromotionKind = 'percentage' | 'fixed' | 'buy-x-get-y' | 'bundle'

export interface Line {
  sku: string
  unitPrice: number
  quantity: number
}

export interface Promotion {
  id: string
  kind: PromotionKind
  skus?: string[]
  percent?: number
  amount?: number
  buy?: number
  get?: number
  price?: number
  priority?: number
  exclusive?: boolean
}

export interface Coupon {
  code: string
  promotion: Promotion
  expiresOn: string
  usageLimit: number
}

export interface Discount {
  promotionId: string
  amount: number
}

export interface Quote {
  subtotal: number
  discounts: Discount[]
  total: number
}

export class PromotionEngine {
  public addPromotion(promotion: Promotion): void {
    throw new Error('Not implemented')
  }

  public addCoupon(coupon: Coupon): void {
    throw new Error('Not implemented')
  }

  public quote(lines: Line[], coupons: string[], today: string): Quote {
    throw new Error('Not implemented')
  }

  public redeem(lines: Line[], coupons: string[], today: string): Quote {
    throw new Error('Not implemented')
  }
}
