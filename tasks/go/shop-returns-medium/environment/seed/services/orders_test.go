package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

type ordFixture struct {
	t         *testing.T
	inventory *Inventory
	payments  *adapters.InMemoryPaymentGateway
	orders    *Orders
	checkout  *Checkout
	customers *Customers
	clock     *adapters.FixedClock
}

// ordShop gives a shop with apples at 250 (10 in stock) and pears at 1000 (5
// in stock).
func ordShop(t *testing.T) ordFixture {
	t.Helper()
	ids := adapters.NewSequentialIDs()
	clock := adapters.NewFixedClock("2026-03-10")
	catalogue := NewCatalogue(adapters.NewInMemoryProductRepository())
	ordMust(catalogue.AddProduct("apple", "Apple", 250))(t)
	ordMust(catalogue.AddProduct("pear", "Pear", 1000))(t)
	inventory := NewInventory(adapters.NewInMemoryStockRepository())
	ordOK(t, inventory.Receive("apple", 10))
	ordOK(t, inventory.Receive("pear", 5))
	repository := adapters.NewInMemoryOrderRepository()
	payments := adapters.NewInMemoryPaymentGateway(ids)
	customers := NewCustomers(CustomersDeps{Repository: adapters.NewInMemoryCustomerRepository(), Clock: clock, IDs: ids})
	checkout := NewCheckout(CheckoutDeps{Catalogue: catalogue, Inventory: inventory, Orders: repository,
		Payments: payments, Clock: clock, IDs: ids, Customers: customers})
	orders := NewOrders(repository, inventory, payments)
	return ordFixture{t, inventory, payments, orders, checkout, customers, clock}
}

// place places an order of the lines (each a SKU and a quantity) and gives
// its id.
func (s ordFixture) place(pairs ...any) string {
	s.t.Helper()
	cart := NewCart()
	for i := 0; i < len(pairs); i += 2 {
		ordOK(s.t, cart.Add(pairs[i].(string), pairs[i+1].(int)))
	}
	return ordMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: cart, PaymentToken: "card"}))(s.t).ID
}

func ordIDs(orders []Order) []string {
	ids := []string{}
	for _, order := range orders {
		ids = append(ids, order.ID)
	}
	return ids
}

func ordEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := ordShow(got), ordShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func ordShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func ordErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func ordOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func ordMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestOrders(t *testing.T) {
	t.Run("finding orders", func(t *testing.T) {
		t.Run("finds an order by its id", func(t *testing.T) {
			s := ordShop(t)
			id := s.place("apple", 2)
			ordEq(t, ordMust(s.orders.Order(id))(t).Total, 500)
			ordEq(t, ordMust(s.orders.Order(id))(t).Status, OrderStatus("paid"))
		})

		t.Run("rejects an unknown order", func(t *testing.T) {
			_, err := ordShop(t).orders.Order("order-9")
			ordErr(t, err, "unknown order order-9")
		})

		t.Run("lists the orders with a status in the order that they were placed", func(t *testing.T) {
			s := ordShop(t)
			first := s.place("apple", 1)
			second := s.place("pear", 1)
			third := s.place("apple", 2)
			ordOK(t, s.orders.Ship(second))
			ordEq(t, ordIDs(s.orders.WithStatus("paid")), []string{first, third})
			ordEq(t, ordIDs(s.orders.WithStatus("shipped")), []string{second})
			ordEq(t, ordIDs(s.orders.All()), []string{first, second, third})
		})

		t.Run("finds the orders of a customer and the orders of a period", func(t *testing.T) {
			s := ordShop(t)
			ada := ordMust(s.customers.Register("Ada", "ada@example.com", nil))(t)
			s.place("apple", 1)
			s.clock.Set("2026-03-12")
			cart := NewCart()
			ordOK(t, cart.Add("pear", 1))
			hers := ordMust(s.checkout.PlaceOrder(CheckoutRequest{Cart: cart, PaymentToken: "card", CustomerID: ada.ID}))(t).ID
			ordEq(t, ordIDs(s.orders.ForCustomer(ada.ID)), []string{hers})
			ordEq(t, ordIDs(ordMust(s.orders.PlacedBetween("2026-03-11", "2026-03-31"))(t)), []string{hers})
		})

		t.Run("searches the orders with a filter", func(t *testing.T) {
			s := ordShop(t)
			s.place("apple", 1)
			second := s.place("pear", 1, "apple", 1)
			ordOK(t, s.orders.Ship(s.place("pear", 2)))
			ordEq(t, ordIDs(s.orders.Search(OrderFilter{SKU: "pear", Status: "paid"})), []string{second})
			ordEq(t, ordIDs(s.orders.Search(OrderFilter{MinTotal: 1250})), []string{"order-2", "order-3"})
		})

		t.Run("finds the paid orders that have waited too long to ship", func(t *testing.T) {
			s := ordShop(t)
			old := s.place("apple", 1)
			s.clock.Set("2026-03-14")
			s.place("apple", 1)
			ordEq(t, ordIDs(s.orders.WaitingSince("2026-03-15", 3)), []string{old})
		})
	})

	t.Run("shipping and cancelling", func(t *testing.T) {
		t.Run("ships a paid order and takes its stock out of the inventory", func(t *testing.T) {
			s := ordShop(t)
			id := s.place("apple", 2)
			ordOK(t, s.orders.Ship(id))
			ordEq(t, ordMust(s.orders.Order(id))(t).Status, OrderStatus("shipped"))
			ordEq(t, s.inventory.Level("apple"), StockLevel{SKU: "apple", OnHand: 8, Reserved: 0})
		})

		t.Run("cancels a paid order, refunds its payment and releases its stock", func(t *testing.T) {
			s := ordShop(t)
			id := s.place("apple", 2, "pear", 1)
			ordOK(t, s.orders.Cancel(id))
			ordEq(t, ordMust(s.orders.Order(id))(t).Status, OrderStatus("cancelled"))
			ordEq(t, s.payments.Refunds(), []Refund{{PaymentID: "payment-1", Amount: 1500}})
			ordEq(t, s.inventory.Level("pear"), StockLevel{SKU: "pear", OnHand: 5, Reserved: 0})
		})

		t.Run("rejects a change to an order that is not paid", func(t *testing.T) {
			s := ordShop(t)
			shipped := s.place("apple", 1)
			ordOK(t, s.orders.Ship(shipped))
			cancelled := s.place("apple", 1)
			ordOK(t, s.orders.Cancel(cancelled))
			ordErr(t, s.orders.Cancel(shipped), "order order-1 is shipped")
			ordErr(t, s.orders.Ship(cancelled), "order order-2 is cancelled")
			_, err := s.orders.CheckPaid(shipped)
			ordErr(t, err, "order order-1 is shipped")
		})
	})

	t.Run("sales", func(t *testing.T) {
		t.Run("adds up the revenue of the orders that are not cancelled", func(t *testing.T) {
			s := ordShop(t)
			s.place("apple", 2)
			ordOK(t, s.orders.Cancel(s.place("pear", 1)))
			ordOK(t, s.orders.Ship(s.place("pear", 2)))
			ordEq(t, s.orders.Revenue(), 2500)
		})

		t.Run("works out the average order value", func(t *testing.T) {
			s := ordShop(t)
			ordEq(t, s.orders.AverageOrderValue(), 0)
			s.place("apple", 1)
			s.place("pear", 1)
			s.place("pear", 1)
			ordEq(t, s.orders.AverageOrderValue(), 750)
		})

		t.Run("ranks the best sellers", func(t *testing.T) {
			s := ordShop(t)
			s.place("apple", 2, "pear", 1)
			s.place("pear", 1)
			ordOK(t, s.orders.Cancel(s.place("apple", 5)))
			ordEq(t, s.orders.BestSellers(5), []SKUSales{{SKU: "apple", Quantity: 2}, {SKU: "pear", Quantity: 2}})
			ordEq(t, s.orders.BestSellers(1), []SKUSales{{SKU: "apple", Quantity: 2}})
		})
	})
}
