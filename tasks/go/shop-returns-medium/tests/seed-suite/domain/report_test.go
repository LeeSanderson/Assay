package domain

import (
	"fmt"
	"strings"
	"testing"
)

func repEq(t *testing.T, got, want any) {
	t.Helper()
	if g, w := repShow(got), repShow(want); g != w {
		t.Fatalf("\ngot  %s\nwant %s", g, w)
	}
}

func repShow(v any) string { return strings.ReplaceAll(fmt.Sprintf("%#v", v), "(nil)", "{}") }

// repOrder gives an order with one line of apples at 250, and the discount
// that takes the subtotal down to the total.
func repOrder(id, placedOn string, apples, discount int, status OrderStatus, customerID string) Order {
	subtotal := apples * 250
	discounts := []Discount{}
	if discount > 0 {
		discounts = []Discount{{PromotionID: "ten", Amount: discount}}
	}
	return Order{ID: id, Lines: []OrderLine{{SKU: "apple", Name: "Apple", UnitPrice: 250, Quantity: apples}},
		Subtotal: subtotal, Discounts: discounts, Total: subtotal - discount, Status: status,
		PaymentID: "payment-" + id, PlacedOn: placedOn, CustomerID: customerID}
}

func repOrders() []Order {
	return []Order{
		repOrder("order-1", "2026-03-09", 4, 100, "paid", "customer-2"), // Monday, 900
		repOrder("order-2", "2026-03-10", 2, 0, "paid", "customer-1"),   // Tuesday, 500
		repOrder("order-3", "2026-03-10", 8, 0, "cancelled", "customer-1"),
		repOrder("order-4", "2026-03-16", 1, 25, "shipped", ""), // Monday, 225
	}
}

func TestReport(t *testing.T) {
	t.Run("sales", func(t *testing.T) {
		t.Run("sums up the orders that count in a period", func(t *testing.T) {
			repEq(t, SalesSummaryOf(repOrders(), "2026-03-01", "2026-03-31"), SalesSummary{
				From: "2026-03-01", To: "2026-03-31", Orders: 3, Units: 7, Subtotal: 1750, Discounts: 125,
				Revenue: 1625, AverageOrder: 541})
		})

		t.Run("gives an average of 0 for a period with no orders", func(t *testing.T) {
			repEq(t, SalesSummaryOf(repOrders(), "2026-04-01", "2026-04-30").AverageOrder, 0)
		})

		t.Run("gives one row for each day with sales, by date", func(t *testing.T) {
			repEq(t, DailySalesOf(repOrders(), "2026-03-01", "2026-03-31"), []DailySales{
				{Date: "2026-03-09", Orders: 1, Revenue: 900},
				{Date: "2026-03-10", Orders: 1, Revenue: 500},
				{Date: "2026-03-16", Orders: 1, Revenue: 225},
			})
		})

		t.Run("gives one row for each weekday with sales, from Monday", func(t *testing.T) {
			repEq(t, WeekdaySalesOf(repOrders(), "2026-03-01", "2026-03-31"), []WeekdaySales{
				{Weekday: "Monday", Orders: 2, Revenue: 1125},
				{Weekday: "Tuesday", Orders: 1, Revenue: 500},
			})
		})

		t.Run("ranks the products by their gross sales", func(t *testing.T) {
			pears := repOrder("order-5", "2026-03-11", 1, 0, "paid", "")
			pears.Lines = []OrderLine{{SKU: "pear", Name: "Pear", UnitPrice: 1000, Quantity: 2}}
			repEq(t, ProductSalesOf(append(repOrders(), pears), "2026-03-01", "2026-03-31"), []ProductSales{
				{SKU: "pear", Units: 2, Gross: 2000, Orders: 1},
				{SKU: "apple", Units: 7, Gross: 1750, Orders: 3},
			})
		})
	})

	t.Run("promotions and customers", func(t *testing.T) {
		t.Run("adds up what each promotion took off, the most first", func(t *testing.T) {
			other := repOrder("order-5", "2026-03-11", 4, 0, "paid", "")
			other.Discounts = []Discount{{PromotionID: "big", Amount: 400}}
			repEq(t, PromotionUsageOf(append(repOrders(), other)), []PromotionUsage{
				{PromotionID: "big", Orders: 1, Amount: 400},
				{PromotionID: "ten", Orders: 2, Amount: 125},
			})
		})

		t.Run("ranks the customers by what they spent, without guests", func(t *testing.T) {
			repEq(t, CustomerSalesOf(repOrders(), 5), []CustomerSales{
				{CustomerID: "customer-2", Orders: 1, Revenue: 900},
				{CustomerID: "customer-1", Orders: 1, Revenue: 500},
			})
			repEq(t, len(CustomerSalesOf(repOrders(), 1)), 1)
		})

		t.Run("groups the customers by the month that they registered", func(t *testing.T) {
			customer := func(id, registeredOn string) Customer {
				return Customer{ID: id, Name: id, Email: id + "@example.com", RegisteredOn: registeredOn}
			}
			repEq(t, Cohorts([]Customer{
				customer("customer-1", "2026-02-20"),
				customer("customer-2", "2026-03-01"),
				customer("customer-3", "2026-03-05"),
			}, repOrders()), []Cohort{
				{Month: "2026-02", Customers: 1, Buyers: 1, Revenue: 500},
				{Month: "2026-03", Customers: 2, Buyers: 1, Revenue: 900},
			})
		})
	})

	t.Run("stock and shipping", func(t *testing.T) {
		t.Run("values the stock on hand of each product, in SKU order", func(t *testing.T) {
			products := []Product{
				{SKU: "pear", Name: "Pear", UnitPrice: 1000},
				{SKU: "apple", Name: "Apple", UnitPrice: 250},
				{SKU: "fig", Name: "Fig", UnitPrice: 400},
			}
			levels := []StockLevel{{SKU: "pear", OnHand: 2, Reserved: 1}, {SKU: "apple", OnHand: 10}}
			repEq(t, StockValues(products, levels), []StockValue{
				{SKU: "apple", OnHand: 10, UnitPrice: 250, Value: 2500},
				{SKU: "pear", OnHand: 2, UnitPrice: 1000, Value: 2000},
			})
		})

		t.Run("adds up the shipping costs of a period by zone", func(t *testing.T) {
			shipment := func(id string, zone Zone, cost Cents, createdOn string) Shipment {
				return Shipment{ID: id, Zone: zone, Cost: cost, CreatedOn: createdOn}
			}
			repEq(t, ShippingCostsOf([]Shipment{
				shipment("shipment-1", "domestic", 400, "2026-03-10"),
				shipment("shipment-2", "europe", 900, "2026-03-11"),
				shipment("shipment-3", "domestic", 500, "2026-03-12"),
				shipment("shipment-4", "domestic", 700, "2026-04-01"),
			}, "2026-03-01", "2026-03-31"), ShippingCosts{Shipments: 3, Cost: 1800,
				ByZone: map[string]Cents{"domestic": 900, "europe": 900}})
		})
	})
}
