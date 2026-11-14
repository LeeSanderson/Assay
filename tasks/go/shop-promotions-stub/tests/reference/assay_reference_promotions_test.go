package shop

import (
	"fmt"
	"testing"
)

const today = "2026-03-10"

// cart is the cart that most cases price: a subtotal of 1500.
func cart() []Line {
	return []Line{
		{SKU: "apple", UnitPrice: 250, Quantity: 2},
		{SKU: "pear", UnitPrice: 1000, Quantity: 1},
	}
}

func engineWith(t *testing.T, promotions ...Promotion) *PromotionEngine {
	t.Helper()
	engine := NewPromotionEngine()
	for _, promotion := range promotions {
		if err := engine.AddPromotion(promotion); err != nil {
			t.Fatalf("AddPromotion(%+v) = %v", promotion, err)
		}
	}
	return engine
}

func engineWithCoupon(t *testing.T, coupon Coupon, promotions ...Promotion) *PromotionEngine {
	t.Helper()
	engine := engineWith(t, promotions...)
	if err := engine.AddCoupon(coupon); err != nil {
		t.Fatalf("AddCoupon(%+v) = %v", coupon, err)
	}
	return engine
}

func saveTen(usageLimit int) Coupon {
	return Coupon{
		Code:       "SAVE10",
		Promotion:  Promotion{ID: "save-ten", Kind: "percentage", Percent: 10},
		ExpiresOn:  "2026-03-31",
		UsageLimit: usageLimit,
	}
}

func discounts(pairs ...any) []Discount {
	var list []Discount
	for i := 0; i < len(pairs); i += 2 {
		list = append(list, Discount{PromotionID: pairs[i].(string), Amount: pairs[i+1].(int)})
	}
	return list
}

func describe(q Quote) string {
	return fmt.Sprintf("{Subtotal:%d Discounts:%v Total:%d}", q.Subtotal, q.Discounts, q.Total)
}

// sameQuote compares two quotes; an empty and a nil Discounts are the same.
func sameQuote(a, b Quote) bool {
	if a.Subtotal != b.Subtotal || a.Total != b.Total || len(a.Discounts) != len(b.Discounts) {
		return false
	}
	for i := range a.Discounts {
		if a.Discounts[i] != b.Discounts[i] {
			return false
		}
	}
	return true
}

func expectQuote(t *testing.T, got Quote, err error, want Quote) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !sameQuote(got, want) {
		t.Fatalf("got %s, want %s", describe(got), describe(want))
	}
}

func expectTotal(t *testing.T, got Quote, err error, want int) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.Total != want {
		t.Fatalf("got total %d, want %d", got.Total, want)
	}
}

func expectError(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil {
		t.Fatalf("got no error, want %q", want)
	}
	if err.Error() != want {
		t.Fatalf("got error %q, want %q", err.Error(), want)
	}
}

func onlyError(_ Quote, err error) error { return err }

