package domain

import (
	"fmt"
	"strings"
	"testing"
)

func stockEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := stockShow(got), stockShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func stockShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func TestStock(t *testing.T) {
	t.Run("stock", func(t *testing.T) {
		t.Run("makes available what is on hand and not reserved", func(t *testing.T) {
			stockEq(t, AvailableOf(StockLevel{SKU: "apple", OnHand: 10, Reserved: 3}), 7)
		})

		t.Run("merges the lines of one SKU, in the order that each SKU first appears", func(t *testing.T) {
			stockEq(t, MergeLines([]StockLine{
				{SKU: "pear", Quantity: 1},
				{SKU: "apple", Quantity: 2},
				{SKU: "pear", Quantity: 3},
			}), []StockLine{{SKU: "pear", Quantity: 4}, {SKU: "apple", Quantity: 2}})
		})

		t.Run("keeps a running balance of the movements", func(t *testing.T) {
			stockEq(t, RunningBalance([]StockMovement{
				{SKU: "apple", Quantity: 10, Reason: "received"},
				{SKU: "apple", Quantity: -4, Reason: "shipped"},
				{SKU: "apple", Quantity: -1, Reason: "counted"},
			}), []BalanceLine{
				{Quantity: 10, Reason: "received", Balance: 10},
				{Quantity: -4, Reason: "shipped", Balance: 6},
				{Quantity: -1, Reason: "counted", Balance: 5},
			})
		})
	})
}
