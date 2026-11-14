package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

func shipLeeds() Address {
	return Address{Line1: "1 High St", City: "Leeds", Postcode: "LS1 1AA", Country: "GB"}
}

func shipParis() Address {
	return Address{Line1: "2 Rue Haute", City: "Paris", Postcode: "75001", Country: "FR"}
}

type shipFixture struct {
	t         *testing.T
	clock     *adapters.FixedClock
	inventory *Inventory
	customers *Customers
	orders    *Orders
	outbox    *adapters.InMemoryOutbox
	shipping  *Shipping
	checkout  *Checkout
}

// shipShop gives a shop with apples at 250 and pears at 1000, 20 of each,
// and the rates of a carrier for the home zone and Europe.
func shipShop(t *testing.T) shipFixture {
	t.Helper()
	ids := adapters.NewSequentialIDs()
	clock := adapters.NewFixedClock("2026-03-10")
	catalogue := NewCatalogue(adapters.NewInMemoryProductRepository())
	shipMust(catalogue.AddProduct("apple", "Apple", 250))(t)
	shipMust(catalogue.AddProduct("pear", "Pear", 1000))(t)
	inventory := NewInventory(adapters.NewInMemoryStockRepository())
	shipOK(t, inventory.Receive("apple", 20))
	shipOK(t, inventory.Receive("pear", 20))
	repository := adapters.NewInMemoryOrderRepository()
	payments := adapters.NewInMemoryPaymentGateway(ids)
	customers := NewCustomers(CustomersDeps{Repository: adapters.NewInMemoryCustomerRepository(), Clock: clock, IDs: ids})
	checkout := NewCheckout(CheckoutDeps{Catalogue: catalogue, Inventory: inventory, Orders: repository,
		Payments: payments, Clock: clock, IDs: ids, Customers: customers})
	orders := NewOrders(repository, inventory, payments)
	outbox := adapters.NewInMemoryOutbox()
	shipping := NewShipping(ShippingDeps{Shipments: adapters.NewInMemoryShipmentRepository(), Orders: orders,
		Customers: customers, Notifier: outbox, Clock: clock, IDs: ids})
	shipOK(t, shipping.SetRate(ShippingRate{Zone: "domestic", FirstUnit: 400, PerExtraUnit: 100, FreeFrom: 5000}))
	shipOK(t, shipping.SetRate(ShippingRate{Zone: "europe", FirstUnit: 900, PerExtraUnit: 200, MaxUnitsPerParcel: 3}))
	return shipFixture{t, clock, inventory, customers, orders, outbox, shipping, checkout}
}

// place places an order for the customer ("" for a guest) of the lines,
// each a SKU and a quantity, and gives its id.
func (s shipFixture) place(customerID string, pairs ...any) string {
	s.t.Helper()
	cart := NewCart()
	for i := 0; i < len(pairs); i += 2 {
		shipOK(s.t, cart.Add(pairs[i].(string), pairs[i+1].(int)))
	}
	request := CheckoutRequest{Cart: cart, PaymentToken: "card", CustomerID: customerID}
	return shipMust(s.checkout.PlaceOrder(request))(s.t).ID
}

func shipIDs(shipments []Shipment) []string {
	ids := []string{}
	for _, shipment := range shipments {
		ids = append(ids, shipment.ID)
	}
	return ids
}

func shipEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := shipShow(got), shipShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func shipShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func shipErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func shipOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func shipMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func shipTo(a Address) *Address { return &a }