func TestPromotionEngine(t *testing.T) {
	t.Run("the cart", func(t *testing.T) {
		t.Run("prices a cart with no promotions at its subtotal", func(t *testing.T) {
			got, err := NewPromotionEngine().Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Total: 1500})
		})

		t.Run("prices an empty cart at zero", func(t *testing.T) {
			got, err := NewPromotionEngine().Quote([]Line{}, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 0, Total: 0})
		})

		t.Run("rejects a line with a quantity below 1", func(t *testing.T) {
			lines := []Line{{SKU: "apple", UnitPrice: 100, Quantity: 0}}
			_, err := NewPromotionEngine().Quote(lines, nil, today)
			expectError(t, err, "quantity must be at least 1")
		})

		t.Run("rejects two lines with the same SKU", func(t *testing.T) {
			lines := []Line{
				{SKU: "apple", UnitPrice: 100, Quantity: 1},
				{SKU: "apple", UnitPrice: 100, Quantity: 2},
			}
			_, err := NewPromotionEngine().Quote(lines, nil, today)
			expectError(t, err, "SKU apple is in more than one line")
		})
	})

	t.Run("percentage discounts", func(t *testing.T) {
		t.Run("takes the percentage off every line when the promotion names no SKUs", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "ten", Kind: "percentage", Percent: 10})
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("ten", 150), Total: 1350})
		})

		t.Run("takes the percentage off the named SKUs only", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "ten", Kind: "percentage", Percent: 10, SKUs: []string{"pear"}})
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("ten", 100), Total: 1400})
		})

		t.Run("rounds the discount down to a whole cent on each line", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "fifteen", Kind: "percentage", Percent: 15})
			lines := []Line{
				{SKU: "apple", UnitPrice: 333, Quantity: 1},
				{SKU: "pear", UnitPrice: 333, Quantity: 1},
			}
			got, err := engine.Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 666, Discounts: discounts("fifteen", 98), Total: 568})
		})

		t.Run("rejects a percent outside 1 to 100", func(t *testing.T) {
			engine := NewPromotionEngine()
			for _, percent := range []int{0, 101} {
				err := engine.AddPromotion(Promotion{ID: "p", Kind: "percentage", Percent: percent})
				expectError(t, err, "percent must be between 1 and 100")
			}
		})
	})

	t.Run("fixed discounts", func(t *testing.T) {
		t.Run("takes the amount off the cart", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "off", Kind: "fixed", Amount: 300})
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("off", 300), Total: 1200})
		})

		t.Run("takes the amount off the named SKUs only, up to what they cost", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "off", Kind: "fixed", Amount: 600, SKUs: []string{"apple"}})
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("off", 500), Total: 1000})
		})

		t.Run("never takes the cart below zero", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "off", Kind: "fixed", Amount: 5000})
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("off", 1500), Total: 0})
		})

		t.Run("rejects an amount that is not positive", func(t *testing.T) {
			err := NewPromotionEngine().AddPromotion(Promotion{ID: "off", Kind: "fixed", Amount: 0})
			expectError(t, err, "amount must be positive")
		})
	})

	t.Run("buy X get Y", func(t *testing.T) {
		t.Run("makes Y units free for each full group of X plus Y units", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "three-for-two", Kind: "buy-x-get-y", Buy: 2, Get: 1, SKUs: []string{"apple"}})
			lines := []Line{{SKU: "apple", UnitPrice: 100, Quantity: 7}}
			got, err := engine.Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 700, Discounts: discounts("three-for-two", 200), Total: 500})
		})

		t.Run("gives nothing for an incomplete group", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "three-for-two", Kind: "buy-x-get-y", Buy: 2, Get: 1})
			lines := []Line{{SKU: "apple", UnitPrice: 100, Quantity: 2}}
			got, err := engine.Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 200, Total: 200})
		})

		t.Run("counts the units of each line on its own", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "two-for-one", Kind: "buy-x-get-y", Buy: 1, Get: 1})
			lines := []Line{
				{SKU: "apple", UnitPrice: 100, Quantity: 3},
				{SKU: "pear", UnitPrice: 50, Quantity: 1},
			}
			got, err := engine.Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 350, Discounts: discounts("two-for-one", 100), Total: 250})
		})

		t.Run("rejects buy or get below 1", func(t *testing.T) {
			engine := NewPromotionEngine()
			for _, pair := range [][2]int{{0, 1}, {1, 0}} {
				err := engine.AddPromotion(Promotion{ID: "b", Kind: "buy-x-get-y", Buy: pair[0], Get: pair[1]})
				expectError(t, err, "buy and get must be at least 1")
			}
		})
	})

	t.Run("bundles", func(t *testing.T) {
		meal := func(price int) Promotion {
			return Promotion{ID: "meal", Kind: "bundle", SKUs: []string{"burger", "fries", "drink"}, Price: price}
		}

		t.Run("prices each complete set of the SKUs at the bundle price", func(t *testing.T) {
			lines := []Line{
				{SKU: "burger", UnitPrice: 500, Quantity: 2},
				{SKU: "fries", UnitPrice: 200, Quantity: 2},
				{SKU: "drink", UnitPrice: 150, Quantity: 1},
			}
			got, err := engineWith(t, meal(700)).Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1550, Discounts: discounts("meal", 150), Total: 1400})
		})

		t.Run("gives nothing when a SKU of the bundle is not in the cart", func(t *testing.T) {
			lines := []Line{
				{SKU: "burger", UnitPrice: 500, Quantity: 1},
				{SKU: "fries", UnitPrice: 200, Quantity: 1},
			}
			got, err := engineWith(t, meal(100)).Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 700, Total: 700})
		})

		t.Run("gives nothing when the bundle price is not below the price of its SKUs", func(t *testing.T) {
			lines := []Line{
				{SKU: "burger", UnitPrice: 500, Quantity: 1},
				{SKU: "fries", UnitPrice: 200, Quantity: 1},
				{SKU: "drink", UnitPrice: 150, Quantity: 1},
			}
			got, err := engineWith(t, meal(850)).Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 850, Total: 850})
		})

		t.Run("rejects a bundle with fewer than two SKUs", func(t *testing.T) {
			err := NewPromotionEngine().AddPromotion(Promotion{ID: "meal", Kind: "bundle", SKUs: []string{"burger"}, Price: 100})
			expectError(t, err, "a bundle needs at least two SKUs")
		})

		t.Run("rejects a negative bundle price", func(t *testing.T) {
			err := NewPromotionEngine().AddPromotion(Promotion{ID: "meal", Kind: "bundle", SKUs: []string{"burger", "fries"}, Price: -1})
			expectError(t, err, "bundle price must not be negative")
		})
	})

	t.Run("precedence", func(t *testing.T) {
		t.Run("applies promotions from the highest priority down", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "a-percent", Kind: "percentage", Percent: 10, Priority: 1},
				Promotion{ID: "b-fixed", Kind: "fixed", Amount: 100, Priority: 2})
			lines := []Line{{SKU: "apple", UnitPrice: 1000, Quantity: 1}}
			got, err := engine.Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1000, Discounts: discounts("b-fixed", 100, "a-percent", 90), Total: 810})
		})

		t.Run("breaks a priority tie by promotion id", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "z-percent", Kind: "percentage", Percent: 10},
				Promotion{ID: "a-fixed", Kind: "fixed", Amount: 100})
			lines := []Line{{SKU: "apple", UnitPrice: 1000, Quantity: 1}}
			got, err := engine.Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1000, Discounts: discounts("a-fixed", 100, "z-percent", 90), Total: 810})
		})

		t.Run("takes a fixed discount from the lines in cart order", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "off", Kind: "fixed", Amount: 300, Priority: 2},
				Promotion{ID: "half-pear", Kind: "percentage", Percent: 50, SKUs: []string{"pear"}, Priority: 1})
			lines := []Line{
				{SKU: "apple", UnitPrice: 200, Quantity: 1},
				{SKU: "pear", UnitPrice: 500, Quantity: 1},
			}
			got, err := engine.Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 700, Discounts: discounts("off", 300, "half-pear", 200), Total: 200})
		})

		t.Run("lets a later promotion work on what earlier promotions left", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "three-for-two", Kind: "buy-x-get-y", Buy: 2, Get: 1, Priority: 2},
				Promotion{ID: "ten", Kind: "percentage", Percent: 10, Priority: 1})
			lines := []Line{{SKU: "apple", UnitPrice: 100, Quantity: 3}}
			got, err := engine.Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 300, Discounts: discounts("three-for-two", 100, "ten", 20), Total: 180})
		})

		t.Run("limits a buy X get Y discount to what is left of the line", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "sixty", Kind: "percentage", Percent: 60, Priority: 2},
				Promotion{ID: "two-for-one", Kind: "buy-x-get-y", Buy: 1, Get: 1, Priority: 1})
			lines := []Line{{SKU: "apple", UnitPrice: 100, Quantity: 2}}
			got, err := engine.Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 200, Discounts: discounts("sixty", 120, "two-for-one", 80), Total: 0})
		})

		t.Run("takes a bundle saving from its lines in cart order", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "meal", Kind: "bundle", SKUs: []string{"burger", "fries", "drink"}, Price: 100, Priority: 2},
				Promotion{ID: "half-fries", Kind: "percentage", Percent: 50, SKUs: []string{"fries"}, Priority: 1})
			lines := []Line{
				{SKU: "drink", UnitPrice: 150, Quantity: 1},
				{SKU: "burger", UnitPrice: 500, Quantity: 1},
				{SKU: "fries", UnitPrice: 200, Quantity: 1},
			}
			got, err := engine.Quote(lines, nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 850, Discounts: discounts("meal", 750, "half-fries", 50), Total: 50})
		})
	})

	t.Run("stacking and exclusivity", func(t *testing.T) {
		t.Run("stacks every promotion that applies", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "ten", Kind: "percentage", Percent: 10},
				Promotion{ID: "off-fifty", Kind: "fixed", Amount: 50})
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("off-fifty", 50, "ten", 145), Total: 1305})
		})

		t.Run("leaves out a promotion that takes nothing off", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "plum-ten", Kind: "percentage", Percent: 10, SKUs: []string{"plum"}},
				Promotion{ID: "off", Kind: "fixed", Amount: 100})
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("off", 100), Total: 1400})
		})

		t.Run("applies an exclusive promotion alone when it comes first", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "vip", Kind: "percentage", Percent: 20, Exclusive: true, Priority: 5},
				Promotion{ID: "off", Kind: "fixed", Amount: 100, Priority: 1})
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("vip", 300), Total: 1200})
		})

		t.Run("skips an exclusive promotion when an earlier promotion applied", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "off", Kind: "fixed", Amount: 100, Priority: 5},
				Promotion{ID: "vip", Kind: "percentage", Percent: 20, Exclusive: true, Priority: 1})
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("off", 100), Total: 1400})
		})

		t.Run("considers the next promotion when an exclusive promotion takes nothing off", func(t *testing.T) {
			engine := engineWith(t,
				Promotion{ID: "plum-deal", Kind: "buy-x-get-y", Buy: 1, Get: 1, SKUs: []string{"plum"}, Exclusive: true, Priority: 5},
				Promotion{ID: "off", Kind: "fixed", Amount: 100, Priority: 1})
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("off", 100), Total: 1400})
		})

		t.Run("rejects a promotion id that is already in the engine", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "ten", Kind: "percentage", Percent: 10})
			err := engine.AddPromotion(Promotion{ID: "ten", Kind: "fixed", Amount: 100})
			expectError(t, err, "promotion ten already exists")
		})

		t.Run("rejects an unknown promotion kind", func(t *testing.T) {
			err := NewPromotionEngine().AddPromotion(Promotion{ID: "gift", Kind: "gift", Amount: 100})
			expectError(t, err, "unknown promotion kind gift")
		})
	})

	t.Run("coupons", func(t *testing.T) {
		t.Run("applies the promotion of a coupon only when its code is given", func(t *testing.T) {
			engine := engineWithCoupon(t, saveTen(5))
			got, err := engine.Quote(cart(), nil, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Total: 1500})
			got, err = engine.Quote(cart(), []string{"SAVE10"}, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Discounts: discounts("save-ten", 150), Total: 1350})
		})

		t.Run("orders a coupon promotion with the other promotions", func(t *testing.T) {
			coupon := saveTen(5)
			coupon.Promotion.Priority = 2
			engine := engineWithCoupon(t, coupon,
				Promotion{ID: "first", Kind: "fixed", Amount: 100, Priority: 3},
				Promotion{ID: "last", Kind: "fixed", Amount: 50, Priority: 1})
			lines := []Line{{SKU: "apple", UnitPrice: 1000, Quantity: 1}}
			got, err := engine.Quote(lines, []string{"SAVE10"}, today)
			expectQuote(t, got, err, Quote{Subtotal: 1000, Discounts: discounts("first", 100, "save-ten", 90, "last", 50), Total: 760})
		})

		t.Run("accepts a coupon on its expiry date", func(t *testing.T) {
			engine := engineWithCoupon(t, saveTen(5))
			got, err := engine.Quote(cart(), []string{"SAVE10"}, "2026-03-31")
			expectTotal(t, got, err, 1350)
		})

		t.Run("rejects a coupon after its expiry date", func(t *testing.T) {
			engine := engineWithCoupon(t, saveTen(5))
			_, err := engine.Quote(cart(), []string{"SAVE10"}, "2026-04-01")
			expectError(t, err, "coupon SAVE10 has expired")
		})

		t.Run("rejects an unknown coupon code", func(t *testing.T) {
			engine := engineWithCoupon(t, saveTen(5))
			_, err := engine.Quote(cart(), []string{"NOPE"}, today)
			expectError(t, err, "unknown coupon NOPE")
		})

		t.Run("rejects a code given twice in one cart", func(t *testing.T) {
			engine := engineWithCoupon(t, saveTen(5))
			_, err := engine.Quote(cart(), []string{"SAVE10", "SAVE10"}, today)
			expectError(t, err, "coupon SAVE10 given more than once")
		})

		t.Run("does not use a coupon when quoting", func(t *testing.T) {
			engine := engineWithCoupon(t, saveTen(1))
			quote, err := engine.Quote(cart(), []string{"SAVE10"}, today)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			got, err := engine.Quote(cart(), []string{"SAVE10"}, today)
			expectQuote(t, got, err, quote)
			got, err = engine.Redeem(cart(), []string{"SAVE10"}, today)
			expectQuote(t, got, err, quote)
		})

		t.Run("uses each coupon once on each redeem until its usage limit", func(t *testing.T) {
			engine := engineWithCoupon(t, saveTen(2))
			got, err := engine.Redeem(cart(), []string{"SAVE10"}, today)
			expectTotal(t, got, err, 1350)
			got, err = engine.Redeem(cart(), []string{"SAVE10"}, today)
			expectTotal(t, got, err, 1350)
			expectError(t, onlyError(engine.Redeem(cart(), []string{"SAVE10"}, today)), "coupon SAVE10 has reached its usage limit")
			expectError(t, onlyError(engine.Quote(cart(), []string{"SAVE10"}, today)), "coupon SAVE10 has reached its usage limit")
		})

		t.Run("counts a use even when the coupon promotion takes nothing off", func(t *testing.T) {
			coupon := saveTen(1)
			coupon.Promotion.SKUs = []string{"plum"}
			engine := engineWithCoupon(t, coupon)
			got, err := engine.Redeem(cart(), []string{"SAVE10"}, today)
			expectQuote(t, got, err, Quote{Subtotal: 1500, Total: 1500})
			expectError(t, onlyError(engine.Redeem(cart(), []string{"SAVE10"}, today)), "coupon SAVE10 has reached its usage limit")
		})

		t.Run("uses no coupon when a redeem fails", func(t *testing.T) {
			engine := engineWithCoupon(t, saveTen(1))
			expectError(t, onlyError(engine.Redeem(cart(), []string{"SAVE10", "NOPE"}, today)), "unknown coupon NOPE")
			got, err := engine.Redeem(cart(), []string{"SAVE10"}, today)
			expectTotal(t, got, err, 1350)
		})

		t.Run("rejects a coupon code that is already in the engine", func(t *testing.T) {
			engine := engineWithCoupon(t, saveTen(5))
			again := saveTen(5)
			again.Promotion = Promotion{ID: "other", Kind: "fixed", Amount: 1}
			expectError(t, engine.AddCoupon(again), "coupon SAVE10 already exists")
		})

		t.Run("rejects a coupon usage limit below 1", func(t *testing.T) {
			expectError(t, NewPromotionEngine().AddCoupon(saveTen(0)), "usage limit must be at least 1")
		})

		t.Run("rejects a coupon whose promotion id is already in the engine", func(t *testing.T) {
			engine := engineWith(t, Promotion{ID: "save-ten", Kind: "fixed", Amount: 100})
			expectError(t, engine.AddCoupon(saveTen(5)), "promotion save-ten already exists")
		})

		t.Run("rejects a coupon whose promotion is not valid", func(t *testing.T) {
			coupon := saveTen(5)
			coupon.Promotion.Percent = 0
			expectError(t, NewPromotionEngine().AddCoupon(coupon), "percent must be between 1 and 100")
		})
	})
}
