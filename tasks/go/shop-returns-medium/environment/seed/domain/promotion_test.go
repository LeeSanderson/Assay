package domain

import (
	"fmt"
	"slices"
	"strings"
	"testing"
)

func promoEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := promoShow(got), promoShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func promoShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func promoErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func promoMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

// promoLines gives lines with a subtotal of 1500.
func promoLines() []Line {
	return []Line{{SKU: "apple", UnitPrice: 250, Quantity: 2}, {SKU: "pear", UnitPrice: 1000, Quantity: 1}}
}

var promoTen = Promotion{ID: "ten", Kind: "percentage", Percent: 10}

func TestPromotion(t *testing.T) {
	t.Run("validation", func(t *testing.T) {
		t.Run("accepts each kind of promotion with its fields", func(t *testing.T) {
			for _, promotion := range []Promotion{
				promoTen,
				{ID: "off", Kind: "fixed", Amount: 100},
				{ID: "x", Kind: "buy-x-get-y", Buy: 2, Get: 1},
				{ID: "pair", Kind: "bundle", SKUs: []string{"apple", "pear"}, Price: 900},
			} {
				if err := ValidatePromotion(promotion); err != nil {
					t.Fatal(err)
				}
			}
		})

		t.Run("rejects the fields that a kind does not allow", func(t *testing.T) {
			promoErr(t, ValidatePromotion(Promotion{ID: "p", Kind: "percentage", Percent: 101}),
				"percent must be between 1 and 100")
			promoErr(t, ValidatePromotion(Promotion{ID: "f", Kind: "fixed", Amount: 0}), "amount must be positive")
			promoErr(t, ValidatePromotion(Promotion{ID: "b", Kind: "bundle", SKUs: []string{"apple"}}),
				"a bundle needs at least two SKUs")
		})
	})

	t.Run("pricing", func(t *testing.T) {
		t.Run("orders promotions by priority, then by id", func(t *testing.T) {
			b, a, c := promoTen, promoTen, promoTen
			b.ID, a.ID, c.ID, c.Priority = "b", "a", "c", 2
			promotions := []Promotion{b, a, c}
			slices.SortStableFunc(promotions, Precedence)
			var ids []string
			for _, p := range promotions {
				ids = append(ids, p.ID)
			}
			promoEq(t, ids, []string{"c", "a", "b"})
		})

		t.Run("prices lines with no promotion at their subtotal", func(t *testing.T) {
			promoEq(t, promoMust(PriceLines(promoLines(), nil))(t),
				Quote{Subtotal: 1500, Discounts: []Discount{}, Total: 1500})
		})

		t.Run("lets each promotion work on what the earlier ones left", func(t *testing.T) {
			first := promoTen
			first.Priority = 1
			quote := promoMust(PriceLines(promoLines(), []Promotion{first, {ID: "off", Kind: "fixed", Amount: 100}}))(t)
			promoEq(t, quote, Quote{Subtotal: 1500,
				Discounts: []Discount{{PromotionID: "ten", Amount: 150}, {PromotionID: "off", Amount: 100}},
				Total:     1250})
		})

		t.Run("prices each complete set of a bundle at the bundle price", func(t *testing.T) {
			lines := []Line{{SKU: "apple", UnitPrice: 250, Quantity: 2}, {SKU: "pear", UnitPrice: 1000, Quantity: 2}}
			pair := Promotion{ID: "pair", Kind: "bundle", SKUs: []string{"apple", "pear"}, Price: 900}
			promoEq(t, promoMust(PriceLines(lines, []Promotion{pair}))(t).Total, 1800)
		})

		t.Run("rejects a SKU on two lines", func(t *testing.T) {
			lines := append(promoLines(), promoLines()[0])
			_, err := PriceLines(lines, nil)
			promoErr(t, err, "SKU apple is in more than one line")
		})
	})

	t.Run("explanations", func(t *testing.T) {
		t.Run("says what each promotion did, in order of precedence", func(t *testing.T) {
			first := promoTen
			first.Priority = 1
			steps := promoMust(ExplainPricing(promoLines(), []Promotion{
				{ID: "kiwi", Kind: "percentage", Percent: 50, SKUs: []string{"kiwi"}},
				{ID: "solo", Kind: "fixed", Amount: 100, Exclusive: true},
				first,
			}))(t)
			promoEq(t, steps, []PricingStep{
				{PromotionID: "ten", Outcome: "applied", Amount: 150},
				{PromotionID: "kiwi", Outcome: "nothing to take", Amount: 0},
				{PromotionID: "solo", Outcome: "not alone", Amount: 0},
			})
		})

		t.Run("marks the promotions after an exclusive one that applied", func(t *testing.T) {
			steps := promoMust(ExplainPricing(promoLines(), []Promotion{
				{ID: "solo", Kind: "fixed", Amount: 100, Exclusive: true, Priority: 1},
				promoTen,
			}))(t)
			var outcomes []Outcome
			for _, step := range steps {
				outcomes = append(outcomes, step.Outcome)
			}
			promoEq(t, outcomes, []Outcome{"applied", "after exclusive"})
		})

		t.Run("describes each kind of promotion in words", func(t *testing.T) {
			promoEq(t, DescribePromotion(promoTen), "10% off everything")
			promoEq(t, DescribePromotion(Promotion{ID: "f", Kind: "fixed", Amount: 250, SKUs: []string{"apple"}}),
				"2.50 off apple")
			promoEq(t, DescribePromotion(Promotion{ID: "x", Kind: "buy-x-get-y", Buy: 2, Get: 1}),
				"buy 2 get 1 free on everything")
			promoEq(t, DescribePromotion(Promotion{ID: "pair", Kind: "bundle", SKUs: []string{"apple", "pear"},
				Price: 900, Exclusive: true}), "apple + pear for 9.00 (not with other offers)")
		})
	})
}
