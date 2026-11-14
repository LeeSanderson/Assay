// Reports: figures for the people who run the shop, read from the stores.
// Each report counts the orders that are not cancelled, at their totals as
// placed (domain/report.go).

package services

import (
	"slices"

	. "shop/domain"
)

type ReportsDeps struct {
	Orders    OrderRepository
	Products  ProductRepository
	Stock     StockRepository
	Shipments ShipmentRepository
	Customers CustomerRepository
}

type MonthlyMargin struct {
	Month    string // YYYY-MM
	Revenue  Cents
	Shipping Cents
	Margin   Cents
}

type StockValuation struct {
	Rows  []StockValue
	Total Cents
}

type MonthlySales struct {
	Month   string // YYYY-MM
	Orders  int
	Revenue Cents
}

// ReorderLine is a product to order more of: its available stock is below
// the threshold.
type ReorderLine struct {
	SKU       string
	Name      string
	Available int
	Suggested int // enough to bring the available stock up to the target
}

type Reports struct {
	deps ReportsDeps
}

func NewReports(deps ReportsDeps) *Reports { return &Reports{deps: deps} }

// inPeriod checks the period, then gives the figure of the orders.
func inPeriod[T any](r *Reports, from, to IsoDate, figure func([]Order, IsoDate, IsoDate) T) (T, error) {
	if err := CheckPeriod(from, to); err != nil {
		var none T
		return none, err
	}
	return figure(r.deps.Orders.List(), from, to), nil
}

func (r *Reports) SalesSummary(from, to IsoDate) (SalesSummary, error) {
	return inPeriod(r, from, to, SalesSummaryOf)
}

func (r *Reports) DailySales(from, to IsoDate) ([]DailySales, error) {
	return inPeriod(r, from, to, DailySalesOf)
}

// MonthlySales gives one row for each month with an order that counts, by
// month.
func (r *Reports) MonthlySales() []MonthlySales {
	months := []MonthlySales{}
	for _, day := range DailySalesOf(r.deps.Orders.List(), "0000-01-01", "9999-12-31") {
		if n := len(months); n > 0 && months[n-1].Month == MonthOf(day.Date) {
			months[n-1].Orders += day.Orders
			months[n-1].Revenue += day.Revenue
		} else {
			months = append(months, MonthlySales{MonthOf(day.Date), day.Orders, day.Revenue})
		}
	}
	return months
}

func (r *Reports) PromotionUsage() []PromotionUsage { return PromotionUsageOf(r.deps.Orders.List()) }

func (r *Reports) StockValuation() StockValuation {
	valuation := StockValuation{Rows: StockValues(r.deps.Products.List(), r.deps.Stock.List())}
	for _, row := range valuation.Rows {
		valuation.Total += row.Value
	}
	return valuation
}

func (r *Reports) TopCustomers(limit int) ([]CustomerSales, error) {
	if err := Check(limit >= 1, "limit must be at least 1"); err != nil {
		return nil, err
	}
	return CustomerSalesOf(r.deps.Orders.List(), limit), nil
}

func (r *Reports) ShippingCosts(from, to IsoDate) (ShippingCosts, error) {
	if err := CheckPeriod(from, to); err != nil {
		return ShippingCosts{}, err
	}
	return ShippingCostsOf(r.deps.Shipments.List(), from, to), nil
}

func (r *Reports) ProductSales(from, to IsoDate) ([]ProductSales, error) {
	return inPeriod(r, from, to, ProductSalesOf)
}

func (r *Reports) WeekdaySales(from, to IsoDate) ([]WeekdaySales, error) {
	return inPeriod(r, from, to, WeekdaySalesOf)
}

func (r *Reports) Cohorts() []Cohort {
	return Cohorts(r.deps.Customers.List(), r.deps.Orders.List())
}

// MonthlyMargin gives the revenue of each month with an order that counts,
// less what the carrier charged for the shipments created that month, by
// month.
func (r *Reports) MonthlyMargin() []MonthlyMargin {
	costs := map[string]Cents{}
	for _, shipment := range r.deps.Shipments.List() {
		costs[MonthOf(shipment.CreatedOn)] += shipment.Cost
	}
	margins := []MonthlyMargin{}
	for _, row := range r.MonthlySales() {
		shipping := costs[row.Month]
		margins = append(margins, MonthlyMargin{row.Month, row.Revenue, shipping, row.Revenue - shipping})
	}
	return margins
}

// Reorder gives the products on sale whose available stock is below
// `threshold`, with the units to order to bring it up to `target`, in SKU
// order.
func (r *Reports) Reorder(threshold, target int) ([]ReorderLine, error) {
	if err := Check(target >= threshold, "the target must not be below the threshold"); err != nil {
		return nil, err
	}
	products := slices.DeleteFunc(r.deps.Products.List(), func(p Product) bool { return p.Discontinued })
	slices.SortFunc(products, func(a, b Product) int { return CompareText(a.SKU, b.SKU) })
	lines := []ReorderLine{}
	for _, product := range products {
		level, _ := r.deps.Stock.Get(product.SKU)
		if available := AvailableOf(level); available < threshold {
			lines = append(lines, ReorderLine{product.SKU, product.Name, available, target - available})
		}
	}
	return lines, nil
}
