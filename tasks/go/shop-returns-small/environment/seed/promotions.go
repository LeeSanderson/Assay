package shop

import (
	"cmp"
	"errors"
	"fmt"
	"math"
	"slices"
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
	if err == nil {
		for _, code := range coupons {
			e.uses[code]++
		}
	}
	return quote, err
}

func (e *PromotionEngine) checkNewPromotion(p Promotion) error {
	taken := slices.ContainsFunc(e.promotions, func(q Promotion) bool { return q.ID == p.ID })
	for _, coupon := range e.coupons {
		taken = taken || coupon.Promotion.ID == p.ID
	}
	switch {
	case taken:
		return fmt.Errorf("promotion %s already exists", p.ID)
	case p.Kind == "percentage" && (p.Percent < 1 || p.Percent > 100):
		return errors.New("percent must be between 1 and 100")
	case p.Kind == "fixed" && p.Amount <= 0:
		return errors.New("amount must be positive")
	case p.Kind == "buy-x-get-y" && (p.Buy < 1 || p.Get < 1):
		return errors.New("buy and get must be at least 1")
	case p.Kind == "bundle" && len(p.SKUs) < 2:
		return errors.New("a bundle needs at least two SKUs")
	case p.Kind == "bundle" && p.Price < 0:
		return errors.New("bundle price must not be negative")
	case !slices.Contains([]PromotionKind{"percentage", "fixed", "buy-x-get-y", "bundle"}, p.Kind):
		return fmt.Errorf("unknown promotion kind %s", p.Kind)
	}
	return nil
}

// takeInOrder takes up to amount from the remaining amounts of the lines, in order.
func takeInOrder(remaining []int, indexes []int, amount int) int {
	left := amount
	for _, i := range indexes {
		take := min(left, remaining[i])
		remaining[i] -= take
		left -= take
	}
	return amount - left
}

func apply(p Promotion, lines []Line, remaining []int) int {
	var eligible []int
	for i, line := range lines {
		if len(p.SKUs) == 0 || slices.Contains(p.SKUs, line.SKU) {
			eligible = append(eligible, i)
		}
	}
	total := 0
	switch p.Kind {
	case "percentage", "buy-x-get-y":
		for _, i := range eligible {
			discount := remaining[i] * p.Percent / 100
			if p.Kind == "buy-x-get-y" {
				free := lines[i].Quantity / (p.Buy + p.Get) * p.Get
				discount = min(free*lines[i].UnitPrice, remaining[i])
			}
			remaining[i] -= discount
			total += discount
		}
	case "fixed":
		total = takeInOrder(remaining, eligible, p.Amount)
	case "bundle":
		sets, saving := math.MaxInt, -p.Price
		for _, sku := range p.SKUs {
			i := slices.IndexFunc(lines, func(line Line) bool { return line.SKU == sku })
			if i < 0 {
				return 0
			}
			sets = min(sets, lines[i].Quantity)
			saving += lines[i].UnitPrice
		}
		if saving > 0 {
			total = takeInOrder(remaining, eligible, sets*saving)
		}
	}
	return total
}

func (e *PromotionEngine) price(lines []Line, codes []string, today string) (Quote, error) {
	quote, remaining := Quote{}, make([]int, len(lines))
	for i, line := range lines {
		if line.Quantity < 1 {
			return Quote{}, errors.New("quantity must be at least 1")
		}
		if slices.ContainsFunc(lines[:i], func(l Line) bool { return l.SKU == line.SKU }) {
			return Quote{}, fmt.Errorf("SKU %s is in more than one line", line.SKU)
		}
		remaining[i] = line.UnitPrice * line.Quantity
		quote.Subtotal += remaining[i]
	}
	considered := slices.Clone(e.promotions)
	for i, code := range codes {
		coupon, ok := e.coupons[code]
		switch {
		case slices.Contains(codes[:i], code):
			return Quote{}, fmt.Errorf("coupon %s given more than once", code)
		case !ok:
			return Quote{}, fmt.Errorf("unknown coupon %s", code)
		case today > coupon.ExpiresOn:
			return Quote{}, fmt.Errorf("coupon %s has expired", code)
		case e.uses[code] >= coupon.UsageLimit:
			return Quote{}, fmt.Errorf("coupon %s has reached its usage limit", code)
		}
		considered = append(considered, coupon.Promotion)
	}
	// The highest priority first, then by id.
	slices.SortStableFunc(considered, func(a, b Promotion) int {
		return cmp.Or(cmp.Compare(b.Priority, a.Priority), cmp.Compare(a.ID, b.ID))
	})
	quote.Total = quote.Subtotal
	for _, p := range considered {
		if p.Exclusive && len(quote.Discounts) > 0 {
			continue
		}
		if amount := apply(p, lines, remaining); amount > 0 {
			quote.Discounts = append(quote.Discounts, Discount{PromotionID: p.ID, Amount: amount})
			quote.Total -= amount
			if p.Exclusive {
				break
			}
		}
	}
	return quote, nil
}
