package domain

import (
	"errors"
	"testing"
)

func errsErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func errsTrue(t *testing.T, ok bool, what string) {
	t.Helper()
	if !ok {
		t.Fatal(what)
	}
}

func TestErrors(t *testing.T) {
	t.Run("shop errors", func(t *testing.T) {
		t.Run("names an unknown record by its kind and id", func(t *testing.T) {
			err := NotFound("order", "order-9")
			var shop *ShopError
			errsTrue(t, errors.As(err, &shop), "not a ShopError")
			errsTrue(t, shop.Code == CodeNotFound, "code "+string(shop.Code))
			errsErr(t, err, "unknown order order-9")
		})

		t.Run("names a record in the wrong state", func(t *testing.T) {
			err := WrongState("order", "order-1", "shipped")
			errsTrue(t, IsShopError(err, CodeState), "not a state error")
			errsErr(t, err, "order order-1 is shipped")
		})

		t.Run("tells a shop error by its code", func(t *testing.T) {
			errsTrue(t, IsShopError(NotFound("order", "x"), CodeNotFound), "not-found")
			errsTrue(t, !IsShopError(NotFound("order", "x"), CodeState), "not state")
			errsTrue(t, !IsShopError(errors.New("boom"), ""), "a plain error")
		})
	})

	t.Run("checks", func(t *testing.T) {
		t.Run("throws an invalid error when a rule does not hold", func(t *testing.T) {
			errsErr(t, Check(false, "no"), "no")
			errsTrue(t, IsShopError(Check(false, "no"), CodeInvalid), "invalid")
			errsTrue(t, Check(true, "no") == nil, "a rule that holds")
		})

		t.Run("rejects a quantity that is not a whole number of at least 1", func(t *testing.T) {
			for _, quantity := range []int{0, -1} {
				errsErr(t, CheckQuantity(quantity), "quantity must be at least 1")
			}
			errsTrue(t, CheckQuantity(1) == nil, "a quantity of 1")
		})

		t.Run("rejects text that holds only spaces", func(t *testing.T) {
			errsErr(t, CheckNotEmpty("  ", "name"), "name must not be empty")
		})
	})
}
