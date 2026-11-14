package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

type coShopFixture struct {
	catalogue *Catalogue
	inventory *Inventory
	orders    *adapters.InMemoryOrderRepository
	payments  *adapters.InMemoryPaymentGateway
	customers *Customers
	checkout  *Checkout
	clock     *adapters.FixedClock
	ids       *adapters.SequentialIDs
}

// coShop gives a shop with apples at 250 (10 in stock) and pears at 1000 (5
// in stock).
func coShop(t *testing.T) coShopFixture {
	t.Helper()
	ids := adapters.NewSequentialIDs()
	clock := adapters.NewFixedClock("2026-03-10")
	catalogue := NewCatalogue(adapters.NewInMemoryProductRepository())
	coMust(catalogue.AddProduct("apple", "Apple", 250))(t)
	coMust(catalogue.AddProduct("pear", "Pear", 1000))(t)
	inventory := NewInventory(adapters.NewInMemoryStockRepository())
	coOK(t, inventory.Receive("apple", 10))
	coOK(t, inventory.Receive("pear", 5))
	orders := adapters.NewInMemoryOrderRepository()
	payments := adapters.NewInMemoryPaymentGateway(ids)
	customers := NewCustomers(CustomersDeps{Repository: adapters.NewInMemoryCustomerRepository(), Clock: clock, IDs: ids})
	checkout := NewCheckout(CheckoutDeps{Catalogue: catalogue, Inventory: inventory, Orders: orders,
		Payments: payments, Clock: clock, IDs: ids, Customers: customers})
	return coShopFixture{catalogue, inventory, orders, payments, customers, checkout, clock, ids}
}

// coCart gives a cart of the lines, each a SKU and a quantity.
func coCart(t *testing.T, pairs ...any) *Cart {
	t.Helper()
	cart := NewCart()
	for i := 0; i < len(pairs); i += 2 {
		coOK(t, cart.Add(pairs[i].(string), pairs[i+1].(int)))
	}
	return cart
}

func coEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := coShow(got), coShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func coShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func coErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func coOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func coMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestCheckout(t *testing.T) {
	t.Run("placing orders", func(t *testing.T) {
		t.Run("places an order at the catalogue prices", func(t *testing.T) {
			s := coShop(t)
			order := coMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "apple", 2, "pear", 1), PaymentToken: "card"}))(t)
			coEq(t, order, Order{
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
			s := coShop(t)
			coEq(t, coMust(s.checkout.Quote(coCart(t, "apple", 2, "pear", 1), nil))(t),
				Quote{Subtotal: 1500, Discounts: []Discount{}, Total: 1500})
			coEq(t, s.orders.List(), []Order{})
			coEq(t, s.inventory.Available("apple"), 10)
		})

		t.Run("charges the payment the total of the order", func(t *testing.T) {
			s := coShop(t)
			coMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "pear", 2), PaymentToken: "card"}))(t)
			coEq(t, s.payments.Charges(), []Payment{{ID: "payment-1", Token: "card", Amount: 2000}})
		})

		t.Run("reserves the stock of the order", func(t *testing.T) {
			s := coShop(t)
			coMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "apple", 3), PaymentToken: "card"}))(t)
			coEq(t, s.inventory.Level("apple"), StockLevel{SKU: "apple", OnHand: 10, Reserved: 3})
		})

		t.Run("saves the order", func(t *testing.T) {
			s := coShop(t)
			order := coMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "apple", 1), PaymentToken: "card"}))(t)
			saved, ok := s.orders.Get("order-1")
			coEq(t, ok, true)
			coEq(t, saved, order)
		})

		t.Run("gives each order its own id", func(t *testing.T) {
			s := coShop(t)
			first := coMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "apple", 1), PaymentToken: "card"}))(t)
			second := coMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "apple", 1), PaymentToken: "card"}))(t)
			coEq(t, []string{first.ID, second.ID}, []string{"order-1", "order-2"})
		})

		t.Run("prices an order with the promotions of an engine", func(t *testing.T) {
			s := coShop(t)
			promotions := NewPromotionEngine()
			coOK(t, promotions.AddPromotion(Promotion{ID: "ten", Kind: "percentage", Percent: 10}))
			checkout := NewCheckout(CheckoutDeps{Catalogue: s.catalogue, Inventory: s.inventory, Orders: s.orders,
				Payments: s.payments, Clock: s.clock, IDs: s.ids, Promotions: promotions})
			order := coMust(checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "pear", 1), PaymentToken: "card"}))(t)
			coEq(t, order.Discounts, []Discount{{PromotionID: "ten", Amount: 100}})
			coEq(t, order.Total, 900)
		})
	})

	t.Run("failed checkouts", func(t *testing.T) {
		t.Run("rejects an empty cart", func(t *testing.T) {
			_, err := coShop(t).checkout.PlaceOrder(CheckoutRequest{Cart: NewCart(), PaymentToken: "card"})
			coErr(t, err, "the cart is empty")
		})

		t.Run("rejects an unknown product", func(t *testing.T) {
			s := coShop(t)
			_, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "kiwi", 1), PaymentToken: "card"})
			coErr(t, err, "unknown product kiwi")
		})

		t.Run("rejects a discontinued product", func(t *testing.T) {
			s := coShop(t)
			coOK(t, s.catalogue.Discontinue("pear"))
			_, err := s.checkout.Quote(coCart(t, "pear", 1), nil)
			coErr(t, err, "product pear is discontinued")
		})

		t.Run("rejects coupons when it has no promotions engine", func(t *testing.T) {
			s := coShop(t)
			_, err := s.checkout.Quote(coCart(t, "pear", 1), []string{"SAVE10"})
			coErr(t, err, "this checkout takes no coupons")
		})

		t.Run("changes nothing when the stock is short", func(t *testing.T) {
			s := coShop(t)
			_, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "apple", 1, "pear", 6), PaymentToken: "card"})
			coErr(t, err, "not enough stock of pear: 5 available")
			coEq(t, s.inventory.Available("apple"), 10)
			coEq(t, s.payments.Charges(), []Payment{})
			coEq(t, s.orders.List(), []Order{})
		})

		t.Run("releases the stock when the payment is declined", func(t *testing.T) {
			s := coShop(t)
			s.payments.Decline("stolen")
			_, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "apple", 2), PaymentToken: "stolen"})
			coErr(t, err, "payment declined")
			coEq(t, s.inventory.Level("apple"), StockLevel{SKU: "apple", OnHand: 10, Reserved: 0})
			coEq(t, s.orders.List(), []Order{})
		})
	})

	t.Run("customers", func(t *testing.T) {
		t.Run("places an order for a customer", func(t *testing.T) {
			s := coShop(t)
			ada := coMust(s.customers.Register("Ada", "ada@example.com", nil))(t)
			order := coMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "apple", 1), PaymentToken: "card",
				CustomerID: ada.ID}))(t)
			coEq(t, order.CustomerID, "customer-1")
		})

		t.Run("rejects an unknown or closed customer and changes nothing", func(t *testing.T) {
			s := coShop(t)
			request := CheckoutRequest{Cart: coCart(t, "apple", 1), PaymentToken: "card", CustomerID: "customer-9"}
			_, err := s.checkout.PlaceOrder(request)
			coErr(t, err, "unknown customer customer-9")
			ada := coMust(s.customers.Register("Ada", "ada@example.com", nil))(t)
			coMust(s.customers.Close(ada.ID))(t)
			request.CustomerID = ada.ID
			_, err = s.checkout.PlaceOrder(request)
			coErr(t, err, "customer customer-1 is closed")
			coEq(t, s.payments.Charges(), []Payment{})
		})
	})

	t.Run("cart problems", func(t *testing.T) {
		t.Run("lists the problems of a cart without throwing", func(t *testing.T) {
			s := coShop(t)
			coMust(s.catalogue.AddProduct("fig", "Fig", 400))(t)
			coOK(t, s.catalogue.Discontinue("fig"))
			coEq(t, s.checkout.Problems(coCart(t, "kiwi", 1, "fig", 1, "pear", 7, "apple", 2)), []CartProblem{
				{SKU: "kiwi", Problem: "unknown product"},
				{SKU: "fig", Problem: "discontinued"},
				{SKU: "pear", Problem: "not enough stock", Available: 5},
			})
		})

		t.Run("fits a cart to what the checkout can place", func(t *testing.T) {
			s := coShop(t)
			coOK(t, s.inventory.Reserve("order-9", []StockLine{{SKU: "apple", Quantity: 10}}))
			items := coCart(t, "kiwi", 1, "pear", 7, "apple", 2)
			coEq(t, len(s.checkout.Fit(items)), 3)
			coEq(t, items.Lines(), []CartLine{{SKU: "pear", Quantity: 5}})
			coEq(t, s.checkout.Problems(items), []CartProblem{})
		})

		t.Run("fills a new cart with the lines of an earlier order", func(t *testing.T) {
			s := coShop(t)
			order := coMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: coCart(t, "apple", 2, "pear", 1), PaymentToken: "card"}))(t)
			coOK(t, s.catalogue.Discontinue("pear"))
			coEq(t, coMust(s.checkout.Reorder(order.ID))(t).Lines(), []CartLine{{SKU: "apple", Quantity: 2}})
			_, err := s.checkout.Reorder("order-9")
			coErr(t, err, "unknown order order-9")
		})
	})
}
