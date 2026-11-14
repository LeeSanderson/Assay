package domain

import (
	"fmt"
	"strings"
	"testing"
)

func cartEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := cartShow(got), cartShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func cartShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func cartErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func cartOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func TestCart(t *testing.T) {
	t.Run("starts empty", func(t *testing.T) {
		cart := NewCart()
		cartEq(t, cart.IsEmpty(), true)
		cartEq(t, cart.Lines(), []CartLine{})
	})

	t.Run("adds lines in the order that they were first added", func(t *testing.T) {
		cart := NewCart()
		cartOK(t, cart.Add("pear", 1))
		cartOK(t, cart.Add("apple", 2))
		cartEq(t, cart.Lines(), []CartLine{{SKU: "pear", Quantity: 1}, {SKU: "apple", Quantity: 2}})
	})

	t.Run("adds to the quantity of a SKU that is in the cart", func(t *testing.T) {
		cart := NewCart()
		cartOK(t, cart.Add("apple", 2))
		cartOK(t, cart.Add("pear", 1))
		cartOK(t, cart.Add("apple", 3))
		cartEq(t, cart.Lines(), []CartLine{{SKU: "apple", Quantity: 5}, {SKU: "pear", Quantity: 1}})
	})

	t.Run("rejects a quantity below 1", func(t *testing.T) {
		cart := NewCart()
		cartErr(t, cart.Add("apple", 0), "quantity must be at least 1")
		cartEq(t, cart.IsEmpty(), true)
	})

	t.Run("sets the quantity of a line", func(t *testing.T) {
		cart := NewCart()
		cartOK(t, cart.Add("apple", 2))
		cartOK(t, cart.SetQuantity("apple", 7))
		cartEq(t, cart.Lines(), []CartLine{{SKU: "apple", Quantity: 7}})
		cartErr(t, cart.SetQuantity("apple", 0), "quantity must be at least 1")
	})

	t.Run("removes a line", func(t *testing.T) {
		cart := NewCart()
		cartOK(t, cart.Add("apple", 2))
		cartOK(t, cart.Add("pear", 1))
		cartOK(t, cart.Remove("apple"))
		cartEq(t, cart.Lines(), []CartLine{{SKU: "pear", Quantity: 1}})
	})

	t.Run("rejects a change to a SKU that is not in the cart", func(t *testing.T) {
		cart := NewCart()
		cartErr(t, cart.Remove("kiwi"), "SKU kiwi is not in the cart")
		cartErr(t, cart.SetQuantity("kiwi", 1), "SKU kiwi is not in the cart")
	})

	t.Run("counts the units and clears the cart", func(t *testing.T) {
		cart := NewCart()
		cartOK(t, cart.Add("apple", 2))
		cartOK(t, cart.Add("pear", 3))
		cartEq(t, cart.ItemCount(), 5)
		cart.Clear()
		cartEq(t, cart.IsEmpty(), true)
		cartEq(t, cart.ItemCount(), 0)
	})
}
