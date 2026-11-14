package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

type accFixture struct {
	service   *Accounts
	customers *Customers
	clock     *adapters.FixedClock
	ada, bob  string
}

// accShop gives two customers, Ada (customer-1) and Bob (customer-2), with
// empty accounts.
func accShop(t *testing.T) accFixture {
	t.Helper()
	clock := adapters.NewFixedClock("2026-03-10")
	ids := adapters.NewSequentialIDs()
	customers := NewCustomers(CustomersDeps{Repository: adapters.NewInMemoryCustomerRepository(), Clock: clock, IDs: ids})
	ada := accMust(customers.Register("Ada", "ada@example.com", nil))(t).ID
	bob := accMust(customers.Register("Bob", "bob@example.com", nil))(t).ID
	service := NewAccounts(AccountsDeps{Repository: adapters.NewInMemoryAccountRepository(), Customers: customers,
		Clock: clock, IDs: ids})
	return accFixture{service, customers, clock, ada, bob}
}

func accEvent(eventType, subject string, data EventData) ShopEvent {
	return ShopEvent{ID: "event-1", Type: eventType, Subject: subject, On: "2026-03-10", Data: data}
}

func accEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := accShow(got), accShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func accShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func accErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func accOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func accMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestAccounts(t *testing.T) {
	t.Run("store credit", func(t *testing.T) {
		t.Run("adds and uses store credit", func(t *testing.T) {
			s := accShop(t)
			accMust(s.service.AddCredit(s.ada, 1000, "gift card"))(t)
			accMust(s.service.UseCredit(s.ada, 400, "order order-1"))(t)
			accEq(t, accMust(s.service.Credit(s.ada))(t), 600)
		})

		t.Run("cannot take store credit below zero", func(t *testing.T) {
			s := accShop(t)
			accMust(s.service.AddCredit(s.ada, 300, "goodwill"))(t)
			_, err := s.service.UseCredit(s.ada, 301, "order order-1")
			accErr(t, err, "customer customer-1 has 300 store credit")
		})

		t.Run("rejects a broken amount or reason, or an unknown customer", func(t *testing.T) {
			s := accShop(t)
			_, err := s.service.AddCredit(s.ada, 0, "gift")
			accErr(t, err, "amount must be at least 1")
			_, err = s.service.AddCredit(s.ada, 100, " ")
			accErr(t, err, "reason must not be empty")
			_, err = s.service.AddCredit("customer-9", 100, "gift")
			accErr(t, err, "unknown customer customer-9")
		})

		t.Run("transfers store credit between customers, all or none", func(t *testing.T) {
			s := accShop(t)
			accMust(s.service.AddCredit(s.ada, 500, "gift"))(t)
			accOK(t, s.service.TransferCredit(s.ada, s.bob, 200))
			accEq(t, []int{accMust(s.service.Credit(s.ada))(t), accMust(s.service.Credit(s.bob))(t)}, []int{300, 200})
			accMust(s.customers.Close(s.bob))(t)
			accErr(t, s.service.TransferCredit(s.ada, s.bob, 100), "customer customer-2 is closed")
			accErr(t, s.service.TransferCredit(s.ada, s.ada, 100), "a customer cannot transfer credit to itself")
			accEq(t, accMust(s.service.Credit(s.ada))(t), 300)
		})

		t.Run("lists the customers who hold credit, the most first", func(t *testing.T) {
			s := accShop(t)
			accMust(s.service.AddCredit(s.ada, 100, "gift"))(t)
			accMust(s.service.AddCredit(s.bob, 400, "gift"))(t)
			accEq(t, s.service.CreditHolders(), []struct {
				CustomerID string
				Credit     Cents
			}{{s.bob, 400}, {s.ada, 100}})
		})
	})

	t.Run("loyalty points", func(t *testing.T) {
		t.Run("awards a point for each whole 100 cents of a placed order", func(t *testing.T) {
			s := accShop(t)
			accOK(t, s.service.OnOrderPlaced(accEvent("order-placed", "order-1", EventData{"total": 1299, "customerId": s.ada})))
			accOK(t, s.service.OnOrderPlaced(accEvent("order-placed", "order-2", EventData{"total": 99, "customerId": s.ada})))
			accOK(t, s.service.OnOrderPlaced(accEvent("order-placed", "order-3", EventData{"total": 5000})))
			accEq(t, accMust(s.service.Points(s.ada))(t), 12)
		})

		t.Run("takes back the points of a cancelled order", func(t *testing.T) {
			s := accShop(t)
			accOK(t, s.service.OnOrderPlaced(accEvent("order-placed", "order-1", EventData{"total": 1299, "customerId": s.ada})))
			accOK(t, s.service.OnOrderPlaced(accEvent("order-placed", "order-2", EventData{"total": 500, "customerId": s.ada})))
			accOK(t, s.service.OnOrderCancelled(accEvent("order-cancelled", "order-1", EventData{"total": 1299, "customerId": s.ada})))
			accEq(t, accMust(s.service.Points(s.ada))(t), 5)
		})

		t.Run("trades points for store credit in blocks of 500", func(t *testing.T) {
			s := accShop(t)
			accOK(t, s.service.OnOrderPlaced(accEvent("order-placed", "order-1", EventData{"total": 120000, "customerId": s.ada})))
			accMust(s.service.RedeemPoints(s.ada, 1000))(t)
			accEq(t, []int{accMust(s.service.Points(s.ada))(t), accMust(s.service.Credit(s.ada))(t)}, []int{200, 1000})
			_, err := s.service.RedeemPoints(s.ada, 250)
			accErr(t, err, "points must be a multiple of 500")
			_, err = s.service.RedeemPoints(s.ada, 500)
			accErr(t, err, "customer customer-1 has 200 points")
		})

		t.Run("gives a statement of every entry and both balances", func(t *testing.T) {
			s := accShop(t)
			accMust(s.service.AddCredit(s.ada, 250, "goodwill"))(t)
			s.clock.Set("2026-03-11")
			accOK(t, s.service.OnOrderPlaced(accEvent("order-placed", "order-4", EventData{"total": 700, "customerId": s.ada})))
			statement := accMust(s.service.Statement(s.ada))(t)
			accEq(t, []int{statement.Credit, statement.Points}, []int{250, 7})
			rows := []string{}
			for _, e := range statement.Entries {
				rows = append(rows, fmt.Sprintf("%s %d %s %s", e.Kind, e.Amount, e.Reason, e.On))
			}
			accEq(t, rows, []string{"credit 250 goodwill 2026-03-10", "points 7 order order-4 2026-03-11"})
		})
	})
}
