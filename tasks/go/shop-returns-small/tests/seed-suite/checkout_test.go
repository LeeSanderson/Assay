package shop

import (
	"reflect"
	"testing"
)

// checkoutWantError fails the test unless err is an error with the text want.
func checkoutWantError(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil {
		t.Fatalf("got no error, want %q", want)
	}
	if err.Error() != want {
		t.Fatalf("got error %q, want %q", err.Error(), want)
	}
}

// checkoutMust fails the test on an error.
func checkoutMust(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// checkoutWant fails the test unless got and want are deeply equal.
func checkoutWant(t *testing.T, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

type checkoutFixture struct {
	catalogue *Catalogue
	inventory *Inventory
	orders    *InMemoryOrderRepository
	payments  *InMemoryPaymentGateway
	checkout  *Checkout
}

// checkoutShop gives a shop with apples at 250 (10 in stock) and pears at 1000
// (5 in stock).
func checkoutShop(t *testing.T) checkoutFixture {
	t.Helper()
	ids := NewSequentialIDs()
	catalogue := NewCatalogue(NewInMemoryProductRepository())
	_, err := catalogue.AddProduct("apple", "Apple", 250)
	checkoutMust(t, err)
	_, err = catalogue.AddProduct("pear", "Pear", 1000)
	checkoutMust(t, err)
	inventory := NewInventory(NewInMemoryStockRepository())
	checkoutMust(t, inventory.Receive("apple", 10))
	checkoutMust(t, inventory.Receive("pear", 5))
	orders := NewInMemoryOrderRepository()
	payments := NewInMemoryPaymentGateway(ids)
	checkout := NewCheckout(CheckoutDeps{
		Catalogue: catalogue,
		Inventory: inventory,
		Orders:    orders,
		Payments:  payments,
		Clock:     NewFixedClock("2026-03-10"),
		IDs:       ids,
	})
	return checkoutFixture{catalogue, inventory, orders, payments, checkout}
}

// checkoutCart gives a cart of the lines, each a SKU and a quantity.
func checkoutCart(t *testing.T, lines ...CartLine) *Cart {
	t.Helper()
	cart := NewCart()
	for _, line := range lines {
		checkoutMust(t, cart.Add(line.SKU, line.Quantity))
	}
	return cart
}

func TestCheckout(t *testing.T) {
	t.Run("places an order at the catalogue prices", func(t *testing.T) {
		s := checkoutShop(t)
		order, err := s.checkout.PlaceOrder(CheckoutRequest{
			Cart:         checkoutCart(t, CartLine{"apple", 2}, CartLine{"pear", 1}),
			PaymentToken: "card",
		})
		checkoutMust(t, err)
		checkoutWant(t, order, Order{
			ID: "order-1",
			Lines: []OrderLine{
				{SKU: "apple", Name: "Apple", UnitPrice: 250, Quantity: 2},
				{SKU: "pear", Name: "Pear", UnitPrice: 1000, Quantity: 1},
			},
			Subtotal:  1500,
			Discounts: []Discount{},
			Total:     1500,
			Status:    "paid",
			PaymentID: "payment-1",
			PlacedOn:  "2026-03-10",
		})
	})

	t.Run("quotes a cart without placing an order", func(t *testing.T) {
		s := checkoutShop(t)
		quote, err := s.checkout.Quote(checkoutCart(t, CartLine{"apple", 2}, CartLine{"pear", 1}), nil)
		checkoutMust(t, err)
		checkoutWant(t, quote, Quote{Subtotal: 1500, Discounts: []Discount{}, Total: 1500})
		checkoutWant(t, len(s.orders.List()), 0)
		checkoutWant(t, s.inventory.Available("apple"), 10)
	})

	t.Run("charges the payment the total of the order", func(t *testing.T) {
		s := checkoutShop(t)
		_, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: checkoutCart(t, CartLine{"pear", 2}), PaymentToken: "card"})
		checkoutMust(t, err)
		checkoutWant(t, s.payments.Charges(), []Payment{{"payment-1", "card", 2000}})
	})

	t.Run("reserves the stock of the order", func(t *testing.T) {
		s := checkoutShop(t)
		_, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: checkoutCart(t, CartLine{"apple", 3}), PaymentToken: "card"})
		checkoutMust(t, err)
		checkoutWant(t, s.inventory.Level("apple"), StockLevel{"apple", 10, 3})
	})

	t.Run("saves the order", func(t *testing.T) {
		s := checkoutShop(t)
		order, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: checkoutCart(t, CartLine{"apple", 1}), PaymentToken: "card"})
		checkoutMust(t, err)
		saved, ok := s.orders.Get("order-1")
		checkoutWant(t, ok, true)
		checkoutWant(t, saved, order)
	})

	t.Run("rejects an empty cart", func(t *testing.T) {
		s := checkoutShop(t)
		_, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: NewCart(), PaymentToken: "card"})
		checkoutWantError(t, err, "the cart is empty")
	})

	t.Run("rejects an unknown product", func(t *testing.T) {
		s := checkoutShop(t)
		_, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: checkoutCart(t, CartLine{"kiwi", 1}), PaymentToken: "card"})
		checkoutWantError(t, err, "unknown product kiwi")
	})

	t.Run("rejects a discontinued product", func(t *testing.T) {
		s := checkoutShop(t)
		checkoutMust(t, s.catalogue.Discontinue("pear"))
		_, err := s.checkout.Quote(checkoutCart(t, CartLine{"pear", 1}), nil)
		checkoutWantError(t, err, "product pear is discontinued")
	})

	t.Run("changes nothing when the stock is short", func(t *testing.T) {
		s := checkoutShop(t)
		_, err := s.checkout.PlaceOrder(CheckoutRequest{
			Cart:         checkoutCart(t, CartLine{"apple", 1}, CartLine{"pear", 6}),
			PaymentToken: "card",
		})
		checkoutWantError(t, err, "not enough stock of pear: 5 available")
		checkoutWant(t, s.inventory.Available("apple"), 10)
		checkoutWant(t, len(s.payments.Charges()), 0)
		checkoutWant(t, len(s.orders.List()), 0)
	})

	t.Run("releases the stock when the payment is declined", func(t *testing.T) {
		s := checkoutShop(t)
		s.payments.Decline("stolen")
		_, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: checkoutCart(t, CartLine{"apple", 2}), PaymentToken: "stolen"})
		checkoutWantError(t, err, "payment declined")
		checkoutWant(t, s.inventory.Level("apple"), StockLevel{"apple", 10, 0})
		checkoutWant(t, len(s.orders.List()), 0)
	})

	t.Run("gives each order its own id", func(t *testing.T) {
		s := checkoutShop(t)
		first, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: checkoutCart(t, CartLine{"apple", 1}), PaymentToken: "card"})
		checkoutMust(t, err)
		second, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: checkoutCart(t, CartLine{"apple", 1}), PaymentToken: "card"})
		checkoutMust(t, err)
		checkoutWant(t, []string{first.ID, second.ID}, []string{"order-1", "order-2"})
	})
}