func TestShipping(t *testing.T) {
	t.Run("rates", func(t *testing.T) {
		t.Run("quotes what the carrier charges to send an order to an address", func(t *testing.T) {
			s := shipShop(t)
			id := s.place("", "apple", 4)
			shipEq(t, shipMust(s.shipping.Quote(id, shipLeeds()))(t), 700)
			// Two parcels to Europe: three units, then one.
			shipEq(t, shipMust(s.shipping.Quote(id, shipParis()))(t), 2200)
		})

		t.Run("sends an order free from the free shipping total of its zone", func(t *testing.T) {
			s := shipShop(t)
			shipEq(t, shipMust(s.shipping.Quote(s.place("", "pear", 5), shipLeeds()))(t), 0)
		})

		t.Run("rejects a zone with no rate", func(t *testing.T) {
			s := shipShop(t)
			id := s.place("", "apple", 1)
			us := shipLeeds()
			us.Country = "US"
			_, err := s.shipping.Quote(id, us)
			shipErr(t, err, "no rate for zone world")
			_, err = s.shipping.Rate("moon")
			shipErr(t, err, "unknown zone moon")
		})
	})

	t.Run("shipments", func(t *testing.T) {
		t.Run("creates the shipment of a paid order to an address", func(t *testing.T) {
			s := shipShop(t)
			id := s.place("", "apple", 4, "pear", 3)
			shipEq(t, shipMust(s.shipping.CreateShipment(id, shipTo(shipParis())))(t), Shipment{
				ID: "shipment-1", OrderID: id, Address: shipParis(), Zone: "europe", Units: 7, Parcels: 3,
				Cost: 3500, Status: "pending", CreatedOn: "2026-03-10",
			})
		})

		t.Run("sends a shipment to the address of the customer of the order", func(t *testing.T) {
			s := shipShop(t)
			ada := shipMust(s.customers.Register("Ada", "ada@example.com", shipTo(shipLeeds())))(t)
			shipment := shipMust(s.shipping.CreateShipment(s.place(ada.ID, "apple", 1), nil))(t)
			shipEq(t, []any{shipment.Address, shipment.Zone, shipment.Cost}, []any{shipLeeds(), Zone("domestic"), 400})
		})

		t.Run("rejects a shipment with no address", func(t *testing.T) {
			s := shipShop(t)
			_, err := s.shipping.CreateShipment(s.place("", "apple", 1), nil)
			shipErr(t, err, "order order-1 has no address")
			bob := shipMust(s.customers.Register("Bob", "bob@example.com", nil))(t)
			_, err = s.shipping.CreateShipment(s.place(bob.ID, "apple", 1), nil)
			shipErr(t, err, "customer customer-1 has no address")
		})

		t.Run("rejects a second shipment of an order, and a shipment of an order that is not paid", func(t *testing.T) {
			s := shipShop(t)
			id := s.place("", "apple", 1)
			shipMust(s.shipping.CreateShipment(id, shipTo(shipLeeds())))(t)
			_, err := s.shipping.CreateShipment(id, shipTo(shipLeeds()))
			shipErr(t, err, "order "+id+" already has a shipment")
			cancelled := s.place("", "apple", 1)
			shipOK(t, s.orders.Cancel(cancelled))
			_, err = s.shipping.CreateShipment(cancelled, shipTo(shipLeeds()))
			shipErr(t, err, "order "+cancelled+" is cancelled")
		})

		t.Run("finds the shipment of an order", func(t *testing.T) {
			s := shipShop(t)
			id := s.place("", "apple", 1)
			shipment := shipMust(s.shipping.CreateShipment(id, shipTo(shipLeeds())))(t)
			shipEq(t, shipMust(s.shipping.ShipmentOf(id))(t), shipment)
			shipEq(t, shipMust(s.shipping.Shipment(shipment.ID))(t), shipment)
			_, err := s.shipping.ShipmentOf(s.place("", "apple", 1))
			shipErr(t, err, "order order-2 has no shipment")
			_, err = s.shipping.Shipment("shipment-9")
			shipErr(t, err, "unknown shipment shipment-9")
		})
	})

	t.Run("dispatch and delivery", func(t *testing.T) {
		t.Run("dispatches a shipment, which ships its order", func(t *testing.T) {
			s := shipShop(t)
			id := s.place("", "apple", 3)
			shipment := shipMust(s.shipping.CreateShipment(id, shipTo(shipLeeds())))(t)
			s.clock.Set("2026-03-11")
			dispatched := shipMust(s.shipping.Dispatch(shipment.ID, "TRK-1"))(t)
			shipEq(t, []any{dispatched.Status, dispatched.TrackingCode, dispatched.DispatchedOn},
				[]any{ShipmentStatus("dispatched"), "TRK-1", "2026-03-11"})
			shipEq(t, shipMust(s.orders.Order(id))(t).Status, OrderStatus("shipped"))
			shipEq(t, s.inventory.Level("apple"), StockLevel{SKU: "apple", OnHand: 17, Reserved: 0})
		})

		t.Run("tells the customer that the order has shipped", func(t *testing.T) {
			s := shipShop(t)
			ada := shipMust(s.customers.Register("Ada", "ada@example.com", shipTo(shipLeeds())))(t)
			id := s.place(ada.ID, "apple", 1)
			shipMust(s.shipping.Dispatch(shipMust(s.shipping.CreateShipment(id, nil))(t).ID, "TRK-9"))(t)
			shipEq(t, s.outbox.Sent(), []Message{{
				To:      "ada@example.com",
				Subject: "Order " + id + " has shipped",
				Body: "Hello Ada, your order " + id + " is on its way to 1 High St, Leeds LS1 1AA, GB. " +
					"Tracking code: TRK-9.",
			}})
		})

		t.Run("sends no message for a guest order", func(t *testing.T) {
			s := shipShop(t)
			id := s.place("", "apple", 1)
			shipMust(s.shipping.Dispatch(shipMust(s.shipping.CreateShipment(id, shipTo(shipLeeds())))(t).ID, "TRK-1"))(t)
			shipEq(t, s.outbox.Sent(), []Message{})
		})

		t.Run("delivers a dispatched shipment, once", func(t *testing.T) {
			s := shipShop(t)
			shipment := shipMust(s.shipping.CreateShipment(s.place("", "apple", 1), shipTo(shipLeeds())))(t)
			_, err := s.shipping.Deliver(shipment.ID)
			shipErr(t, err, "shipment shipment-1 is pending")
			shipMust(s.shipping.Dispatch(shipment.ID, "TRK-1"))(t)
			s.clock.Set("2026-03-13")
			shipEq(t, shipMust(s.shipping.Deliver(shipment.ID))(t).DeliveredOn, "2026-03-13")
			_, err = s.shipping.Dispatch(shipment.ID, "TRK-2")
			shipErr(t, err, "shipment shipment-1 is delivered")
		})

		t.Run("rejects an empty tracking code", func(t *testing.T) {
			s := shipShop(t)
			shipment := shipMust(s.shipping.CreateShipment(s.place("", "apple", 1), shipTo(shipLeeds())))(t)
			_, err := s.shipping.Dispatch(shipment.ID, " ")
			shipErr(t, err, "tracking code must not be empty")
		})

		t.Run("does not dispatch the shipment of an order that was cancelled", func(t *testing.T) {
			s := shipShop(t)
			id := s.place("", "apple", 1)
			shipment := shipMust(s.shipping.CreateShipment(id, shipTo(shipLeeds())))(t)
			shipOK(t, s.orders.Cancel(id))
			_, err := s.shipping.Dispatch(shipment.ID, "TRK-1")
			shipErr(t, err, "order "+id+" is cancelled")
			shipEq(t, shipMust(s.shipping.Shipment(shipment.ID))(t).Status, ShipmentStatus("pending"))
		})
	})

	t.Run("cancellation", func(t *testing.T) {
		t.Run("cancels a pending shipment, and lets the order have a new one", func(t *testing.T) {
			s := shipShop(t)
			id := s.place("", "apple", 1)
			first := shipMust(s.shipping.CreateShipment(id, shipTo(shipLeeds())))(t)
			shipEq(t, shipMust(s.shipping.Cancel(first.ID))(t).Status, ShipmentStatus("cancelled"))
			second := shipMust(s.shipping.CreateShipment(id, shipTo(shipParis())))(t)
			shipEq(t, shipMust(s.shipping.ShipmentOf(id))(t).ID, second.ID)
		})

		t.Run("cancels the pending shipment of a cancelled order", func(t *testing.T) {
			s := shipShop(t)
			id := s.place("", "apple", 1)
			shipment := shipMust(s.shipping.CreateShipment(id, shipTo(shipLeeds())))(t)
			shipOK(t, s.orders.Cancel(id))
			shipOK(t, s.shipping.OnOrderCancelled(ShopEvent{ID: "event-1", Type: "order-cancelled", Subject: id,
				On: "2026-03-10", Data: EventData{}}))
			shipEq(t, shipMust(s.shipping.Shipment(shipment.ID))(t).Status, ShipmentStatus("cancelled"))
		})
	})

	t.Run("tracking the carrier", func(t *testing.T) {
		t.Run("lists the pending shipments and the overdue ones", func(t *testing.T) {
			s := shipShop(t)
			first := shipMust(s.shipping.CreateShipment(s.place("", "apple", 1), shipTo(shipLeeds())))(t)
			second := shipMust(s.shipping.CreateShipment(s.place("", "apple", 1), shipTo(shipLeeds())))(t)
			shipMust(s.shipping.Dispatch(first.ID, "TRK-1"))(t)
			shipEq(t, shipIDs(s.shipping.Pending()), []string{second.ID})
			s.clock.Set("2026-03-15")
			shipEq(t, s.shipping.Overdue(5), []Shipment{})
			shipEq(t, shipIDs(s.shipping.Overdue(4)), []string{first.ID})
		})

		t.Run("works out the days from dispatch to delivery", func(t *testing.T) {
			s := shipShop(t)
			shipEq(t, s.shipping.AverageDeliveryDays(), 0)
			for _, days := range []int{2, 5} {
				s.clock.Set("2026-03-10")
				shipment := shipMust(s.shipping.CreateShipment(s.place("", "apple", 1), shipTo(shipLeeds())))(t)
				shipMust(s.shipping.Dispatch(shipment.ID, "TRK"))(t)
				shipOK(t, s.clock.Advance(days))
				shipMust(s.shipping.Deliver(shipment.ID))(t)
			}
			shipEq(t, s.shipping.AverageDeliveryDays(), 3)
			shipEq(t, shipIDs(shipMust(s.shipping.DeliveredBetween("2026-03-15", "2026-03-31"))(t)),
				[]string{"shipment-2"})
		})
	})
}
