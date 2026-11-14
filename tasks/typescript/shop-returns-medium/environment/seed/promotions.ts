// The promotions engine: the promotions and coupons that take money off a
// cart, and the rules by which they stack.

export type {
  Coupon,
  Discount,
  Line,
  Outcome,
  PricingStep,
  Promotion,
  PromotionKind,
  Quote,
} from './domain/promotion.ts'
export { describePromotion } from './domain/promotion.ts'
export type { CouponUsage } from './services/promotion-engine.ts'
export { PromotionEngine } from './services/promotion-engine.ts'
