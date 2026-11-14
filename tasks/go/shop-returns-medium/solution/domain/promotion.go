// Promotions: the rules that take money off a cart. A promotion is a
// percentage or a fixed amount off, buy X get Y free, or a bundle price for a
// set of SKUs. The pricing works line by line on what earlier promotions left
// of each line, so that the discounts never take a line below zero. What each
// promotion took from a line is its part of the discount on that line.

package domain

import (
	"cmp"
	"fmt"
	"slices"
	"strings"
)

type PromotionKind string // `percentage`, `fixed`, `buy-x-get-y` or `bundle`

type Line struct {
	SKU       string
	UnitPrice Cents
	Quantity  int
}

type Promotion struct {
	ID        string
	Kind      PromotionKind
	SKUs      []string // the SKUs that it applies to; every SKU when empty
	Percent   int      // percentage
	Amount    Cents    // fixed
	Buy       int      // buy-x-get-y
	Get       int      // buy-x-get-y
	Price     Cents    // bundle: the price of one set of its SKUs
	Priority  int      // higher first
	Exclusive bool     // applies only alone
}

type Coupon struct {
	Code       string
	Promotion  Promotion
	ExpiresOn  string
	UsageLimit int
}

type Discount struct {
	PromotionID string
	Amount      Cents
}

type Quote struct {
	Subtotal  Cents
	Discounts []Discount
	Total     Cents
}

func ValidatePromotion(p Promotion) error {
	switch p.Kind {
	case "percentage":
		return Check(p.Percent >= 1 && p.Percent <= 100, "percent must be between 1 and 100")
	case "fixed":
		return Check(p.Amount > 0, "amount must be positive")
	case "buy-x-get-y":
		return Check(p.Buy >= 1 && p.Get >= 1, "buy and get must be at least 1")
	case "bundle":
		return first(Check(len(p.SKUs) >= 2, "a bundle needs at least two SKUs"),
			Check(p.Price >= 0, "bundle price must not be negative"))
	}
	return Invalid(fmt.Sprintf("unknown promotion kind %s", p.Kind))
}

// Precedence is the order in which promotions are considered: the highest
// priority first, then by id.
func Precedence(a, b Promotion) int {
	return cmp.Or(b.Priority-a.Priority, CompareText(a.ID, b.ID))
}

// CheckLines checks the lines of a cart: a quantity of at least 1, and each
// SKU once.
func CheckLines(lines []Line) error {
	for i, line := range lines {
		if line.Quantity < 1 {
			return Invalid("quantity must be at least 1")
		}
		if slices.ContainsFunc(lines[:i], func(l Line) bool { return l.SKU == line.SKU }) {
			return Invalid(fmt.Sprintf("SKU %s is in more than one line", line.SKU))
		}
	}
	return nil
}

// ApplyPromotion applies one promotion to the remaining amounts of the lines,
// and gives what it took off in all. It changes `remaining`.
func ApplyPromotion(p Promotion, lines []Line, remaining []Cents) Cents {
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
			discount := PercentOf(remaining[i], p.Percent)
			if p.Kind == "buy-x-get-y" {
				free := lines[i].Quantity / (p.Buy + p.Get) * p.Get
				discount = min(Times(lines[i].UnitPrice, free), remaining[i])
			}
			remaining[i] -= discount
			total += discount
		}
	case "fixed":
		total = TakeInOrder(remaining, eligible, p.Amount)
	case "bundle":
		var members []int
		sets, full := -1, 0
		for _, sku := range p.SKUs {
			i := slices.IndexFunc(lines, func(line Line) bool { return line.SKU == sku })
			if i < 0 {
				return 0
			}
			members = append(members, i)
			if sets < 0 || lines[i].Quantity < sets {
				sets = lines[i].Quantity
			}
			full += lines[i].UnitPrice
		}
		if saving := full - p.Price; sets > 0 && saving > 0 {
			slices.Sort(members)
			total = TakeInOrder(remaining, members, Times(saving, sets))
		}
	}
	return total
}

