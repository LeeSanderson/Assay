package domain

import (
	"fmt"
	"strings"
	"testing"
)

func invEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := invShow(got), invShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func invShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func invMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func invOrder() Order {
	return Order{ID: "order-3",
		Lines: []OrderLine{
			{SKU: "apple", Name: "Apple", UnitPrice: 250, Quantity: 2},
			{SKU: "pear", Name: "Pear", UnitPrice: 1000, Quantity: 1},
		},
		Subtotal: 1500, Discounts: []Discount{{PromotionID: "off", Amount: 300}}, Total: 1200,
		Status: "shipped", PaymentID: "payment-3", PlacedOn: "2026-03-10"}
}

func TestInvoice(t *testing.T) {
	t.Run("invoices", func(t *testing.T) {
		t.Run("numbers invoices with six digits", func(t *testing.T) {
			invEq(t, []string{InvoiceNumber(1), InvoiceNumber(123456)}, []string{"INV-000001", "INV-123456"})
		})

		t.Run("copies the lines, the discounts and the total of the order", func(t *testing.T) {
			invEq(t, invMust(InvoiceOf(invOrder(), "invoice-1", "INV-000001", 2000, "2026-03-12"))(t), Invoice{
				ID: "invoice-1", Number: "INV-000001", OrderID: "order-3",
				Lines: []InvoiceLine{
					{SKU: "apple", Description: "Apple", Quantity: 2, UnitPrice: 250, Amount: 500},
					{SKU: "pear", Description: "Pear", Quantity: 1, UnitPrice: 1000, Amount: 1000},
				},
				Subtotal: 1500, Discounts: []Discount{{PromotionID: "off", Amount: 300}}, Total: 1200,
				TaxRate: 2000, Tax: 200, IssuedOn: "2026-03-12",
			})
		})

		t.Run("names the customer of the order, when it has one", func(t *testing.T) {
			order := invOrder()
			order.CustomerID = "customer-1"
			invoice := invMust(InvoiceOf(order, "i", "n", 0, "2026-03-12"))(t)
			invEq(t, []any{invoice.CustomerID, invoice.Tax}, []any{"customer-1", 0})
		})
	})
}
