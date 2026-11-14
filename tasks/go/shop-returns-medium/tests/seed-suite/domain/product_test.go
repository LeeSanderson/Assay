package domain

import (
	"fmt"
	"strings"
	"testing"
)

func prodEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := prodShow(got), prodShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func prodShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func prodErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func prodMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestProduct(t *testing.T) {
	t.Run("products", func(t *testing.T) {
		t.Run("makes a product that is on sale", func(t *testing.T) {
			prodEq(t, prodMust(NewProduct("apple", "Apple", 250))(t),
				Product{SKU: "apple", Name: "Apple", UnitPrice: 250, Discontinued: false})
		})

		t.Run("checks the SKU, then the name, then the price", func(t *testing.T) {
			_, err := NewProduct("", "", 0)
			prodErr(t, err, "SKU must not be empty")
			_, err = NewProduct("apple", "", 0)
			prodErr(t, err, "name must not be empty")
			_, err = NewProduct("apple", "Apple", 0)
			prodErr(t, err, "unit price must be at least 1")
		})

		t.Run("reads a product from a row of a price list", func(t *testing.T) {
			prodEq(t, prodMust(ProductOfRow(ProductRow{SKU: " fig ", Name: "Fig ", Price: "4.20"}))(t),
				Product{SKU: "fig", Name: "Fig", UnitPrice: 420, Discontinued: false})
			_, err := ProductOfRow(ProductRow{SKU: "fig", Name: "Fig", Price: "cheap"})
			prodErr(t, err, "cheap is not an amount")
		})
	})
}
