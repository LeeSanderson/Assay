package shop

import (
	"errors"
	"fmt"
	"sort"
)

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

type PromotionEngine struct {
	promotions []Promotion
	coupons    map[string]Coupon
	uses       map[string]int
}

func NewPromotionEngine() *PromotionEngine {
	return &PromotionEngine{coupons: map[string]Coupon{}, uses: map[string]int{}}
}

func validate(p Promotion) error {
	switch p.Kind {
	case "percentage":
		if p.Percent < 1 || p.Percent > 100 {
			return errors.New("percent must be between 1 and 100")
		}
	case "fixed":
		if p.Amount <= 0 {
			return errors.New("amount must be positive")
		}
	case "buy-x-get-y":
		if p.Buy < 1 || p.Get < 1 {
			return errors.New("buy and get must be at least 1")
		}
	case "bundle":
		if len(p.SKUs) < 2 {
			return errors.New("a bundle needs at least two SKUs")
		}
		if p.Price < 0 {
			return errors.New("bundle price must not be negative")
		}
	default:
		return fmt.Errorf("unknown promotion kind %s", p.Kind)
	}
	return nil
}

func (e *PromotionEngine) checkNewPromotion(p Promotion) error {
	for _, existing := range e.promotions {
		if existing.ID == p.ID {
			return fmt.Errorf("promotion %s already exists", p.ID)
		}
	}
	for _, coupon := range e.coupons {
		if coupon.Promotion.ID == p.ID {
			return fmt.Errorf("promotion %s already exists", p.ID)
		}
	}
	return validate(p)
}

func (e *PromotionEngine) AddPromotion(promotion Promotion) error {
	if err := e.checkNewPromotion(promotion); err != nil {
		return err
	}
	e.promotions = append(e.promotions, promotion)
	return nil
}

func (e *PromotionEngine) AddCoupon(coupon Coupon) error {
	if _, ok := e.coupons[coupon.Code]; ok {
		return fmt.Errorf("coupon %s already exists", coupon.Code)
	}
	if coupon.UsageLimit < 1 {
		return errors.New("usage limit must be at least 1")
	}
	if err := e.checkNewPromotion(coupon.Promotion); err != nil {
		return err
	}
	e.coupons[coupon.Code] = coupon
	return nil
}

func (e *PromotionEngine) Quote(lines []Line, coupons []string, today string) (Quote, error) {
	return e.price(lines, coupons, today)
}

func (e *PromotionEngine) Redeem(lines []Line, coupons []string, today string) (Quote, error) {
	quote, err := e.price(lines, coupons, today)
	if err != nil {
		return Quote{}, err
	}
	for _, code := range coupons {
		e.uses[code]++
	}
	return quote, nil
}

// takeInOrder takes up to amount from the remaining amounts of the given
// lines, in cart order, and returns what it took.
func takeInOrder(remaining []int, indexes []int, amount int) int {
	left := amount
	for _, i := range indexes {
		take := min(left, remaining[i])
		remaining[i] -= take
		left -= take
	}
	return amount - left
}

func contains(list []string, s string) bool {
	for _, item := range list {
		if item == s {
			return true
		}
	}
	return false
}

func apply(p Promotion, lines []Line, remaining []int) int {
	var eligible []int
	for i, line := range lines {
		if len(p.SKUs) == 0 || contains(p.SKUs, line.SKU) {
			eligible = append(eligible, i)
		}
	}
	total := 0
	switch p.Kind {
	case "percentage":
		for _, i := range eligible {
			discount := remaining[i] * p.Percent / 100
			remaining[i] -= discount
			total += discount
		}
	case "fixed":
		total = takeInOrder(remaining, eligible, p.Amount)
	case "buy-x-get-y":
		for _, i := range eligible {
			free := lines[i].Quantity / (p.Buy + p.Get) * p.Get
			discount := min(free*lines[i].UnitPrice, remaining[i])
			remaining[i] -= discount
			total += discount
		}
	case "bundle":
		var members []int
		sets, full := -1, 0
		for _, sku := range p.SKUs {
			found := -1
			for i, line := range lines {
				if line.SKU == sku {
					found = i
				}
			}
			if found < 0 {
				return 0
			}
			members = append(members, found)
			if sets < 0 || lines[found].Quantity < sets {
				sets = lines[found].Quantity
			}
			full += lines[found].UnitPrice
		}
		saving := full - p.Price
		if sets <= 0 || saving <= 0 {
			return 0
		}
		sort.Ints(members)
		total = takeInOrder(remaining, members, sets*saving)
	}
	return total
}

func (e *PromotionEngine) price(lines []Line, codes []string, today string) (Quote, error) {
	skus := map[string]bool{}
	for _, line := range lines {
		if line.Quantity < 1 {
			return Quote{}, errors.New("quantity must be at least 1")
		}
		if skus[line.SKU] {
			return Quote{}, fmt.Errorf("SKU %s is in more than one line", line.SKU)
		}
		skus[line.SKU] = true
	}
	considered := append([]Promotion(nil), e.promotions...)
	given := map[string]bool{}
	for _, code := range codes {
		if given[code] {
			return Quote{}, fmt.Errorf("coupon %s given more than once", code)
		}
		given[code] = true
		coupon, ok := e.coupons[code]
		if !ok {
			return Quote{}, fmt.Errorf("unknown coupon %s", code)
		}
		if today > coupon.ExpiresOn {
			return Quote{}, fmt.Errorf("coupon %s has expired", code)
		}
		if e.uses[code] >= coupon.UsageLimit {
			return Quote{}, fmt.Errorf("coupon %s has reached its usage limit", code)
		}
		considered = append(considered, coupon.Promotion)
	}
	// The highest priority first, then by id.
	sort.SliceStable(considered, func(a, b int) bool {
		if considered[a].Priority != considered[b].Priority {
			return considered[a].Priority > considered[b].Priority
		}
		return considered[a].ID < considered[b].ID
	})

	remaining := make([]int, len(lines))
	subtotal := 0
	for i, line := range lines {
		remaining[i] = line.UnitPrice * line.Quantity
		subtotal += remaining[i]
	}
	quote := Quote{Subtotal: subtotal, Total: subtotal}
	for _, p := range considered {
		if p.Exclusive && len(quote.Discounts) > 0 {
			continue
		}
		amount := apply(p, lines, remaining)
		if amount == 0 {
			continue
		}
		quote.Discounts = append(quote.Discounts, Discount{PromotionID: p.ID, Amount: amount})
		quote.Total -= amount
		if p.Exclusive {
			break
		}
	}
	return quote, nil
}
