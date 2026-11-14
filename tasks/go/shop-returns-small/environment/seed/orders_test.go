package shop

import (
	"reflect"
	"testing"
)

// ordersWantError fails the test unless err is an error with the text want.
func ordersWantError(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil {
		t.Fatalf("got no error, want %q", want)
	}
	if err.Error() != want {
		t.Fatalf("got error %q, want %q", err.Error(), want)
	}
}

// ordersMust fails the test on an error.
func ordersMust(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

// ordersWant fails the test unless got and want are deeply equal.
func ordersWant(t *testing.T, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

type ordersFixture struct {
	catalogue *Catalogue
	inventory *Inventory
	orders    *InMemoryOrderRepository
	payments  *InMemoryPaymentGateway
	checkout  *Checkout
}

// ordersShop gives a shop with apples at 250 (10 in stock) and pears at 1000
// (5 in stock).
func ordersShop(t *testing.T) ordersFixture {
	t.Helper()
	ids := NewSequentialIDs()
	catalogue := NewCatalogue(NewInMemoryProductRepository())
	_, err := catalogue.AddProduct("apple", "Apple", 250)
	ordersMust(t, err)
	_, err = catalogue.AddProduct("pear", "Pear", 1000)
	ordersMust(t, err)
	inventory := NewInventory(NewInMemoryStockRepository())
	ordersMust(t, inventory.Receive("apple", 10))
	ordersMust(t, inventory.Receive("pear", 5))
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
	return ordersFixture{catalogue, inventory, orders, payments, checkout}
}

// ordersCart gives a cart of the lines, each a SKU and a quantity.
func ordersCart(t *testing.T, lines ...CartLine) *Cart {
	t.Helper()
	cart := NewCart()
	for _, line := range lines {
		ordersMust(t, cart.Add(line.SKU, line.Quantity))
	}
	return cart
}

type ordersServiceFixture struct {
	ordersFixture
	service *Orders
	t       *testing.T
}

func ordersService(t *testing.T) ordersServiceFixture {
	t.Helper()
	s := ordersShop(t)
	return ordersServiceFixture{s, NewOrders(s.orders, s.inventory, s.payments), t}
}

// place places an order of the lines and gives its id.
func (s ordersServiceFixture) place(lines ...CartLine) string {
	s.t.Helper()
	order, err := s.checkout.PlaceOrder(CheckoutRequest{Cart: ordersCart(s.t, lines...), PaymentToken: "card"})
	ordersMust(s.t, err)
	return order.ID
}

func ordersOrderIDs(orders []Order) []string {
	ids := []string{}
	for _, order := range orders {
		ids = append(ids, order.ID)
	}
	return ids
}

func TestOrders(t *testing.T) {
	t.Run("finds an order by its id", func(t *testing.T) {
		s := ordersService(t)
		id := s.place(CartLine{"apple", 2})
		order, err := s.service.Order(id)
		ordersMust(t, err)
		ordersWant(t, order.Total, 500)
		ordersWant(t, order.Status, OrderStatus("paid"))
	})

	t.Run("rejects an unknown order", func(t *testing.T) {
		_, err := ordersService(t).service.Order("order-9")
		ordersWantError(t, err, "unknown order order-9")
	})

	t.Run("ships a paid order and takes its stock out of the inventory", func(t *testing.T) {
		s := ordersService(t)
		id := s.place(CartLine{"apple", 2})
		ordersMust(t, s.service.Ship(id))
		order, _ := s.service.Order(id)
		ordersWant(t, order.Status, OrderStatus("shipped"))
		ordersWant(t, s.inventory.Level("apple"), StockLevel{"apple", 8, 0})
	})

	t.Run("cancels a paid order, refunds its payment and releases its stock", func(t *testing.T) {
		s := ordersService(t)
		id := s.place(CartLine{"apple", 2}, CartLine{"pear", 1})
		ordersMust(t, s.service.Cancel(id))
		order, _ := s.service.Order(id)
		ordersWant(t, order.Status, OrderStatus("cancelled"))
		ordersWant(t, s.payments.Refunds(), []Refund{{"payment-1", 1500}})
		ordersWant(t, s.inventory.Level("pear"), StockLevel{"pear", 5, 0})
	})

	t.Run("rejects a change to an order that is not paid", func(t *testing.T) {
		s := ordersService(t)
		shipped := s.place(CartLine{"apple", 1})
		ordersMust(t, s.service.Ship(shipped))
		cancelled := s.place(CartLine{"apple", 1})
		ordersMust(t, s.service.Cancel(cancelled))
		ordersWantError(t, s.service.Cancel(shipped), "order order-1 is shipped")
		ordersWantError(t, s.service.Ship(cancelled), "order order-2 is cancelled")
	})

	t.Run("lists the orders with a status in the order that they were placed", func(t *testing.T) {
		s := ordersService(t)
		first := s.place(CartLine{"apple", 1})
		second := s.place(CartLine{"pear", 1})
		third := s.place(CartLine{"apple", 2})
		ordersMust(t, s.service.Ship(second))
		ordersWant(t, ordersOrderIDs(s.service.WithStatus("paid")), []string{first, third})
		ordersWant(t, ordersOrderIDs(s.service.WithStatus("shipped")), []string{second})
	})

	t.Run("adds up the revenue of the orders that are not cancelled", func(t *testing.T) {
		s := ordersService(t)
		s.place(CartLine{"apple", 2})
		ordersMust(t, s.service.Cancel(s.place(CartLine{"pear", 1})))
		ordersMust(t, s.service.Ship(s.place(CartLine{"pear", 2})))
		ordersWant(t, s.service.Revenue(), 2500)
	})

	t.Run("ranks the best sellers", func(t *testing.T) {
		s := ordersService(t)
		s.place(CartLine{"apple", 2}, CartLine{"pear", 1})
		s.place(CartLine{"pear", 1})
		ordersMust(t, s.service.Cancel(s.place(CartLine{"apple", 5})))
		ordersWant(t, s.service.BestSellers(5), []SKUSales{{"apple", 2}, {"pear", 2}})
		ordersWant(t, s.service.BestSellers(1), []SKUSales{{"apple", 2}})
	})
}
