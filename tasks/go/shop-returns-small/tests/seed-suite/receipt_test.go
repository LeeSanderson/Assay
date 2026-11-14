package shop

import (
	"reflect"
	"strings"
	"testing"
)

// receiptWant fails the test unless got and want are deeply equal.
func receiptWant(t *testing.T, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func receiptOrder() Order {
	return Order{
		ID: "order-7",
		Lines: []OrderLine{
			{SKU: "apple", Name: "Apple", UnitPrice: 250, Quantity: 2},
			{SKU: "pear", Name: "Pear", UnitPrice: 1000, Quantity: 1},
		},
		Subtotal:  1500,
		Total:     1500,
		Status:    "paid",
		PaymentID: "payment-7",
		PlacedOn:  "2026-03-10",
	}
}

func TestReceipt(t *testing.T) {
	t.Run("formats cents as units and hundredths", func(t *testing.T) {
		got := []string{FormatCents(1234), FormatCents(5), FormatCents(0), FormatCents(-150)}
		receiptWant(t, got, []string{"12.34", "0.05", "0.00", "-1.50"})
	})

	t.Run("prints the lines, the subtotal and the total of an order", func(t *testing.T) {
		receiptWant(t, Receipt(receiptOrder()), strings.Join([]string{
			"Order order-7 (2026-03-10)",
			"2 x Apple                           5.00",
			"1 x Pear                           10.00",
			"Subtotal                           15.00",
			"Total                              15.00",
			"",
		}, "\n"))
	})

	t.Run("prints each discount as a negative amount and the status of an order that is not paid", func(t *testing.T) {
		order := receiptOrder()
		order.Discounts = []Discount{{PromotionID: "ten", Amount: 150}}
		order.Total = 1350
		order.Status = "cancelled"
		receiptWant(t, Receipt(order), strings.Join([]string{
			"Order order-7 (2026-03-10)",
			"2 x Apple                           5.00",
			"1 x Pear                           10.00",
			"Subtotal                           15.00",
			"Discount ten                       -1.50",
			"Total                              13.50",
			"Status: cancelled",
			"",
		}, "\n"))
	})
}
