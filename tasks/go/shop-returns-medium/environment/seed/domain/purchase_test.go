package domain

import (
	"fmt"
	"strings"
	"testing"
)

func purEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := purShow(got), purShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func purShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func purErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func purOrder() PurchaseOrder {
	return PurchaseOrder{ID: "purchase-1", SupplierID: "supplier-1",
		Lines: []PurchaseLine{
			{SKU: "apple", Quantity: 10, UnitCost: 120, Received: 10},
			{SKU: "pear", Quantity: 4, UnitCost: 600, Received: 1},
		},
		Status: "sent", CreatedOn: "2026-03-10"}
}

func TestPurchase(t *testing.T) {
	t.Run("purchase orders", func(t *testing.T) {
		t.Run("knows what is outstanding and what the order costs", func(t *testing.T) {
			order := purOrder()
			purEq(t, []int{Outstanding(order.Lines[0]), Outstanding(order.Lines[1])}, []int{0, 3})
			purEq(t, IsReceived(order), false)
			purEq(t, CostOfPurchase(order), 3600)
		})

		t.Run("is received once every unit has come in", func(t *testing.T) {
			order := purOrder()
			for i := range order.Lines {
				order.Lines[i].Received = order.Lines[i].Quantity
			}
			purEq(t, IsReceived(order), true)
		})

		t.Run("checks its status", func(t *testing.T) {
			purErr(t, CheckPurchaseStatus(purOrder(), "draft"), "purchase purchase-1 is sent")
		})

		t.Run("checks a supplier and a line", func(t *testing.T) {
			purErr(t, CheckSupplier("Orchard", "sales@orchard.example", -1), "lead time must be a whole number of days")
			purErr(t, CheckPurchaseLine("apple", 1, 0), "unit cost must be at least 1")
			purErr(t, CheckPurchaseLine("apple", 0, 10), "quantity must be at least 1")
		})
	})
}
