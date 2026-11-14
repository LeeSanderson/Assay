package shop

import (
	"reflect"
	"testing"
)

// cartWantError fails the test unless err is an error with the text want.
func cartWantError(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil {
		t.Fatalf("got no error, want %q", want)
	}
	if err.Error() != want {
		t.Fatalf("got error %q, want %q", err.Error(), want)
	}
}

// cartMust fails the test on an error.
func cartMust(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// cartWant fails the test unless got and want are deeply equal.
func cartWant(t *testing.T, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func TestCart(t *testing.T) {
	t.Run("starts empty", func(t *testing.T) {
		cart := NewCart()
		cartWant(t, cart.IsEmpty(), true)
		cartWant(t, len(cart.Lines()), 0)
	})

	t.Run("adds lines in the order that they were first added", func(t *testing.T) {
		cart := NewCart()
		cartMust(t, cart.Add("pear", 1))
		cartMust(t, cart.Add("apple", 2))
		cartWant(t, cart.Lines(), []CartLine{{"pear", 1}, {"apple", 2}})
	})

	t.Run("adds to the quantity of a SKU that is in the cart", func(t *testing.T) {
		cart := NewCart()
		cartMust(t, cart.Add("apple", 2))
		cartMust(t, cart.Add("pear", 1))
		cartMust(t, cart.Add("apple", 3))
		cartWant(t, cart.Lines(), []CartLine{{"apple", 5}, {"pear", 1}})
	})

	t.Run("rejects a quantity below 1", func(t *testing.T) {
		cart := NewCart()
		cartWantError(t, cart.Add("apple", 0), "quantity must be at least 1")
		cartWant(t, cart.IsEmpty(), true)
	})

	t.Run("sets the quantity of a line", func(t *testing.T) {
		cart := NewCart()
		cartMust(t, cart.Add("apple", 2))
		cartMust(t, cart.SetQuantity("apple", 7))
		cartWant(t, cart.Lines(), []CartLine{{"apple", 7}})
		cartWantError(t, cart.SetQuantity("apple", 0), "quantity must be at least 1")
	})

	t.Run("removes a line", func(t *testing.T) {
		cart := NewCart()
		cartMust(t, cart.Add("apple", 2))
		cartMust(t, cart.Add("pear", 1))
		cartMust(t, cart.Remove("apple"))
		cartWant(t, cart.Lines(), []CartLine{{"pear", 1}})
	})

	t.Run("rejects a change to a SKU that is not in the cart", func(t *testing.T) {
		cart := NewCart()
		cartWantError(t, cart.Remove("kiwi"), "SKU kiwi is not in the cart")
		cartWantError(t, cart.SetQuantity("kiwi", 1), "SKU kiwi is not in the cart")
	})

	t.Run("counts the units and clears the cart", func(t *testing.T) {
		cart := NewCart()
		cartMust(t, cart.Add("apple", 2))
		cartMust(t, cart.Add("pear", 3))
		cartWant(t, cart.ItemCount(), 5)
		cart.Clear()
		cartWant(t, cart.IsEmpty(), true)
		cartWant(t, cart.ItemCount(), 0)
	})
}
