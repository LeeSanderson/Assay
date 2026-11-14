// Reports: figures over the orders, the stock and the shipments, and their CSV.

package shop

import (
	"shop/adapters"
	"shop/domain"
	"shop/services"
)

type (
	Cohort         = domain.Cohort
	CustomerSales  = domain.CustomerSales
	DailySales     = domain.DailySales
	ProductSales   = domain.ProductSales
	PromotionUsage = domain.PromotionUsage
	SalesSummary   = domain.SalesSummary
	ShippingCosts  = domain.ShippingCosts
	StockValue     = domain.StockValue
	WeekdaySales   = domain.WeekdaySales
	MonthlyMargin  = services.MonthlyMargin
	MonthlySales   = services.MonthlySales
	ReorderLine    = services.ReorderLine
	ReportsDeps    = services.ReportsDeps
	StockValuation = services.StockValuation
	Reports        = services.Reports
)

var (
	DailySalesCSV     = adapters.DailySalesCSV
	PromotionUsageCSV = adapters.PromotionUsageCSV
	StockValuesCSV    = adapters.StockValuesCSV
	NewReports        = services.NewReports
)

// ToCSV writes rows as CSV, one column for each of the columns (adapters/csv.go).
func ToCSV[T any](rows []T, columns []adapters.Column[T]) string {
	return adapters.ToCSV(rows, columns)
}
