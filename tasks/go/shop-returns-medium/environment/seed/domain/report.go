// Reports: figures over the orders, the stock and the shipments, worked out
// from the records as they are. Each figure counts the orders that are not
// cancelled, at their totals as placed. These are pure functions;
// services/reports.go loads the records and calls them. Go has one name
// space for types and functions, so the function of each figure is named
// <Figure>Of.

package domain

import (
	"cmp"
	"slices"
)

type SalesSummary struct {
	From         IsoDate
	To           IsoDate
	Orders       int
	Units        int
	Subtotal     Cents
	Discounts    Cents
	Revenue      Cents
	AverageOrder Cents // revenue / orders, rounded down; 0 with no orders
}

type DailySales struct {
	Date    IsoDate
	Orders  int
	Revenue Cents
}

type PromotionUsage struct {
	PromotionID string
	Orders      int
	Amount      Cents
}

type StockValue struct {
	SKU       string
	OnHand    int
	UnitPrice Cents
	Value     Cents
}

type CustomerSales struct {
	CustomerID string
	Orders     int
	Revenue    Cents
}

type ShippingCosts struct {
	Shipments int
	Cost      Cents
	ByZone    map[string]Cents
}

// rows keeps one row for each key, in the order that each key first came.
type rows[T any] struct {
	keys  []string
	byKey map[string]*T
}

func (r *rows[T]) at(key string, fresh func() T) *T {
	if r.byKey == nil {
		r.byKey = map[string]*T{}
	}
	if _, ok := r.byKey[key]; !ok {
		row := fresh()
		r.byKey[key], r.keys = &row, append(r.keys, key)
	}
	return r.byKey[key]
}

// sorted gives the rows, sorted by the order.
func (r *rows[T]) sorted(order func(a, b T) int) []T {
	list := []T{}
	for _, key := range r.keys {
		list = append(list, *r.byKey[key])
	}
	slices.SortStableFunc(list, order)
	return list
}

// CountedIn gives the orders that count, placed in the period.
func CountedIn(orders []Order, from, to IsoDate) []Order {
	return slices.DeleteFunc(slices.Clone(orders), func(order Order) bool {
		return !Counts(order) || !Within(order.PlacedOn, from, to)
	})
}

func SalesSummaryOf(orders []Order, from, to IsoDate) SalesSummary {
	summary := SalesSummary{From: from, To: to}
	for _, order := range CountedIn(orders, from, to) {
		summary.Orders++
		summary.Units += UnitsOf(order)
		summary.Subtotal += order.Subtotal
		summary.Discounts += DiscountTotal(order)
		summary.Revenue += order.Total
	}
	if summary.Orders > 0 {
		summary.AverageOrder = summary.Revenue / summary.Orders
	}
	return summary
}

// DailySalesOf gives one row for each day of the period with an order that
// counts, by date.
func DailySalesOf(orders []Order, from, to IsoDate) []DailySales {
	var days rows[DailySales]
	for _, order := range CountedIn(orders, from, to) {
		day := days.at(order.PlacedOn, func() DailySales { return DailySales{Date: order.PlacedOn} })
		day.Orders++
		day.Revenue += order.Total
	}
	return days.sorted(func(a, b DailySales) int { return CompareText(a.Date, b.Date) })
}

type WeekdaySales struct {
	Weekday string
	Orders  int
	Revenue Cents
}

