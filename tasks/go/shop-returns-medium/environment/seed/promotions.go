// The promotions engine: the promotions and coupons that take money off a
// cart, and the rules by which they stack.

package shop

import (
	"shop/domain"
	"shop/services"
)

type (
	Coupon          = domain.Coupon
	Discount        = domain.Discount
	Line            = domain.Line
	Outcome         = domain.Outcome
	PricingStep     = domain.PricingStep
	Promotion       = domain.Promotion
	PromotionKind   = domain.PromotionKind
	Quote           = domain.Quote
	CouponUsage     = services.CouponUsage
	PromotionEngine = services.PromotionEngine
)

var (
	DescribePromotion  = domain.DescribePromotion
	NewPromotionEngine = services.NewPromotionEngine
)
