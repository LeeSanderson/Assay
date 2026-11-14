package adapters

import (
	"fmt"
	"strings"
	"testing"

	. "shop/domain"
)

func memEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := memShow(got), memShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func memShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func memErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func memMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func memOrder() Order {
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

func memGateway() *InMemoryPaymentGateway { return NewInMemoryPaymentGateway(NewSequentialIDs()) }

func TestMemory(t *testing.T) {
	t.Run("stores", func(t *testing.T) {
		t.Run("gives back a copy of what it saved", func(t *testing.T) {
			orders := NewInMemoryOrderRepository()
			orders.Save(memOrder())
			copy, _ := orders.Get("order-1")
			copy.Lines[0].Quantity = 9
			got, _ := orders.Get("order-1")
			memEq(t, got, memOrder())
		})

		t.Run("keeps a copy of what it was given", func(t *testing.T) {
			products := NewInMemoryProductRepository()
			apple := Product{SKU: "apple", Name: "Apple", UnitPrice: 250}
			products.Save(apple)
			apple.UnitPrice = 1
			got, _ := products.Get("apple")
			memEq(t, got.UnitPrice, 250)
		})

		t.Run("lists records in the order that each was first saved", func(t *testing.T) {
			orders := NewInMemoryOrderRepository()
			second := memOrder()
			second.ID = "order-2"
			orders.Save(second)
			orders.Save(memOrder())
			second.Status = "shipped"
			orders.Save(second)
			var got [][]string
			for _, order := range orders.List() {
				got = append(got, []string{order.ID, string(order.Status)})
			}
			memEq(t, got, [][]string{{"order-2", "shipped"}, {"order-1", "paid"}})
		})

		t.Run("keeps the reservations and the movements of the stock", func(t *testing.T) {
			stock := NewInMemoryStockRepository()
			stock.SaveReservation(Reservation{OrderID: "order-1", Lines: []StockLine{{SKU: "apple", Quantity: 2}}})
			stock.AddMovement(StockMovement{SKU: "apple", Quantity: 5, Reason: "received"})
			reservation, _ := stock.Reservation("order-1")
			memEq(t, reservation.Lines, []StockLine{{SKU: "apple", Quantity: 2}})
			memEq(t, len(stock.Reservations()), 1)
			stock.RemoveReservation("order-1")
			_, found := stock.Reservation("order-1")
			memEq(t, found, false)
			memEq(t, stock.Movements(), []StockMovement{{SKU: "apple", Quantity: 5, Reason: "received"}})
		})

		t.Run("keeps the entries of each account and the events, oldest first", func(t *testing.T) {
			accounts := NewInMemoryAccountRepository()
			accounts.Add(AccountEntry{ID: "entry-1", CustomerID: "customer-1", Kind: "credit", Amount: 500,
				Reason: "gift", On: "2026-03-10"})
			accounts.Add(AccountEntry{ID: "entry-2", CustomerID: "customer-2", Kind: "credit", Amount: 1,
				Reason: "gift", On: "2026-03-10"})
			var ids []string
			for _, entry := range accounts.Entries("customer-1") {
				ids = append(ids, entry.ID)
			}
			memEq(t, ids, []string{"entry-1"})
			events := NewInMemoryEventStore()
			events.Append(ShopEvent{ID: "event-1", Type: "order-placed", Subject: "o", On: "d", Data: EventData{}})
			list := events.List()
			memEq(t, len(list), 1)
			memEq(t, list[0].ID, "event-1")
		})
	})

	t.Run("the payment gateway", func(t *testing.T) {
		t.Run("charges a token", func(t *testing.T) {
			payments := memGateway()
			memEq(t, memMust(payments.Charge("card", 1500))(t), Payment{ID: "payment-1", Token: "card", Amount: 1500})
			memEq(t, payments.Charges(), []Payment{{ID: "payment-1", Token: "card", Amount: 1500}})
		})

		t.Run("rejects an amount below 1", func(t *testing.T) {
			payments := memGateway()
			_, err := payments.Charge("card", 0)
			memErr(t, err, "amount must be at least 1")
			memEq(t, payments.Charges(), []Payment{})
		})

		t.Run("declines a declined token", func(t *testing.T) {
			payments := memGateway()
			payments.Decline("stolen")
			_, err := payments.Charge("stolen", 100)
			memErr(t, err, "payment declined")
			memEq(t, payments.Charges(), []Payment{})
		})

		t.Run("refunds a whole payment once", func(t *testing.T) {
			payments := memGateway()
			payment := memMust(payments.Charge("card", 1500))(t)
			memEq(t, memMust(payments.Refund(payment.ID))(t), Refund{PaymentID: "payment-1", Amount: 1500})
			_, err := payments.Refund(payment.ID)
			memErr(t, err, "payment payment-1 is already refunded")
			memEq(t, payments.Refunds(), []Refund{{PaymentID: "payment-1", Amount: 1500}})
		})

		t.Run("rejects a refund of an unknown payment", func(t *testing.T) {
			_, err := memGateway().Refund("payment-9")
			memErr(t, err, "unknown payment payment-9")
		})

		t.Run("holds the charges less the refunds", func(t *testing.T) {
			payments := memGateway()
			memMust(payments.Charge("card", 1500))(t)
			memMust(payments.Refund(memMust(payments.Charge("card", 400))(t).ID))(t)
			memEq(t, payments.Balance(), 1500)
		})
	})

	t.Run("the outbox", func(t *testing.T) {
		t.Run("keeps each message, in the order sent", func(t *testing.T) {
			outbox := NewInMemoryOutbox()
			outbox.Send(Message{To: "ada@example.com", Subject: "One", Body: "1"})
			outbox.Send(Message{To: "bob@example.com", Subject: "Two", Body: "2"})
			var subjects []string
			for _, m := range outbox.Sent() {
				subjects = append(subjects, m.Subject)
			}
			memEq(t, subjects, []string{"One", "Two"})
			memEq(t, outbox.SentTo("bob@example.com"), []Message{{To: "bob@example.com", Subject: "Two", Body: "2"}})
		})
	})
}
