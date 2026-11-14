package adapters

import (
	"fmt"
	"strings"
	"testing"

	. "shop/domain"
)

func textEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := textShow(got), textShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func textShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func textLines(lines ...string) string { return strings.Join(lines, "\n") }

func textOrder() Order {
	return Order{
		ID: "order-7",
		Lines: []OrderLine{
			{SKU: "apple", Name: "Apple", UnitPrice: 250, Quantity: 2},
			{SKU: "pear", Name: "Pear", UnitPrice: 1000, Quantity: 1},
		},
		Subtotal:  1500,
		Discounts: []Discount{},
		Total:     1500,
		Status:    "paid",
		PaymentID: "payment-7",
		PlacedOn:  "2026-03-10",
	}
}

func textShipment() Shipment {
	return Shipment{
		ID:        "shipment-2",
		OrderID:   "order-7",
		Address:   Address{Line1: "1 High St", City: "Leeds", Postcode: "LS1 1AA", Country: "GB"},
		Zone:      "domestic",
		Units:     3,
		Parcels:   1,
		Cost:      600,
		Status:    "pending",
		CreatedOn: "2026-03-10",
	}
}

func TestText(t *testing.T) {
	t.Run("receipts", func(t *testing.T) {
		t.Run("prints the lines, the subtotal and the total of an order", func(t *testing.T) {
			textEq(t, Receipt(textOrder()), textLines(
				"Order order-7 (2026-03-10)",
				"2 x Apple                           5.00",
				"1 x Pear                           10.00",
				"Subtotal                           15.00",
				"Total                              15.00",
				""))
		})

		t.Run("prints each discount as a negative amount and the status of an order that is not paid", func(t *testing.T) {
			order := textOrder()
			order.Discounts = []Discount{{PromotionID: "ten", Amount: 150}}
			order.Total = 1350
			order.Status = "cancelled"
			textEq(t, Receipt(order), textLines(
				"Order order-7 (2026-03-10)",
				"2 x Apple                           5.00",
				"1 x Pear                           10.00",
				"Subtotal                           15.00",
				"Discount ten                       -1.50",
				"Total                              13.50",
				"Status: cancelled",
				""))
		})
	})

	t.Run("documents", func(t *testing.T) {
		t.Run("prints an invoice with the tax that it includes", func(t *testing.T) {
			invoice := Invoice{
				ID:         "invoice-1",
				Number:     "INV-000001",
				OrderID:    "order-7",
				CustomerID: "customer-1",
				Lines:      []InvoiceLine{{SKU: "pear", Description: "Pear", Quantity: 1, UnitPrice: 1200, Amount: 1200}},
				Subtotal:   1200,
				Discounts:  []Discount{},
				Total:      1200,
				TaxRate:    2000,
				Tax:        200,
				IssuedOn:   "2026-03-12",
			}
			textEq(t, InvoiceText(invoice), textLines(
				"Invoice INV-000001 (2026-03-12)",
				"Order order-7 for customer-1",
				"1 x Pear @ 12.00                   12.00",
				"Subtotal                           12.00",
				"Total                              12.00",
				"Tax included at 20%                 2.00",
				""))
		})

		t.Run("prints a shipping label and a packing slip", func(t *testing.T) {
			two := textShipment()
			two.Parcels = 2
			textEq(t, ShippingLabel(two), textLines(
				"Shipment shipment-2 for order order-7",
				"To: 1 High St, Leeds LS1 1AA, GB",
				"Units: 3 in 2 parcels",
				"Zone: domestic",
				""))
			textEq(t, PackingSlip(textOrder(), textShipment()), textLines(
				"Packing slip for order order-7",
				"Ship to: 1 High St, Leeds LS1 1AA, GB",
				"[ ]   2 x apple Apple",
				"[ ]   1 x pear Pear",
				"Units: 3",
				""))
		})

		t.Run("prints the statement of an account", func(t *testing.T) {
			text := StatementText(Statement{
				CustomerID: "customer-1",
				Credit:     300,
				Points:     12,
				Entries: []AccountEntry{
					{ID: "entry-1", CustomerID: "customer-1", Kind: "credit", Amount: 300, Reason: "gift", On: "2026-03-10"},
					{ID: "entry-2", CustomerID: "customer-1", Kind: "points", Amount: 12, Reason: "order order-1",
						On: "2026-03-11"},
				},
			})
			textEq(t, text, textLines(
				"Statement of customer-1",
				"2026-03-10 gift                     3.00",
				"2026-03-11 order order-1       12 points",
				"Store credit                        3.00",
				"Points: 12",
				""))
		})

		t.Run("writes a rate as a percentage", func(t *testing.T) {
			textEq(t, []string{FormatRate(2000), FormatRate(550), FormatRate(525), FormatRate(0)},
				[]string{"20%", "5.5%", "5.25%", "0%"})
		})
	})

	t.Run("json lines", func(t *testing.T) {
		t.Run("writes events one a line and reads them back", func(t *testing.T) {
			events := []ShopEvent{
				{ID: "event-1", Type: "order-placed", Subject: "order-1", On: "2026-03-10", Data: EventData{}},
				{ID: "event-2", Type: "order-shipped", Subject: "order-1", On: "2026-03-11", Data: EventData{"total": 5}},
			}
			text := EventsAsJSONLines(events)
			textEq(t, len(strings.Split(text, "\n")), 3)
			back, err := EventsFromJSONLines(text)
			if err != nil {
				t.Fatal(err)
			}
			textEq(t, back, events)
			textEq(t, EventsAsJSONLines(nil), "")
		})

		t.Run("rejects a line that is not an event", func(t *testing.T) {
			_, err := EventsFromJSONLines("{\"id\":\"event-1\",\"type\":\"x\"}\n{\"hello\":1}\n")
			if err == nil || err.Error() != "line 2 is not an event" {
				t.Fatalf("got error %v", err)
			}
		})
	})
}
