package domain

import (
	"fmt"
	"strings"
	"testing"
)

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

func custOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func custHome() Address {
	return Address{Line1: "1 High St", City: "Leeds", Postcode: "LS1 1AA", Country: "GB"}
}

func TestCustomer(t *testing.T) {
	t.Run("customers", func(t *testing.T) {
		t.Run("keeps an email address in lower case without spaces", func(t *testing.T) {
			custEq(t, NormaliseEmail("  Ada@Example.COM "), "ada@example.com")
		})

		t.Run("rejects a text that is not an email address", func(t *testing.T) {
			custErr(t, CheckEmail("ada.example.com"), "ada.example.com is not an email address")
			custOK(t, CheckEmail("Ada@Example.com"))
		})

		t.Run("checks each part of an address", func(t *testing.T) {
			custOK(t, CheckAddress(custHome()))
			noCity := custHome()
			noCity.City = " "
			custErr(t, CheckAddress(noCity), "city must not be empty")
			lower := custHome()
			lower.Country = "gb"
			custErr(t, CheckAddress(lower), "gb is not a country code")
		})

		t.Run("writes an address on one line", func(t *testing.T) {
			custEq(t, FormatAddress(custHome()), "1 High St, Leeds LS1 1AA, GB")
		})

		t.Run("copies a customer with its address", func(t *testing.T) {
			home := custHome()
			customer := Customer{ID: "customer-1", Name: "Ada", Email: "ada@example.com",
				Address: &home, RegisteredOn: "2026-03-10"}
			copied := CopyCustomer(customer)
			copied.Address.City = "York"
			custEq(t, customer.Address.City, "Leeds")
		})
	})

	t.Run("accounts", func(t *testing.T) {
		t.Run("keeps a balance of each kind of entry", func(t *testing.T) {
			entry := func(kind EntryKind, amount int) AccountEntry {
				return AccountEntry{ID: "entry", CustomerID: "customer-1", Kind: kind, Amount: amount,
					Reason: "test", On: "2026-03-10"}
			}
			entries := []AccountEntry{entry("credit", 500), entry("points", 12), entry("credit", -200)}
			custEq(t, BalanceOf(entries, "credit"), 300)
			custEq(t, BalanceOf(entries, "points"), 12)
		})
	})
}
