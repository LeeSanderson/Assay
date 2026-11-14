package services

import (
	"fmt"
	"strings"
	"testing"

	"shop/adapters"
	. "shop/domain"
)

type repFixture struct {
	t         *testing.T
	clock     *adapters.FixedClock
	catalogue *Catalogue
	inventory *Inventory
	customers *Customers
	orders    *Orders
	shipments *adapters.InMemoryShipmentRepository
	reports   *Reports
	checkout  *Checkout
}

// repShop gives a shop with apples at 250 and pears at 1000, 20 of each, and
// 10% off pears.
func repShop(t *testing.T) repFixture {
	t.Helper()
	ids := adapters.NewSequentialIDs()
	clock := adapters.NewFixedClock("2026-03-10")
	products := adapters.NewInMemoryProductRepository()
	catalogue := NewCatalogue(products)
	repMust(catalogue.AddProduct("apple", "Apple", 250))(t)
	repMust(catalogue.AddProduct("pear", "Pear", 1000))(t)
	stock := adapters.NewInMemoryStockRepository()
	inventory := NewInventory(stock)
	repOK(t, inventory.Receive("apple", 20))
	repOK(t, inventory.Receive("pear", 20))
	promotions := NewPromotionEngine()
	repOK(t, promotions.AddPromotion(Promotion{ID: "pears", Kind: "percentage", Percent: 10, SKUs: []string{"pear"}}))
	repository := adapters.NewInMemoryOrderRepository()
	payments := adapters.NewInMemoryPaymentGateway(ids)
	customerStore := adapters.NewInMemoryCustomerRepository()
	customers := NewCustomers(CustomersDeps{Repository: customerStore, Clock: clock, IDs: ids})
	checkout := NewCheckout(CheckoutDeps{Catalogue: catalogue, Inventory: inventory, Orders: repository,
		Payments: payments, Clock: clock, IDs: ids, Promotions: promotions, Customers: customers})
	orders := NewOrders(repository, inventory, payments)
	shipments := adapters.NewInMemoryShipmentRepository()
	reports := NewReports(ReportsDeps{Orders: repository, Products: products, Stock: stock, Shipments: shipments,
		Customers: customerStore})
	return repFixture{t, clock, catalogue, inventory, customers, orders, shipments, reports, checkout}
}

// place places an order for the customer ("" for a guest) of the lines,
// each a SKU and a quantity, and gives its id.
func (s repFixture) place(customerID string, pairs ...any) string {
	s.t.Helper()
	cart := NewCart()
	for i := 0; i < len(pairs); i += 2 {
		repOK(s.t, cart.Add(pairs[i].(string), pairs[i+1].(int)))
	}
	request := CheckoutRequest{Cart: cart, PaymentToken: "card", CustomerID: customerID}
	return repMust(s.checkout.PlaceOrder(request))(s.t).ID
}

func repEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := repShow(got), repShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func repShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

func repErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil || err.Error() != want {
		t.Fatalf("got error %v, want %q", err, want)
	}
}

func repOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func repMust[T any](v T, err error) func(*testing.T) T {
	return func(t *testing.T) T {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
}

func TestReports(t *testing.T) {
	t.Run("sales reports", func(t *testing.T) {
		t.Run("sums up the sales of a period", func(t *testing.T) {
			s := repShop(t)
			s.place("", "apple", 2, "pear", 1) // 500 + 900
			repOK(t, s.orders.Cancel(s.place("", "pear", 5)))
			s.clock.Set("2026-04-01")
			s.place("", "apple", 1)
			repEq(t, repMust(s.reports.SalesSummary("2026-03-01", "2026-03-31"))(t), SalesSummary{
				From: "2026-03-01", To: "2026-03-31", Orders: 1, Units: 3, Subtotal: 1500, Discounts: 100,
				Revenue: 1400, AverageOrder: 1400,
			})
		})

		t.Run("rejects a period that ends before it starts", func(t *testing.T) {
			_, err := repShop(t).reports.SalesSummary("2026-03-31", "2026-03-01")
			repErr(t, err, "the period from 2026-03-31 to 2026-03-01 ends before it starts")
		})

		t.Run("gives the sales of each day, each weekday and each month", func(t *testing.T) {
			s := repShop(t)
			s.place("", "apple", 1)
			s.place("", "apple", 2)
			s.clock.Set("2026-04-02")
			s.place("", "pear", 1)
			repEq(t, repMust(s.reports.DailySales("2026-03-01", "2026-04-30"))(t), []DailySales{
				{Date: "2026-03-10", Orders: 2, Revenue: 750},
				{Date: "2026-04-02", Orders: 1, Revenue: 900},
			})
			repEq(t, repMust(s.reports.WeekdaySales("2026-03-01", "2026-04-30"))(t), []WeekdaySales{
				{Weekday: "Tuesday", Orders: 2, Revenue: 750},
				{Weekday: "Thursday", Orders: 1, Revenue: 900},
			})
			repEq(t, s.reports.MonthlySales(), []MonthlySales{
				{Month: "2026-03", Orders: 2, Revenue: 750},
				{Month: "2026-04", Orders: 1, Revenue: 900},
			})
		})

		t.Run("ranks the products by their gross sales", func(t *testing.T) {
			s := repShop(t)
			s.place("", "apple", 6, "pear", 1)
			repEq(t, repMust(s.reports.ProductSales("2026-03-01", "2026-03-31"))(t), []ProductSales{
				{SKU: "apple", Units: 6, Gross: 1500, Orders: 1},
				{SKU: "pear", Units: 1, Gross: 1000, Orders: 1},
			})
		})

		t.Run("adds up what each promotion took off", func(t *testing.T) {
			s := repShop(t)
			s.place("", "pear", 2)
			s.place("", "pear", 1, "apple", 1)
			repEq(t, s.reports.PromotionUsage(), []PromotionUsage{{PromotionID: "pears", Orders: 2, Amount: 300}})
		})
	})

	t.Run("customer reports", func(t *testing.T) {
		t.Run("ranks the customers by what they spent", func(t *testing.T) {
			s := repShop(t)
			ada := repMust(s.customers.Register("Ada", "ada@example.com", nil))(t).ID
			bob := repMust(s.customers.Register("Bob", "bob@example.com", nil))(t).ID
			s.place(ada, "apple", 1)
			s.place(bob, "pear", 1)
			s.place(ada, "apple", 2)
			repEq(t, repMust(s.reports.TopCustomers(5))(t), []CustomerSales{
				{CustomerID: bob, Orders: 1, Revenue: 900},
				{CustomerID: ada, Orders: 2, Revenue: 750},
			})
			_, err := s.reports.TopCustomers(0)
			repErr(t, err, "limit must be at least 1")
		})

		t.Run("groups the customers by the month that they registered", func(t *testing.T) {
			s := repShop(t)
			ada := repMust(s.customers.Register("Ada", "ada@example.com", nil))(t).ID
			s.clock.Set("2026-04-01")
			repMust(s.customers.Register("Bob", "bob@example.com", nil))(t)
			s.place(ada, "apple", 1)
			repEq(t, s.reports.Cohorts(), []Cohort{
				{Month: "2026-03", Customers: 1, Buyers: 1, Revenue: 250},
				{Month: "2026-04", Customers: 1, Buyers: 0, Revenue: 0},
			})
		})
	})

	t.Run("stock reports", func(t *testing.T) {
		t.Run("values the stock on hand", func(t *testing.T) {
			s := repShop(t)
			repOK(t, s.inventory.WriteOff("pear", 18))
			repEq(t, s.reports.StockValuation(), StockValuation{
				Rows: []StockValue{
					{SKU: "apple", OnHand: 20, UnitPrice: 250, Value: 5000},
					{SKU: "pear", OnHand: 2, UnitPrice: 1000, Value: 2000},
				},
				Total: 7000,
			})
		})

		t.Run("suggests what to reorder to bring the stock up to a target", func(t *testing.T) {
			s := repShop(t)
			repMust(s.catalogue.AddProduct("fig", "Fig", 400))(t)
			repMust(s.catalogue.AddProduct("kiwi", "Kiwi", 300))(t)
			repOK(t, s.catalogue.Discontinue("kiwi"))
			repOK(t, s.inventory.WriteOff("pear", 15))
			s.place("", "pear", 2)
			repEq(t, repMust(s.reports.Reorder(5, 12))(t), []ReorderLine{
				{SKU: "fig", Name: "Fig", Available: 0, Suggested: 12},
				{SKU: "pear", Name: "Pear", Available: 3, Suggested: 9},
			})
			_, err := s.reports.Reorder(5, 4)
			repErr(t, err, "the target must not be below the threshold")
		})
	})

	t.Run("shipping reports", func(t *testing.T) {
		t.Run("adds up the shipping costs and the margin of each month", func(t *testing.T) {
			s := repShop(t)
			id := s.place("", "pear", 1)
			s.shipments.Save(Shipment{
				ID: "shipment-1", OrderID: id,
				Address: Address{Line1: "1 High St", City: "Leeds", Postcode: "LS1 1AA", Country: "GB"},
				Zone:    "domestic", Units: 1, Parcels: 1, Cost: 400, Status: "pending", CreatedOn: "2026-03-11",
			})
			repEq(t, repMust(s.reports.ShippingCosts("2026-03-01", "2026-03-31"))(t),
				ShippingCosts{Shipments: 1, Cost: 400, ByZone: map[string]Cents{"domestic": 400}})
			repEq(t, s.reports.MonthlyMargin(), []MonthlyMargin{
				{Month: "2026-03", Revenue: 900, Shipping: 400, Margin: 500},
			})
		})
	})
}
