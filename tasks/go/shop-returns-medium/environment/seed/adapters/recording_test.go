package adapters

import (
	"fmt"
	"strings"
	"testing"

	. "shop/domain"
)

func recEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := recShow(got), recShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func recShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func recOrder() Order {
	return Order{
		ID:        "order-1",
		Lines:     []OrderLine{{SKU: "apple", Name: "Apple", UnitPrice: 250, Quantity: 2}},
		Subtotal:  500,
		Discounts: []Discount{},
		Total:     500,
		Status:    "paid",
		PaymentID: "payment-1",
		PlacedOn:  "2026-03-10",
	}
}

// recSink is a sink that keeps each change.
type recSink struct{ changes []Change }

func (s *recSink) Record(change Change) (ShopEvent, error) {
	s.changes = append(s.changes, change)
	return ShopEvent{}, nil
}

func TestRecording(t *testing.T) {
	t.Run("recording stores", func(t *testing.T) {
		t.Run("saves through the store that they wrap", func(t *testing.T) {
			inner := NewInMemoryOrderRepository()
			orders := NewRecordingOrderRepository(inner, &recSink{})
			orders.Save(recOrder())
			got, _ := inner.Get("order-1")
			recEq(t, got, recOrder())
			got, _ = orders.Get("order-1")
			recEq(t, got, recOrder())
			recEq(t, len(orders.List()), 1)
		})

		t.Run("records each change that a rule turns into an event", func(t *testing.T) {
			changes := &recSink{}
			orders := NewRecordingOrderRepository(NewInMemoryOrderRepository(), changes)
			orders.Save(recOrder())
			orders.Save(recOrder())
			cancelled := recOrder()
			cancelled.Status = "cancelled"
			orders.Save(cancelled)
			var types []string
			for _, change := range changes.changes {
				types = append(types, change.Type)
			}
			recEq(t, types, []string{"order-placed", "order-cancelled"})
		})

		t.Run("records the changes of customers by their own rule", func(t *testing.T) {
			changes := &recSink{}
			customers := NewRecordingCustomerRepository(NewInMemoryCustomerRepository(), changes)
			ada := Customer{ID: "customer-1", Name: "Ada", Email: "ada@example.com", RegisteredOn: "d"}
			customers.Save(ada)
			ada.Name = "Ada L"
			customers.Save(ada)
			recEq(t, changes.changes, []Change{
				{Type: "customer-registered", Subject: "customer-1", Data: EventData{"email": "ada@example.com"}},
				{Type: "customer-updated", Subject: "customer-1", Data: EventData{"fields": "name"}},
			})
		})
	})
}
