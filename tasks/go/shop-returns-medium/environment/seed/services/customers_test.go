package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

func custHome() Address {
	return Address{Line1: "1 High St", City: "Leeds", Postcode: "LS1 1AA", Country: "GB"}
}

func custService() (*adapters.FixedClock, *Customers) {
	clock := adapters.NewFixedClock("2026-03-10")
	return clock, NewCustomers(CustomersDeps{Repository: adapters.NewInMemoryCustomerRepository(),
		Clock: clock, IDs: adapters.NewSequentialIDs()})
}

func custNames(customers []Customer) []string {
	names := []string{}
	for _, customer := range customers {
		names = append(names, customer.Name)
	}
	return names
}

func custEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := custShow(got), custShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func custShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func custErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func custMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestCustomers(t *testing.T) {
	t.Run("registration", func(t *testing.T) {
		t.Run("registers a customer with a lower-case email address", func(t *testing.T) {
			_, service := custService()
			home := custHome()
			ada := custMust(service.Register(" Ada ", "Ada@Example.com", &home))(t)
			if ada.Address == nil {
				t.Fatal("no address")
			}
			custEq(t, *ada.Address, custHome())
			ada.Address = nil
			custEq(t, ada, Customer{ID: "customer-1", Name: "Ada", Email: "ada@example.com", RegisteredOn: "2026-03-10"})
		})

		t.Run("registers a customer without an address", func(t *testing.T) {
			_, service := custService()
			bob := custMust(service.Register("Bob", "bob@example.com", nil))(t)
			custEq(t, bob.Address == nil, true)
			_, err := service.AddressOf(bob.ID)
			custErr(t, err, "customer customer-1 has no address")
		})

		t.Run("rejects an email address that is already registered, in any case", func(t *testing.T) {
			_, service := custService()
			custMust(service.Register("Ada", "ada@example.com", nil))(t)
			_, err := service.Register("Ada two", "ADA@example.com", nil)
			custErr(t, err, "email ada@example.com is already registered")
		})

		t.Run("rejects a broken name, email address or address", func(t *testing.T) {
			_, service := custService()
			_, err := service.Register("", "ada@example.com", nil)
			custErr(t, err, "name must not be empty")
			_, err = service.Register("Ada", "ada", nil)
			custErr(t, err, "ada is not an email address")
			broken := custHome()
			broken.Postcode = ""
			_, err = service.Register("Ada", "ada@example.com", &broken)
			custErr(t, err, "postcode must not be empty")
		})
	})

	t.Run("finding customers", func(t *testing.T) {
		t.Run("finds a customer by id or by email address", func(t *testing.T) {
			_, service := custService()
			ada := custMust(service.Register("Ada", "ada@example.com", nil))(t)
			custEq(t, custMust(service.Customer(ada.ID))(t).Name, "Ada")
			custEq(t, custMust(service.ByEmail("ADA@EXAMPLE.COM"))(t).ID, ada.ID)
			_, err := service.Customer("customer-9")
			custErr(t, err, "unknown customer customer-9")
			_, err = service.ByEmail("bob@example.com")
			custErr(t, err, "unknown customer bob@example.com")
		})

		t.Run("searches the names and email addresses in any case", func(t *testing.T) {
			_, service := custService()
			custMust(service.Register("Ada Lovelace", "ada@example.com", nil))(t)
			custMust(service.Register("Bob", "bob@lovelace.example", nil))(t)
			custMust(service.Register("Cy", "cy@example.com", nil))(t)
			custEq(t, custNames(service.Search("LOVELACE")), []string{"Ada Lovelace", "Bob"})
		})
	})

	t.Run("changes", func(t *testing.T) {
		t.Run("renames a customer and changes its email address", func(t *testing.T) {
			_, service := custService()
			ada := custMust(service.Register("Ada", "ada@example.com", nil))(t)
			custMust(service.Register("Bob", "bob@example.com", nil))(t)
			custEq(t, custMust(service.Rename(ada.ID, "Ada L"))(t).Name, "Ada L")
			custEq(t, custMust(service.ChangeEmail(ada.ID, "AL@example.com"))(t).Email, "al@example.com")
			custEq(t, custMust(service.ChangeEmail(ada.ID, "al@example.com"))(t).Email, "al@example.com")
			_, err := service.ChangeEmail(ada.ID, "bob@example.com")
			custErr(t, err, "email bob@example.com is already registered")
		})

		t.Run("moves a customer to a new address", func(t *testing.T) {
			_, service := custService()
			ada := custMust(service.Register("Ada", "ada@example.com", nil))(t)
			custMust(service.MoveTo(ada.ID, custHome()))(t)
			custEq(t, custMust(service.AddressOf(ada.ID))(t), custHome())
		})

		t.Run("closes the account of a customer once", func(t *testing.T) {
			clock, service := custService()
			ada := custMust(service.Register("Ada", "ada@example.com", nil))(t)
			bob := custMust(service.Register("Bob", "bob@example.com", nil))(t)
			clock.Set("2026-04-01")
			custEq(t, custMust(service.Close(ada.ID))(t).ClosedOn, "2026-04-01")
			_, err := service.Open(ada.ID)
			custErr(t, err, "customer customer-1 is closed")
			_, err = service.Close(ada.ID)
			custErr(t, err, "customer customer-1 is closed")
			ids := []string{}
			for _, customer := range service.OpenCustomers() {
				ids = append(ids, customer.ID)
			}
			custEq(t, ids, []string{bob.ID})
		})
	})
}
