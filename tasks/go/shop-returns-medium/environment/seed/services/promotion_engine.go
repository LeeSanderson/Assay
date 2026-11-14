// The promotions engine: the promotions that the shop runs, and the coupons
// that customers can give at checkout. It prices lines with the promotions
// that always apply and those of the coupons given. A quote uses no coupon;
// a redeem uses each coupon given once. The engine holds its promotions and
// coupons in memory: they are the shop's configuration, not its records.

package services

import (
	"fmt"
	"maps"
	"slices"

	. "shop/domain"
)

// CouponUsage is a coupon and how many times it has been used.
type CouponUsage struct {
	Code       string
	Uses       int
	UsageLimit int
	ExpiresOn  string
}

type PromotionEngine struct {
	promotions []Promotion
	coupons    map[string]Coupon
	uses       map[string]int
}

func NewPromotionEngine() *PromotionEngine {
	return &PromotionEngine{coupons: map[string]Coupon{}, uses: map[string]int{}}
}

func (e *PromotionEngine) AddPromotion(promotion Promotion) error {
	if err := e.checkNewPromotion(promotion); err != nil {
		return err
	}
	e.promotions = append(e.promotions, promotion)
	return nil
}

// RemovePromotion ends a promotion that always applies.
func (e *PromotionEngine) RemovePromotion(id string) error {
	i := slices.IndexFunc(e.promotions, func(p Promotion) bool { return p.ID == id })
	if i < 0 {
		return NotFound("promotion", id)
	}
	e.promotions = slices.Delete(e.promotions, i, i+1)
	return nil
}

func (e *PromotionEngine) AddCoupon(coupon Coupon) error {
	if _, ok := e.coupons[coupon.Code]; ok {
		return Conflict(fmt.Sprintf("coupon %s already exists", coupon.Code))
	}
	if err := first(Check(coupon.UsageLimit >= 1, "usage limit must be at least 1"),
		e.checkNewPromotion(coupon.Promotion)); err != nil {
		return err
	}
	e.coupons[coupon.Code] = coupon
	e.uses[coupon.Code] = 0
	return nil
}

// RemoveCoupon withdraws a coupon that no one has used yet.
func (e *PromotionEngine) RemoveCoupon(code string) error {
	if _, ok := e.coupons[code]; !ok {
		return NotFound("coupon", code)
	}
	if e.uses[code] > 0 {
		return Invalid(fmt.Sprintf("coupon %s has been used", code))
	}
	delete(e.coupons, code)
	delete(e.uses, code)
	return nil
}

// PromotionsFor gives the promotions that always apply and can take money
// off the SKU: those that name it, and those that name no SKU, in the order
// that they were added.
func (e *PromotionEngine) PromotionsFor(sku string) []Promotion {
	return slices.DeleteFunc(e.ActivePromotions(), func(p Promotion) bool {
		return len(p.SKUs) > 0 && !slices.Contains(p.SKUs, sku)
	})
}

// ActivePromotions gives the promotions that always apply, in the order that
// they were added.
func (e *PromotionEngine) ActivePromotions() []Promotion { return slices.Clone(e.promotions) }

// CouponUsage gives the coupons and their uses, by code.
func (e *PromotionEngine) CouponUsage() []CouponUsage {
	usage := []CouponUsage{}
	for _, code := range slices.Sorted(maps.Keys(e.coupons)) {
		coupon := e.coupons[code]
		usage = append(usage, CouponUsage{code, e.uses[code], coupon.UsageLimit, coupon.ExpiresOn})
	}
	return usage
}

func (e *PromotionEngine) Quote(lines []Line, coupons []string, today string) (Quote, error) {
	return e.price(lines, coupons, today)
}

func (e *PromotionEngine) Redeem(lines []Line, coupons []string, today string) (Quote, error) {
	quote, err := e.price(lines, coupons, today)
	if err == nil {
		for _, code := range coupons {
			e.uses[code]++
		}
	}
	return quote, err
}

func (e *PromotionEngine) checkNewPromotion(promotion Promotion) error {
	taken := slices.ContainsFunc(e.promotions, func(p Promotion) bool { return p.ID == promotion.ID })
	for _, coupon := range e.coupons {
		taken = taken || coupon.Promotion.ID == promotion.ID
	}
	if taken {
		return Conflict(fmt.Sprintf("promotion %s already exists", promotion.ID))
	}
	return ValidatePromotion(promotion)
}

// Explain gives what each promotion would do to the lines, and why, as Quote
// prices them. It uses no coupon.
func (e *PromotionEngine) Explain(lines []Line, coupons []string, today string) ([]PricingStep, error) {
	considered, err := e.considered(lines, coupons, today)
	if err != nil {
		return nil, err
	}
	return ExplainPricing(lines, considered)
}

// Describe puts the promotions and coupons in words, the promotions first,
// then the coupons by code.
func (e *PromotionEngine) Describe() []string {
	texts := []string{}
	for _, promotion := range e.promotions {
		texts = append(texts, DescribePromotion(promotion))
	}
	for _, code := range slices.Sorted(maps.Keys(e.coupons)) {
		coupon := e.coupons[code]
		texts = append(texts, fmt.Sprintf("%s: %s, until %s", code, DescribePromotion(coupon.Promotion), coupon.ExpiresOn))
	}
	return texts
}

func (e *PromotionEngine) price(lines []Line, codes []string, today string) (Quote, error) {
	considered, err := e.considered(lines, codes, today)
	if err != nil {
		return Quote{}, err
	}
	return PriceLines(lines, considered)
}

// considered gives the promotions that apply: those that always do, and
// those of the coupons. It checks the lines first, then each coupon in the
// order given.
func (e *PromotionEngine) considered(lines []Line, codes []string, today string) ([]Promotion, error) {
	if err := CheckLines(lines); err != nil {
		return nil, err
	}
	considered := slices.Clone(e.promotions)
	for i, code := range codes {
		coupon, ok := e.coupons[code]
		switch {
		case slices.Contains(codes[:i], code):
			return nil, Invalid(fmt.Sprintf("coupon %s given more than once", code))
		case !ok:
			return nil, NotFound("coupon", code)
		case today > coupon.ExpiresOn:
			return nil, Invalid(fmt.Sprintf("coupon %s has expired", code))
		case e.uses[code] >= coupon.UsageLimit:
			return nil, Invalid(fmt.Sprintf("coupon %s has reached its usage limit", code))
		}
		considered = append(considered, coupon.Promotion)
	}
	return considered, nil
}
