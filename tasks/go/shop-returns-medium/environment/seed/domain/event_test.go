package domain

import (
	"fmt"
	"strings"
	"testing"
)

func evEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := evShow(got), evShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func evShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

// evChange checks that a rule gave the change.
func evChange(t *testing.T, got Change, ok bool, want Change) {
	t.Helper()
	if !ok {
		t.Fatal("no change")
	}
	evEq(t, got, want)
}

func evNone(_ Change, ok bool) func(*testing.T) {
	return func(t *testing.T) {
		t.Helper()
		if ok {
			t.Fatal("a change, want none")
		}
	}
}

func evOrder() Order {
	return Order{ID: "order-1", Lines: []OrderLine{{SKU: "apple", Name: "Apple", UnitPrice: 250, Quantity: 2}},
		Subtotal: 500, Discounts: []Discount{}, Total: 500, Status: "paid", PaymentID: "payment-1",
		PlacedOn: "2026-03-10"}
}

func TestEvent(t *testing.T) {
	t.Run("order changes", func(t *testing.T) {
		t.Run("places a new order", func(t *testing.T) {
			change, ok := OrderChange(nil, evOrder())
			evChange(t, change, ok, Change{Type: "order-placed", Subject: "order-1",
				Data: EventData{"total": 500, "lines": 1}})
		})

		t.Run("names the customer of the order", func(t *testing.T) {
			order := evOrder()
			order.CustomerID = "customer-1"
			change, _ := OrderChange(nil, order)
			evEq(t, change.Data, EventData{"total": 500, "lines": 1, "customerId": "customer-1"})
		})

		t.Run("turns a change of status into an event of the new status", func(t *testing.T) {
			before, shipped := evOrder(), evOrder()
			shipped.Status = "shipped"
			change, ok := OrderChange(&before, shipped)
			evChange(t, change, ok, Change{Type: "order-shipped", Subject: "order-1",
				Data: EventData{"total": 500}})
		})

		t.Run("gives no event when the status stays the same", func(t *testing.T) {
			before := evOrder()
			evNone(OrderChange(&before, evOrder()))(t)
		})
	})

	t.Run("other changes", func(t *testing.T) {
		shipment := Shipment{ID: "shipment-1", OrderID: "order-1",
			Address: Address{Line1: "1 High St", City: "Leeds", Postcode: "LS1 1AA", Country: "GB"},
			Zone:    "domestic", Units: 2, Parcels: 1, Cost: 500, Status: "pending", CreatedOn: "2026-03-10"}

		t.Run("creates and dispatches a shipment", func(t *testing.T) {
			created, _ := ShipmentChange(nil, shipment)
			evEq(t, created.Type, "shipment-created")
			dispatched := shipment
			dispatched.Status, dispatched.TrackingCode = "dispatched", "TRK1"
			change, ok := ShipmentChange(&shipment, dispatched)
			evChange(t, change, ok, Change{Type: "shipment-dispatched", Subject: "shipment-1",
				Data: EventData{"orderId": "order-1", "trackingCode": "TRK1"}})
		})

		t.Run("issues an invoice once", func(t *testing.T) {
			invoice := Invoice{ID: "invoice-1", OrderID: "order-1", Number: "INV-000001", Total: 500}
			change, ok := InvoiceChange(nil, invoice)
			evChange(t, change, ok, Change{Type: "invoice-issued", Subject: "invoice-1",
				Data: EventData{"orderId": "order-1", "number": "INV-000001", "total": 500}})
			evNone(InvoiceChange(&invoice, invoice))(t)
		})

		t.Run("registers, updates and closes a customer", func(t *testing.T) {
			ada := Customer{ID: "customer-1", Name: "Ada", Email: "ada@example.com", RegisteredOn: "2026-03-10"}
			registered, _ := CustomerChange(nil, ada)
			evEq(t, registered.Type, "customer-registered")
			renamed := ada
			renamed.Name, renamed.Email = "Ada L", "al@example.com"
			updated, _ := CustomerChange(&ada, renamed)
			evEq(t, updated.Data, EventData{"fields": "name,email"})
			evNone(CustomerChange(&ada, ada))(t)
			closed := ada
			closed.ClosedOn = "2026-04-01"
			change, _ := CustomerChange(&ada, closed)
			evEq(t, change.Type, "customer-closed")
		})
	})
}