// PriceLines prices the lines with the promotions, in order of precedence.
// Each promotion works on what the earlier ones left. An exclusive promotion
// applies only when no earlier promotion took anything off, and then stops
// the rest. A promotion that takes nothing off is left out.
func PriceLines(lines []Line, promotions []Promotion) (Quote, error) {
	steps, err := ExplainPricing(lines, promotions)
	if err != nil {
		return Quote{}, err
	}
	quote := Quote{Discounts: []Discount{}}
	for _, line := range lines {
		quote.Subtotal += Times(line.UnitPrice, line.Quantity)
	}
	quote.Total = quote.Subtotal
	for _, step := range steps {
		if step.Outcome == "applied" {
			quote.Discounts = append(quote.Discounts, Discount{step.PromotionID, step.Amount})
			quote.Total -= step.Amount
		}
	}
	return quote, nil
}

// Outcome is what happened to one promotion when the lines were priced:
// `applied` (it took the amount off), `nothing to take` (it applies to none
// of the lines, or what is left of them), `not alone` (it is exclusive, and
// an earlier promotion applied) or `after exclusive` (an exclusive promotion
// applied before it).
type Outcome string

type PricingStep struct {
	PromotionID string
	Outcome     Outcome
	Amount      Cents
}

// ExplainPricing gives each promotion, in order of precedence, with what it
// did to the lines: the reasons behind a quote.
func ExplainPricing(lines []Line, promotions []Promotion) ([]PricingStep, error) {
	steps, _, err := pricing(lines, promotions)
	return steps, err
}

// DiscountsByLine gives the part of each discount on each line, as
// PriceLines prices them: what each promotion took from the remaining amount
// of the line. One list for each line, in the order that the promotions
// applied; no part of 0.
func DiscountsByLine(lines []Line, promotions []Promotion) ([][]Discount, error) {
	_, parts, err := pricing(lines, promotions)
	return parts, err
}

func pricing(lines []Line, promotions []Promotion) ([]PricingStep, [][]Discount, error) {
	if err := CheckLines(lines); err != nil {
		return nil, nil, err
	}
	parts := make([][]Discount, len(lines))
	remaining := make([]Cents, len(lines))
	for i, line := range lines {
		remaining[i] = Times(line.UnitPrice, line.Quantity)
	}
	steps, applied, stopped := []PricingStep{}, 0, false
	for _, p := range slices.SortedStableFunc(slices.Values(promotions), Precedence) {
		step := PricingStep{PromotionID: p.ID, Outcome: "after exclusive"}
		if !stopped && p.Exclusive && applied > 0 {
			step.Outcome = "not alone"
		} else if !stopped {
			step.Outcome = "nothing to take"
			before := slices.Clone(remaining)
			step.Amount = ApplyPromotion(p, lines, remaining)
			for i, left := range remaining {
				if left < before[i] {
					parts[i] = append(parts[i], Discount{PromotionID: p.ID, Amount: before[i] - left})
				}
			}
			if step.Amount > 0 {
				step.Outcome = "applied"
				applied++
				stopped = p.Exclusive
			}
		}
		steps = append(steps, step)
	}
	return steps, parts, nil
}

// DescribePromotion puts a promotion in words, as the shop shows it to
// customers.
func DescribePromotion(p Promotion) string {
	on := strings.Join(p.SKUs, ", ")
	if len(p.SKUs) == 0 {
		on = "everything"
	}
	text := string(p.Kind)
	switch p.Kind {
	case "percentage":
		text = fmt.Sprintf("%d%% off %s", p.Percent, on)
	case "fixed":
		text = fmt.Sprintf("%s off %s", FormatCents(p.Amount), on)
	case "buy-x-get-y":
		text = fmt.Sprintf("buy %d get %d free on %s", p.Buy, p.Get, on)
	case "bundle":
		text = fmt.Sprintf("%s for %s", strings.Join(p.SKUs, " + "), FormatCents(p.Price))
	}
	if p.Exclusive {
		text += " (not with other offers)"
	}
	return text
}
