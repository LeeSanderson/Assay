package services

import (
	"fmt"
	"strings"
	"testing"

	. "shop/domain"
)

const pengToday = "2026-03-10"

// pengLines gives lines with a subtotal of 1500.
func pengLines() []Line {
	return []Line{{SKU: "apple", UnitPrice: 250, Quantity: 2}, {SKU: "pear", UnitPrice: 1000, Quantity: 1}}
}

func pengSave10() Coupon {
	return Coupon{Code: "SAVE10", Promotion: Promotion{ID: "save-ten", Kind: "percentage", Percent: 10},
		ExpiresOn: "2026-03-31", UsageLimit: 2}
}

func pengEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := pengShow(got), pengShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func pengShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func pengErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func pengOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func pengMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func pengIDs(promotions []Promotion) []string {
	ids := []string{}
	for _, p := range promotions {
		ids = append(ids, p.ID)
	}
	return ids
}

func TestPromotionEngine(t *testing.T) {
	t.Run("promotions", func(t *testing.T) {
		t.Run("prices lines with the promotions that always apply", func(t *testing.T) {
			engine := NewPromotionEngine()
			pengOK(t, engine.AddPromotion(Promotion{ID: "off", Kind: "fixed", Amount: 200}))
			pengEq(t, pengMust(engine.Quote(pengLines(), nil, pengToday))(t), Quote{Subtotal: 1500,
				Discounts: []Discount{{PromotionID: "off", Amount: 200}}, Total: 1300})
		})

		t.Run("ends a promotion", func(t *testing.T) {
			engine := NewPromotionEngine()
			pengOK(t, engine.AddPromotion(Promotion{ID: "off", Kind: "fixed", Amount: 200}))
			pengOK(t, engine.RemovePromotion("off"))
			pengEq(t, pengMust(engine.Quote(pengLines(), nil, pengToday))(t).Total, 1500)
			pengErr(t, engine.RemovePromotion("off"), "unknown promotion off")
		})

		t.Run("lists the promotions that can take money off a SKU", func(t *testing.T) {
			engine := NewPromotionEngine()
			pengOK(t, engine.AddPromotion(Promotion{ID: "all", Kind: "percentage", Percent: 5}))
			pengOK(t, engine.AddPromotion(Promotion{ID: "pears", Kind: "percentage", Percent: 10, SKUs: []string{"pear"}}))
			pengEq(t, pengIDs(engine.PromotionsFor("pear")), []string{"all", "pears"})
			pengEq(t, pengIDs(engine.PromotionsFor("apple")), []string{"all"})
			pengEq(t, len(engine.ActivePromotions()), 2)
		})

		t.Run("rejects a promotion id that is already in the engine", func(t *testing.T) {
			engine := NewPromotionEngine()
			pengOK(t, engine.AddPromotion(Promotion{ID: "off", Kind: "fixed", Amount: 200}))
			pengErr(t, engine.AddPromotion(Promotion{ID: "off", Kind: "fixed", Amount: 100}),
				"promotion off already exists")
		})
	})

	t.Run("coupons", func(t *testing.T) {
		t.Run("counts the uses of each coupon on each redeem", func(t *testing.T) {
			engine := NewPromotionEngine()
			pengOK(t, engine.AddCoupon(pengSave10()))
			pengMust(engine.Quote(pengLines(), []string{"SAVE10"}, pengToday))(t)
			pengMust(engine.Redeem(pengLines(), []string{"SAVE10"}, pengToday))(t)
			pengEq(t, engine.CouponUsage(), []CouponUsage{
				{Code: "SAVE10", Uses: 1, UsageLimit: 2, ExpiresOn: "2026-03-31"},
			})
		})

		t.Run("withdraws a coupon that no one has used", func(t *testing.T) {
			engine := NewPromotionEngine()
			pengOK(t, engine.AddCoupon(pengSave10()))
			used := pengSave10()
			used.Code, used.Promotion.ID = "USED", "u"
			pengOK(t, engine.AddCoupon(used))
			pengMust(engine.Redeem(pengLines(), []string{"USED"}, pengToday))(t)
			pengOK(t, engine.RemoveCoupon("SAVE10"))
			_, err := engine.Quote(pengLines(), []string{"SAVE10"}, pengToday)
			pengErr(t, err, "unknown coupon SAVE10")
			pengErr(t, engine.RemoveCoupon("USED"), "coupon USED has been used")
			pengErr(t, engine.RemoveCoupon("NOPE"), "unknown coupon NOPE")
		})

		t.Run("checks the lines before the coupons", func(t *testing.T) {
			engine := NewPromotionEngine()
			_, err := engine.Quote([]Line{{SKU: "apple", UnitPrice: 250, Quantity: 0}}, []string{"NOPE"}, pengToday)
			pengErr(t, err, "quantity must be at least 1")
		})
	})

	t.Run("explanations", func(t *testing.T) {
		t.Run("explains a quote without using a coupon", func(t *testing.T) {
			engine := NewPromotionEngine()
			once := pengSave10()
			once.UsageLimit = 1
			pengOK(t, engine.AddCoupon(once))
			pengOK(t, engine.AddPromotion(Promotion{ID: "kiwi", Kind: "fixed", Amount: 100, SKUs: []string{"kiwi"}}))
			pengEq(t, pengMust(engine.Explain(pengLines(), []string{"SAVE10"}, pengToday))(t), []PricingStep{
				{PromotionID: "kiwi", Outcome: "nothing to take", Amount: 0},
				{PromotionID: "save-ten", Outcome: "applied", Amount: 150},
			})
			pengEq(t, pengMust(engine.Redeem(pengLines(), []string{"SAVE10"}, pengToday))(t).Total, 1350)
		})

		t.Run("describes its promotions and coupons in words", func(t *testing.T) {
			engine := NewPromotionEngine()
			pengOK(t, engine.AddPromotion(Promotion{ID: "pears", Kind: "percentage", Percent: 10, SKUs: []string{"pear"}}))
			pengOK(t, engine.AddCoupon(pengSave10()))
			pengEq(t, engine.Describe(), []string{"10% off pear", "SAVE10: 10% off everything, until 2026-03-31"})
		})
	})
}
