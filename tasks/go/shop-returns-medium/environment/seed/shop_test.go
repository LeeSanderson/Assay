package shop

import (
	"fmt"
	"strings"
	"testing"
)

func wholeEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := wholeShow(got), wholeShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func wholeShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func wholeOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func wholeMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

var wholeLeeds = Address{Line1: "1 High St", City: "Leeds", Postcode: "LS1 1AA", Country: "GB"}

// wholeFixture is the whole shop, with Ada and a way to place her orders.
type wholeFixture struct {
	*Shop
	ada   Customer
	place func(items ...CartLine) Order
}

// wholeShop gives the whole shop, with apples at 250 and pears at 1000, 20
// of each, a domestic rate, and Ada (customer-1), who lives in Leeds.
func wholeShop(t *testing.T) wholeFixture {
	t.Helper()
	shop := wholeMust(CreateShop(ShopOptions{Today: "2026-03-10",
		Rates: []ShippingRate{{Zone: "domestic", FirstUnit: 400, PerExtraUnit: 100}}}))(t)
	wholeMust(shop.Catalogue.AddProduct("apple", "Apple", 250))(t)
	wholeMust(shop.Catalogue.AddProduct("pear", "Pear", 1000))(t)
	wholeOK(t, shop.Inventory.Receive("apple", 20))
	wholeOK(t, shop.Inventory.Receive("pear", 20))
	address := wholeLeeds
	ada := wholeMust(shop.Customers.Register("Ada", "ada@example.com", &address))(t)
	place := func(items ...CartLine) Order {
		t.Helper()
		cart := NewCart()
		for _, item := range items {
			wholeOK(t, cart.Add(item.SKU, item.Quantity))
		}
		return wholeMust(shop.Checkout.PlaceOrder(CheckoutRequest{Cart: cart, PaymentToken: "card",
			CustomerID: ada.ID}))(t)
	}
	return wholeFixture{shop, ada, place}
}

func wholeItem(sku string, quantity int) CartLine { return CartLine{SKU: sku, Quantity: quantity} }

func TestWholeShop(t *testing.T) {
	t.Run("the shop", func(t *testing.T) {
		t.Run("records each change of an order, a shipment, an invoice and a customer", func(t *testing.T) {
			s := wholeShop(t)
			order := s.place(wholeItem("apple", 2))
			shipment := wholeMust(s.Shipping.CreateShipment(order.ID, nil))(t)
			wholeMust(s.Shipping.Dispatch(shipment.ID, "TRK-1"))(t)
			wholeMust(s.Invoicing.Issue(order.ID))(t)
			var got [][]string
			for _, event := range s.Events.All() {
				got = append(got, []string{event.Type, event.Subject})
			}
			wholeEq(t, got, [][]string{
				{"customer-registered", "customer-1"},
				{"order-placed", order.ID},
				{"shipment-created", shipment.ID},
				{"order-shipped", order.ID},
				{"shipment-dispatched", shipment.ID},
				{"invoice-issued", "invoice-1"},
			})
		})

		t.Run("awards loyalty points when an order is placed, and takes them back when it is cancelled", func(t *testing.T) {
			s := wholeShop(t)
			first := s.place(wholeItem("pear", 2))
			s.place(wholeItem("apple", 3))
			wholeEq(t, wholeMust(s.Accounts.Points(s.ada.ID))(t), 27)
			wholeOK(t, s.Orders.Cancel(first.ID))
			wholeEq(t, wholeMust(s.Accounts.Points(s.ada.ID))(t), 7)
		})

		t.Run("cancels the pending shipment of a cancelled order", func(t *testing.T) {
			s := wholeShop(t)
			order := s.place(wholeItem("apple", 1))
			shipment := wholeMust(s.Shipping.CreateShipment(order.ID, nil))(t)
			wholeOK(t, s.Orders.Cancel(order.ID))
			wholeEq(t, wholeMust(s.Shipping.Shipment(shipment.ID))(t).Status, ShipmentStatus("cancelled"))
		})

		t.Run("prices orders with its promotions engine", func(t *testing.T) {
			s := wholeShop(t)
			wholeOK(t, s.Promotions.AddPromotion(Promotion{ID: "ten", Kind: "percentage", Percent: 10}))
			wholeEq(t, s.place(wholeItem("pear", 1)).Total, 900)
			wholeEq(t, s.Reports.PromotionUsage(), []PromotionUsage{{PromotionID: "ten", Orders: 1, Amount: 100}})
		})

		t.Run("tells the customer when an order ships", func(t *testing.T) {
			s := wholeShop(t)
			order := s.place(wholeItem("apple", 1))
			wholeMust(s.Shipping.Dispatch(wholeMust(s.Shipping.CreateShipment(order.ID, nil))(t).ID, "TRK-7"))(t)
			var subjects []string
			for _, message := range s.Outbox.SentTo("ada@example.com") {
				subjects = append(subjects, message.Subject)
			}
			wholeEq(t, subjects, []string{"Order " + order.ID + " has shipped"})
		})

		t.Run("brings stock in through purchasing and sells it", func(t *testing.T) {
			s := wholeShop(t)
			supplier := wholeMust(s.Purchasing.AddSupplier("Orchard", "sales@orchard.example", 3))(t)
			draft := wholeMust(s.Purchasing.Draft(supplier.ID))(t)
			wholeMust(s.Purchasing.AddLine(draft.ID, "apple", 30, 120))(t)
			wholeMust(s.Purchasing.Send(draft.ID))(t)
			wholeMust(s.Purchasing.ReceiveAll(draft.ID))(t)
			s.place(wholeItem("apple", 45))
			wholeEq(t, s.Inventory.Level("apple"), StockLevel{SKU: "apple", OnHand: 50, Reserved: 45})
		})

		t.Run("reports its sales, stock and shipping together", func(t *testing.T) {
			s := wholeShop(t)
			order := s.place(wholeItem("apple", 4))
			wholeMust(s.Shipping.CreateShipment(order.ID, nil))(t)
			wholeEq(t, wholeMust(s.Reports.SalesSummary("2026-03-01", "2026-03-31"))(t).Revenue, 1000)
			wholeEq(t, s.Reports.MonthlyMargin(), []MonthlyMargin{
				{Month: "2026-03", Revenue: 1000, Shipping: 700, Margin: 300}})
			wholeEq(t, s.Reports.StockValuation().Total, 25000)
		})

		t.Run("uses the tax rate that it is given", func(t *testing.T) {
			zero := 0
			custom := wholeMust(CreateShop(ShopOptions{Today: "2026-03-10", TaxRate: &zero}))(t)
			wholeMust(custom.Catalogue.AddProduct("apple", "Apple", 250))(t)
			wholeOK(t, custom.Inventory.Receive("apple", 1))
			cart := NewCart()
			wholeOK(t, cart.Add("apple", 1))
			order := wholeMust(custom.Checkout.PlaceOrder(CheckoutRequest{Cart: cart, PaymentToken: "card"}))(t)
			wholeEq(t, wholeMust(custom.Invoicing.Issue(order.ID))(t).Tax, 0)
		})
	})
}
