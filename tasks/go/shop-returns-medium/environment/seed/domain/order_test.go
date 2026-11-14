package domain

import (
	"fmt"
	"strings"
	"testing"
)

func ordEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := ordShow(got), ordShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func ordShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func ordErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func ordMove(t *testing.T, order Order, status OrderStatus) Order {
	t.Helper()
	moved, err := MoveTo(order, status)
	if err != nil {
		t.Fatal(err)
	}
	return moved
}

func ordOrder() Order {
	return Order{ID: "order-1",
		Lines: []OrderLine{
			{SKU: "apple", Name: "Apple", UnitPrice: 250, Quantity: 2},
			{SKU: "pear", Name: "Pear", UnitPrice: 1000, Quantity: 1},
		},
		Subtotal:  1500,
		Discounts: []Discount{{PromotionID: "ten", Amount: 150}, {PromotionID: "off", Amount: 50}},
		Total:     1300, Status: "paid", PaymentID: "payment-1", PlacedOn: "2026-03-10", CustomerID: "customer-1"}
}

func TestOrder(t *testing.T) {
	t.Run("the status of an order", func(t *testing.T) {
		t.Run("moves a paid order to shipped or cancelled", func(t *testing.T) {
			order := ordOrder()
			ordEq(t, ordMove(t, order, "shipped").Status, OrderStatus("shipped"))
			ordEq(t, ordMove(t, order, "cancelled").Status, OrderStatus("cancelled"))
			ordEq(t, order.Status, OrderStatus("paid"))
		})

		t.Run("moves a shipped or cancelled order nowhere", func(t *testing.T) {
			_, err := MoveTo(ordMove(t, ordOrder(), "shipped"), "cancelled")
			ordErr(t, err, "order order-1 is shipped")
			_, err = MoveTo(ordMove(t, ordOrder(), "cancelled"), "shipped")
			ordErr(t, err, "order order-1 is cancelled")
		})

		t.Run("counts an order in the sales unless it was cancelled", func(t *testing.T) {
			ordEq(t, Counts(ordOrder()), true)
			ordEq(t, Counts(ordMove(t, ordOrder(), "shipped")), true)
			ordEq(t, Counts(ordMove(t, ordOrder(), "cancelled")), false)
		})
	})

	t.Run("the amounts of an order", func(t *testing.T) {
		t.Run("adds up its lines, its units and its discounts", func(t *testing.T) {
			order := ordOrder()
			ordEq(t, []Cents{LineTotal(order.Lines[0]), LineTotal(order.Lines[1])}, []Cents{500, 1000})
			ordEq(t, UnitsOf(order), 3)
			ordEq(t, DiscountTotal(order), 200)
			ordEq(t, QuantityOf(order, "apple"), 2)
			ordEq(t, QuantityOf(order, "kiwi"), 0)
		})

		t.Run("copies an order so that a change to the copy leaves it as it was", func(t *testing.T) {
			order := ordOrder()
			copied := CopyOrder(order)
			copied.Lines[0].Quantity = 9
			copied.Discounts[0].Amount = 1
			ordEq(t, order.Lines[0].Quantity, 2)
			ordEq(t, order.Discounts[0].Amount, 150)
		})
	})

	t.Run("order filters", func(t *testing.T) {
		t.Run("matches every order with an empty filter", func(t *testing.T) {
			ordEq(t, Matches(ordOrder(), OrderFilter{}), true)
		})

		t.Run("matches each field that the filter gives", func(t *testing.T) {
			order := ordOrder()
			ordEq(t, Matches(order, OrderFilter{Status: "paid", CustomerID: "customer-1", SKU: "pear"}), true)
			ordEq(t, Matches(order, OrderFilter{SKU: "kiwi"}), false)
			ordEq(t, Matches(order, OrderFilter{CustomerID: "customer-2"}), false)
			ordEq(t, Matches(order, OrderFilter{From: "2026-03-10", To: "2026-03-10"}), true)
			ordEq(t, Matches(order, OrderFilter{From: "2026-03-11"}), false)
			ordEq(t, Matches(order, OrderFilter{MinTotal: 1300}), true)
			ordEq(t, Matches(order, OrderFilter{MinTotal: 1301}), false)
		})
	})
}