var week = []string{"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}

// WeekdaySalesOf gives the orders that count, placed in the period, by the
// day of the week, from Monday to Sunday. A day with no order is left out.
func WeekdaySalesOf(orders []Order, from, to IsoDate) []WeekdaySales {
	var days rows[WeekdaySales]
	for _, order := range CountedIn(orders, from, to) {
		name := Weekday(order.PlacedOn)
		day := days.at(name, func() WeekdaySales { return WeekdaySales{Weekday: name} })
		day.Orders++
		day.Revenue += order.Total
	}
	return days.sorted(func(a, b WeekdaySales) int {
		return slices.Index(week, a.Weekday) - slices.Index(week, b.Weekday)
	})
}

// PromotionUsageOf gives what each promotion took off over the orders that
// count: the most first, and by promotion id on a tie.
func PromotionUsageOf(orders []Order) []PromotionUsage {
	var usage rows[PromotionUsage]
	for _, order := range slices.DeleteFunc(slices.Clone(orders), func(o Order) bool { return !Counts(o) }) {
		for _, discount := range order.Discounts {
			id := discount.PromotionID
			row := usage.at(id, func() PromotionUsage { return PromotionUsage{PromotionID: id} })
			row.Orders++
			row.Amount += discount.Amount
		}
	}
	return usage.sorted(func(a, b PromotionUsage) int {
		return cmp.Or(b.Amount-a.Amount, CompareText(a.PromotionID, b.PromotionID))
	})
}

// StockValues gives the value of the stock on hand of each product at its
// price, in SKU order. A product with no stock on hand is left out.
func StockValues(products []Product, levels []StockLevel) []StockValue {
	values := []StockValue{}
	for _, product := range products {
		i := slices.IndexFunc(levels, func(level StockLevel) bool { return level.SKU == product.SKU })
		if i >= 0 && levels[i].OnHand > 0 {
			onHand := levels[i].OnHand
			values = append(values, StockValue{product.SKU, onHand, product.UnitPrice,
				Times(product.UnitPrice, onHand)})
		}
	}
	slices.SortFunc(values, func(a, b StockValue) int { return CompareText(a.SKU, b.SKU) })
	return values
}

// CustomerSalesOf gives the customers who spent the most over the orders
// that count, at most `limit` of them, and by customer id on a tie. Guest
// orders are left out.
func CustomerSalesOf(orders []Order, limit int) []CustomerSales {
	var sales rows[CustomerSales]
	for _, order := range orders {
		if id := order.CustomerID; Counts(order) && id != "" {
			row := sales.at(id, func() CustomerSales { return CustomerSales{CustomerID: id} })
			row.Orders++
			row.Revenue += order.Total
		}
	}
	list := sales.sorted(func(a, b CustomerSales) int {
		return cmp.Or(b.Revenue-a.Revenue, CompareText(a.CustomerID, b.CustomerID))
	})
	return list[:min(limit, len(list))]
}

type ProductSales struct {
	SKU    string
	Units  int
	Gross  Cents // the units at their unit prices, before any discount
	Orders int
}

// ProductSalesOf gives the units and the gross sales of each SKU over the
// orders that count, placed in the period: the most gross first, and by SKU
// on a tie.
func ProductSalesOf(orders []Order, from, to IsoDate) []ProductSales {
	var sales rows[ProductSales]
	for _, order := range CountedIn(orders, from, to) {
		for _, line := range order.Lines {
			row := sales.at(line.SKU, func() ProductSales { return ProductSales{SKU: line.SKU} })
			row.Units += line.Quantity
			row.Gross += LineTotal(line)
			row.Orders++
		}
	}
	return sales.sorted(func(a, b ProductSales) int {
		return cmp.Or(b.Gross-a.Gross, CompareText(a.SKU, b.SKU))
	})
}

type Cohort struct {
	Month     string // the month in which the customers registered, YYYY-MM
	Customers int
	Buyers    int // the customers of the cohort with an order that counts
	Revenue   Cents
}

// Cohorts groups the customers by the month that they registered, by month,
// with how many of them bought and what they spent over the orders that
// count.
func Cohorts(customers []Customer, orders []Order) []Cohort {
	var cohorts rows[Cohort]
	for _, customer := range customers {
		month := customer.RegisteredOn[:7]
		row := cohorts.at(month, func() Cohort { return Cohort{Month: month} })
		row.Customers++
		bought := false
		for _, order := range orders {
			if Counts(order) && order.CustomerID == customer.ID {
				bought = true
				row.Revenue += order.Total
			}
		}
		if bought {
			row.Buyers++
		}
	}
	return cohorts.sorted(func(a, b Cohort) int { return CompareText(a.Month, b.Month) })
}

// ShippingCostsOf gives what the carrier charged for the shipments created
// in the period.
func ShippingCostsOf(shipments []Shipment, from, to IsoDate) ShippingCosts {
	costs := ShippingCosts{ByZone: map[string]Cents{}}
	for _, shipment := range shipments {
		if Within(shipment.CreatedOn, from, to) {
			costs.Shipments++
			costs.Cost += shipment.Cost
			costs.ByZone[string(shipment.Zone)] += shipment.Cost
		}
	}
	return costs
}
