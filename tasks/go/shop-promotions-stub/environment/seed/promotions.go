package shop

import "errors"

type PromotionKind string

type Line struct {
	SKU       string
	UnitPrice int
	Quantity  int
}

type Promotion struct {
	ID        string
	Kind      PromotionKind
	SKUs      []string
	Percent   int
	Amount    int
	Buy       int
	Get       int
	Price     int
	Priority  int
	Exclusive bool
}

type Coupon struct {
	Code       string
	Promotion  Promotion
	ExpiresOn  string
	UsageLimit int
}

type Discount struct {
	PromotionID string
	Amount      int
}

type Quote struct {
	Subtotal  int
	Discounts []Discount
	Total     int
}

type PromotionEngine struct{}

func NewPromotionEngine() *PromotionEngine {
	return &PromotionEngine{}
}

func (e *PromotionEngine) AddPromotion(promotion Promotion) error {
	return errors.New("not implemented")
}

func (e *PromotionEngine) AddCoupon(coupon Coupon) error {
	return errors.New("not implemented")
}

func (e *PromotionEngine) Quote(lines []Line, coupons []string, today string) (Quote, error) {
	return Quote{}, errors.New("not implemented")
}

func (e *PromotionEngine) Redeem(lines []Line, coupons []string, today string) (Quote, error) {
	return Quote{}, errors.New("not implemented")
}
